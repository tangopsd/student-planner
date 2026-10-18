"""Check a week plan against the student's hours and locked deadlines."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ical_parser import LOCAL_TZ
from models import Block, Item, Plan, Profile

EPSILON = 1e-6
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def validate_week(
    profile: Profile,
    items: list[Item],
    plan: Plan | None,
    locked_baseline: dict[str, str],
    original_ids: set[str],
) -> list[str]:
    """Return human-readable problems. An empty list means the week is valid.

    Canvas all-day deadlines are stored at local midnight. Study may run until
    sleep on that calendar day. Locked deadlines are compared with the dues
    captured when planning started.
    """
    errors: list[str] = []
    by_id = {item.id: item for item in items}
    for item_id in sorted(original_ids - set(by_id)):
        errors.append(f"Deadline {item_id} is missing. Do not remove existing deadlines.")
    for item_id, due in locked_baseline.items():
        item = by_id.get(item_id)
        if item is None or not item.locked or item.due_or_start != due:
            errors.append(f"Locked deadline {item_id} moved or was unlocked.")
    if plan is None or not plan.blocks:
        errors.append("No blocks were scheduled for this week.")
        return errors

    week_start = date.fromisoformat(plan.week_start)
    week_end = week_start + timedelta(days=6)
    wake = _clock(profile.waking_hours.wake)
    sleep = _clock(profile.waking_hours.sleep)
    spans: list[tuple[datetime, datetime, Block]] = []
    hours: dict[date, float] = {}

    seen: set[str] = set()
    for block in plan.blocks:
        if block.id in seen:
            errors.append(f"Two blocks share an id ({block.id}).")
        seen.add(block.id)
        try:
            start = _local(block.start)
            end = _local(block.end)
        except ValueError:
            errors.append(f"Block {block.id} has a bad time.")
            continue
        if end <= start:
            errors.append(f"Block {block.id} ends before it starts.")
            continue
        if start.date() != end.date():
            errors.append(f"Block {block.id} crosses midnight.")
            continue
        day = start.date()
        if not week_start <= day <= week_end:
            errors.append(f"Block {block.id} is outside the week of {plan.week_start}.")
        if _parts(start) < wake:
            errors.append(
                f"Block {block.id} starts before waking hours ({profile.waking_hours.wake})."
            )
        if _parts(end) > sleep:
            errors.append(f"Block {block.id} ends after sleep ({profile.waking_hours.sleep}).")
        if block.item_id is not None and block.item_id not in by_id:
            errors.append(f"Block {block.id} links to an unknown deadline.")
        elif block.item_id is not None and block.kind in ("study", "personal"):
            cutoff = _cutoff(_local(by_id[block.item_id].due_or_start))
            if end > cutoff:
                title = by_id[block.item_id].title
                errors.append(f"Block {block.id} ends after the deadline for {title}.")
        if block.kind in ("study", "personal"):
            hours[day] = hours.get(day, 0.0) + (end - start).total_seconds() / 3600
        spans.append((start, end, block))

    for index, (start, end, block) in enumerate(spans):
        for other_start, other_end, other in spans[index + 1 :]:
            if start < other_end and other_start < end:
                errors.append(f"Blocks {block.id} and {other.id} overlap.")
        weekday = DAY_KEYS[start.weekday()]
        for commitment in profile.fixed_commitments:
            if commitment.day != weekday:
                continue
            commit_start, commit_end = _on_day(start.date(), commitment.start, commitment.end)
            if start < commit_end and commit_start < end:
                errors.append(f"Block {block.id} overlaps the commitment {commitment.title}.")

    for day, total in sorted(hours.items()):
        if total > profile.daily_capacity_hours + EPSILON:
            errors.append(
                f"{WEEKDAYS[day.weekday()]} {day.isoformat()} is over the "
                f"{_hours(profile.daily_capacity_hours)} hour study capacity "
                f"({_hours(total)} hours)."
            )
    return errors


def explain_plan_errors(errors: list[str]) -> str:
    """A short sentence for the page. The validator text stays available for a retry."""
    text = " ".join(errors)
    lowered = text.lower()
    if "block " not in lowered and "deadline" not in lowered and "overlap" not in lowered:
        return text
    if "deadline" in lowered:
        return "That move would run past the deadline, so I left the week as it was."
    if "overlap" in lowered:
        return "That time overlaps something else, so I left the week as it was."
    if "waking" in lowered or "sleep" in lowered:
        return "That time is outside waking hours, so I left the week as it was."
    if "capacity" in lowered:
        return "That day is already at the study limit, so I left the week as it was."
    if "locked" in lowered:
        return "That deadline is locked, so I left it where it is."
    return "I couldn't update the week without breaking the schedule."


def _local(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _clock(value: str) -> tuple[int, int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute), 0


def _parts(value: datetime) -> tuple[int, int, int]:
    return value.hour, value.minute, value.second


def _midnight(value: datetime) -> bool:
    return (
        value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


def _cutoff(due: datetime) -> datetime:
    local = due.astimezone(LOCAL_TZ)
    if _midnight(local):
        return local.replace(hour=23, minute=59, second=59, microsecond=0)
    return local


def _on_day(day: date, start: str, end: str) -> tuple[datetime, datetime]:
    start_clock = _clock(start)
    end_clock = _clock(end)
    return (
        datetime(day.year, day.month, day.day, *start_clock, tzinfo=LOCAL_TZ),
        datetime(day.year, day.month, day.day, *end_clock, tzinfo=LOCAL_TZ),
    )


def _hours(value: float) -> str:
    rounded = round(value + 0.0, 2)
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return text or "0"
