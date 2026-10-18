"""Schedule one week from deadlines already on the desk.

Applies a typed request to the week already stored on the desk.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

from ical_parser import LOCAL_TZ
from models import Block, Item, Plan, Profile
from planning.validator import explain_plan_errors, validate_week
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
    "up",
}
MOVE_WORDS = {"move", "reschedule", "shift", "push"}
MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
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
    # A plain "plan the week" keeps the blocks already saved. A move is handled above.
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
    """Edit the current week when the request asks to move something."""
    if not _is_change_request(request, week_start):
        return None
    mentions = _day_mentions(request, week_start)
    if not mentions:
        return _refused(store, week_start, "Tell me which day to move it to.")
    source = mentions[0] if len(mentions) >= 2 else None
    target_day = mentions[-1]
    items = store.items()
    chosen = _block_on_day(existing, source, items, request) if source is not None else None
    if source is not None and chosen is None:
        return _refused(store, week_start, f"Nothing is scheduled on {_day_label(source)} to move.")
    item = (
        _item_for(items, chosen.item_id)
        if chosen is not None
        else _match_item(items, request, week_start, existing)
    )
    if item is None:
        return _refused(store, week_start, "Say which deadline to move, and which day.")
    wants_new = bool({"review", "study"} & set(_words(request)))
    if chosen is None and existing is not None:
        linked = [block for block in existing.blocks if block.item_id == item.id]
        study = [block for block in linked if block.kind in ("study", "personal")]
        if study:
            chosen = study[0]
        elif not wants_new:
            fixed = [block for block in linked if block.kind == "fixed"]
            chosen = fixed[0] if fixed else None
    if chosen is None and wants_new:
        return _add_review(store, week_start, item, target_day)
    if chosen is None:
        return _refused(store, week_start, f"Nothing on the week is scheduled for {item.title}.")
    if item.locked and chosen.kind == "fixed":
        return _refused(store, week_start, f"{item.title} is locked, so its time stays put.")
    duration = _local(chosen.end) - _local(chosen.start)
    preferred = _local(chosen.start)
    return _move_with_retry(store, week_start, item, chosen, target_day, preferred, duration)


def _move_with_retry(
    store: Store,
    week_start: str,
    item: Item,
    chosen: Block,
    target_day: date,
    preferred: datetime,
    duration: timedelta,
) -> dict:
    """Move once, and if the validator objects, try one corrected time."""
    week = date.fromisoformat(week_start)
    profile = store.profile()
    existing = store.latest_plan(week_start)
    placed = _place(profile, existing, target_day, chosen.id, preferred, duration, None)
    if placed is None:
        return _refused(store, week_start, f"{_day_label(target_day)} is full during waking hours.")
    if not _write_move(store, chosen.id, placed, item.title, target_day):
        return _refused(store, week_start, "I couldn't move that block.")
    errors = _week_errors(store, week_start)
    if not errors:
        start, end = placed
        return _ok(store, week_start, f"Moved {item.title} to {_day_label(target_day)}, {_clock(start)}–{_clock(end)}.", 1)
    raw = list(errors)
    _undo(store)
    cutoff = _cutoff_for(item.due_or_start)
    retry_day = target_day if week <= target_day <= week + timedelta(days=6) and target_day <= cutoff.date() else cutoff.date()
    if retry_day < week or retry_day > week + timedelta(days=6):
        return _failed(store, week_start, explain_plan_errors(raw))
    existing = store.latest_plan(week_start)
    placed = _place(profile, existing, retry_day, chosen.id, preferred, duration, cutoff)
    if placed is None or not _write_move(store, chosen.id, placed, item.title, retry_day):
        return _failed(store, week_start, explain_plan_errors(raw))
    errors = _week_errors(store, week_start)
    if errors:
        _undo(store)
        return _failed(store, week_start, explain_plan_errors(errors))
    start, end = placed
    if retry_day != target_day:
        message = (
            f"{_day_label(target_day)} is after the deadline, so I scheduled "
            f"{item.title} on {_day_label(retry_day)}, {_clock(start)}–{_clock(end)}."
        )
    else:
        message = f"Moved {item.title} to {_day_label(retry_day)}, {_clock(start)}–{_clock(end)}."
    return _ok(store, week_start, message, 2)


def _add_review(store: Store, week_start: str, item: Item, target_day: date) -> dict:
    """Add one study block. A locked exam stays where it is."""
    week = date.fromisoformat(week_start)
    profile = store.profile()
    duration = timedelta(hours=1)
    cutoff = _cutoff_for(item.due_or_start)
    existing = store.latest_plan(week_start)
    placed = _place(profile, existing, target_day, None, None, duration, None)
    if placed is None:
        return _refused(store, week_start, f"{_day_label(target_day)} is full during waking hours.")
    if not _write_new(store, week_start, item, placed, target_day):
        return _refused(store, week_start, "I couldn't add that block.")
    errors = _week_errors(store, week_start)
    if not errors:
        start, end = placed
        return _ok(
            store,
            week_start,
            f"Added a review for {item.title} on {_day_label(target_day)}, {_clock(start)}–{_clock(end)}.",
            1,
        )
    raw = list(errors)
    _undo(store)
    retry_day = target_day if week <= target_day <= week + timedelta(days=6) and target_day <= cutoff.date() else cutoff.date()
    if retry_day < week or retry_day > week + timedelta(days=6):
        return _failed(store, week_start, explain_plan_errors(raw))
    existing = store.latest_plan(week_start)
    placed = _place(profile, existing, retry_day, None, None, duration, cutoff)
    if placed is None or not _write_new(store, week_start, item, placed, retry_day):
        return _failed(store, week_start, explain_plan_errors(raw))
    errors = _week_errors(store, week_start)
    if errors:
        _undo(store)
        return _failed(store, week_start, explain_plan_errors(errors))
    start, end = placed
    return _ok(
        store,
        week_start,
        f"Added a review for {item.title} on {_day_label(retry_day)}, {_clock(start)}–{_clock(end)}.",
        2,
    )


def _write_new(
    store: Store,
    week_start: str,
    item: Item,
    placed: tuple[datetime, datetime],
    day: date,
) -> bool:
    start, end = placed
    block = _block(item, start, end, "study")
    summary = f"Added a review for {item.title} on {_day_label(day)}"
    try:
        store.create_blocks(week_start, [block], summary, datetime.now(LOCAL_TZ).isoformat())
    except StoreError:
        return False
    return True


def _write_move(store: Store, block_id: str, placed: tuple[datetime, datetime], title: str, day: date) -> bool:
    start, end = placed
    summary = f"Moved {title} to {_day_label(day)}"
    try:
        store.move_block(block_id, start.isoformat(), end.isoformat(), summary, datetime.now(LOCAL_TZ).isoformat())
    except StoreError:
        return False
    return True


def _week_errors(store: Store, week_start: str) -> list[str]:
    items = store.items()
    return validate_week(
        store.profile(),
        items,
        store.latest_plan(week_start),
        {item.id: item.due_or_start for item in items if item.locked},
        {item.id for item in items},
    )


def _undo(store: Store) -> None:
    try:
        store.undo()
    except StoreError:
        pass


def _ok(store: Store, week_start: str, message: str, attempts: int) -> dict:
    return {
        "week_start": week_start,
        "plan": store.latest_plan(week_start),
        "valid": True,
        "errors": [],
        "attempts": attempts,
        "message": message,
    }


def _failed(store: Store, week_start: str, message: str) -> dict:
    return {
        "week_start": week_start,
        "plan": store.latest_plan(week_start),
        "valid": False,
        "errors": [message],
        "attempts": 2,
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


def _is_change_request(request: str, week_start: str) -> bool:
    words = set(_words(request))
    return bool(words & MOVE_WORDS) or bool(_day_mentions(request, week_start))


def _day_mentions(request: str, week_start: str) -> list[date]:
    week = date.fromisoformat(week_start)
    tokens = _words(request)
    mentions: list[date] = []
    index = 0
    while index < len(tokens):
        word = tokens[index]
        if word in WEEKDAY_INDEX:
            mentions.append(week + timedelta(days=WEEKDAY_INDEX[word]))
            index += 1
            continue
        if word in MONTHS and index + 1 < len(tokens):
            day_number = _day_number(tokens[index + 1])
            if day_number is not None:
                try:
                    mentions.append(date(week.year, MONTHS[word], day_number))
                except ValueError:
                    pass
                index += 2
                continue
        index += 1
    return mentions


def _day_number(token: str) -> int | None:
    match = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", token)
    if match is None:
        return None
    return int(match.group(1))


def _day_label(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.strftime('%b')} {day.day}"


def _block_on_day(plan: Plan | None, day: date, items: list[Item], request: str) -> Block | None:
    if plan is None:
        return None
    on_day = [block for block in plan.blocks if _local(block.start).date() == day]
    if not on_day:
        return None
    if len(on_day) == 1:
        return on_day[0]
    by_id = {item.id: item for item in items}
    best = on_day[0]
    best_score = -1
    for block in on_day:
        item = by_id.get(block.item_id or "")
        score = _title_score(item.title, request) if item is not None else 0
        if score > best_score:
            best = block
            best_score = score
    return best


def _item_for(items: list[Item], item_id: str | None) -> Item | None:
    for item in items:
        if item.id == item_id:
            return item
    return None


def _words(request: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", request.lower())


def _title_score(title: str, request: str) -> int:
    wanted = _match_words(request)
    title_words = set(_words(title))
    score = 0
    for word in wanted:
        if word in title_words:
            score += len(word)
        elif len(word) >= 3 and any(word in part or part in word for part in title_words if len(part) >= 3):
            score += len(word)
    return score


def _match_words(request: str) -> list[str]:
    words = []
    for word in _words(request):
        if word in STOP_WORDS or word in WEEKDAY_INDEX or word in MONTHS:
            continue
        if _day_number(word) is not None:
            continue
        words.append(word)
    return words


def _match_item(
    items: list[Item],
    request: str,
    week_start: str,
    existing: Plan | None,
) -> Item | None:
    """Pick a deadline. A block already on this week beats an older assignment with the same word."""
    if not _match_words(request):
        return None
    week = date.fromisoformat(week_start)
    week_end = week + timedelta(days=6)
    scheduled = set() if existing is None else {block.item_id for block in existing.blocks}
    best: Item | None = None
    best_rank = (0, 0, 0, 0)
    for item in items:
        score = _title_score(item.title, request)
        if score <= 0:
            continue
        cutoff = _cutoff_for(item.due_or_start).date()
        rank = (
            score,
            1 if item.id in scheduled else 0,
            1 if week <= cutoff <= week_end else 0,
            1 if cutoff >= week else 0,
        )
        if rank > best_rank:
            best = item
            best_rank = rank
    return best


def _place(
    profile: Profile,
    plan,
    day: date,
    skip_id: str | None,
    preferred: datetime | None,
    duration: timedelta,
    not_after: datetime | None,
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

    def fits(start: datetime, end: datetime) -> bool:
        if end <= start or start < wake or end > sleep:
            return False
        if not_after is not None and end > not_after:
            return False
        return not _overlaps(start, end, occupied)

    if preferred is not None:
        start = _on_clock(day, f"{preferred.hour:02d}:{preferred.minute:02d}")
        end = start + duration
        if fits(start, end):
            return start, end
    if duration == timedelta(hours=1):
        for start, end in reversed(_slots(day, profile)):
            if fits(start, end):
                return start, end
        return None
    cursor = sleep - duration
    while cursor >= wake:
        end = cursor + duration
        if fits(cursor, end):
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
