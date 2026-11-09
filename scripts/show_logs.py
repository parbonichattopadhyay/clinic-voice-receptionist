"""Print recent tool calls from the log table — your main debugging view.

Usage:
  python scripts/show_logs.py                 # last 20 calls
  python scripts/show_logs.py -n 50 --errors  # last 50 failures only
  python scripts/show_logs.py --call <vapi_call_id>   # one phone call, in order
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--call", help="Vapi call id")
    a = ap.parse_args()

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    sql, params = "SELECT * FROM tool_calls WHERE 1=1", []
    if a.call:
        sql += " AND call_id = ?"
        params.append(a.call)
    if a.errors:
        sql += " AND ok = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(a.n)
    rows = list(reversed(conn.execute(sql, params).fetchall()))
    for r in rows:
        status = "OK " if r["ok"] else f"ERR {r['error_code']}"
        res = json.loads(r["result"])
        summary = res.get("message") or (res.get("error") or {}).get("message", "")
        print(f"[{r['ts']}] {r['source']:<4} {r['tool']:<22} {status:<28} {r['duration_ms']:>6.1f}ms")
        print(f"    in : {r['inputs']}")
        print(f"    out: {summary}")
    if not rows:
        print("No tool calls logged yet.")


if __name__ == "__main__":
    main()
