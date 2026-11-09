"""Seed the database with FAKE providers, slots for the next 14 days, and test patients.

Usage:  python -m app.seed            (wipes and reseeds clinic.db)

Every name and date of birth here is invented. Several are deliberately tricky
so you can test the agent's edge cases:
  - Maria Garcia x2 with different DOBs (same name, different people)
  - Robert O'Brien (apostrophe: STT may give "OBrien" or "O Brien")
  - Wei Zhang (existing patient with no appointments)
"""
from __future__ import annotations

import os
import random
from datetime import date, datetime, time, timedelta

from . import clock, config, db
from .tools import name_key

PROVIDERS = [
    ("Dr. Maya Patel", "Patel", "Family Medicine"),
    ("Dr. James Okafor", "Okafor", "Family Medicine"),
    ("Lisa Chen, NP", "Chen", "Nurse Practitioner"),
]

# 9:00–11:30 and 1:00–4:30, 30-minute slots, weekdays only
SLOT_TIMES = [time(h, m) for h in (9, 10, 11) for m in (0, 30)] + \
             [time(h, m) for h in (13, 14, 15, 16) for m in (0, 30)]

PATIENTS = [
    ("John Smith", "1985-03-14"),
    ("Maria Garcia", "1990-07-22"),
    ("Maria Garcia", "1972-11-05"),
    ("Aisha Rahman", "2001-01-30"),
    ("Robert O'Brien", "1958-09-09"),
    ("Wei Zhang", "1995-12-01"),
]

# (patient index, provider index, nth business day from start, time, reason)
APPOINTMENTS = [
    (0, 0, 2, time(10, 0), "annual physical"),
    (1, 1, 3, time(14, 0), "blood pressure follow-up"),
    (2, 0, 4, time(9, 30), "sore throat"),
    (3, 2, 5, time(9, 30), "flu shot"),
    (4, 1, 7, time(11, 0), "medication refill visit"),
    (4, 2, 9, time(15, 0), "follow-up"),
]

BLOCKED_FRACTION = 0.30  # ~30% of slots "held" so the schedule looks realistic


def nth_business_day(start: date, n: int) -> date:
    d, count = start, 0
    while True:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d


def seed(conn, start: date | None = None, days: int = 14, rng_seed: int = 42) -> None:
    start = start or clock.now().date()
    rng = random.Random(rng_seed)

    for tbl in ("tool_calls", "transfers", "appointments", "patients", "slots", "providers"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute("DELETE FROM sqlite_sequence")

    for name, last, spec in PROVIDERS:
        conn.execute("INSERT INTO providers (name, last_name, specialty) VALUES (?, ?, ?)", (name, last, spec))

    appt_keys = {(p + 1, datetime.combine(nth_business_day(start, d), t).isoformat(timespec="minutes"))
                 for _, p, d, t, _ in APPOINTMENTS}

    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for provider_id in range(1, len(PROVIDERS) + 1):
            for t in SLOT_TIMES:
                start_iso = datetime.combine(day, t).isoformat(timespec="minutes")
                # Never block a slot we're about to put a seeded appointment in.
                blocked = 0 if (provider_id, start_iso) in appt_keys else int(rng.random() < BLOCKED_FRACTION)
                conn.execute("INSERT INTO slots (provider_id, start_time, is_blocked) VALUES (?, ?, ?)",
                             (provider_id, start_iso, blocked))

    for full_name, dob in PATIENTS:
        conn.execute("INSERT INTO patients (full_name, name_key, dob) VALUES (?, ?, ?)",
                     (full_name, name_key(full_name), dob))

    for p_idx, prov_idx, nth, t, reason in APPOINTMENTS:
        start_iso = datetime.combine(nth_business_day(start, nth), t).isoformat(timespec="minutes")
        slot = conn.execute("SELECT id FROM slots WHERE provider_id = ? AND start_time = ?",
                            (prov_idx + 1, start_iso)).fetchone()
        conn.execute("INSERT INTO appointments (patient_id, slot_id, reason) VALUES (?, ?, ?)",
                     (p_idx + 1, slot["id"], reason))
    conn.commit()


if __name__ == "__main__":
    path = config.DB_PATH
    if os.path.exists(path):
        os.remove(path)
    conn = db.connect(path)
    db.init_schema(conn)
    seed(conn)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("providers", "slots", "patients", "appointments")}
    open_slots = conn.execute(
        "SELECT COUNT(*) FROM slots WHERE is_blocked = 0 AND id NOT IN "
        "(SELECT slot_id FROM appointments WHERE status = 'scheduled')").fetchone()[0]
    print(f"Seeded {path}: {counts}, open slots: {open_slots}")
    print("Test patients (FAKE):")
    for r in conn.execute(
        """SELECT pt.full_name, pt.dob, s.start_time, pr.name AS provider FROM patients pt
           LEFT JOIN appointments a ON a.patient_id = pt.id
           LEFT JOIN slots s ON s.id = a.slot_id LEFT JOIN providers pr ON pr.id = s.provider_id
           ORDER BY pt.id, s.start_time"""):
        print(f"  {r['full_name']:<16} DOB {r['dob']}  ->  {r['start_time'] or '(no appointments)'}  {r['provider'] or ''}")
    conn.close()
