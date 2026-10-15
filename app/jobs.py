import json
import os
import secrets
import threading
import time
from pathlib import Path
from chat import snapshot
from policy import admit
from private_model import Blocked

class Jobs:
    def __init__(self, model, data_dir):
        self.model = model
        self.lock = threading.RLock()
        self.path = Path(data_dir) / "policy.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.enabled = saved.get("private_enabled", True) is True
        self.epoch = saved.get("epoch", 0)
        self.jobs = {}
        self.keys = {}
        self.worker_active = False

    def policy(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("invalid_policy")
        with self.lock:
            next_epoch = self.epoch + 1
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"private_enabled": enabled, "epoch": next_epoch}))
            tmp.chmod(0o600)
            os.replace(tmp, self.path)
            self.enabled = enabled
            self.epoch = next_epoch
            for j in self.jobs.values():
                j.update(status="quarantined", reason="policy_changed", result=None)
            self.keys.clear()

    def create(self, thread, key):
        if thread not in ("garden", "bookclub") or not isinstance(key, str) or not 8 <= len(key) <= 96:
            raise ValueError("invalid_selection")
        with self.lock:
            self.purge()
            if key in self.keys:
                old = self.jobs[self.keys[key]]
                if old["thread"] != thread:
                    raise ValueError("idempotency_conflict")
                return self.public(old)
            if self.worker_active:
                raise Blocked("worker_busy")
            decision = admit(labels=["private"], private_enabled=self.enabled)
            if decision.route == "block":
                raise Blocked(decision.reason)
            if not self.model.key:
                raise Blocked("private_route_not_configured")
            ident = secrets.token_urlsafe(18)
            job = {"id": ident, "status": "queued", "reason": None, "thread": thread,
                   "epoch": self.epoch, "expires": time.time()+900, "result": None}
            self.jobs[ident] = job
            self.keys[key] = ident
            self.worker_active = True
            threading.Thread(target=self.run, args=(ident,), daemon=True).start()
            return self.public(job)

    def run(self, ident):
        with self.lock:
            j = self.jobs[ident]
            if j["epoch"] != self.epoch or j["status"] != "queued":
                self.worker_active = False
                return
            j["status"] = "running"
            packet = snapshot(j["thread"])
        try:
            text = self.model.summarize(packet)
            if not isinstance(text, str) or not text.strip() or len(text.encode()) > 16000:
                raise Blocked("invalid_output")
            with self.lock:
                if j["epoch"] != self.epoch or j["status"] != "running" or j["expires"] <= time.time():
                    j.update(status="quarantined", result=None, reason="stale_delivery")
                else:
                    j.update(status="complete", result=text, attestation=getattr(self.model, "last_attestation", None))
        except Exception as exc:
            with self.lock:
                if j["status"] == "running":
                    j.update(status="blocked", reason=str(exc) if isinstance(exc, Blocked) else "private_provider_unavailable", result=None)
        finally:
            with self.lock:
                self.worker_active = False

    def purge(self):
        for j in self.jobs.values():
            if j["expires"] <= time.time():
                j.update(status="expired", result=None, reason="retention_expired")
        # Bounded metadata, including idempotency index.
        terminal = [k for k,v in self.jobs.items() if v["status"] not in ("running", "queued")]
        for ident in terminal[:-64]:
            del self.jobs[ident]
            self.keys = {k:v for k,v in self.keys.items() if v != ident}

    @staticmethod
    def public(job):
        return {k:job[k] for k in ("id", "status", "reason")}

    def get(self, ident, human=False):
        with self.lock:
            self.purge()
            j = self.jobs[ident]
            out = self.public(j)
            if human and j["status"] == "complete" and j["epoch"] == self.epoch:
                out.update(text=j["result"], classification="private", trust="untrusted",
                           source_ids=[m["id"] for m in snapshot(j["thread"])["messages"]],
                           route="tinfoil/glm-5-3", simulated=True, attestation=j.get("attestation"))
            return out

    def cancel(self, ident):
        with self.lock:
            self.jobs[ident].update(status="cancelled", result=None, reason="owner_cancelled")
            return self.public(self.jobs[ident])
