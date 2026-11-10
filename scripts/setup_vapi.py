"""Create (or update) the Vapi assistant from code.

Usage:
  python scripts/setup_vapi.py --dry-run     # print the config, call nothing
  python scripts/setup_vapi.py               # create the assistant, or update it if VAPI_ASSISTANT_ID is set

Reads from .env:
  VAPI_API_KEY            (required) private key from the Vapi dashboard
  PUBLIC_URL              (required) your ngrok URL, e.g. https://abc123.ngrok-free.app
  VAPI_ASSISTANT_ID       (optional) set automatically after the first run
  TRANSFER_PHONE_NUMBER   (optional) E.164 number for live transfers, e.g. +15551234567
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from vapi.assistant_config import build_assistant  # noqa: E402

ENV_PATH = ROOT / ".env"
API = "https://api.vapi.ai"


def save_assistant_id(assistant_id: str) -> None:
    text = ENV_PATH.read_text() if ENV_PATH.exists() else ""
    if re.search(r"^VAPI_ASSISTANT_ID=.*$", text, flags=re.M):
        text = re.sub(r"^VAPI_ASSISTANT_ID=.*$", f"VAPI_ASSISTANT_ID={assistant_id}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\nVAPI_ASSISTANT_ID={assistant_id}\n"
    ENV_PATH.write_text(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(ENV_PATH)
    api_key = os.getenv("VAPI_API_KEY", "").strip()
    public_url = os.getenv("PUBLIC_URL", "").strip()
    assistant_id = os.getenv("VAPI_ASSISTANT_ID", "").strip()
    transfer = os.getenv("TRANSFER_PHONE_NUMBER", "").strip() or None

    if not public_url.startswith("https://"):
        sys.exit("PUBLIC_URL in .env must be your https ngrok URL (e.g. https://abc123.ngrok-free.app)")

    config = build_assistant(public_url, transfer_number=transfer)

    if args.dry_run:
        print(json.dumps(config, indent=2))
        return
    if not api_key:
        sys.exit("VAPI_API_KEY is missing from .env (Vapi dashboard -> API Keys -> Private key)")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if assistant_id:
        r = httpx.patch(f"{API}/assistant/{assistant_id}", headers=headers, json=config, timeout=30)
        action = "Updated"
    else:
        r = httpx.post(f"{API}/assistant", headers=headers, json=config, timeout=30)
        action = "Created"

    if r.status_code >= 400:
        print(f"Vapi returned {r.status_code}:")
        print(r.text)
        sys.exit(1)

    data = r.json()
    save_assistant_id(data["id"])
    print(f"{action} assistant: {data['name']}")
    print(f"  id: {data['id']}  (saved to .env as VAPI_ASSISTANT_ID)")
    print(f"  tools point to: {public_url.rstrip('/')}/vapi/tools")
    print(f"  live transfer: {'on -> ' + transfer if transfer else 'off (transfer_to_human logs only)'}")
    print("Open https://dashboard.vapi.ai/assistants, select it, and click 'Talk to Assistant' to test.")


if __name__ == "__main__":
    main()
