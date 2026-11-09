"""One section per tool. Each test name reads like a scenario a caller could create."""
from datetime import datetime

from tests.conftest import TOMORROW


def err(res):
    assert res["ok"] is False, res
    return res["error"]["code"]


# ---------------------------------------------------------------- check_availability

class TestCheckAvailability:
    def test_returns_short_list_of_open_slots_with_spoken_text(self, call):
        res = call("check_availability", date=TOMORROW)
        assert res["ok"]
        assert 0 < len(res["slots"]) <= 5
        assert res["total_open"] >= len(res["slots"])
        s = res["slots"][0]
        assert {"slot_id", "provider", "start", "spoken"} <= s.keys()
        assert s["spoken"].startswith("Tuesday, November 10 at")

    def test_past_date_is_rejected(self, call):
        assert err(call("check_availability", date="2026-11-02")) == "DATE_IN_PAST"

    def test_natural_language_date_is_rejected_with_hint(self, call):
        res = call("check_availability", date="next tuesday")
        assert err(res) == "INVALID_DATE"
        assert "YYYY-MM-DD" in res["error"]["agent_hint"]

    def test_weekend_suggests_next_open_day(self, call):
        res = call("check_availability", date="2026-11-14")  # Saturday
        assert res["ok"] and res["slots"] == []
        assert res["next_available_date"] == "2026-11-16"
        assert "weekends" in res["message"]

    def test_provider_filter_with_title(self, call):
        res = call("check_availability", date=TOMORROW, provider="Dr. Patel")
        assert res["provider"] == "Dr. Maya Patel"
        assert all(s["provider"] == "Dr. Maya Patel" for s in res["slots"])

    def test_provider_fuzzy_match_for_misheard_name(self, call):
        res = call("check_availability", date=TOMORROW, provider="doctor okafur")
        assert res["provider"] == "Dr. James Okafor"

    def test_unknown_provider_lists_real_ones(self, call):
        res = call("check_availability", date=TOMORROW, provider="Dr. House")
        assert err(res) == "PROVIDER_NOT_FOUND"
        assert "Dr. Maya Patel" in res["providers"]

    def test_afternoon_filter(self, call):
        res = call("check_availability", date=TOMORROW, time_of_day="afternoon")
        assert res["slots"] and all(s["start"][11:16] >= "12:00" for s in res["slots"])

    def test_today_only_offers_future_times(self, call, frozen_now):
        frozen_now["now"] = datetime(2026, 11, 9, 14, 0)
        res = call("check_availability", date="2026-11-09")
        assert all(s["start"] > "2026-11-09T14:00" for s in res["slots"])

    def test_booked_slot_is_not_offered(self, call):
        res = call("check_availability", date="2026-11-11", provider="Patel")
        assert "2026-11-11T10:00" not in [s["start"] for s in res["slots"]]  # John Smith's


# ---------------------------------------------------------------- book_appointment

class TestBookAppointment:
    def test_new_patient_books_and_slot_disappears(self, call, open_slot):
        slot = open_slot()
        res = call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                   slot_id=slot["slot_id"], reason="checkup")
        assert res["ok"] and res["patient_status"] == "new"
        assert res["appointment_id"] > 0
        again = call("check_availability", date=TOMORROW)
        assert slot["slot_id"] not in [s["slot_id"] for s in again["slots"]]

    def test_existing_patient_exact_match(self, call, open_slot):
        res = call("book_appointment", patient_name="john smith", dob="1985-03-14",
                   slot_id=open_slot()["slot_id"], reason="cough")
        assert res["patient_status"] == "existing" and res["patient_name"] == "John Smith"

    def test_mumbled_name_matches_existing_patient_by_dob(self, call, open_slot):
        res = call("book_appointment", patient_name="Jon Smith", dob="1985-03-14",
                   slot_id=open_slot()["slot_id"], reason="cough")
        assert res["patient_status"] == "existing" and res["name_matched_fuzzily"] is True

    def test_double_booking_returns_slot_taken_with_alternatives(self, call, open_slot):
        slot = open_slot()
        call("book_appointment", patient_name="A Person", dob="1980-01-01", slot_id=slot["slot_id"], reason="x")
        res = call("book_appointment", patient_name="B Person", dob="1981-01-01", slot_id=slot["slot_id"], reason="y")
        assert err(res) == "SLOT_TAKEN"
        alt_ids = [a["slot_id"] for a in res["alternatives"]]
        assert alt_ids and slot["slot_id"] not in alt_ids

    def test_invented_slot_id(self, call):
        assert err(call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                        slot_id=999999, reason="checkup")) == "SLOT_NOT_FOUND"

    def test_blocked_slot_cannot_be_booked(self, call, conn):
        blocked = conn.execute("SELECT id FROM slots WHERE is_blocked = 1 LIMIT 1").fetchone()["id"]
        assert err(call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                        slot_id=blocked, reason="checkup")) == "SLOT_TAKEN"

    def test_missing_reason_field(self, call, open_slot):
        res = call("book_appointment", patient_name="Dana Lee", dob="1999-04-02", slot_id=open_slot()["slot_id"])
        assert err(res) == "INVALID_INPUT"
        assert "reason" in res["error"]["message"]

    def test_blank_reason(self, call, open_slot):
        assert err(call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                        slot_id=open_slot()["slot_id"], reason="   ")) == "MISSING_FIELD"

    def test_future_dob(self, call, open_slot):
        assert err(call("book_appointment", patient_name="Dana Lee", dob="2030-01-01",
                        slot_id=open_slot()["slot_id"], reason="checkup")) == "INVALID_DOB"

    def test_slot_id_as_string_is_accepted(self, call, open_slot):
        res = call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                   slot_id=str(open_slot()["slot_id"]), reason="checkup")
        assert res["ok"]

    def test_slot_in_past(self, call, open_slot, frozen_now):
        slot = open_slot()
        frozen_now["now"] = datetime(2026, 11, 10, 17, 0)
        assert err(call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                        slot_id=slot["slot_id"], reason="checkup")) == "DATE_IN_PAST"


# ---------------------------------------------------------------- find_appointment

class TestFindAppointment:
    def test_finds_upcoming_appointment(self, call):
        res = call("find_appointment", patient_name="John Smith", dob="1985-03-14")
        assert res["ok"] and len(res["appointments"]) == 1
        assert res["appointments"][0]["spoken"] == "Wednesday, November 11 at 10 AM with Dr. Maya Patel"

    def test_apostrophe_name_variants(self, call):
        for variant in ("Robert O'Brien", "robert obrien", "Robert O Brien"):
            res = call("find_appointment", patient_name=variant, dob="1958-09-09")
            assert res["ok"] and len(res["appointments"]) == 2, variant

    def test_same_name_different_people(self, call):
        res = call("find_appointment", patient_name="Maria Garcia", dob="1972-11-05")
        assert [a["start"] for a in res["appointments"]] == ["2026-11-13T09:30"]

    def test_dob_mismatch_does_not_leak_real_dob(self, call):
        res = call("find_appointment", patient_name="John Smith", dob="1985-03-15")
        assert err(res) == "DOB_MISMATCH"
        assert "1985-03-14" not in str(res)

    def test_unknown_patient(self, call):
        assert err(call("find_appointment", patient_name="Nobody Here", dob="1990-01-01")) == "PATIENT_NOT_FOUND"

    def test_patient_with_no_appointments(self, call):
        res = call("find_appointment", patient_name="Wei Zhang", dob="1995-12-01")
        assert res["ok"] and res["appointments"] == []
        assert "no upcoming" in res["message"]

    def test_past_appointments_are_hidden(self, call, frozen_now):
        frozen_now["now"] = datetime(2026, 11, 12, 0, 0)  # after John's Wed appt
        res = call("find_appointment", patient_name="John Smith", dob="1985-03-14")
        assert res["appointments"] == []


# ---------------------------------------------------------------- reschedule_appointment

def _johns_appt(call):
    return call("find_appointment", patient_name="John Smith", dob="1985-03-14")["appointments"][0]


class TestReschedule:
    def test_reschedule_moves_and_frees_old_slot(self, call, open_slot, conn):
        appt = _johns_appt(call)
        old_slot = conn.execute("SELECT slot_id FROM appointments WHERE id = ?",
                                (appt["appointment_id"],)).fetchone()["slot_id"]
        new = open_slot()
        res = call("reschedule_appointment", appointment_id=appt["appointment_id"], new_slot_id=new["slot_id"])
        assert res["ok"] and res["new_slot"]["slot_id"] == new["slot_id"]
        assert "Wednesday, November 11" in res["old_time"]
        offered = call("check_availability", date="2026-11-11", provider="Patel")["total_open"]
        assert offered > 0
        # Old slot is open again: booking it must succeed
        assert call("book_appointment", patient_name="Dana Lee", dob="1999-04-02",
                    slot_id=old_slot, reason="checkup")["ok"]

    def test_reschedule_to_taken_slot_leaves_original_unchanged(self, call, open_slot):
        appt = _johns_appt(call)
        taken = open_slot()
        call("book_appointment", patient_name="Dana Lee", dob="1999-04-02", slot_id=taken["slot_id"], reason="x")
        res = call("reschedule_appointment", appointment_id=appt["appointment_id"], new_slot_id=taken["slot_id"])
        assert err(res) == "SLOT_TAKEN"
        assert _johns_appt(call)["start"] == "2026-11-11T10:00"

    def test_same_slot(self, call, conn):
        appt = _johns_appt(call)
        slot_id = conn.execute("SELECT slot_id FROM appointments WHERE id = ?",
                               (appt["appointment_id"],)).fetchone()["slot_id"]
        assert err(call("reschedule_appointment", appointment_id=appt["appointment_id"],
                        new_slot_id=slot_id)) == "SAME_SLOT"

    def test_unknown_appointment(self, call, open_slot):
        assert err(call("reschedule_appointment", appointment_id=9999,
                        new_slot_id=open_slot()["slot_id"])) == "APPOINTMENT_NOT_FOUND"


# ---------------------------------------------------------------- cancel_appointment

class TestCancel:
    def test_cancel_then_slot_reopens(self, call, conn):
        appt = _johns_appt(call)
        res = call("cancel_appointment", appointment_id=appt["appointment_id"])
        assert res["ok"] and "Wednesday, November 11" in res["cancelled"]
        assert call("find_appointment", patient_name="John Smith", dob="1985-03-14")["appointments"] == []
        starts = [s["start"] for s in call("check_availability", date="2026-11-11", provider="Patel")["slots"]]
        assert "2026-11-11T10:00" in starts

    def test_cancel_twice(self, call):
        appt_id = _johns_appt(call)["appointment_id"]
        call("cancel_appointment", appointment_id=appt_id)
        assert err(call("cancel_appointment", appointment_id=appt_id)) == "APPOINTMENT_ALREADY_CANCELLED"

    def test_cannot_cancel_past_appointment(self, call, frozen_now):
        appt_id = _johns_appt(call)["appointment_id"]
        frozen_now["now"] = datetime(2026, 11, 12, 9, 0)
        assert err(call("cancel_appointment", appointment_id=appt_id)) == "APPOINTMENT_IN_PAST"

    def test_reschedule_cancelled_appointment(self, call, open_slot):
        appt_id = _johns_appt(call)["appointment_id"]
        call("cancel_appointment", appointment_id=appt_id)
        assert err(call("reschedule_appointment", appointment_id=appt_id,
                        new_slot_id=open_slot()["slot_id"])) == "APPOINTMENT_ALREADY_CANCELLED"


# ---------------------------------------------------------------- transfer_to_human

class TestTransfer:
    def test_transfer_is_recorded(self, call, conn):
        res = call("transfer_to_human", reason="caller asked for a person")
        assert res["ok"]
        row = conn.execute("SELECT reason FROM transfers WHERE id = ?", (res["transfer_id"],)).fetchone()
        assert row["reason"] == "caller asked for a person"

    def test_transfer_requires_reason(self, call):
        assert err(call("transfer_to_human")) == "INVALID_INPUT"


# ---------------------------------------------------------------- logging

class TestLogging:
    def test_every_call_is_logged_including_errors(self, call, client, conn):
        call("check_availability", date=TOMORROW)
        call("find_appointment", patient_name="John Smith", dob="1985-03-15")  # DOB mismatch
        rows = conn.execute("SELECT tool, ok, error_code, inputs FROM tool_calls ORDER BY id").fetchall()
        assert [(r["tool"], r["ok"], r["error_code"]) for r in rows] == [
            ("check_availability", 1, None),
            ("find_appointment", 0, "DOB_MISMATCH"),
        ]
        logs = client.get("/logs?errors_only=true").json()
        assert len(logs) == 1 and logs[0]["inputs"]["dob"] == "1985-03-15"

    def test_unknown_tool_is_404_on_rest(self, client):
        assert client.post("/tools/drop_tables", json={}).status_code == 404
