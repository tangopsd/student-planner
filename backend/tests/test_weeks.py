from datetime import date

from ical_parser import EXPECTED_1, EXPECTED_2
from weeks import format_week_label, group_items


def test_examples_share_the_week_of_october_19():
    weeks = group_items(EXPECTED_1 + EXPECTED_2, today=date(2026, 10, 17))
    assert len(weeks) == 1
    assert weeks[0]["week_start"] == "2026-10-19"
    assert weeks[0]["week_end"] == "2026-10-25"
    assert weeks[0]["label"] == "Oct 19 – 25, 2026"
    assert weeks[0]["relation"] == "upcoming"
    assert [item["id"] for item in weeks[0]["items"]] == [
        EXPECTED_2[0]["id"],
        EXPECTED_1[0]["id"],
    ]


def test_relation_against_a_fixed_today():
    items = [
        {"id": "a", "title": "A", "due_or_start": "2026-10-14T12:00:00-07:00"},
        {"id": "b", "title": "B", "due_or_start": "2026-10-22T12:00:00-07:00"},
        {"id": "c", "title": "C", "due_or_start": "2026-11-02T10:00:00-08:00"},
    ]
    weeks = group_items(items, today=date(2026, 10, 17))
    assert [week["relation"] for week in weeks] == ["current", "upcoming", "upcoming"]
    assert weeks[0]["week_start"] == "2026-10-12"
    assert weeks[2]["label"] == "Nov 2 – 8, 2026"


def test_utc_instant_uses_los_angeles_wall_time():
    # 06:30Z is still Sunday evening in Pacific, so it belongs to the prior week.
    items = [{"id": "z", "title": "Z", "due_or_start": "2026-10-19T06:30:00+00:00"}]
    weeks = group_items(items, today=date(2026, 10, 17))
    assert weeks[0]["week_start"] == "2026-10-12"
    assert weeks[0]["relation"] == "current"


def test_cross_month_label():
    assert format_week_label(date(2026, 10, 26), date(2026, 11, 1)) == "Oct 26 – Nov 1, 2026"
