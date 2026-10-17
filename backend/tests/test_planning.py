"""Validator, planner tools, and the Gemini retry loop. No network calls."""

import json
from datetime import date

import pytest

from models import Block, Commitment, Item, Plan, Profile, WakingHours
from planning.gemini_plan import GeminiError, ModelTurn, choose_week_start, plan_week
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


def test_missing_api_key_refuses_before_a_request(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = Store(tmp_path / "state.json")
    with pytest.raises(GeminiError) as caught:
        plan_week(store, "Plan the week")
    assert caught.value.status_code == 400
    assert "GEMINI_API_KEY" in str(caught.value)


def test_gemini_endpoint_keeps_items_without_a_key(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    created = client.post(
        "/api/items",
        json={"title": "HW1", "type": "assignment", "due_or_start": "2026-10-23T18:00"},
    ).json()
    response = client.post("/api/plan/gemini", json={"request": "Plan the week"})
    assert response.status_code == 400
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert client.get("/api/items").json()[0]["id"] == created["id"]
    assert client.get("/api/plans").json() == []


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


def test_declarations_cover_the_planner_tools():
    pytest.importorskip("google.genai")
    from planning.gemini_plan import build_declarations

    assert [item.name for item in build_declarations()] == TOOL_NAMES
