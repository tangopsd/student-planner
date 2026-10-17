from ical_parser import EXPECTED_1, EXPECTED_2, EXAMPLE_1, EXAMPLE_2, parse_ical


def test_shipped_examples():
    assert parse_ical(EXAMPLE_1) == EXPECTED_1
    assert parse_ical(EXAMPLE_2) == EXPECTED_2


def test_skips_events_without_dtstart_and_duplicate_uids():
    raw = """BEGIN:VEVENT
UID:once@example.edu
SUMMARY:HW1 problem set
DTSTART:20261020T170000Z
END:VEVENT
BEGIN:VEVENT
UID:once@example.edu
SUMMARY:HW1 problem set
DTSTART:20261020T170000Z
END:VEVENT
BEGIN:VEVENT
UID:nodate@example.edu
SUMMARY:Mystery
END:VEVENT
"""
    items = parse_ical(raw)
    assert len(items) == 1
    assert items[0]["id"] == "once@example.edu"
    assert items[0]["type"] == "assignment"
    assert items[0]["locked"] is False


def test_quiz_keyword_and_default_event():
    raw = """BEGIN:VEVENT
UID:q@example.edu
SUMMARY:CSE 414 Quiz 2
DTSTART;TZID=America/Los_Angeles:20261102T100000
END:VEVENT
BEGIN:VEVENT
UID:p@example.edu
SUMMARY:Grocery run
DTSTART;TZID=America/Los_Angeles:20261102T180000
END:VEVENT
"""
    items = {item["id"]: item for item in parse_ical(raw)}
    assert items["q@example.edu"]["type"] == "quiz"
    assert items["q@example.edu"]["locked"] is False
    assert items["p@example.edu"]["type"] == "event"
    assert items["p@example.edu"]["course"] is None
