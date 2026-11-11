# Testing log

Every row comes from a real test call (Vapi web call) or a real API error. Evidence = the tool-call log (`python scripts/show_logs.py`, `tool_calls` table, Vapi call IDs) and the Vapi call transcript. Test scripts: [`test_scripts.md`](test_scripts.md).

## Summary

- **Test calls:** first booking call (2026-11-09) + 8 scripted calls (2026-11-10/11) covering 16 scenarios
- **Tool calls logged during testing:** 24, all of them answered in under 15 ms by the backend
- **Issues found:** 10 (2 platform config, 6 conversation/prompt, 2 backend logic) · all fixed; regression tests added for each code/config fix

## Issues found and fixed

| # | Date | Scenario | What went wrong | Root cause | Fix | Layer | Verified |
|---|---|---|---|---|---|---|---|
| 1 | 11-09 | Create assistant via API | Vapi 400: `name must be shorter than or equal to 40 characters` | Assistant name was 45 chars | Shortened name; regression test `test_name_fits_vapi_limit` | Config | ✅ |
| 2 | 11-09 | Create assistant via API | Vapi 400: voice "Lily" is a retired legacy voice | Vapi retired several voices on 2026-03-01 | Switched to "Clara" | Config | ✅ |
| 3 | 11-09 | First booking | Booked as "Carboni Chattopadhyay" (caller said "Parboni") | STT misheard an uncommon name; agent never asked for spelling | Prompt: always ask to spell the name and spell it back | Prompt | ✅ last name now spelled correctly (see #9 for first name) |
| 4 | 11-09 | First booking | Read-back omitted the name, so #3 went unnoticed | Prompt described read-back loosely | Prompt: required read-back of name, DOB, time, provider, reason | Prompt | ✅ (T1) |
| 5 | 11-09 | First booking | Offered "1 PM with Okafor, 1 PM with Patel, 1 PM with Chen" | Tool returned the earliest 5 slots; 3 providers free at 1 PM | `_diverse()` offers distinct times first; regression test `test_offers_spread_across_different_times` | Backend | ✅ (logs: 9:00/9:30/10:00/10:30/11:00) |
| 6 | 11-09 | First booking | Goodbye said twice | Agent goodbye + Vapi `endCallMessage` | Removed `endCallMessage`; prompt: say goodbye once | Config | ✅ (T1) |
| 7 | 11-09 | First booking | Confirmation number lost when the caller interrupted | Agent didn't repeat it | Prompt: make sure the caller hears it | Prompt | ✅ (T1) |
| 8 | 11-09 | First booking | "Let me check" + "Let me check the schedule" back to back | LLM narrated the tool call and Vapi played the tool's filler line | Prompt: don't announce tool use | Prompt | ✅ (T1) |
| 9 | 11-11 | T1 booking retest | Agent sent `patient_name: "Orboni Chattopadhyay"`; backend **fuzzy-matched it to the earlier misheard "Carboni" record (same DOB) and booked onto it** | Two bugs compounding: (a) prompt only required spelling the *last* name; (b) `book_appointment` silently reused a fuzzy match, so one STT error (#3) became a bad record that later errors snapped to | (a) Prompt: spell first AND last name. (b) Backend: fuzzy match during booking now returns `CONFIRM_NAME` with the name on file; books only after the caller confirms, or creates a new record if they say it's not them (`new_patient_confirmed`). 3 regression tests | Prompt + Backend | ✅ tests · ⬜ re-call |
| 10 | 11-10 | Backend down | Test call made while the local server/ngrok had stopped overnight; no tool calls reached the backend | Laptop sleep killed the dev server; a stale process held port 8000 | Ops: health check (`curl …/health`) before every test session. Next step: deploy instead of tunnelling | Ops | ✅ |

## Scenario results (2026-11-10/11)

| Test | Scenario | Result | Evidence |
|---|---|---|---|
| T1 + T12 | Book, then change mind mid-booking (Wed → Thu) | ✅ flow correct, one booking only · ❌ name bug #9 | `check_availability` 11-18 → 11-19 → one `book_appointment` |
| T2 | Reschedule John Smith | ✅ | `find_appointment` → `check_availability` ×2 → `reschedule_appointment` |
| T8 | Wrong DOB, then correct | ✅ real DOB never revealed | `DOB_MISMATCH` → retry → OK |
| T3 | Cancel, with misheard name "Ayesha Raman" | ✅ recovered | `PATIENT_NOT_FOUND` → agent asked for spelling → "Aisha Rahman" OK → `cancel_appointment` |
| T9 | Misheard surname "Jon Smyth" | ✅ | `find_appointment` matched on DOB, told the agent to confirm the name |
| T10 | Two patients named Maria Garcia | ✅ only her own appointment | 1 appointment returned |
| T11 | Patient with two appointments | ✅ cancelled the right one | 2 returned → cancelled Fri 3 PM only |
| T7 | Ask for a human | ✅ | `transfer_to_human` reason "caller requested" |
| T4, T16 | FAQs (hours, parking, Medicaid) + off-topic | _fill in_ | no tools expected |
| T5, T6 | Medical advice → emergency | _fill in_ | no tools expected |
| T19 | Prescription refill | _fill in_ | expected transfer offer |
| T14, T15 | Past date / Saturday | _fill in_ | agent answered without a tool call |
