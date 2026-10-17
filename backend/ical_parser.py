"""Parse a raw iCal string into a list of planner items. Standard library only."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo  # on Windows you may need: pip install tzdata

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# First matching type wins, checked in this order. Whole-word, case-insensitive.
TYPE_RULES = [
    ("exam", ["exam", "midterm"]),
    ("quiz", ["quiz", "quizzes"]),
    ("assignment", ["hw", "homework", "assignment", "problem set", "pset",
                    "project", "lab", "report", "essay", "paper"]),
    ("event", ["meeting", "rehearsal", "office hours", "lecture", "section",
               "session", "club", "practice"]),
]
DEFAULT_TYPE = "event"

COURSE_RE = re.compile(r"\b([A-Z]{2,4})\s?(\d{3})\b")


def _classify(title):
    for type_name, keywords in TYPE_RULES:
        for kw in keywords:
            # Allows plurals and trailing digits, so "HW3" and "labs" both match.
            if re.search(r"\b" + re.escape(kw) + r"(?:s|es)?\d*\b", title, re.I):
                return type_name
    return DEFAULT_TYPE


def _unescape(text):
    return re.sub(
        r"\\(.)",
        lambda m: "\n" if m.group(1) in "nN" else m.group(1),
        text,
    )


def _to_iso(value, params):
    """Convert an iCal date or datetime value to ISO 8601 in local time."""
    if "T" not in value:  # date-only (all-day) value
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=LOCAL_TZ).isoformat()
    dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    else:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"]))
        except (KeyError, Exception):
            dt = dt.replace(tzinfo=LOCAL_TZ)  # floating time: assume local
    return dt.astimezone(LOCAL_TZ).isoformat()


def parse_ical(raw):
    """Return one dict per VEVENT: id, title, course, type, due_or_start,
    description, locked. Events without a DTSTART are skipped."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # unfold continuation lines

    items, seen, event = [], set(), None
    for line in text.split("\n"):
        if line.strip().upper() == "BEGIN:VEVENT":
            event = {}
            continue
        if line.strip().upper() == "END:VEVENT":
            if event is not None and "DTSTART" in event:
                title = _unescape(event.get("SUMMARY", "")).strip()
                dtstart_value, dtstart_params = event["DTSTART"]
                due = _to_iso(dtstart_value, dtstart_params)
                uid = event.get("UID", f"{due}-{title}")
                item_type = _classify(title)
                if uid not in seen:
                    seen.add(uid)
                    match = COURSE_RE.search(title)
                    items.append({
                        "id": uid,
                        "title": title,
                        "course": f"{match.group(1)} {match.group(2)}" if match else None,
                        "type": item_type,
                        "due_or_start": due,
                        "description": _unescape(event.get("DESCRIPTION", "")).strip(),
                        "locked": item_type == "exam",
                    })
            event = None
            continue
        if event is None or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        name, *param_parts = name_part.split(";")
        name = name.upper()
        if name == "DTSTART":
            params = dict(p.split("=", 1) for p in param_parts if "=" in p)
            event["DTSTART"] = (value.strip(), params)
        elif name in ("UID", "SUMMARY", "DESCRIPTION"):
            event[name] = value
    return items


# ---------------------------------------------------------------- examples
EXAMPLE_1 = """BEGIN:VEVENT
UID:event-assignment-1001@example.edu
DTSTART:20261024T060000Z
SUMMARY:HW3: SQL queries and joins [CSE 414 A Au 26]
DESCRIPTION:Write SQL for problems 1 to 5.
END:VEVENT"""

EXPECTED_1 = [{
    "id": "event-assignment-1001@example.edu",
    "title": "HW3: SQL queries and joins [CSE 414 A Au 26]",
    "course": "CSE 414",
    "type": "assignment",
    "due_or_start": "2026-10-23T23:00:00-07:00",
    "description": "Write SQL for problems 1 to 5.",
    "locked": False,
}]

EXAMPLE_2 = (
    "BEGIN:VEVENT\n"
    "UID:exam-2002@example.edu\n"
    "DTSTART;TZID=America/Los_Angeles:20261022T180000\n"
    "SUMMARY:MATH 207 Midterm Exam\n"
    "DESCRIPTION:Bring a calculator.\\nRoom to be announced\\, check\n"
    "  the syllabus.\n"
    "END:VEVENT"
)

EXPECTED_2 = [{
    "id": "exam-2002@example.edu",
    "title": "MATH 207 Midterm Exam",
    "course": "MATH 207",
    "type": "exam",
    "due_or_start": "2026-10-22T18:00:00-07:00",
    "description": "Bring a calculator.\nRoom to be announced, check the syllabus.",
    "locked": True,
}]

if __name__ == "__main__":
    assert parse_ical(EXAMPLE_1) == EXPECTED_1
    assert parse_ical(EXAMPLE_2) == EXPECTED_2
    print("Both examples pass.")
