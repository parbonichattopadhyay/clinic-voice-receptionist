"""Errors the voice agent can recover from.

Every error has:
  - code:        stable machine-readable identifier (shows up in logs, easy to grep)
  - message:     what went wrong, in plain English
  - agent_hint:  what the agent should say/do next. The LLM reads this, so it's
                 effectively part of the prompt — write it like an instruction.
"""


class ToolError(Exception):
    def __init__(self, code: str, message: str, agent_hint: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.agent_hint = agent_hint
        self.extra = extra

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message, "agent_hint": self.agent_hint},
            **self.extra,
        }
