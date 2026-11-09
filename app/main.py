"""Clinic Voice Receptionist — FastAPI backend (FICTIONAL DEMO, fake data only).

Two ways in, one code path:
  POST /tools/{tool_name}   plain JSON args — for curl, tests, and debugging
  POST /vapi/tools          Vapi's 'tool-calls' webhook format — what the voice agent hits

Both go through run_tool(), which validates, executes, and logs every call.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from . import config, db
from .errors import ToolError
from .models import TOOL_MODELS
from .tools import TOOLS

log = logging.getLogger("clinic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_schema(conn)
    conn.close()
    yield


app = FastAPI(title="Riverside Family Medicine — Voice Receptionist API (DEMO)", lifespan=lifespan)


# ---------------------------------------------------------------- core dispatcher

def _validation_to_tool_error(e: ValidationError) -> ToolError:
    problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
    return ToolError(
        "INVALID_INPUT",
        f"Invalid tool arguments: {problems}",
        "Fix the listed arguments (ask the caller if you're missing information) and call the tool again.",
    )


def run_tool(name: str, args: dict, *, call_id: str | None = None, source: str = "rest") -> dict:
    started = time.perf_counter()
    conn = db.connect()
    try:
        if name not in TOOLS:
            raise ToolError("UNKNOWN_TOOL", f"No tool named '{name}'.",
                            "Only use the tools you were given.")
        try:
            parsed = TOOL_MODELS[name](**(args or {}))
        except ValidationError as e:
            raise _validation_to_tool_error(e)

        kwargs = parsed.model_dump()
        if name == "check_availability":
            kwargs["date_str"] = kwargs.pop("date")
        if name == "transfer_to_human":
            kwargs["call_id"] = call_id
        result = TOOLS[name](conn, **kwargs)
    except ToolError as e:
        result = e.to_dict()
    except Exception:  # never let a crash become dead air on the phone
        log.exception("Unhandled error in tool %s", name)
        result = ToolError(
            "INTERNAL_ERROR", "Something went wrong on our side.",
            "Apologize, say you're having trouble with the scheduling system, and offer to transfer to the front desk.",
        ).to_dict()

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    _log_tool_call(conn, name, args, result, call_id, source, duration_ms)
    conn.close()
    log.info("tool=%s ok=%s code=%s call_id=%s %.1fms", name, result.get("ok"),
             (result.get("error") or {}).get("code"), call_id, duration_ms)
    return result


def _log_tool_call(conn, name, args, result, call_id, source, duration_ms):
    try:
        conn.execute(
            """INSERT INTO tool_calls (ts, call_id, source, tool, inputs, result, ok, error_code, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), call_id, source, name,
             json.dumps(args, default=str), json.dumps(result, default=str),
             1 if result.get("ok") else 0, (result.get("error") or {}).get("code"), duration_ms),
        )
        conn.commit()
    except Exception:
        log.exception("Failed to write tool_calls log")  # logging must never break the call


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {"ok": True, "demo": True, "note": "Fictional clinic. Fake data only."}


@app.post("/tools/{tool_name}")
async def call_tool(tool_name: str, request: Request):
    if tool_name not in TOOLS:
        raise HTTPException(404, f"Unknown tool '{tool_name}'")
    try:
        args = await request.json()
    except Exception:
        args = {}
    return run_tool(tool_name, args if isinstance(args, dict) else {}, source="rest")


def _check_secret(request: Request):
    if not config.VAPI_SECRET:
        return
    header = request.headers.get("x-vapi-secret") or ""
    auth = request.headers.get("authorization") or ""
    if header != config.VAPI_SECRET and auth != f"Bearer {config.VAPI_SECRET}":
        raise HTTPException(401, "Invalid or missing secret")


def _parse_vapi_tool_call(tc: dict) -> tuple[str, str, dict]:
    """Vapi has shipped a few shapes over time; accept all of them."""
    fn = tc.get("function") or {}
    name = tc.get("name") or fn.get("name") or ""
    args = tc.get("arguments") or tc.get("parameters") or fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {}
    return tc.get("id", ""), name, args


@app.post("/vapi/tools")
async def vapi_tools(request: Request):
    """Vapi 'tool-calls' webhook.

    Request:  {"message": {"type": "tool-calls", "toolCallList": [...], "call": {"id": ...}}}
    Response: {"results": [{"toolCallId": "...", "result": "<single-line string>"}]}

    Always HTTP 200 with a result per call, including failures: the error JSON goes in
    `result` so the LLM actually sees the agent_hint and can recover out loud.
    """
    _check_secret(request)
    body = await request.json()
    message = body.get("message") or {}
    if message.get("type") not in (None, "tool-calls"):
        return {}
    call_id = (message.get("call") or {}).get("id")
    results = []
    for tc in message.get("toolCallList") or []:
        tc_id, name, args = _parse_vapi_tool_call(tc)
        result = run_tool(name, args, call_id=call_id, source="vapi")
        results.append({"toolCallId": tc_id, "result": json.dumps(result, separators=(",", ":"))})
    return {"results": results}


@app.get("/logs")
def get_logs(limit: int = 50, call_id: str | None = None, errors_only: bool = False):
    conn = db.connect()
    sql, params = "SELECT * FROM tool_calls WHERE 1=1", []
    if call_id:
        sql += " AND call_id = ?"
        params.append(call_id)
    if errors_only:
        sql += " AND ok = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 500))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{**dict(r), "inputs": json.loads(r["inputs"]), "result": json.loads(r["result"])} for r in rows]


@app.get("/appointments")
def list_appointments():
    """Debug view of upcoming schedule (fake data)."""
    conn = db.connect()
    rows = conn.execute(
        """SELECT a.id, a.status, a.reason, pt.full_name, pt.dob, s.start_time, pr.name AS provider
           FROM appointments a JOIN patients pt ON pt.id = a.patient_id
           JOIN slots s ON s.id = a.slot_id JOIN providers pr ON pr.id = s.provider_id
           ORDER BY s.start_time"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
