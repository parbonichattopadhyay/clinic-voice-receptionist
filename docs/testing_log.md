# Testing log

Every row comes from a real test call (Vapi web call) or a real API error. Evidence = the tool-call log (`python scripts/show_logs.py`, `tool_calls` table, Vapi call IDs) and the Vapi call transcript. Test scripts: [`test_scripts.md`](test_scripts.md).

## Summary

- **Test calls:** first booking call (2026-11-09) + 8 scripted calls (2026-11-10/11) covering 16 scenarios + 1 recorded demo call
- **Tool calls logged during testing:** 31 across 12 calls; slowest backend response 14.7 ms
- **Issues found:** 11 (5 prompt, 3 platform config, 1 backend, 1 prompt + backend, 1 ops) · regression tests added for each code/config fix

## Issues found and fixed

| # | Date | Scenario | What went wrong | Root cause | Fix | Layer | Verified |
|---|---|---|---|---|---|---|---|
| 1 | 11-09 | Create assistant via API | Vapi 400: `name must be shorter than or equal to 40 characters` | Assistant name was 45 chars | Shortened name; regression test `test_name_fits_vapi_limit` | Config | Yes |
| 2 | 11-09 | Create assistant via API | Vapi 400: voice "Lily" is a retired legacy voice | Vapi retired several voices on 2026-03-01 | Switched to "Clara" | Config | Yes |
| 3 | 11-09 | First booking | Booked as "Carboni Chattopadhyay" (caller said "Parboni") | STT misheard an uncommon name; agent never asked for spelling | Prompt: always ask to spell the name and spell it back | Prompt | Yes: last name now spelled correctly (see #9 for first name) |
| 4 | 11-09 | First booking | Read-back omitted the name, so #3 went unnoticed | Prompt described read-back loosely | Prompt: required read-back of name, DOB, time, provider, reason | Prompt | Yes (T1) |
| 5 | 11-09 | First booking | Offered "1 PM with Okafor, 1 PM with Patel, 1 PM with Chen" | Tool returned the earliest 5 slots; 3 providers free at 1 PM | `_diverse()` offers distinct times first; regression test `test_offers_spread_across_different_times` | Backend | Yes (logs: 9:00/9:30/10:00/10:30/11:00) |
| 6 | 11-09 | First booking | Goodbye said twice | Agent goodbye + Vapi `endCallMessage` | Removed `endCallMessage`; prompt: say goodbye once | Config | Yes (T1) |
| 7 | 11-09 | First booking | Confirmation number lost when the caller interrupted | Agent didn't repeat it | Prompt: make sure the caller hears it | Prompt | Yes (T1) |
| 8 | 11-09 | First booking | "Let me check" + "Let me check the schedule" back to back | LLM narrated the tool call and Vapi played the tool's filler line | Prompt: don't announce tool use | Prompt | Yes (T1) |
| 9 | 11-11 | T1 booking retest | Agent sent `patient_name: "Orboni Chattopadhyay"`; backend **fuzzy-matched it to the earlier misheard "Carboni" record (same DOB) and booked onto it** | Two bugs compounding: (a) prompt only required spelling the *last* name; (b) `book_appointment` silently reused a fuzzy match, so one STT error (#3) became a bad record that later errors snapped to | (a) Prompt: spell first AND last name. (b) Backend: fuzzy match during booking now returns `CONFIRM_NAME` with the name on file; books only after the caller confirms, or creates a new record if they say it's not them (`new_patient_confirmed`). 3 regression tests | Prompt + Backend | Yes: 3 regression tests + live call 11-11: `CONFIRM_NAME` → caller said no → new record "Parboni Chattopadhyay" |
| 10 | 11-10 | Backend down | Test call made while the local server/ngrok had stopped overnight; no tool calls reached the backend | Laptop sleep killed the dev server; a stale process held port 8000 | Ops: health check (`curl …/health`) before every test session. Next step: deploy instead of tunnelling | Ops | Yes |
| 11 | 11-11 | Demo recording: booking for "Abigail Smith" | Agent skipped asking for the spelling and went straight to DOB | LLM didn't follow the spelling rule for a common-sounding, third-party name; prompt rules are probabilistic | Prompt: spelling is a required step before the read-back, including for common names and when booking for someone else. Note: the critical safeguard (confirming similar names) is enforced in the backend, not just the prompt | Prompt | Not yet (re-test pending) |

## Scenario results (2026-11-10/11)

| Test | Scenario | Result | Evidence |
|---|---|---|---|
| T1 + T12 | Book, then change mind mid-booking (Wed → Thu) | Pass for the flow (one booking only); fail on the name (bug #9) | `check_availability` 11-18 → 11-19 → one `book_appointment` |
| T2 | Reschedule John Smith | Yes | `find_appointment` → `check_availability` ×2 → `reschedule_appointment` |
| T8 | Wrong DOB, then correct | Pass: real DOB never revealed | `DOB_MISMATCH` → retry → OK |
| T3 | Cancel, with misheard name "Ayesha Raman" | Pass: recovered | `PATIENT_NOT_FOUND` → agent asked for spelling → "Aisha Rahman" OK → `cancel_appointment` |
| T9 | Misheard surname "Jon Smyth" | Yes | `find_appointment` matched on DOB, told the agent to confirm the name |
| T10 | Two patients named Maria Garcia | Pass: only her own appointment | 1 appointment returned |
| T11 | Patient with two appointments | Pass: cancelled the right one | 2 returned → cancelled Fri 3 PM only |
| T7 | Ask for a human | Yes | `transfer_to_human` reason "caller requested" |
| T4, T16 | FAQs (hours, parking, Medicaid) + off-topic | Pass: answered from prompt; didn't invent Medicaid coverage; redirected pizza question | transcript (no tools expected) |
| T5, T6 | Medical advice → emergency | Pass: refused to advise on ibuprofen; chest pain → told to hang up and call 911 | transcript (no tools expected) |
| T19 | Prescription refill | Pass: offered front desk instead of handling it | transcript |
| T14, T15 | Past date / Saturday | Pass: declined, suggested another day | transcript (answered from prompt's date + hours) |
