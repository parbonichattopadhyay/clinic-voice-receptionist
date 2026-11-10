"""The Vapi assistant config is generated from code; make sure it's well-formed."""
from app.models import TOOL_MODELS
from vapi.assistant_config import build_assistant

URL = "https://example.ngrok-free.app"


def _functions(cfg):
    return {t["function"]["name"]: t for t in cfg["model"]["tools"] if t["type"] == "function"}


def test_every_backend_tool_is_registered_and_points_at_server():
    fns = _functions(build_assistant(URL))
    assert set(fns) == set(TOOL_MODELS)
    assert all(t["server"]["url"] == URL + "/vapi/tools" for t in fns.values())


def test_schemas_are_clean_openai_style():
    for name, tool in _functions(build_assistant(URL)).items():
        params = tool["function"]["parameters"]
        assert params["type"] == "object"
        text = str(params)
        assert "anyOf" not in text and "title" not in text and "default" not in text, name


def test_required_and_optional_fields():
    fns = _functions(build_assistant(URL))
    ca = fns["check_availability"]["function"]["parameters"]
    assert ca["required"] == ["date"]
    assert ca["properties"]["time_of_day"]["enum"] == ["morning", "afternoon", "any"]
    assert set(fns["book_appointment"]["function"]["parameters"]["required"]) == {
        "patient_name", "dob", "slot_id", "reason"}


def test_prompt_has_live_date_and_safety_rules():
    prompt = build_assistant(URL)["model"]["messages"][0]["content"]
    assert '{{"now" | date:' in prompt and "America/New_York" in prompt
    assert "911" in prompt and "medical advice" in prompt.lower()


def test_transfer_tool_only_when_number_given():
    types = lambda c: [t["type"] for t in c["model"]["tools"]]  # noqa: E731
    assert "transferCall" not in types(build_assistant(URL))
    assert "transferCall" in types(build_assistant(URL, transfer_number="+15551234567"))
    assert "endCall" in types(build_assistant(URL))


def test_name_fits_vapi_limit():
    # Vapi rejects assistant names over 40 characters (found on first real API call)
    assert len(build_assistant(URL)["name"]) <= 40


def test_no_automatic_end_call_message():
    # Regression: agent said goodbye, then Vapi's endCallMessage said it again.
    assert "endCallMessage" not in build_assistant(URL)
