"""Schedule one week from deadlines already on the desk.

Used when GEMINI_API_KEY is not set, so Plan this week still returns blocks.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

from ical_parser import LOCAL_TZ
from models import Block, Item, Plan, Profile
from planning.validator import validate_week
from store import Store, StoreError

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKDAY_INDEX = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
STOP_WORDS = {
    "a",
    "an",
    "the",
    "my",
    "to",
    "on",
    "for",
    "please",
    "can",
    "you",
    "move",
    "reschedule",
    "shift",
    "push",
    "put",
    "place",
    "schedule",
    "block",
    "session",
    "this",
    "week",
    "review",
    "study",
}


def plan_locally(store: Store, week_start: str, request: str = "") -> dict:
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
    rescheduled = _reschedule(store, week_start, request, existing)
    if rescheduled is not None:
        return rescheduled
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


def _reschedule(store: Store, week_start: str, request: str, existing: Plan | None) -> dict | None:
    """Move or add one block when the request names a weekday. Otherwise leave planning alone."""
    day_index = _target_weekday(request)
    if day_index is None:
        return None
    items = store.items()
    item = _match_item(items, request)
    if item is None:
        return _refused(store, week_start, "Say which deadline to move, and which day.")
    target_day = date.fromisoformat(week_start) + timedelta(days=day_index)
    blocks = [] if existing is None else list(existing.blocks)
    linked = [block for block in blocks if block.item_id == item.id]
    study = [block for block in linked if block.kind in ("study", "personal")]
    wants_review = bool({"review", "study"} & set(_words(request)))
    if study:
        chosen = study[0]
        placed = _place(store.profile(), existing, target_day, chosen.id, _local(chosen.start), _local(chosen.end) - _local(chosen.start))
        if placed is None:
            return _refused(store, week_start, f"{DAY_NAMES[day_index]} is full during waking hours.")
        start, end = placed
        summary = f"Moved {item.title} to {DAY_NAMES[day_index]}"
        try:
            store.move_block(chosen.id, start.isoformat(), end.isoformat(), summary, datetime.now(LOCAL_TZ).isoformat())
        except StoreError as exc:
            return _refused(store, week_start, str(exc))
        message = f"Moved {item.title} to {DAY_NAMES[day_index]}, {_clock(start)}–{_clock(end)}."
    elif wants_review or not linked:
        if item.locked and not wants_review and linked:
            return _refused(store, week_start, f"{item.title} is locked, so its time stays put.")
        placed = _place(store.profile(), existing, target_day, None, None, timedelta(hours=1))
        if placed is None:
            return _refused(store, week_start, f"{DAY_NAMES[day_index]} is full during waking hours.")
        start, end = placed
        block = _block(item, start, end, "personal" if item.type == "personal" else "study")
        summary = f"Added a review for {item.title} on {DAY_NAMES[day_index]}"
        try:
            store.create_blocks(week_start, [block], summary, datetime.now(LOCAL_TZ).isoformat())
        except StoreError as exc:
            return _refused(store, week_start, str(exc))
        message = f"Added a review for {item.title} on {DAY_NAMES[day_index]}, {_clock(start)}–{_clock(end)}."
    else:
        return _refused(store, week_start, f"{item.title} is locked, so its time stays put.")
    plan = store.latest_plan(week_start)
    original_ids = {row.id for row in store.items()}
    locked_baseline = {row.id: row.due_or_start for row in store.items() if row.locked}
    errors = validate_week(store.profile(), store.items(), plan, locked_baseline, original_ids)
    if errors:
        try:
            store.undo()
        except StoreError:
            pass
        plan = store.latest_plan(week_start)
        return {
            "week_start": week_start,
            "plan": plan,
            "valid": False,
            "errors": errors,
            "attempts": 1,
            "message": " ".join(errors),
        }
    return {
        "week_start": week_start,
        "plan": plan,
        "valid": True,
        "errors": [],
        "attempts": 1,
        "message": message,
    }


def _refused(store: Store, week_start: str, message: str) -> dict:
    return {
        "week_start": week_start,
        "plan": store.latest_plan(week_start),
        "valid": False,
        "errors": [message],
        "attempts": 1,
        "message": message,
    }


def _target_weekday(request: str) -> int | None:
    found = None
    for word in _words(request):
        if word in WEEKDAY_INDEX:
            found = WEEKDAY_INDEX[word]
    return found


def _words(request: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", request.lower())


def _match_item(items: list[Item], request: str) -> Item | None:
    wanted = [word for word in _words(request) if word not in STOP_WORDS and word not in WEEKDAY_INDEX]
    if not wanted:
        return None
    best: Item | None = None
    best_score = 0
    for item in items:
        title_words = set(_words(item.title))
        score = 0
        for word in wanted:
            if word in title_words:
                score += len(word)
            elif len(word) >= 3 and any(word in part or part in word for part in title_words if len(part) >= 3):
                score += len(word)
        if score > best_score:
            best = item
            best_score = score
    return best


def _place(
    profile: Profile,
    plan,
    day: date,
    skip_id: str | None,
    preferred: datetime | None,
    duration: timedelta,
) -> tuple[datetime, datetime] | None:
    occupied = _commitments(profile, day)
    if plan is not None:
        for block in plan.blocks:
            if skip_id is not None and block.id == skip_id:
                continue
            start = _local(block.start)
            if start.date() != day:
                continue
            occupied.append((start, _local(block.end)))
    wake = _on_clock(day, profile.waking_hours.wake)
    sleep = _on_clock(day, profile.waking_hours.sleep)
    if preferred is not None:
        start = _on_clock(day, f"{preferred.hour:02d}:{preferred.minute:02d}")
        end = start + duration
        if wake <= start and end <= sleep and not _overlaps(start, end, occupied):
            return start, end
    if duration == timedelta(hours=1):
        for start, end in reversed(_slots(day, profile)):
            if not _overlaps(start, end, occupied):
                return start, end
        return None
    cursor = sleep - duration
    while cursor >= wake:
        end = cursor + duration
        if end <= sleep and not _overlaps(cursor, end, occupied):
            return cursor, end
        cursor -= timedelta(minutes=30)
    return None


def _clock(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return f"{hour}:{moment.minute:02d} {suffix}"


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
