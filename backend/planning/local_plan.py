"""Schedule one week from deadlines already on the desk.

Used when GEMINI_API_KEY is not set, so Plan this week still returns blocks.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from uuid import uuid4

from ical_parser import LOCAL_TZ
from models import Block, Item, Profile
from planning.validator import validate_week
from store import Store

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def plan_locally(store: Store, week_start: str) -> dict:
    items = store.items()
    original_ids = {item.id for item in items}
    locked_baseline = {item.id: item.due_or_start for item in items if item.locked}
    existing = store.latest_plan(week_start)
    errors = validate_week(
        store.profile(),
        items,
        existing,
        locked_baseline,
        original_ids,
    )
    if existing is not None and existing.blocks:
        return {
            "week_start": week_start,
            "plan": existing,
            "valid": not errors,
            "errors": errors,
            "attempts": 1,
            "message": "This week already has a schedule." if not errors else "This week is already scheduled, and it still breaks the rules.",
        }

    blocks = propose_blocks(store.profile(), items, week_start)
    plan = existing
    if blocks:
        count = len(blocks)
        summary = f"Scheduled {count} block" if count == 1 else f"Scheduled {count} blocks"
        plan = store.create_blocks(
            week_start,
            blocks,
            summary,
            datetime.now(LOCAL_TZ).isoformat(),
        )
    errors = validate_week(
        store.profile(),
        store.items(),
        plan,
        locked_baseline,
        original_ids,
    )
    scheduled = 0 if plan is None else len(plan.blocks)
    if scheduled:
        message = f"Scheduled {scheduled} blocks for the week of {week_start}."
    else:
        message = "No open assignment, quiz, or exam fell in this week."
    return {
        "week_start": week_start,
        "plan": plan,
        "valid": not errors,
        "errors": errors,
        "attempts": 1,
        "message": message,
    }


def propose_blocks(profile: Profile, items: list[Item], week_start: str) -> list[Block]:
    week = date.fromisoformat(week_start)
    days = [week + timedelta(days=offset) for offset in range(7)]
    week_end = days[-1]
    spans: dict[date, list[tuple[datetime, datetime]]] = {day: [] for day in days}
    study_hours = {day: 0.0 for day in days}
    for day in days:
        spans[day].extend(_commitments(profile, day))

    blocks: list[Block] = []
    for item in items:
        if item.status != "open":
            continue
        if item.type == "exam" or (item.type == "event" and not _is_midnight(item.due_or_start)):
            block = _fixed_block(item, profile, week, week_end, spans)
            if block is not None:
                blocks.append(block)

    study_items = [
        item
        for item in items
        if item.status == "open" and item.type in ("assignment", "quiz", "personal")
    ]
    study_items.sort(key=lambda item: (_cutoff_for(item.due_or_start), item.title))
    for item in study_items:
        blocks.extend(_study_blocks(item, profile, week, week_end, spans, study_hours))
    return blocks


def _study_blocks(
    item: Item,
    profile: Profile,
    week: date,
    week_end: date,
    spans: dict[date, list[tuple[datetime, datetime]]],
    study_hours: dict[date, float],
) -> list[Block]:
    cutoff = _cutoff_for(item.due_or_start)
    if cutoff.date() < week or cutoff.date() > week_end:
        return []
    remaining = _study_hours(item)
    if remaining <= 0:
        return []
    blocks: list[Block] = []
    day = min(cutoff.date(), week_end)
    while day >= week and remaining > 0:
        for start, end in reversed(_slots(day, profile)):
            if end > cutoff or _overlaps(start, end, spans[day]):
                continue
            duration = (end - start).total_seconds() / 3600
            if study_hours[day] + duration > profile.daily_capacity_hours + 1e-6:
                continue
            block = _block(item, start, end, "personal" if item.type == "personal" else "study")
            blocks.append(block)
            spans[day].append((start, end))
            study_hours[day] += duration
            remaining -= 1
            break
        day -= timedelta(days=1)
    return blocks


def _fixed_block(
    item: Item,
    profile: Profile,
    week: date,
    week_end: date,
    spans: dict[date, list[tuple[datetime, datetime]]],
) -> Block | None:
    start = _local(item.due_or_start)
    if start.date() < week or start.date() > week_end:
        return None
    if _is_midnight(item.due_or_start):
        return None
    wake = _on_clock(start.date(), profile.waking_hours.wake)
    sleep = _on_clock(start.date(), profile.waking_hours.sleep)
    if start < wake:
        return None
    end = min(start + timedelta(hours=1), sleep)
    if end <= start or _overlaps(start, end, spans[start.date()]):
        return None
    spans[start.date()].append((start, end))
    return _block(item, start, end, "fixed")


def _study_hours(item: Item) -> int:
    if item.estimated_effort_hours is None:
        return 1
    if item.estimated_effort_hours <= 0:
        return 0
    return min(4, math.ceil(item.estimated_effort_hours - 1e-9))


def _block(item: Item, start: datetime, end: datetime, kind: str) -> Block:
    return Block(
        id=str(uuid4()),
        item_id=item.id,
        start=start.isoformat(),
        end=end.isoformat(),
        kind=kind,
        status="scheduled",
        reason=item.title[:180],
    )


def _slots(day: date, profile: Profile) -> list[tuple[datetime, datetime]]:
    cursor = _on_clock(day, profile.waking_hours.wake)
    stop = _on_clock(day, profile.waking_hours.sleep)
    slots: list[tuple[datetime, datetime]] = []
    while cursor + timedelta(hours=1) <= stop:
        slots.append((cursor, cursor + timedelta(hours=1)))
        cursor += timedelta(hours=1)
    return slots


def _commitments(profile: Profile, day: date) -> list[tuple[datetime, datetime]]:
    key = DAY_KEYS[day.weekday()]
    spans = []
    for commitment in profile.fixed_commitments:
        if commitment.day != key:
            continue
        spans.append(
            (_on_clock(day, commitment.start), _on_clock(day, commitment.end))
        )
    return spans


def _overlaps(
    start: datetime,
    end: datetime,
    spans: list[tuple[datetime, datetime]],
) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in spans)


def _local(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _is_midnight(value: str) -> bool:
    local = _local(value)
    return local.hour == 0 and local.minute == 0 and local.second == 0 and local.microsecond == 0


def _cutoff_for(value: str) -> datetime:
    local = _local(value)
    if _is_midnight(value):
        return local.replace(hour=23, minute=59, second=59, microsecond=0)
    return local


def _on_clock(day: date, clock: str) -> datetime:
    hour, minute = clock.split(":")
    return datetime(day.year, day.month, day.day, int(hour), int(minute), tzinfo=LOCAL_TZ)
