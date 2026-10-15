from pathlib import Path
assert all((Path(__file__).resolve().parent.parent / "web" / p).is_file() for p in ("index.html", "app.js", "styles.css"))
print("Static view ready; shared WizardApp resource is supplied by the host.")
