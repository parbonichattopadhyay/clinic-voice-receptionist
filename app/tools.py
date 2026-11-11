"""Business logic for every tool the voice agent can call.

Design rules (these matter for a voice agent):
  1. Never raise an unhandled exception for a caller mistake. Raise ToolError with an
     agent_hint so the LLM knows how to recover out loud.
  2. Return a `spoken` string wherever the agent will read something back, so the LLM
     doesn't have to format dates itself (it gets them wrong surprisingly often).
  3. Keep lists short. A caller can't hold 16 time slots in their head; offer a few.
  4. Never leak another patient's data (e.g., on DOB mismatch, don't reveal the real DOB).
"""
from __future__ import annotations

import difflib
import re
import sqlite3
from datetime import date, datetime, timedelta

from . import clock
from .errors import ToolError

MAX_SLOTS_OFFERED = 5
FUZZY_NAME_THRESHOLD = 0.85
LOOKAHEAD_DAYS = 21


# ---------------------------------------------------------------- helpers

def name_key(name: str) -> str:
    """'Robert O'Brien' / 'robert obrien' / 'Robert O Brien' -> 'robertobrien'."""
    return re.sub(r"[^a-z]", "", (name or "").lower())


def spoken_dt(dt: datetime) -> str:
    """datetime -> 'Tuesday, November 10 at 9:30 AM' (what the agent should say)."""
    hour = dt.strftime("%I").lstrip("0")
    minute = dt.strftime("%M")
    time_part = f"{hour} {dt.strftime('%p')}" if minute == "00" else f"{hour}:{minute} {dt.strftime('%p')}"
    return f"{dt.strftime('%A, %B')} {dt.day} at {time_part}"


def spoken_date(d: date) -> str:
    return f"{d.strftime('%A, %B')} {d.day}"


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        raise ToolError(
            "INVALID_DATE",
            f"{field} '{value}' is not a valid date in YYYY-MM-DD format.",
            f"Convert the caller's {field.replace('_', ' ')} to YYYY-MM-DD and call the tool again. "
            "If you're unsure what they meant, ask them to repeat it.",
        )


def parse_dob(value: str) -> date:
    dob = parse_date(value, "dob")
    today = clock.now().date()
    if dob > today:
        raise ToolError(
            "INVALID_DOB",
            "Date of birth is in the future.",
            "Politely ask the caller to repeat their date of birth, including the year.",
        )
    if dob.year < today.year - 120:
        raise ToolError(
            "INVALID_DOB",
            "Date of birth is more than 120 years ago.",
            "You may have misheard the year. Ask the caller to repeat their date of birth.",
        )
    return dob


def require_text(value, field: str, max_len: int = 200) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text:
        raise ToolError(
            "MISSING_FIELD",
            f"{field} is required.",
            f"Ask the caller for their {field.replace('_', ' ')} before calling this tool.",
        )
    return text[:max_len]


def _slot_row(conn, slot_id: int):
    return conn.execute(
        """SELECT s.id, s.start_time, s.is_blocked, s.provider_id, p.name AS provider
           FROM slots s JOIN providers p ON p.id = s.provider_id WHERE s.id = ?""",
        (slot_id,),
    ).fetchone()


def _slot_dict(row) -> dict:
    start = datetime.fromisoformat(row["start_time"])
    return {
        "slot_id": row["id"],
        "provider": row["provider"],
        "start": row["start_time"],
        "spoken": f"{spoken_dt(start)} with {row['provider']}",
    }


def _open_slots(conn, *, day: date | None = None, provider_id: int | None = None,
                time_of_day: str | None = None, after: datetime | None = None,
                until: date | None = None, limit: int | None = None) -> list[sqlite3.Row]:
    """Open = not blocked, no scheduled appointment, and in the future."""
    sql = """
        SELECT s.id, s.start_time, s.provider_id, p.name AS provider
        FROM slots s
        JOIN providers p ON p.id = s.provider_id
        WHERE s.is_blocked = 0
          AND NOT EXISTS (SELECT 1 FROM appointments a
                          WHERE a.slot_id = s.id AND a.status = 'scheduled')
          AND s.start_time > ?
    """
    params: list = [(after or clock.now()).isoformat(timespec="minutes")]
    if day:
        sql += " AND substr(s.start_time, 1, 10) = ?"
        params.append(day.isoformat())
    if until:
        sql += " AND substr(s.start_time, 1, 10) <= ?"
        params.append(until.isoformat())
    if provider_id:
        sql += " AND s.provider_id = ?"
        params.append(provider_id)
    if time_of_day == "morning":
        sql += " AND substr(s.start_time, 12, 5) < '12:00'"
    elif time_of_day == "afternoon":
        sql += " AND substr(s.start_time, 12, 5) >= '12:00'"
    sql += " ORDER BY s.start_time, p.name"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def _diverse(slots: list, n: int) -> list:
    """Pick up to n slots, preferring distinct start times.

    Without this, a 1 PM opening with three providers fills three of the offers
    with the same time (seen in the first real test call). Callers care more
    about *when* than *who*, so spread the times first, then fill.
    """
    picked, seen_times = [], set()
    for s in slots:
        if s["start_time"] not in seen_times:
            picked.append(s)
            seen_times.add(s["start_time"])
        if len(picked) == n:
            return picked
    for s in slots:
        if s not in picked:
            picked.append(s)
        if len(picked) == n:
            break
    return sorted(picked, key=lambda s: s["start_time"])


def resolve_provider(conn, provider: str | None):
    """'Dr. Patel', 'doctor patel', 'Patel', 'Maya Patel' -> provider row. None if not given."""
    if not provider or not provider.strip():
        return None
    q = re.sub(r"\b(dr|doctor|np|nurse|practitioner)\b\.?", " ", provider.lower())
    q_key = name_key(q)
    rows = conn.execute("SELECT id, name, last_name, specialty FROM providers").fetchall()
    for r in rows:
        if q_key in (name_key(r["last_name"]), name_key(r["name"].replace("Dr.", ""))) or \
           name_key(r["last_name"]) in q_key:
            return r
    # Fuzzy fallback for transcription errors ("Dr. Patell", "Okafur")
    best = max(rows, key=lambda r: difflib.SequenceMatcher(None, q_key, name_key(r["last_name"])).ratio())
    if difflib.SequenceMatcher(None, q_key, name_key(best["last_name"])).ratio() >= 0.75:
        return best
    names = ", ".join(r["name"] for r in rows)
    raise ToolError(
        "PROVIDER_NOT_FOUND",
        f"No provider matching '{provider}'.",
        f"Tell the caller our providers are {names}, and ask which they'd like, or offer the first available.",
        providers=[r["name"] for r in rows],
    )


def _find_patient(conn, patient_name: str, dob: date):
    """Return (patient_row, match_type) or (None, reason).

    match_type: 'exact' | 'fuzzy'   reason: 'dob_mismatch' | 'not_found'
    """
    key = name_key(patient_name)
    row = conn.execute(
        "SELECT * FROM patients WHERE name_key = ? AND dob = ?", (key, dob.isoformat())
    ).fetchone()
    if row:
        return row, "exact"

    # Speech-to-text mangles names ("Jon Smyth"). DOB is transcribed far more reliably,
    # so match DOB exactly and the name fuzzily among patients with that DOB.
    same_dob = conn.execute("SELECT * FROM patients WHERE dob = ?", (dob.isoformat(),)).fetchall()
    scored = sorted(
        ((difflib.SequenceMatcher(None, key, p["name_key"]).ratio(), p) for p in same_dob),
        key=lambda t: t[0], reverse=True,
    )
    if scored and scored[0][0] >= FUZZY_NAME_THRESHOLD:
        return scored[0][1], "fuzzy"

    if conn.execute("SELECT 1 FROM patients WHERE name_key = ?", (key,)).fetchone():
        return None, "dob_mismatch"
    return None, "not_found"


# ---------------------------------------------------------------- tools

def check_availability(conn, date_str: str, provider: str | None = None,
                       time_of_day: str | None = None) -> dict:
    day = parse_date(date_str, "date")
    today = clock.now().date()
    if day < today:
        raise ToolError(
            "DATE_IN_PAST",
            f"{day.isoformat()} is in the past (today is {today.isoformat()}).",
            "Tell the caller that date has already passed and ask what upcoming day works. "
            "If they said a weekday like 'Tuesday', they probably mean the NEXT one.",
            today=today.isoformat(),
        )
    tod = (time_of_day or "").strip().lower() or None
    if tod not in (None, "morning", "afternoon", "any"):
        tod = None
    if tod == "any":
        tod = None

    prov = resolve_provider(conn, provider)
    prov_id = prov["id"] if prov else None
    slots = _open_slots(conn, day=day, provider_id=prov_id, time_of_day=tod)

    result = {
        "ok": True,
        "date": day.isoformat(),
        "date_spoken": spoken_date(day),
        "provider": prov["name"] if prov else None,
        "time_of_day": tod,
        "total_open": len(slots),
        "slots": [_slot_dict(s) for s in _diverse(slots, MAX_SLOTS_OFFERED)],
    }

    if slots:
        more = f" ({len(slots)} open in total; offer two or three, not all)" if len(slots) > 3 else ""
        result["message"] = f"Open times on {spoken_date(day)}{more}."
        return result

    # Nothing that day: find the next date that does have something, so the agent
    # can offer a concrete alternative instead of a dead end.
    nxt = _open_slots(conn, provider_id=prov_id, time_of_day=tod,
                      after=datetime.combine(day + timedelta(days=1), datetime.min.time()),
                      until=day + timedelta(days=LOOKAHEAD_DAYS), limit=1)
    why = "the clinic is closed on weekends" if day.weekday() >= 5 else "there are no open times"
    if nxt:
        nd = datetime.fromisoformat(nxt[0]["start_time"]).date()
        result["next_available_date"] = nd.isoformat()
        result["message"] = (f"No openings on {spoken_date(day)} because {why}. "
                             f"The next date with openings is {spoken_date(nd)}.")
    else:
        result["next_available_date"] = None
        result["message"] = (f"No openings on {spoken_date(day)} because {why}, and nothing in the next "
                             f"{LOOKAHEAD_DAYS} days. Offer to transfer the caller to the front desk.")
    return result


def book_appointment(conn, patient_name: str, dob: str, slot_id: int, reason: str,
                     new_patient_confirmed: bool = False) -> dict:
    patient_name = require_text(patient_name, "patient_name", 100)
    reason = require_text(reason, "reason", 200)
    dob_d = parse_dob(dob)
    if len(name_key(patient_name)) < 2:
        raise ToolError("MISSING_FIELD", "Patient name is too short.",
                        "Ask the caller to say and spell their full name.")

    slot = _slot_row(conn, int(slot_id))
    if not slot:
        raise ToolError("SLOT_NOT_FOUND", f"Slot {slot_id} does not exist.",
                        "Call check_availability again and use a slot_id from its results. Never invent slot ids.")
    start = datetime.fromisoformat(slot["start_time"])
    if start <= clock.now():
        raise ToolError("DATE_IN_PAST", "That time has already passed.",
                        "Call check_availability for an upcoming date and offer new times.")
    if slot["is_blocked"]:
        raise ToolError("SLOT_TAKEN", "That time is not available.",
                        "Apologize, and offer one of the alternatives listed.",
                        alternatives=_alternatives(conn, slot))

    patient, match = _find_patient(conn, patient_name, dob_d)
    if match == "fuzzy" and new_patient_confirmed:
        patient = None  # caller said the similar record is NOT them
    elif match == "fuzzy":
        # Found in testing: a misheard name ("Orboni") fuzzy-matched an earlier misheard
        # record ("Carboni") and the booking silently went onto the wrong record.
        # Never attach a booking to a fuzzy match without the caller confirming the name.
        raise ToolError(
            "CONFIRM_NAME",
            f"No exact match, but a patient with this date of birth is on file as {patient['full_name']}.",
            f"Ask: \"I have your name as {patient['full_name']}, is that right?\" If yes, call book_appointment "
            f"again with patient_name exactly \"{patient['full_name']}\". If no, ask them to spell their full "
            "name and call again with the corrected name and new_patient_confirmed=true.",
            matched_name=patient["full_name"],
        )
    if patient is None:
        cur = conn.execute("INSERT INTO patients (full_name, name_key, dob) VALUES (?, ?, ?)",
                           (patient_name.title(), name_key(patient_name), dob_d.isoformat()))
        patient_id, patient_status, display_name = cur.lastrowid, "new", patient_name.title()
    else:
        patient_id, patient_status, display_name = patient["id"], "existing", patient["full_name"]

    try:
        cur = conn.execute("INSERT INTO appointments (patient_id, slot_id, reason) VALUES (?, ?, ?)",
                           (patient_id, slot["id"], reason))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ToolError(
            "SLOT_TAKEN",
            f"{spoken_dt(start)} with {slot['provider']} was just booked by someone else.",
            "Apologize briefly, offer one or two of the alternatives listed, and book the one the caller picks.",
            alternatives=_alternatives(conn, slot),
        )

    spoken = f"{spoken_dt(start)} with {slot['provider']}"
    return {
        "ok": True,
        "appointment_id": cur.lastrowid,
        "patient_name": display_name,
        "patient_status": patient_status,
        "name_matched_fuzzily": match == "fuzzy",
        "slot": _slot_dict(slot),
        "reason": reason,
        "message": f"Booked: {display_name}, {spoken}, for {reason}. "
                   f"Confirmation number {cur.lastrowid}.",
    }


def _alternatives(conn, slot) -> list[dict]:
    """Nearest open slots: same provider same day first, then anyone that day, then next days."""
    start = datetime.fromisoformat(slot["start_time"])
    alts = _open_slots(conn, day=start.date(), provider_id=slot["provider_id"], limit=3)
    if len(alts) < 3:
        alts += [s for s in _open_slots(conn, day=start.date(), limit=6)
                 if s["id"] not in {a["id"] for a in alts}][: 3 - len(alts)]
    if len(alts) < 3:
        later = _open_slots(conn, provider_id=slot["provider_id"],
                            after=datetime.combine(start.date() + timedelta(days=1), datetime.min.time()),
                            limit=3 - len(alts))
        alts += later
    return [_slot_dict(a) for a in alts]


def find_appointment(conn, patient_name: str, dob: str) -> dict:
    patient_name = require_text(patient_name, "patient_name", 100)
    dob_d = parse_dob(dob)
    patient, match = _find_patient(conn, patient_name, dob_d)

    if match == "dob_mismatch":
        raise ToolError(
            "DOB_MISMATCH",
            "A patient with that name exists, but the date of birth does not match.",
            "Do NOT reveal any details. Say you couldn't verify those details and ask the caller to repeat "
            "their date of birth. If it fails twice, offer to transfer them to the front desk.",
        )
    if match == "not_found":
        raise ToolError(
            "PATIENT_NOT_FOUND",
            "No patient found with that name and date of birth.",
            "Ask the caller to spell their last name and confirm their date of birth, then try once more. "
            "If still not found, they may be a new patient; offer to book a new appointment or transfer.",
        )

    rows = conn.execute(
        """SELECT a.id, a.reason, s.id AS slot_id, s.start_time, p.name AS provider
           FROM appointments a
           JOIN slots s ON s.id = a.slot_id
           JOIN providers p ON p.id = s.provider_id
           WHERE a.patient_id = ? AND a.status = 'scheduled' AND s.start_time > ?
           ORDER BY s.start_time""",
        (patient["id"], clock.now().isoformat(timespec="minutes")),
    ).fetchall()
    appts = [{
        "appointment_id": r["id"],
        "provider": r["provider"],
        "start": r["start_time"],
        "reason": r["reason"],
        "spoken": f"{spoken_dt(datetime.fromisoformat(r['start_time']))} with {r['provider']}",
    } for r in rows]

    result = {
        "ok": True,
        "patient_name": patient["full_name"],
        "name_matched_fuzzily": match == "fuzzy",
        "appointments": appts,
    }
    if match == "fuzzy":
        result["message"] = (f"Matched on date of birth with a similar name: {patient['full_name']}. "
                             "Confirm the name with the caller before continuing.")
    elif not appts:
        result["message"] = "Patient verified, but they have no upcoming appointments. Offer to book one."
    else:
        result["message"] = f"Patient verified. {len(appts)} upcoming appointment(s)."
    return result


def _active_appointment(conn, appointment_id: int):
    row = conn.execute(
        """SELECT a.*, s.start_time, s.provider_id, p.name AS provider
           FROM appointments a JOIN slots s ON s.id = a.slot_id
           JOIN providers p ON p.id = s.provider_id WHERE a.id = ?""",
        (int(appointment_id),),
    ).fetchone()
    if not row:
        raise ToolError("APPOINTMENT_NOT_FOUND", f"No appointment with id {appointment_id}.",
                        "Call find_appointment with the caller's name and date of birth to get the correct appointment_id.")
    if row["status"] == "cancelled":
        raise ToolError("APPOINTMENT_ALREADY_CANCELLED", "That appointment was already cancelled.",
                        "Tell the caller it's already cancelled and offer to book a new one.")
    if datetime.fromisoformat(row["start_time"]) <= clock.now():
        raise ToolError("APPOINTMENT_IN_PAST", "That appointment time has already passed.",
                        "Tell the caller it can't be changed because it already happened, and offer to book a new one.")
    return row


def reschedule_appointment(conn, appointment_id: int, new_slot_id: int) -> dict:
    appt = _active_appointment(conn, appointment_id)
    new_slot = _slot_row(conn, int(new_slot_id))
    if not new_slot:
        raise ToolError("SLOT_NOT_FOUND", f"Slot {new_slot_id} does not exist.",
                        "Call check_availability and use a slot_id from its results.")
    if new_slot["id"] == appt["slot_id"]:
        raise ToolError("SAME_SLOT", "That is the same time as the current appointment.",
                        "Tell the caller that's already their appointment time and ask if they want a different time.")
    new_start = datetime.fromisoformat(new_slot["start_time"])
    if new_start <= clock.now():
        raise ToolError("DATE_IN_PAST", "That time has already passed.",
                        "Call check_availability for an upcoming date.")
    if new_slot["is_blocked"]:
        raise ToolError("SLOT_TAKEN", "That time is not available.",
                        "Offer one of the alternatives listed.", alternatives=_alternatives(conn, new_slot))

    old_spoken = f"{spoken_dt(datetime.fromisoformat(appt['start_time']))} with {appt['provider']}"
    try:
        conn.execute(
            """UPDATE appointments SET slot_id = ?, previous_slot_id = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (new_slot["id"], appt["slot_id"], appt["id"]),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ToolError(
            "SLOT_TAKEN", f"{spoken_dt(new_start)} with {new_slot['provider']} was just taken.",
            "Apologize, offer one of the alternatives. The original appointment is unchanged.",
            alternatives=_alternatives(conn, new_slot),
        )
    new_spoken = f"{spoken_dt(new_start)} with {new_slot['provider']}"
    return {
        "ok": True,
        "appointment_id": appt["id"],
        "old_time": old_spoken,
        "new_slot": _slot_dict(new_slot),
        "message": f"Rescheduled from {old_spoken} to {new_spoken}.",
    }


def cancel_appointment(conn, appointment_id: int) -> dict:
    appt = _active_appointment(conn, appointment_id)
    conn.execute("UPDATE appointments SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?",
                 (appt["id"],))
    conn.commit()
    spoken = f"{spoken_dt(datetime.fromisoformat(appt['start_time']))} with {appt['provider']}"
    return {
        "ok": True,
        "appointment_id": appt["id"],
        "cancelled": spoken,
        "message": f"Cancelled the appointment on {spoken}. Ask if they'd like to rebook.",
    }


def transfer_to_human(conn, reason: str, call_id: str | None = None) -> dict:
    reason = require_text(reason, "reason", 300)
    cur = conn.execute("INSERT INTO transfers (call_id, reason) VALUES (?, ?)", (call_id, reason))
    conn.commit()
    return {
        "ok": True,
        "transfer_id": cur.lastrowid,
        "message": "Transfer logged. Tell the caller you're connecting them to the front desk now.",
    }


# Registry used by the API layer: tool name -> function
TOOLS = {
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "find_appointment": find_appointment,
    "reschedule_appointment": reschedule_appointment,
    "cancel_appointment": cancel_appointment,
    "transfer_to_human": transfer_to_human,
}
