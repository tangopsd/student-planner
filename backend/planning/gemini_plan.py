"""Send the current desk to Gemini and apply its tool calls."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from ical_parser import LOCAL_TZ
from models import Item
from planning.tool_log import begin_tool_log, tool_log
from planning.tools import TOOL_SPECS, ToolContext, execute_tool, plain
from planning.validator import explain_plan_errors, validate_week
from store import Store
from weeks import today_in_la

MAX_ROUNDS = 8
DEFAULT_MODEL = "gemini-3.6-flash"
FALLBACK_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
)
BUSY_MESSAGE = "Gemini is busy right now. Try again in a moment, or type the request."
_preferred_model: str | None = None


class GeminiError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class FunctionCall:
    def __init__(self, name: str, args: dict, thought_signature: bytes | None = None):
        self.name = name
        self.args = args
        self.thought_signature = thought_signature


class ModelTurn:
    def __init__(self, text: str, calls: list | None = None):
        self.text = text
        parsed: list[FunctionCall] = []
        for call in calls or []:
            if isinstance(call, FunctionCall):
                parsed.append(call)
                continue
            signature = call[2] if len(call) > 2 else None
            parsed.append(FunctionCall(call[0], call[1], signature))
        self.calls = parsed


def choose_week_start(items: list[Item], today: date | None = None) -> date:
    """Pick the Monday to plan.

    On Saturday or Sunday, plan next week when any open deadline is still
    due on or after that Monday. Otherwise use the week of the earliest
    open deadline that is still ahead.
    """
    current = today or today_in_la()
    future: list[date] = []
    for item in items:
        if item.status != "open":
            continue
        due = _due_date(item)
        if due >= current:
            future.append(due)
    if current.weekday() >= 5:
        next_monday = current + timedelta(days=7 - current.weekday())
        if any(due >= next_monday for due in future):
            return next_monday
    if future:
        earliest = min(future)
        return earliest - timedelta(days=earliest.weekday())
    if current.weekday() >= 5:
        return current + timedelta(days=7 - current.weekday())
    return current - timedelta(days=current.weekday())


def plan_week(
    store: Store,
    request: str,
    week_start: str | None = None,
    model: Any = None,
) -> dict:
    """Plan one week from the deadlines already in the store.

    Typed requests are applied locally so the week updates without waiting on
    Gemini. A model passed in by tests still uses the tool-calling loop.
    """
    text = request.strip()
    if not text:
        raise GeminiError("Say what you want planned", 400)
    begin_tool_log()
    items = store.items()
    target = _require_monday(week_start) if week_start else choose_week_start(items).isoformat()
    if model is None:
        from planning.local_plan import plan_locally

        result = plan_locally(store, target, text)
        result["tool_calls"] = tool_log()
        return result

    profile = store.profile()
    original_ids = {item.id for item in items}
    locked_baseline = {item.id: item.due_or_start for item in items if item.locked}
    context = ToolContext(store, locked_baseline, original_ids)
    transcript: list[dict] = [
        {"role": "user", "text": _prompt(text, target, profile, items)}
    ]

    attempts = 0
    message = ""
    errors: list[str] = []
    plan = None
    for attempt in (0, 1):
        attempts = attempt + 1
        message = _converse(model, transcript, context)
        plan = store.latest_plan(target)
        errors = validate_week(
            store.profile(),
            store.items(),
            plan,
            locked_baseline,
            original_ids,
        )
        if not errors:
            break
        if attempt == 0:
            transcript.append({"role": "user", "text": _retry_message(errors, target)})

    if errors:
        message = explain_plan_errors(errors)
        errors = [message]
    return {
        "week_start": target,
        "plan": plan,
        "valid": not errors,
        "errors": errors,
        "attempts": attempts,
        "message": (message or "")[:2000],
        "tool_calls": tool_log(),
    }


def build_declarations():
    from google.genai import types

    return [
        types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters=spec["parameters"],
        )
        for spec in TOOL_SPECS
    ]


def model_sequence() -> list[str]:
    """Preferred model first, then backups that still accept this key."""
    preferred = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    names = [preferred]
    for name in FALLBACK_MODELS:
        if name not in names:
            names.append(name)
    if _preferred_model and _preferred_model in names:
        names.remove(_preferred_model)
        names.insert(0, _preferred_model)
    return names


def remember_model(name: str) -> None:
    global _preferred_model
    _preferred_model = name


def retryable_model_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in ("503", "429", "unavailable", "high demand", "404", "not_found", "no longer available")
    )


class GoogleGeminiModel:
    """Manual function calling. The SDK must not run the tools itself."""

    def __init__(self, client=None):
        if client is None:
            key = os.environ.get("GEMINI_API_KEY", "").strip()
            if not key:
                raise GeminiError("Set GEMINI_API_KEY to plan with Gemini.", 400)
            from google import genai

            client = genai.Client(api_key=key)
        self._client = client
        self._models = model_sequence()
        self._model_name = self._models[0]
        self._declarations = build_declarations()

    def complete(self, turns: list[dict]) -> ModelTurn:
        from google.genai import types

        contents = []
        for turn in turns:
            role = turn.get("role")
            if role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=turn.get("text") or "")],
                    )
                )
            elif role == "model":
                parts = []
                if turn.get("text"):
                    parts.append(types.Part.from_text(text=turn["text"]))
                for call in turn.get("calls") or []:
                    signature = call.get("thought_signature")
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=call["name"],
                                args=call.get("args") or {},
                            ),
                            thought_signature=signature or None,
                        )
                    )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                parts = []
                for item in turn.get("responses") or []:
                    response = item.get("response") or {"error": "Empty tool response"}
                    if not isinstance(response, dict):
                        response = {"result": response}
                    parts.append(
                        types.Part.from_function_response(
                            name=item["name"],
                            response=response,
                        )
                    )
                if parts:
                    contents.append(types.Content(role="user", parts=parts))
        config = types.GenerateContentConfig(
            temperature=0.2,
            tools=[types.Tool(function_declarations=self._declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        last_error: Exception | None = None
        for name in list(self._models):
            try:
                response = self._client.models.generate_content(
                    model=name,
                    contents=contents,
                    config=config,
                )
            except GeminiError:
                raise
            except Exception as exc:
                last_error = exc
                if retryable_model_error(exc):
                    continue
                raise GeminiError(
                    "Gemini could not update the week. Try again in a moment.",
                    502,
                ) from exc
            remember_model(name)
            self._model_name = name
            self._models = [name] + [item for item in self._models if item != name]
            return _turn_from_response(response)
        raise GeminiError(BUSY_MESSAGE, 503) from last_error


def _converse(model: Any, transcript: list[dict], context: ToolContext) -> str:
    message = ""
    for _ in range(MAX_ROUNDS):
        turn = model.complete(list(transcript))
        calls = [
            {
                "name": call.name,
                "args": call.args,
                "thought_signature": call.thought_signature,
            }
            for call in turn.calls
        ]
        transcript.append({"role": "model", "text": turn.text or "", "calls": calls})
        if turn.text:
            message = turn.text
        if not calls:
            return message
        responses = []
        for call in calls:
            responses.append(
                {
                    "name": call["name"],
                    "response": execute_tool(context, call["name"], call["args"]),
                }
            )
        transcript.append({"role": "tool", "responses": responses})
    return message


def _turn_from_response(response: Any) -> ModelTurn:
    candidates = getattr(response, "candidates", None) or []
    content = getattr(candidates[0], "content", None) if candidates else None
    parts = list(getattr(content, "parts", None) or [])
    if not parts:
        fallback = getattr(response, "text", None)
        if fallback:
            return ModelTurn(str(fallback), [])
        raise GeminiError("Gemini returned no plan.", 502)
    texts: list[str] = []
    calls: list[tuple[str, dict]] = []
    for part in parts:
        function_call = getattr(part, "function_call", None)
        name = getattr(function_call, "name", None) if function_call else None
        if name:
            raw_args = getattr(function_call, "args", None) or {}
            args = plain(raw_args)
            if not isinstance(args, dict):
                args = {}
            signature = getattr(part, "thought_signature", None)
            calls.append((name, args, signature if isinstance(signature, bytes) else None))
            continue
        text = getattr(part, "text", None)
        if text:
            texts.append(text)
    return ModelTurn("\n".join(texts).strip(), calls)


def _prompt(request: str, week_start: str, profile, items: list[Item]) -> str:
    open_items = [item for item in items if item.status == "open"]
    open_items.sort(key=lambda item: item.due_or_start)
    lines = []
    for item in open_items[:80]:
        effort = (
            "unestimated"
            if item.estimated_effort_hours is None
            else f"{item.estimated_effort_hours}h"
        )
        locked = " locked" if item.locked else ""
        course = item.course or "no course"
        lines.append(
            f"- {item.id} | {item.type}{locked} | {course} | {item.title} | "
            f"due {item.due_or_start} | {effort}"
        )
    hidden = len(open_items) - len(lines)
    if hidden > 0:
        lines.append(f"- {hidden} more open deadlines. Call list_items for the rest.")
    commitments = [
        f"- {item.day} {item.start}-{item.end} {item.title}"
        for item in profile.fixed_commitments
    ] or ["- none"]
    windows = [
        f"- {window.day} {window.start}-{window.end}"
        for window in profile.preferred_study_windows
    ] or ["- none"]
    locked_lines = [
        f"- {item.id} due {item.due_or_start} {item.title}"
        for item in items
        if item.locked
    ] or ["- none"]
    return (
        "You are scheduling a student's week. Keep every deadline that is already on the desk. "
        "When the student adds a new commitment, call add_item before you schedule it.\n\n"
        f"Student request: {request}\n\n"
        f"Today is {today_in_la().isoformat()} in America/Los_Angeles.\n"
        f"Target week (Monday): {week_start}\n"
        f"Wake {profile.waking_hours.wake}, sleep {profile.waking_hours.sleep}, "
        f"daily study capacity {profile.daily_capacity_hours} hours.\n"
        "Fixed commitments:\n"
        f"{chr(10).join(commitments)}\n"
        "Preferred study windows (use them when you can; waking hours and capacity are mandatory):\n"
        f"{chr(10).join(windows)}\n"
        "Locked deadlines, which must keep their current time:\n"
        f"{chr(10).join(locked_lines)}\n"
        f"Open deadlines already on the desk ({len(open_items)}):\n"
        f"{chr(10).join(lines) or '- none'}\n\n"
        "Rules:\n"
        "- If the request adds something that is not already listed, call add_item. "
        "Use type event for a rehearsal, appointment, or meeting, assignment for homework, "
        "quiz for a quiz, and exam for an exam. due_or_start is the start in Pacific time, "
        "or midnight on the due day when no clock was given.\n"
        f"- After add_item, call create_blocks for {week_start}. "
        "An event gets one fixed block over the stated time, or one hour when only a start was given. "
        "An assignment or quiz gets a study block that finishes by the deadline.\n"
        "- If the request moves an existing block, call move_block. "
        "Do not call add_item for a deadline that already exists.\n"
        "- If the request says delete, remove, or cancel, call delete_block for that block. "
        "Leave a locked exam on the week.\n"
        "- Locked exams stay at their current time. You may add a fixed block at the exam "
        "time (about 1 hour). Fixed and buffer blocks do not count toward study capacity.\n"
        "- If an assignment or quiz has no estimated effort, assume 1 hour of study.\n"
        "- Stay inside waking hours. Do not cross midnight. No overlapping blocks. "
        "Do not overlap fixed commitments.\n"
        "- A due time of midnight means the work is due that calendar day; study may run until sleep that day.\n"
        "- Study and personal blocks must finish by the deadline. Fixed blocks may cover the exam itself.\n"
        f"- Call get_week_plan for {week_start} before you finish, and fix any errors it reports.\n"
    )


def _retry_message(errors: list[str], week_start: str) -> str:
    listed = "\n".join(f"- {error}" for error in errors)
    return (
        f"The plan is invalid for the week of {week_start}:\n"
        f"{listed}\n"
        "Fix it with move_block, delete_block, or create_blocks. "
        "Do not recreate or delete existing deadlines."
    )


def _require_monday(value: str) -> str:
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise GeminiError("Week start must be YYYY-MM-DD", 400) from exc
    if day.weekday() != 0:
        raise GeminiError("Week start must be a Monday", 400)
    return day.isoformat()


def _due_date(item: Item) -> date:
    parsed = datetime.fromisoformat(item.due_or_start)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ).date()
