"""Record planner tool calls for the on-screen log. Does not change what the tools do."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_calls: ContextVar[list[dict] | None] = ContextVar("planner_tool_calls", default=None)


def begin_tool_log() -> None:
    _calls.set([])


def note_tool(name: str, args: dict[str, Any] | None) -> None:
    current = _calls.get()
    if current is None:
        return
    cleaned: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key == "thought_signature":
            continue
        cleaned[str(key)] = value
    current.append({"name": name, "args": cleaned})


def tool_log() -> list[dict]:
    return [dict(call) for call in (_calls.get() or [])]
