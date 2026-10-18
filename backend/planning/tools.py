"""Planner tools Gemini can call against the JSON store."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from calendar_io import normalize_instant
from ical_parser import LOCAL_TZ
from models import Block, Item
from planning.validator import validate_week
from store import Store, StoreError
from weeks import week_start_for

TOOL_NAMES = [
    "list_items",
    "add_item",
    "move_item",
    "create_blocks",
    "move_block",
    "delete_block",
    "get_week_plan",
    "set_constraint",
    "mark_progress",
    "undo_last_change",
]

ITEM_TYPES = ["assignment", "quiz", "exam", "event", "personal"]
BLOCK_KINDS = ["study", "fixed", "personal", "buffer"]

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_items",
        "description": (
            "List deadlines already on the desk. Optional Monday week_start "
            "(YYYY-MM-DD) and status open or done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "week_start": {
                    "type": "string",
                    "description": "Monday YYYY-MM-DD. Omit to list every deadline.",
                },
                "status": {"type": "string", "enum": ["open", "done"]},
            },
        },
    },
    {
        "name": "add_item",
        "description": (
            "Add one new commitment that is not already on the desk: an appointment, "
            "rehearsal, meeting, or deadline. Use this when the student says "
            "'add a rehearsal' or 'I have a dentist appointment'. "
            "Do not use this to copy an existing deadline. Exams are locked."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "course": {"type": "string"},
                "type": {"type": "string", "enum": ITEM_TYPES},
                "due_or_start": {
                    "type": "string",
                    "description": "ISO datetime. A value without a zone is Pacific time.",
                },
                "estimated_effort_hours": {"type": "number"},
                "description": {"type": "string"},
            },
            "required": ["title", "type", "due_or_start"],
        },
    },
    {
        "name": "move_item",
        "description": (
            "Change a deadline time or its estimated effort. "
            "Locked deadlines cannot move."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "due_or_start": {"type": "string"},
                "estimated_effort_hours": {"type": "number"},
            },
            "required": ["item_id"],
        },
    },
    {
        "name": "create_blocks",
        "description": (
            "Add blocks to the latest plan for a Monday week. The first call "
            "creates version 1. Later calls append to that version. "
            "Do not invent copies of existing deadlines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "week_start": {"type": "string", "description": "Monday YYYY-MM-DD."},
                "blocks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "item_id": {"type": "string"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                            "kind": {"type": "string", "enum": BLOCK_KINDS},
                            "reason": {"type": "string"},
                        },
                        "required": ["start", "end", "kind"],
                    },
                },
            },
            "required": ["week_start", "blocks"],
        },
    },
    {
        "name": "move_block",
        "description": "Move one block on the latest plan to a new start and end.",
        "parameters": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
            "required": ["block_id", "start", "end"],
        },
    },
    {
        "name": "delete_block",
        "description": "Remove one block from the latest plan.",
        "parameters": {
            "type": "object",
            "properties": {"block_id": {"type": "string"}},
            "required": ["block_id"],
        },
    },
    {
        "name": "get_week_plan",
        "description": "Return the latest plan for a Monday week and any validator errors.",
        "parameters": {
            "type": "object",
            "properties": {"week_start": {"type": "string"}},
            "required": ["week_start"],
        },
    },
    {
        "name": "set_constraint",
        "description": (
            "Change wake, sleep, or daily study capacity. At least one field "
            "is required. Wake and sleep are HH:MM on the same day."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "wake": {"type": "string"},
                "sleep": {"type": "string"},
                "daily_capacity_hours": {"type": "number"},
            },
        },
    },
    {
        "name": "mark_progress",
        "description": (
            "Mark a deadline open or done, or a block scheduled, done, or skipped. "
            "Send item_id or block_id, not both."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "block_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["status"],
        },
    },
    {
        "name": "undo_last_change",
        "description": "Undo the last planner change to deadlines, profile, or blocks.",
        "parameters": {"type": "object", "properties": {}},
    },
]


class ToolContext:
    def __init__(self, store: Store, locked_baseline: dict[str, str], original_ids: set[str]):
        self.store = store
        self.locked_baseline = locked_baseline
        self.original_ids = original_ids


def execute_tool(ctx: ToolContext, name: str, args: Any) -> dict:
    """Run one tool. Failures are returned to the model as {"error": "..."}."""
    try:
        payload = plain(args or {})
        if not isinstance(payload, dict):
            return {"error": "Tool arguments must be an object"}
        handler = HANDLERS.get(name)
        if handler is None:
            return {"error": f"Unknown tool {name}"}
        return handler(ctx, payload)
    except (StoreError, ValueError, ValidationError, TypeError) as exc:
        return {"error": _error_text(exc)}


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return plain(dump())
    items = getattr(value, "items", None)
    if callable(items):
        try:
            return {str(key): plain(item) for key, item in items()}
        except TypeError:
            pass
    return value


def _error_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        messages = []
        for err in exc.errors():
            message = str(err.get("msg", "Invalid value"))
            prefix = "Value error, "
            if message.startswith(prefix):
                message = message[len(prefix) :]
            messages.append(message)
        return "; ".join(messages) or "Invalid value"
    return str(exc)


def _now() -> str:
    return datetime.now(LOCAL_TZ).isoformat()


def _text(args: dict, key: str, default: str | None = None) -> str | None:
    if key not in args or args[key] is None:
        return default
    return str(args[key]).strip()


def _monday(value: str) -> str:
    from datetime import date

    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Week start must be YYYY-MM-DD") from exc
    if day.weekday() != 0:
        raise ValueError("Week start must be a Monday")
    return day.isoformat()


def _optional_float(args: dict, key: str) -> tuple[float | None, bool]:
    if key not in args:
        return None, False
    if args[key] is None:
        return None, True
    try:
        return float(args[key]), True
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _compact(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "course": item.course,
        "type": item.type,
        "due_or_start": item.due_or_start,
        "estimated_effort_hours": item.estimated_effort_hours,
        "locked": item.locked,
        "status": item.status,
    }


def _list_items(ctx: ToolContext, args: dict) -> dict:
    week = _text(args, "week_start")
    monday = _monday(week) if week else None
    status = _text(args, "status")
    if status is not None and status not in ("open", "done"):
        raise ValueError("Status must be open or done")
    rows = []
    for item in ctx.store.items():
        if status is not None and item.status != status:
            continue
        if monday is not None:
            due = datetime.fromisoformat(item.due_or_start)
            if week_start_for(due).isoformat() != monday:
                continue
        rows.append(_compact(item))
    return {"items": rows}


def _add_item(ctx: ToolContext, args: dict) -> dict:
    title = _text(args, "title") or ""
    if not title:
        raise ValueError("Title is required")
    if len(title) > 300:
        raise ValueError("Title is too long")
    item_type = _text(args, "type") or ""
    if item_type not in ITEM_TYPES:
        raise ValueError("Type must be assignment, quiz, exam, event, or personal")
    due_raw = _text(args, "due_or_start")
    if not due_raw:
        raise ValueError("A date and time is required")
    due = normalize_instant(due_raw)
    course = _text(args, "course") or None
    description = (_text(args, "description") or "")[:5000]
    effort, present = _optional_float(args, "estimated_effort_hours")
    if present and effort is not None and not 0 <= effort <= 100:
        raise ValueError("Estimated effort must be between 0 and 100 hours")
    item = ctx.store.add_manual_item(
        title=title,
        course=course,
        item_type=item_type,
        due_or_start=due,
        estimated_effort_hours=effort if present else None,
        description=description,
        summary=f"Added {title}",
    )
    return {"item": _compact(item)}


def _move_item(ctx: ToolContext, args: dict) -> dict:
    item_id = _text(args, "item_id") or ""
    if not item_id:
        raise ValueError("item_id is required")
    current = next((item for item in ctx.store.items() if item.id == item_id), None)
    if current is None:
        raise StoreError(f"No deadline with id {item_id}")
    due = None
    if "due_or_start" in args and args["due_or_start"] is not None:
        moved = normalize_instant(str(args["due_or_start"]))
        if moved != current.due_or_start:
            due = moved
    effort, update_effort = _optional_float(args, "estimated_effort_hours")
    item = ctx.store.move_item(
        item_id,
        f"Updated {current.title}",
        due_or_start=due,
        estimated_effort_hours=effort,
        update_effort=update_effort,
    )
    return {"item": _compact(item)}


def _block_from(raw: Any) -> Block:
    if not isinstance(raw, dict):
        raise ValueError("Each block must be an object")
    kind = str(raw.get("kind") or "").strip()
    if kind not in BLOCK_KINDS:
        raise ValueError("Block kind must be study, fixed, personal, or buffer")
    start = normalize_instant(str(raw.get("start") or ""))
    end = normalize_instant(str(raw.get("end") or ""))
    if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
        raise ValueError("Block end must be after the start")
    block_id = str(raw.get("id") or "").strip() or str(uuid4())
    item_id = str(raw.get("item_id") or "").strip() or None
    reason = str(raw.get("reason") or "").strip()[:500]
    return Block(
        id=block_id,
        item_id=item_id,
        start=start,
        end=end,
        kind=kind,
        status="scheduled",
        reason=reason,
    )


def _create_blocks(ctx: ToolContext, args: dict) -> dict:
    week = _monday(_text(args, "week_start") or "")
    raw_blocks = args.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("Send at least one block")
    if len(raw_blocks) > 200:
        raise ValueError("Too many blocks in one call")
    blocks = [_block_from(raw) for raw in raw_blocks]
    summary = f"Scheduled {len(blocks)} block" if len(blocks) == 1 else f"Scheduled {len(blocks)} blocks"
    plan = ctx.store.create_blocks(week, blocks, summary, _now())
    return {
        "week_start": plan.week_start,
        "version": plan.version,
        "added": [block.model_dump(mode="json") for block in blocks],
        "block_count": len(plan.blocks),
    }


def _move_block(ctx: ToolContext, args: dict) -> dict:
    block_id = _text(args, "block_id") or ""
    if not block_id:
        raise ValueError("block_id is required")
    start = normalize_instant(_text(args, "start") or "")
    end = normalize_instant(_text(args, "end") or "")
    block = ctx.store.move_block(block_id, start, end, f"Moved block {block_id}", _now())
    return {"block": block.model_dump(mode="json")}


def _delete_block(ctx: ToolContext, args: dict) -> dict:
    block_id = _text(args, "block_id") or ""
    if not block_id:
        raise ValueError("block_id is required")
    deleted = ctx.store.delete_block(block_id, f"Removed block {block_id}", _now())
    return {"deleted": deleted}


def _get_week_plan(ctx: ToolContext, args: dict) -> dict:
    week = _monday(_text(args, "week_start") or "")
    plan = ctx.store.latest_plan(week)
    errors = validate_week(
        ctx.store.profile(),
        ctx.store.items(),
        plan,
        ctx.locked_baseline,
        ctx.original_ids,
    )
    return {
        "week_start": week,
        "plan": None if plan is None else plan.model_dump(mode="json"),
        "valid": not errors,
        "errors": errors,
    }


def _set_constraint(ctx: ToolContext, args: dict) -> dict:
    wake = _text(args, "wake") if "wake" in args else None
    sleep = _text(args, "sleep") if "sleep" in args else None
    capacity, present = _optional_float(args, "daily_capacity_hours")
    if wake is None and sleep is None and not present:
        raise ValueError("Send wake, sleep, or daily_capacity_hours")
    profile = ctx.store.set_constraint(
        "Updated hours",
        wake=wake,
        sleep=sleep,
        daily_capacity_hours=capacity if present else None,
    )
    return {
        "wake": profile.waking_hours.wake,
        "sleep": profile.waking_hours.sleep,
        "daily_capacity_hours": profile.daily_capacity_hours,
    }


def _mark_progress(ctx: ToolContext, args: dict) -> dict:
    status = _text(args, "status") or ""
    item_id = _text(args, "item_id")
    block_id = _text(args, "block_id")
    if bool(item_id) == bool(block_id):
        raise ValueError("Send either an item_id or a block_id")
    if item_id:
        item = ctx.store.mark_item_progress(item_id, status, f"Marked {item_id} {status}")
        return {"item": _compact(item)}
    block = ctx.store.mark_block_progress(block_id or "", status, f"Marked block {block_id} {status}", _now())
    return {"block": block.model_dump(mode="json")}


def _undo(ctx: ToolContext, args: dict) -> dict:
    del args
    summary = ctx.store.undo()
    return {"undone": True, "summary": summary}


HANDLERS = {
    "list_items": _list_items,
    "add_item": _add_item,
    "move_item": _move_item,
    "create_blocks": _create_blocks,
    "move_block": _move_block,
    "delete_block": _delete_block,
    "get_week_plan": _get_week_plan,
    "set_constraint": _set_constraint,
    "mark_progress": _mark_progress,
    "undo_last_change": _undo,
}
