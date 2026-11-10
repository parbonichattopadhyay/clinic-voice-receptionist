# Testing log

Every row comes from a real test call (Vapi web call) or a real API error. Evidence = the tool-call log (`python scripts/show_logs.py`) and the Vapi call transcript.

| # | Date | Scenario | What went wrong | Root cause | Fix (prompt / code / config) | Verified |
|---|---|---|---|---|---|---|
| 1 | 2026-11-09 | Setup: create assistant via API | Vapi returned 400: `name must be shorter than or equal to 40 characters` | Assistant name was 45 chars | Config: shortened name; added regression test `test_name_fits_vapi_limit` | ✅ |
| 2 | 2026-11-09 | Setup: create assistant via API | Vapi returned 400: voice "Lily" is a retired legacy voice | Vapi retired several voices on 2026-03-01 | Config: switched voice to Clara | ✅ |
| 3 | 2026-11-09 | First booking: "checkup this afternoon" at 7:25 PM | ✅ Correct: no openings today, offered tomorrow | — | — | ✅ |
| 4 | 2026-11-09 | First booking: name capture | Booked as "Carboni Chattopadhyay" (caller said "Parboni") | STT misheard an uncommon name; agent never asked for spelling | Prompt: always ask to spell last name and spell it back | ⬜ retest |
| 5 | 2026-11-09 | First booking: read-back | Read-back omitted the name, so error #4 went unnoticed | Prompt described read-back loosely; LLM shortened it | Prompt: required read-back of name, DOB, time, provider, reason | ⬜ retest |
| 6 | 2026-11-09 | First booking: offering times | Offered "1 PM with Okafor, 1 PM with Patel, 1 PM with Chen" | `check_availability` returned the first 5 slots by time; 3 providers free at 1 PM | Code: `_diverse()` picks distinct times first; regression test `test_offers_spread_across_different_times` | ⬜ retest |
| 7 | 2026-11-09 | First booking: ending | Goodbye said twice | Agent said goodbye, then Vapi `endCallMessage` repeated it | Config: removed `endCallMessage`; prompt: say goodbye once | ⬜ retest |
| 8 | 2026-11-09 | First booking: confirmation | Confirmation number never heard (caller interrupted with "okay, thank you") | Agent didn't repeat it after the interruption | Prompt: make sure the caller hears the confirmation number | ⬜ retest |
| 9 | 2026-11-09 | First booking: filler speech | "Let me check" + "Let me check the schedule" back to back | LLM narrated the tool call and Vapi played the tool's request-start message | Prompt: don't announce tool use | ⬜ retest |
