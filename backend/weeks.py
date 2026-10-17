"""Group deadline items into Monday-start weeks in America/Los_Angeles."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ical_parser import LOCAL_TZ

MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def today_in_la() -> date:
    return datetime.now(LOCAL_TZ).date()


def week_start_for(instant: datetime) -> date:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=LOCAL_TZ)
    local = instant.astimezone(LOCAL_TZ)
    return local.date() - timedelta(days=local.weekday())


def format_week_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{MONTHS[start.month - 1]} {start.day} – {end.day}, {start.year}"
    if start.year == end.year:
        return (
            f"{MONTHS[start.month - 1]} {start.day} – "
            f"{MONTHS[end.month - 1]} {end.day}, {start.year}"
        )
    return (
        f"{MONTHS[start.month - 1]} {start.day}, {start.year} – "
        f"{MONTHS[end.month - 1]} {end.day}, {end.year}"
    )


def group_items(items: list[dict], today: date | None = None) -> list[dict]:
    """Return weeks that contain at least one item, earliest week first."""
    current = today if today is not None else today_in_la()
    current_start = current - timedelta(days=current.weekday())
    buckets: dict[date, list[dict]] = {}
    for item in items:
        due = datetime.fromisoformat(item["due_or_start"])
        start = week_start_for(due)
        buckets.setdefault(start, []).append(item)

    weeks = []
    for start in sorted(buckets):
        end = start + timedelta(days=6)
        if start < current_start:
            relation = "past"
        elif start == current_start:
            relation = "current"
        else:
            relation = "upcoming"
        members = sorted(buckets[start], key=lambda row: (row["due_or_start"], row["title"]))
        weeks.append(
            {
                "week_start": start.isoformat(),
                "week_end": end.isoformat(),
                "label": format_week_label(start, end),
                "relation": relation,
                "items": members,
            }
        )
    return weeks
