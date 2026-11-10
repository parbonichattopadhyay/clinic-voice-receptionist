"""Builds the Vapi assistant config from code.

The tool parameter schemas are generated from the same Pydantic models the backend
uses to validate inputs (app/models.py), so the agent's view of each tool and the
server's validation can't drift apart.
"""
from __future__ import annotations

import copy
from pathlib import Path

from app.models import TOOL_MODELS

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "system_prompt.md"

ASSISTANT_NAME = "Riverside Receptionist (DEMO)"  # Vapi limit: 40 chars
FIRST_MESSAGE = ("Thanks for calling Riverside Family Medicine. This is Riley, the clinic's virtual assistant. "
                 "How can I help you today?")

# What each tool is for, written for the LLM. Descriptions are effectively prompt text.
TOOL_DESCRIPTIONS = {
    "check_availability": (
        "Find open appointment times on a specific date. Returns up to 5 slots with a slot_id and a "
        "'spoken' description to read aloud. If the date has no openings, returns next_available_date."),
    "book_appointment": (
        "Book an appointment in a slot from check_availability. Only call after reading the details back "
        "to the caller and getting a clear yes. Creates the patient record if they're new."),
    "find_appointment": (
        "Verify a caller by full name and date of birth and list their upcoming appointments. "
        "Required before rescheduling or cancelling."),
    "reschedule_appointment": (
        "Move an existing appointment (appointment_id from find_appointment) to a new slot "
        "(slot_id from check_availability). Only call after the caller confirms."),
    "cancel_appointment": (
        "Cancel an appointment (appointment_id from find_appointment). Only call after the caller confirms."),
    "transfer_to_human": (
        "Record that the caller needs a human (front desk) and why. Call this whenever you hand the caller "
        "off to a person."),
}

# Short filler lines Vapi speaks while the tool runs, so the caller never hears dead air.
TOOL_FILLERS = {
    "check_availability": "Let me check the schedule.",
    "book_appointment": "Booking that now.",
    "find_appointment": "Let me look that up.",
    "reschedule_appointment": "One moment while I move that.",
    "cancel_appointment": "One moment.",
}


def clean_schema(schema: dict) -> dict:
    """Pydantic JSON schema -> plain OpenAI-style function parameters.

    Drops 'title'/'default', and collapses Optional[X] (anyOf [X, null]) to X,
    since an optional field is already expressed by leaving it out of 'required'.
    """
    s = copy.deepcopy(schema)
    s.pop("title", None)
    props = {}
    for name, prop in s.get("properties", {}).items():
        prop = dict(prop)
        prop.pop("title", None)
        prop.pop("default", None)
        if "anyOf" in prop:
            non_null = [p for p in prop.pop("anyOf") if p.get("type") != "null"]
            if len(non_null) == 1:
                prop.update(non_null[0])
        props[name] = prop
    return {"type": "object", "properties": props, "required": s.get("required", [])}


def function_tools(server_url: str) -> list[dict]:
    tools = []
    for name, model in TOOL_MODELS.items():
        tool = {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": clean_schema(model.model_json_schema()),
            },
            "server": {"url": server_url},
        }
        if name in TOOL_FILLERS:
            tool["messages"] = [{"type": "request-start", "content": TOOL_FILLERS[name]}]
        tools.append(tool)
    return tools


def build_assistant(public_url: str, transfer_number: str | None = None,
                    model: str = "gpt-4.1", voice_id: str = "Clara") -> dict:
    server_url = public_url.rstrip("/") + "/vapi/tools"
    tools = function_tools(server_url)
    tools.append({"type": "endCall"})
    if transfer_number:
        tools.append({
            "type": "transferCall",
            "destinations": [{
                "type": "number",
                "number": transfer_number,
                "description": "Riverside Family Medicine front desk",
            }],
        })

    return {
        "name": ASSISTANT_NAME,
        "firstMessage": FIRST_MESSAGE,
        "model": {
            "provider": "openai",
            "model": model,
            "temperature": 0.3,
            "messages": [{"role": "system", "content": PROMPT_PATH.read_text()}],
            "tools": tools,
        },
        "voice": {"provider": "vapi", "voiceId": voice_id},
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en"},
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 600,
    }
