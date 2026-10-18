"""Validator, planner tools, and the Gemini retry loop. No network calls."""

import json
from datetime import date

import pytest

from models import Block, Commitment, Item, Plan, Profile, WakingHours
from planning.gemini_plan import ModelTurn, choose_week_start, plan_week
from planning.tools import TOOL_NAMES, ToolContext, execute_tool
from planning.validator import validate_week
from store import Store, StoreError


def make_profile(commitments=None, capacity=4.0, wake="08:00", sleep="23:30"):
    return Profile(
        waking_hours=WakingHours(wake=wake, sleep=sleep),
        fixed_commitments=commitments or [],
        preferred_study_windows=[],
        daily_capacity_hours=capacity,
    )


def make_item(**overrides):
    data = dict(
        id="hw-1",
        title="HW1",
        course="CSE 414",
        type="assignment",
        due_or_start="2026-10-23T18:00:00-07:00",
        source="manual",
        estimated_effort_hours=1,
        locked=False,
        status="open",
        description="",
    )
    data.update(overrides)
    return Item(**data)


def make_block(**overrides):
    data = dict(
        id="b1",
        item_id="hw-1",
        start="2026-10-20T18:00:00-07:00",
        end="2026-10-20T19:00:00-07:00",
        kind="study",
        status="scheduled",
        reason="",
    )
    data.update(overrides)
    return Block(**data)


def make_plan(blocks, week="2026-10-19"):
    return Plan(
        week_start=week,
        blocks=blocks,
        version=1,
        previous_version=None,
        change_log=[],
    )


def errors_for(blocks, items=None, profile=None, locked=None, original=None, week="2026-10-19"):
    rows = items if items is not None else [make_item()]
    return validate_week(
        profile or make_profile(),
        rows,
        make_plan(blocks, week),
        {} if locked is None else locked,
        {item.id for item in rows} if original is None else original,
    )


def test_overlap_waking_hours_capacity_and_commitments():
    overlap = errors_for(
        [
            make_block(),
            make_block(id="b2", start="2026-10-20T18:30:00-07:00", end="2026-10-20T19:30:00-07:00"),
        ]
    )
    assert any("overlap" in error for error in overlap)

    touching = errors_for(
        [
            make_block(),
            make_block(id="b2", start="2026-10-20T19:00:00-07:00", end="2026-10-20T20:00:00-07:00"),
        ]
    )
    assert touching == []

    early = errors_for(
        [make_block(start="2026-10-20T07:00:00-07:00", end="2026-10-20T08:30:00-07:00")]
    )
    assert any("waking" in error for error in early)

    late = errors_for(
        [make_block(start="2026-10-20T22:00:00-07:00", end="2026-10-20T23:45:00-07:00")]
    )
    assert any("sleep" in error for error in late)

    over = errors_for(
        [
            make_block(id="b1", start="2026-10-20T08:00:00-07:00", end="2026-10-20T12:00:00-07:00"),
            make_block(id="b2", start="2026-10-20T12:00:00-07:00", end="2026-10-20T13:00:00-07:00"),
        ]
    )
    assert any("capacity" in error for error in over)

    buffer = errors_for(
        [
            make_block(
                id="b1",
                kind="buffer",
                item_id=None,
                start="2026-10-20T08:00:00-07:00",
                end="2026-10-20T14:00:00-07:00",
            ),
            make_block(id="b2", start="2026-10-20T14:00:00-07:00", end="2026-10-20T16:00:00-07:00"),
        ]
    )
    assert buffer == []

    lecture = Commitment(
        id="c1",
        title="Lecture",
        course="CSE 414",
        day="tue",
        start="18:00",
        end="19:00",
    )
    clash = errors_for([make_block()], profile=make_profile(commitments=[lecture]))
    assert any("Lecture" in error for error in clash)
    clear = errors_for(
        [make_block(start="2026-10-20T19:00:00-07:00", end="2026-10-20T20:00:00-07:00")],
        profile=make_profile(commitments=[lecture]),
    )
    assert clear == []


def test_midnight_due_and_locked_baseline():
    midnight = make_item(due_or_start="2026-10-21T00:00:00-07:00")
    same_day = errors_for(
        [make_block(start="2026-10-21T20:00:00-07:00", end="2026-10-21T22:00:00-07:00")],
        items=[midnight],
    )
    assert same_day == []
    next_day = errors_for(
        [make_block(start="2026-10-22T08:00:00-07:00", end="2026-10-22T09:00:00-07:00")],
        items=[midnight],
    )
    assert any("deadline" in error for error in next_day)

    timed = make_item(due_or_start="2026-10-21T17:00:00-07:00")
    fits = errors_for(
        [make_block(start="2026-10-21T16:00:00-07:00", end="2026-10-21T17:00:00-07:00")],
        items=[timed],
    )
    assert fits == []
    late = errors_for(
        [make_block(start="2026-10-21T16:00:00-07:00", end="2026-10-21T17:30:00-07:00")],
        items=[timed],
    )
    assert any("deadline" in error for error in late)

    exam = make_item(
        id="exam-1",
        title="Midterm",
        type="exam",
        locked=True,
        estimated_effort_hours=None,
        due_or_start="2026-10-26T15:30:00-07:00",
    )
    sitting = errors_for(
        [
            make_block(
                id="sit",
                item_id="exam-1",
                kind="fixed",
                start="2026-10-26T15:30:00-07:00",
                end="2026-10-26T16:30:00-07:00",
            )
        ],
        items=[exam],
        locked={"exam-1": exam.due_or_start},
        week="2026-10-26",
    )
    assert sitting == []

    moved = exam.model_copy(update={"due_or_start": "2026-10-27T15:30:00-07:00"})
    changed = validate_week(
        make_profile(),
        [moved, make_item()],
        make_plan([make_block()]),
        {"exam-1": exam.due_or_start},
        {"exam-1", "hw-1"},
    )
    assert any("Locked deadline exam-1" in error for error in changed)

    missing = validate_week(
        make_profile(),
        [exam],
        None,
        {"exam-1": exam.due_or_start},
        {"exam-1", "hw-1"},
    )
    assert any("hw-1 is missing" in error for error in missing)
    assert any("No blocks were scheduled" in error for error in missing)


def test_choose_week_start_skips_to_next_monday_on_the_weekend():
    saturday = date(2026, 10, 17)
    items = [
        make_item(due_or_start="2026-10-18T12:00:00-07:00"),
        make_item(id="later", due_or_start="2026-10-26T15:30:00-07:00"),
    ]
    assert choose_week_start(items, saturday) == date(2026, 10, 19)

    wednesday = date(2026, 10, 21)
    assert choose_week_start(
        [make_item(due_or_start="2026-10-22T12:00:00-07:00")],
        wednesday,
    ) == date(2026, 10, 19)

    only_sunday = [make_item(due_or_start="2026-10-18T12:00:00-07:00")]
    assert choose_week_start(only_sunday, saturday) == date(2026, 10, 12)

    assert choose_week_start(
        [make_item(status="done", due_or_start="2026-10-28T12:00:00-07:00")],
        saturday,
    ) == date(2026, 10, 19)


def test_state_without_undo_stack_loads(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "profile": {
                    "waking_hours": {"wake": "08:00", "sleep": "23:30"},
                    "fixed_commitments": [],
                    "preferred_study_windows": [],
                    "daily_capacity_hours": 4,
                },
                "items": [],
                "plans": [],
            }
        ),
        encoding="utf-8",
    )
    store = Store(path)
    assert store.items() == []
    assert store.plans() == []


def test_undo_restores_plans_and_appends_on_the_same_version(tmp_path):
    store = Store(tmp_path / "state.json")
    store.add_item(make_item())
    at = "2026-10-17T12:00:00-07:00"
    store.create_blocks("2026-10-19", [make_block()], "Scheduled 1 block", at)
    store.create_blocks(
        "2026-10-19",
        [make_block(id="b2", start="2026-10-20T19:00:00-07:00", end="2026-10-20T20:00:00-07:00")],
        "Scheduled 1 block",
        at,
    )
    plans = store.plans("2026-10-19")
    assert len(plans) == 1
    assert plans[0].version == 1
    assert [block.id for block in plans[0].blocks] == ["b1", "b2"]
    assert len(plans[0].change_log) == 2

    with pytest.raises(StoreError, match="already exists"):
        store.create_blocks("2026-10-19", [make_block()], "again", at)
    assert store.undo() == "Scheduled 1 block"
    assert [block.id for block in store.latest_plan("2026-10-19").blocks] == ["b1"]
    assert store.undo() == "Scheduled 1 block"
    assert store.plans() == []
    assert len(store.items()) == 1
    with pytest.raises(StoreError, match="Nothing to undo"):
        store.undo()


def test_locked_move_does_not_push_undo(tmp_path):
    store = Store(tmp_path / "state.json")
    exam = make_item(
        id="exam-1",
        title="Midterm",
        type="exam",
        locked=True,
        estimated_effort_hours=None,
        due_or_start="2026-10-26T15:30:00-07:00",
    )
    store.add_item(exam)
    ctx = ToolContext(store, {exam.id: exam.due_or_start}, {exam.id})
    moved = execute_tool(
        ctx,
        "move_item",
        {"item_id": exam.id, "due_or_start": "2026-10-30T10:00:00-07:00"},
    )
    assert "locked" in moved["error"].lower()
    with pytest.raises(StoreError, match="Nothing to undo"):
        store.undo()
    assert store.items()[0].due_or_start == exam.due_or_start
    assert store.items()[0].locked is True

    missing = execute_tool(
        ctx,
        "create_blocks",
        {
            "week_start": "2026-10-19",
            "blocks": [
                {
                    "id": "ghost",
                    "item_id": "missing",
                    "start": "2026-10-20T18:00:00-07:00",
                    "end": "2026-10-20T19:00:00-07:00",
                    "kind": "study",
                }
            ],
        },
    )
    assert "error" in missing
    assert store.plans() == []
    with pytest.raises(StoreError, match="Nothing to undo"):
        store.undo()


def test_tools_list_filter_constraint_and_week_errors(tmp_path):
    store = Store(tmp_path / "state.json")
    store.add_item(make_item())
    ctx = ToolContext(store, {}, {"hw-1"})
    listed = execute_tool(ctx, "list_items", {"week_start": "2026-10-19", "status": "open"})
    assert [item["id"] for item in listed["items"]] == ["hw-1"]
    later = execute_tool(ctx, "list_items", {"week_start": "2026-10-26"})
    assert later["items"] == []
    assert "error" in execute_tool(ctx, "drop_table", {})

    changed = execute_tool(ctx, "set_constraint", {"daily_capacity_hours": 2})
    assert changed["daily_capacity_hours"] == 2
    assert store.undo() == "Updated hours"
    assert store.profile().daily_capacity_hours == 4
    invalid = execute_tool(ctx, "set_constraint", {"wake": "23:00", "sleep": "07:00"})
    assert "error" in invalid
    with pytest.raises(StoreError, match="Nothing to undo"):
        store.undo()

    execute_tool(
        ctx,
        "create_blocks",
        {
            "week_start": "2026-10-19",
            "blocks": [
                {
                    "id": "b1",
                    "item_id": "hw-1",
                    "start": "2026-10-20T18:00:00-07:00",
                    "end": "2026-10-20T19:00:00-07:00",
                    "kind": "study",
                },
                {
                    "id": "b2",
                    "item_id": "hw-1",
                    "start": "2026-10-20T18:30:00-07:00",
                    "end": "2026-10-20T19:30:00-07:00",
                    "kind": "study",
                },
            ],
        },
    )
    view = execute_tool(ctx, "get_week_plan", {"week_start": "2026-10-19"})
    assert view["valid"] is False
    assert any("overlap" in error for error in view["errors"])
    undone = execute_tool(ctx, "undo_last_change", {})
    assert undone["undone"] is True
    assert store.plans() == []
    assert [item.id for item in store.items()] == ["hw-1"]


class OverlapThenFix:
    def __init__(self):
        self.calls = 0
        self.fixed = False

    def complete(self, turns):
        self.calls += 1
        invalid = any(
            turn.get("role") == "user" and "The plan is invalid" in turn.get("text", "")
            for turn in turns
        )
        if not invalid:
            if self.calls == 1:
                return ModelTurn(
                    "Scheduling the overlap.",
                    [
                        (
                            "create_blocks",
                            {
                                "week_start": "2026-10-19",
                                "blocks": [
                                    {
                                        "id": "b1",
                                        "item_id": "hw-1",
                                        "start": "2026-10-20T18:00:00-07:00",
                                        "end": "2026-10-20T19:00:00-07:00",
                                        "kind": "study",
                                        "reason": "First pass",
                                    },
                                    {
                                        "id": "b2",
                                        "item_id": "hw-1",
                                        "start": "2026-10-20T18:30:00-07:00",
                                        "end": "2026-10-20T19:30:00-07:00",
                                        "kind": "study",
                                        "reason": "Overlaps",
                                    },
                                ],
                            },
                        )
                    ],
                )
            return ModelTurn("Done.", [])
        if not self.fixed:
            self.fixed = True
            return ModelTurn(
                "Fixing the overlap.",
                [
                    ("delete_block", {"block_id": "b2"}),
                    (
                        "create_blocks",
                        {
                            "week_start": "2026-10-19",
                            "blocks": [
                                {
                                    "id": "b3",
                                    "item_id": "hw-1",
                                    "start": "2026-10-20T19:00:00-07:00",
                                    "end": "2026-10-20T20:00:00-07:00",
                                    "kind": "study",
                                    "reason": "After the overlap was removed",
                                }
                            ],
                        },
                    ),
                ],
            )
        return ModelTurn("Done.", [])


def test_retry_keeps_existing_items_and_repairs_the_week(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    exam = make_item(
        id="exam-1",
        title="Midterm",
        type="exam",
        locked=True,
        estimated_effort_hours=None,
        due_or_start="2026-10-26T15:30:00-07:00",
    )
    store.add_item(exam)
    store.add_item(make_item())
    model = OverlapThenFix()
    result = plan_week(store, "Plan the week", week_start="2026-10-19", model=model)
    assert result["valid"] is True, result["errors"]
    assert result["attempts"] == 2
    assert result["week_start"] == "2026-10-19"
    assert model.calls == 4
    ids = [block.id for block in result["plan"].blocks]
    assert ids == ["b1", "b3"]
    stored = {item.id: item for item in store.items()}
    assert set(stored) == {"hw-1", "exam-1"}
    assert stored["exam-1"].locked is True
    assert stored["exam-1"].due_or_start == exam.due_or_start


def test_missing_api_key_schedules_existing_items(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    exam = make_item(
        id="exam-1",
        title="Midterm",
        type="exam",
        locked=True,
        estimated_effort_hours=None,
        due_or_start="2026-10-26T15:30:00-07:00",
    )
    event = make_item(
        id="class-1",
        title="Five in a row",
        type="event",
        due_or_start="2026-10-20T15:30:00-07:00",
        estimated_effort_hours=None,
    )
    store.add_item(exam)
    store.add_item(event)
    store.add_item(make_item(due_or_start="2026-10-23T18:00:00-07:00"))
    store.add_item(
        make_item(
            id="midnight-1",
            title="Assignment 2",
            due_or_start="2026-10-21T00:00:00-07:00",
            estimated_effort_hours=None,
        )
    )
    result = plan_week(store, "Plan the week", week_start="2026-10-19")
    assert result["valid"] is True, result["errors"]
    assert result["week_start"] == "2026-10-19"
    blocks = result["plan"].blocks
    assert blocks
    by_item: dict[str, list] = {}
    for block in blocks:
        by_item.setdefault(block.item_id, []).append(block)
    assert any(block.kind == "study" for block in by_item["hw-1"])
    assert any(block.kind == "study" for block in by_item["midnight-1"])
    assert by_item["class-1"][0].kind == "fixed"
    assert "exam-1" not in by_item
    stored = {item.id: item for item in store.items()}
    assert set(stored) == {"hw-1", "exam-1", "class-1", "midnight-1"}
    assert stored["exam-1"].locked is True
    assert stored["exam-1"].due_or_start == exam.due_or_start
    again = plan_week(store, "Plan the week", week_start="2026-10-19")
    assert [block.id for block in again["plan"].blocks] == [block.id for block in blocks]


def test_typed_rehearsal_calls_add_item_and_shows_a_block(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from planning.tools import execute_tool as real_tool

    calls = []

    def spy(ctx, name, args):
        calls.append(name)
        return real_tool(ctx, name, args)

    monkeypatch.setattr("planning.local_plan.execute_tool", spy)
    store = Store(tmp_path / "state.json")
    store.add_item(make_item())
    plan_week(store, "Plan the week", week_start="2026-10-19")
    result = plan_week(store, "add a rehearsal on Friday from 7 to 9pm", week_start="2026-10-19")
    assert result["valid"] is True, result
    assert calls == ["add_item", "create_blocks"]
    added = next(item for item in store.items() if item.title == "Rehearsal")
    assert added.type == "event"
    assert added.source == "manual"
    block = next(block for block in result["plan"].blocks if block.item_id == added.id)
    assert block.kind == "fixed"
    assert block.start.startswith("2026-10-23T19:00")
    assert block.end.startswith("2026-10-23T21:00")
    assert "Friday" in result["message"]
    assert [call["name"] for call in result["tool_calls"]] == ["add_item", "create_blocks"]


def test_typed_dentist_appointment_fills_one_hour(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    store.add_item(make_item())
    first = plan_week(store, "Plan the week", week_start="2026-10-19")
    kept = [block.id for block in first["plan"].blocks]
    result = plan_week(store, "I have a dentist appointment Tuesday at 3", week_start="2026-10-19")
    assert result["valid"] is True, result
    added = next(item for item in store.items() if item.title == "Dentist appointment")
    block = next(block for block in result["plan"].blocks if block.item_id == added.id)
    assert block.kind == "fixed"
    assert block.start.startswith("2026-10-20T15:00")
    assert block.end.startswith("2026-10-20T16:00")
    assert kept == [row.id for row in result["plan"].blocks if row.id in kept]


def test_typed_homework_gets_a_study_block(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    result = plan_week(store, "add homework on Wednesday", week_start="2026-10-19")
    assert result["valid"] is True, result
    added = store.items()[0]
    assert added.type == "assignment"
    block = result["plan"].blocks[0]
    assert block.item_id == added.id
    assert block.kind == "study"
    assert block.start.startswith("2026-10-21")


def test_typed_delete_removes_the_friday_rehearsal(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from planning.tools import execute_tool as real_tool

    calls = []

    def spy(ctx, name, args):
        calls.append(name)
        return real_tool(ctx, name, args)

    monkeypatch.setattr("planning.local_plan.execute_tool", spy)
    store = Store(tmp_path / "state.json")
    plan_week(store, "add a rehearsal on Friday from 7 to 9pm", week_start="2026-10-19")
    calls.clear()
    result = plan_week(store, "delete the rehearsal on Friday", week_start="2026-10-19")
    assert result["valid"] is True, result
    assert calls == ["delete_block"]
    assert [call["name"] for call in result["tool_calls"]] == ["delete_block"]
    assert result["plan"].blocks == []
    assert store.items() == []
    assert result["message"] == "Removed Rehearsal from Friday Oct 23."


def test_typed_delete_keeps_the_deadline_while_another_block_uses_it(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    plan_week(store, "add a rehearsal on Friday from 7 to 9pm", week_start="2026-10-19")
    item = store.items()[0]
    store.create_blocks(
        "2026-10-19",
        [
            make_block(
                id="extra-block",
                item_id=item.id,
                start="2026-10-22T16:00:00-07:00",
                end="2026-10-22T17:00:00-07:00",
                kind="fixed",
                reason="Rehearsal",
            )
        ],
        "second sitting",
        "2026-10-17T16:00:00-07:00",
    )
    result = plan_week(store, "delete the rehearsal on Friday", week_start="2026-10-19")
    assert result["valid"] is True, result
    assert [row.id for row in store.items()] == [item.id]
    assert [block.start[:10] for block in result["plan"].blocks] == ["2026-10-22"]


def test_typed_delete_drops_a_deadline_that_only_an_older_plan_mentions(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    plan_week(store, "add a rehearsal on Friday from 7 to 9pm", week_start="2026-10-19")
    item_id = store.items()[0].id
    latest = store.latest_plan("2026-10-19")
    assert latest is not None
    store.add_plan("2026-10-19", list(latest.blocks), "Saved a copy", "2026-10-17T16:00:00-07:00")
    with pytest.raises(StoreError, match="still linked"):
        store.delete_item(item_id)
    result = plan_week(store, "delete the rehearsal on Friday", week_start="2026-10-19")
    assert result["valid"] is True, result
    assert result["plan"].blocks == []
    assert store.items() == []
    history = store.plans("2026-10-19")
    assert history[0].blocks[0].item_id == item_id
    assert history[-1].blocks == []


def test_typed_remove_finds_the_dentist_without_a_day(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    plan_week(store, "I have a dentist appointment Tuesday at 3", week_start="2026-10-19")
    plan_week(store, "add a club meeting on Wednesday from 4 to 5pm", week_start="2026-10-19")
    result = plan_week(store, "remove my dentist appointment", week_start="2026-10-19")
    assert result["valid"] is True, result
    assert "Removed Dentist appointment" in result["message"]
    titles = [block.reason for block in result["plan"].blocks]
    assert "Dentist appointment" not in titles
    assert any("Club meeting" in title for title in titles)


def test_cancel_on_a_day_leaves_the_other_block(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    plan_week(store, "add a club meeting on Wednesday from 4 to 5pm", week_start="2026-10-19")
    plan_week(store, "add a club meeting on Friday from 4 to 5pm", week_start="2026-10-19")
    result = plan_week(store, "cancel the club meeting on Wednesday", week_start="2026-10-19")
    assert result["valid"] is True, result
    assert "Wednesday" in result["message"]
    assert len(result["plan"].blocks) == 1
    assert result["plan"].blocks[0].start.startswith("2026-10-23")


def test_locked_exam_is_not_deleted(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    exam = make_item(
        id="exam-1",
        title="Midterm Exam",
        type="exam",
        locked=True,
        estimated_effort_hours=None,
        due_or_start="2026-10-21T15:30:00-07:00",
    )
    store.add_item(exam)
    store.create_blocks(
        "2026-10-19",
        [
            make_block(
                id="exam-block",
                item_id="exam-1",
                start="2026-10-21T15:30:00-07:00",
                end="2026-10-21T16:30:00-07:00",
                kind="fixed",
            )
        ],
        "seed",
        "2026-10-17T16:00:00-07:00",
    )
    result = plan_week(store, "delete the midterm on Wednesday", week_start="2026-10-19")
    assert result["valid"] is False
    assert "locked" in result["message"].lower()
    assert result["plan"].blocks[0].id == "exam-block"
    assert store.items()[0].locked is True


def test_prompt_tells_gemini_to_call_add_item_for_a_new_event():
    from planning.gemini_plan import _prompt

    text = _prompt(
        "add a rehearsal on Friday from 7 to 9pm",
        "2026-10-19",
        make_profile(),
        [],
    )
    assert "call add_item" in text
    assert "create_blocks" in text
    assert "move_block" in text


def test_reschedule_request_moves_the_matching_block(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    store.add_item(make_item())
    first = plan_week(store, "Plan the week", week_start="2026-10-19")
    original = next(block for block in first["plan"].blocks if block.item_id == "hw-1")
    moved = plan_week(store, "move HW1 to Wednesday", week_start="2026-10-19")
    assert moved["valid"] is True, moved["errors"]
    block = next(row for row in moved["plan"].blocks if row.item_id == "hw-1")
    assert block.id == original.id
    assert block.start.startswith("2026-10-21")
    assert "Wednesday" in moved["message"]
    assert any(call["name"] == "move_block" for call in moved["tool_calls"])
    assert store.items()[0].due_or_start == "2026-10-23T18:00:00-07:00"


def test_review_request_adds_a_block_without_moving_the_exam(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    exam = make_item(
        id="exam-1",
        title="Midterm Exam",
        type="exam",
        locked=True,
        estimated_effort_hours=None,
        due_or_start="2026-10-26T15:30:00-07:00",
    )
    store.add_item(exam)
    store.add_item(make_item())
    plan_week(store, "Plan the week", week_start="2026-10-19")
    result = plan_week(store, "move my midterm review to Wednesday", week_start="2026-10-19")
    assert result["valid"] is True, result["errors"]
    reviews = [block for block in result["plan"].blocks if block.item_id == "exam-1"]
    assert len(reviews) == 1
    assert reviews[0].kind == "study"
    assert reviews[0].start.startswith("2026-10-21")
    stored = {item.id: item for item in store.items()}
    assert stored["exam-1"].locked is True
    assert stored["exam-1"].due_or_start == exam.due_or_start


def test_saturday_assignment_moves_to_tuesday(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    store.add_item(
        make_item(
            id="warm-up",
            title="Assignment 0: Python Warm-up",
            course="CSE 415 A",
            due_or_start="2026-10-05T00:00:00-07:00",
            estimated_effort_hours=None,
        )
    )
    store.add_item(
        make_item(
            id="arch-1",
            title="Assignment 01: Your Third Place",
            course="ARCH 151 A",
            due_or_start="2026-10-24T00:00:00-07:00",
            estimated_effort_hours=None,
        )
    )
    store.create_blocks(
        "2026-10-19",
        [
            make_block(
                id="sat-block",
                item_id="arch-1",
                start="2026-10-24T22:00:00-07:00",
                end="2026-10-24T23:00:00-07:00",
            )
        ],
        "seed",
        "2026-10-17T16:00:00-07:00",
    )
    result = plan_week(store, "move saturday's assignment up to tuesday", week_start="2026-10-19")
    assert result["valid"] is True, result["errors"]
    assert "already has a schedule" not in result["message"].lower()
    assert "Block " not in result["message"]
    assert len(result["plan"].blocks) == 1
    moved = result["plan"].blocks[0]
    assert moved.id == "sat-block"
    assert moved.item_id == "arch-1"
    assert moved.start.startswith("2026-10-20")
    assert store.items()[0].id == "warm-up"


def test_calendar_date_replans_the_existing_week(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    store.add_item(
        make_item(
            id="arch-1",
            title="Assignment 01: Your Third Place",
            due_or_start="2026-10-24T00:00:00-07:00",
            estimated_effort_hours=None,
        )
    )
    store.create_blocks(
        "2026-10-19",
        [
            make_block(
                id="sat-block",
                item_id="arch-1",
                start="2026-10-24T22:00:00-07:00",
                end="2026-10-24T23:00:00-07:00",
            )
        ],
        "seed",
        "2026-10-17T16:00:00-07:00",
    )
    result = plan_week(store, "move oct 24th's assignment to october 23rd", week_start="2026-10-19")
    assert result["valid"] is True, result["errors"]
    assert "already has a schedule" not in result["message"].lower()
    assert result["plan"].blocks[0].id == "sat-block"
    assert result["plan"].blocks[0].start.startswith("2026-10-23")


def test_deadline_retry_hides_the_raw_validator_error(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    store.set_constraint("shorter day", wake="08:00", sleep="10:00")
    store.add_item(
        make_item(
            id="hw-1",
            title="HW1",
            due_or_start="2026-10-20T00:00:00-07:00",
            estimated_effort_hours=1,
        )
    )
    store.add_item(
        make_item(
            id="other",
            title="Other",
            due_or_start="2026-10-21T00:00:00-07:00",
            estimated_effort_hours=1,
        )
    )
    store.create_blocks(
        "2026-10-19",
        [
            make_block(
                id="mon-block",
                item_id="hw-1",
                start="2026-10-19T08:00:00-07:00",
                end="2026-10-19T09:00:00-07:00",
            ),
            make_block(
                id="tue-block",
                item_id="other",
                start="2026-10-20T08:00:00-07:00",
                end="2026-10-20T10:00:00-07:00",
            ),
        ],
        "seed",
        "2026-10-17T16:00:00-07:00",
    )
    result = plan_week(store, "move monday's assignment to saturday", week_start="2026-10-19")
    assert result["valid"] is False
    assert result["attempts"] == 2
    assert "Block " not in result["message"]
    assert "deadline" in result["message"].lower()
    assert result["errors"] == [result["message"]]
    kept = next(block for block in result["plan"].blocks if block.id == "mon-block")
    assert kept.start.startswith("2026-10-19")


class LeavesTheOverlap:
    def __init__(self):
        self.retry = ""

    def complete(self, turns):
        for turn in turns:
            if turn.get("role") == "user" and "The plan is invalid" in turn.get("text", ""):
                self.retry = turn["text"]
                return ModelTurn("I could not fix it.", [])
        return ModelTurn(
            "Scheduling the overlap.",
            [
                (
                    "create_blocks",
                    {
                        "week_start": "2026-10-19",
                        "blocks": [
                            {
                                "id": "b1",
                                "item_id": "hw-1",
                                "start": "2026-10-20T18:00:00-07:00",
                                "end": "2026-10-20T19:00:00-07:00",
                                "kind": "study",
                                "reason": "First pass",
                            },
                            {
                                "id": "b2",
                                "item_id": "hw-1",
                                "start": "2026-10-20T18:30:00-07:00",
                                "end": "2026-10-20T19:30:00-07:00",
                                "kind": "study",
                                "reason": "Overlaps",
                            },
                        ],
                    },
                )
            ],
        )


def test_validator_error_is_sent_back_once_then_shortened(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    store.add_item(make_item())
    model = LeavesTheOverlap()
    result = plan_week(store, "Plan the week", week_start="2026-10-19", model=model)
    assert result["attempts"] == 2
    assert result["valid"] is False
    assert "Blocks b1 and b2 overlap." in model.retry
    assert "Block " not in result["message"]
    assert result["errors"] == [result["message"]]
    assert "overlap" in result["message"].lower()


def test_gemini_endpoint_keeps_items_without_a_key(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    created = client.post(
        "/api/items",
        json={"title": "HW1", "type": "assignment", "due_or_start": "2026-10-23T18:00"},
    ).json()
    response = client.post(
        "/api/plan/gemini",
        json={"request": "Plan the week", "week_start": "2026-10-19"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["plan"]["blocks"]
    assert body["plan"]["blocks"][0]["item_id"] == created["id"]
    assert client.get("/api/items").json()[0]["id"] == created["id"]
    assert len(client.get("/api/items").json()) == 1


def test_gemini_endpoint_returns_the_planner_result(client, monkeypatch):
    def fake(store, request, week_start=None, model=None):
        del store, model
        assert request == "Plan the week"
        assert week_start == "2026-10-19"
        return {
            "week_start": week_start,
            "plan": None,
            "valid": True,
            "errors": [],
            "attempts": 1,
            "message": "ok",
        }

    monkeypatch.setattr("main.plan_week", fake)
    response = client.post(
        "/api/plan/gemini",
        json={"request": "Plan the week", "week_start": "2026-10-19"},
    )
    assert response.status_code == 200
    assert response.json()["week_start"] == "2026-10-19"
    assert response.json()["valid"] is True


def test_turn_keeps_the_thought_signature_from_the_model():
    from planning.gemini_plan import _turn_from_response

    class Call:
        name = "list_items"
        args = {}

    class Part:
        function_call = Call()
        thought_signature = b"sig"
        text = None

    class Content:
        parts = [Part()]

    class Candidate:
        content = Content()

    class Response:
        candidates = [Candidate()]
        text = None

    turn = _turn_from_response(Response())
    assert turn.calls[0].name == "list_items"
    assert turn.calls[0].thought_signature == b"sig"


def test_declarations_cover_the_planner_tools():
    pytest.importorskip("google.genai")
    from planning.gemini_plan import build_declarations

    assert [item.name for item in build_declarations()] == TOOL_NAMES
