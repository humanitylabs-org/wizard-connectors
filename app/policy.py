"""Closed admission rules. Callers cannot supply or downgrade labels."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Decision:
    route: str
    reason: str

def admit(*, labels, reviewed_public=False, private_enabled=True,
          model="tinfoil/glm-5-3", binding="private", eligible=True, current=True):
    if not current:
        return Decision("block", "stale_authority")
    if not labels or any(x not in ("public", "private") for x in labels):
        return Decision("block", "invalid_classification")
    private = not reviewed_public or "private" in labels
    if not private:
        return Decision("allow_public", "public_inputs")
    if binding != "private":
        return Decision("block", "private_binding_required")
    if model != "tinfoil/glm-5-3" or not eligible:
        return Decision("block", "ineligible_private_route")
    if not private_enabled:
        return Decision("block", "private_route_disabled")
    return Decision("allow_private", "private_inputs")
