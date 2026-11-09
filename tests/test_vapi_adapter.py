"""The /vapi/tools webhook: Vapi's request shape in, Vapi's response shape out."""
import json

from app import config, tools
from tests.conftest import TOMORROW


def vapi_body(*tool_calls, call_id="call-test-123"):
    return {"message": {"type": "tool-calls", "call": {"id": call_id}, "toolCallList": list(tool_calls)}}


def tc(id_, name, args, shape="function"):
    if shape == "function":  # arguments nested under "function", sometimes as a JSON string
        return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    return {"id": id_, "name": name, "arguments": args}  # flat shape


def results(resp):
    assert resp.status_code == 200, resp.text
    return {r["toolCallId"]: json.loads(r["result"]) for r in resp.json()["results"]}


def test_function_shape_with_string_arguments(client):
    out = results(client.post("/vapi/tools", json=vapi_body(tc("t1", "check_availability", {"date": TOMORROW}))))
    assert out["t1"]["ok"] and out["t1"]["slots"]


def test_flat_shape(client):
    out = results(client.post("/vapi/tools", json=vapi_body(
        tc("t1", "find_appointment", {"patient_name": "John Smith", "dob": "1985-03-14"}, shape="flat"))))
    assert out["t1"]["appointments"]


def test_result_is_single_line_string(client):
    resp = client.post("/vapi/tools", json=vapi_body(tc("t1", "check_availability", {"date": TOMORROW})))
    assert "\n" not in resp.json()["results"][0]["result"]


def test_multiple_calls_each_get_a_result(client):
    out = results(client.post("/vapi/tools", json=vapi_body(
        tc("a", "check_availability", {"date": TOMORROW}),
        tc("b", "find_appointment", {"patient_name": "Wei Zhang", "dob": "1995-12-01"}),
    )))
    assert set(out) == {"a", "b"}


def test_errors_still_return_200_with_hint(client):
    out = results(client.post("/vapi/tools", json=vapi_body(tc("t1", "check_availability", {"date": "2020-01-01"}))))
    assert out["t1"]["ok"] is False
    assert out["t1"]["error"]["code"] == "DATE_IN_PAST"
    assert out["t1"]["error"]["agent_hint"]


def test_unknown_tool_name_is_a_recoverable_error(client):
    out = results(client.post("/vapi/tools", json=vapi_body(tc("t1", "delete_everything", {}))))
    assert out["t1"]["error"]["code"] == "UNKNOWN_TOOL"


def test_crash_becomes_internal_error_not_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db exploded")
    monkeypatch.setitem(tools.TOOLS, "check_availability", boom)
    out = results(client.post("/vapi/tools", json=vapi_body(tc("t1", "check_availability", {"date": TOMORROW}))))
    assert out["t1"]["error"]["code"] == "INTERNAL_ERROR"


def test_logs_capture_vapi_call_id(client, conn):
    client.post("/vapi/tools", json=vapi_body(tc("t1", "check_availability", {"date": TOMORROW}), call_id="abc"))
    row = conn.execute("SELECT call_id, source FROM tool_calls").fetchone()
    assert (row["call_id"], row["source"]) == ("abc", "vapi")
    assert client.get("/logs?call_id=abc").json()[0]["tool"] == "check_availability"


def test_other_message_types_are_ignored(client):
    resp = client.post("/vapi/tools", json={"message": {"type": "status-update", "status": "in-progress"}})
    assert resp.status_code == 200 and resp.json() == {}


def test_secret_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "VAPI_SECRET", "s3cret")
    body = vapi_body(tc("t1", "check_availability", {"date": TOMORROW}))
    assert client.post("/vapi/tools", json=body).status_code == 401
    assert client.post("/vapi/tools", json=body, headers={"x-vapi-secret": "s3cret"}).status_code == 200
    assert client.post("/vapi/tools", json=body, headers={"Authorization": "Bearer s3cret"}).status_code == 200
