"""Use the registry shipped beside the portable Google setup script."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from google_agreement_definitions import COUNTRIES, DOCUMENTS, IDS, VERSION, options
