# Clinic Voice Receptionist (DEMO)

> ⚠️ **Demo project. "Riverside Family Medicine" is fictional. All patient data is fake.**

An AI phone receptionist that books, reschedules, and cancels appointments, answers FAQs, and hands off to a human. Vapi handles telephony, speech, and the LLM. This repo is the backend the agent calls: tools, validation, scheduling logic, and call logging.

*(Full README with the architecture diagram, "what I built vs. Vapi", and the testing log comes in Phase 5.)*

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed                    # creates clinic.db with fake data
uvicorn app.main:app --reload --reload-dir app --port 8000
pytest                                # 50 tests
```

API docs: http://localhost:8000/docs

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /tools/{tool_name}` | Call a tool with plain JSON args (curl / tests) |
| `POST /vapi/tools` | Vapi `tool-calls` webhook (what the voice agent hits) |
| `GET /logs?call_id=&errors_only=` | Tool-call log |
| `GET /appointments` | Debug view of the schedule |

Tools: `check_availability`, `book_appointment`, `find_appointment`, `reschedule_appointment`, `cancel_appointment`, `transfer_to_human`.

`python scripts/show_logs.py --errors` prints recent failed tool calls.
