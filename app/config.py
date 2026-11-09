"""Settings loaded from environment / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

DB_PATH = os.getenv("DB_PATH", str(ROOT / "clinic.db"))
CLINIC_TZ = os.getenv("CLINIC_TZ", "America/New_York")
# Optional shared secret. If set, /vapi/tools rejects requests without it.
VAPI_SECRET = os.getenv("VAPI_SECRET", "")
