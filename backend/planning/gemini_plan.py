"""Send the current desk to Gemini and apply its tool calls."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from ical_parser import LOCAL_TZ
from models import Item
from planning.tools import TOOL_SPECS, ToolContext, execute_tool, plain
from planning.validator import explain_plan_errors, validate_week
from store import Store
from weeks import today_in_la

MAX_ROUNDS = 8


class GeminiError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class FunctionCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class ModelTurn:
    def __init__(self, text: str, calls: list[tuple[str, dict]] | None = None):
        self.text = text
        self.calls = [FunctionCall(name, args) for name, args in (calls or [])]


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

    Tool calls run against that store. The validator runs after the model
    stops, and the conversation continues once if the week is invalid.
    """
    text = request.strip()
    if not text:
        raise GeminiError("Say what you want planned", 400)
    items = store.items()
    target = _require_monday(week_start) if week_start else choose_week_start(items).isoformat()
    if model is None and not os.environ.get("GEMINI_API_KEY", "").strip():
        from planning.local_plan import plan_locally

        return plan_locally(store, target, text)
    if model is None:
        model = GoogleGeminiModel()

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


class GoogleGeminiModel:
    """Manual function calling. The SDK must not run the tools itself."""

    def __init__(self):
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise GeminiError("Set GEMINI_API_KEY to plan with Gemini.", 400)
        from google import genai

        self._client = genai.Client(api_key=key)
        self._model_name = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"
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
                    parts.append(
                        types.Part.from_function_call(
                            name=call["name"],
                            args=call.get("args") or {},
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
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=contents,
                config=config,
            )
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError(f"Gemini request failed: {exc}", 502) from exc
        return _turn_from_response(response)


def _converse(model: Any, transcript: list[dict], context: ToolContext) -> str:
    message = ""
    for _ in range(MAX_ROUNDS):
        turn = model.complete(list(transcript))
        calls = [{"name": call.name, "args": call.args} for call in turn.calls]
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
            calls.append((name, args))
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
        "You are scheduling a student's week. The deadlines already exist. "
        "Do not create, replace, or delete them.\n\n"
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
        f"- Call list_items, then create_blocks for {week_start}. Prefer one create_blocks call.\n"
        "- Do not call add_item for a deadline that already exists.\n"
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
