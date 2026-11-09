"""Test fixtures: fresh temp DB per test, frozen clock, seeded fake data.

Frozen 'now' = Monday 2026-11-09 08:00 clinic time. With that start date the
seeded appointments land on:
  John Smith      1985-03-14  Wed 2026-11-11 10:00  Dr. Maya Patel
  Maria Garcia    1990-07-22  Thu 2026-11-12 14:00  Dr. James Okafor
  Maria Garcia    1972-11-05  Fri 2026-11-13 09:30  Dr. Maya Patel
  Aisha Rahman    2001-01-30  Mon 2026-11-16 09:30  Lisa Chen, NP
  Robert O'Brien  1958-09-09  Wed 2026-11-18 11:00  Dr. James Okafor
                              Fri 2026-11-20 15:00  Lisa Chen, NP
  Wei Zhang       1995-12-01  (none)
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app import clock, config, db
from app.main import app
from app.seed import seed

FROZEN_NOW = datetime(2026, 11, 9, 8, 0)
TOMORROW = "2026-11-10"


@pytest.fixture
def frozen_now(monkeypatch):
    state = {"now": FROZEN_NOW}
    monkeypatch.setattr(clock, "now", lambda: state["now"])
    return state  # tests can do frozen_now["now"] = ... to time-travel


@pytest.fixture
def client(tmp_path, monkeypatch, frozen_now):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "VAPI_SECRET", "")
    conn = db.connect(db_path)
    db.init_schema(conn)
    seed(conn, start=date(2026, 11, 9))
    conn.close()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def conn(client):
    c = db.connect(config.DB_PATH)
    yield c
    c.close()


@pytest.fixture
def call(client):
    """call('book_appointment', patient_name=..., ...) -> result dict"""
    def _call(tool, **args):
        r = client.post(f"/tools/{tool}", json=args)
        assert r.status_code == 200, r.text
        return r.json()
    return _call


@pytest.fixture
def open_slot(call):
    """Return the first open slot tomorrow (dict with slot_id, provider, start, spoken)."""
    def _open(date_str=TOMORROW, **kw):
        res = call("check_availability", date=date_str, **kw)
        assert res["ok"] and res["slots"], res
        return res["slots"][0]
    return _open
