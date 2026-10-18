from pathlib import Path

from fastapi.testclient import TestClient

from ical_parser import EXPECTED_1, EXPECTED_2, EXAMPLE_1, EXAMPLE_2, parse_ical
from main import create_app
from models import Item


SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample-calendar.ics"


def test_upload_examples_and_group_them(client):
    raw = EXAMPLE_1 + "\n" + EXAMPLE_2
    response = client.post(
        "/api/calendar",
        files={"file": ("deadlines.ics", raw, "text/calendar")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2
    assert body["updated"] == 0
    assert body["parsed"] == 2
    by_id = {item["id"]: item for item in body["items"]}
    exam = by_id[EXPECTED_2[0]["id"]]
    homework = by_id[EXPECTED_1[0]["id"]]
    assert exam["type"] == "exam"
    assert exam["locked"] is True
    assert exam["course"] == "MATH 207"
    assert exam["due_or_start"] == EXPECTED_2[0]["due_or_start"]
    assert exam["description"] == EXPECTED_2[0]["description"]
    assert exam["source"] == "canvas"
    assert exam["status"] == "open"
    assert exam["estimated_effort_hours"] is None
    assert homework["type"] == "assignment"
    assert homework["locked"] is False
    assert homework["course"] == "CSE 414"

    weeks = client.get("/api/weeks").json()["weeks"]
    assert len(weeks) == 1
    assert weeks[0]["week_start"] == "2026-10-19"
    assert weeks[0]["label"] == "Oct 19 – 25, 2026"
    assert [item["title"] for item in weeks[0]["items"]] == [
        "MATH 207 Midterm Exam",
        "HW3: SQL queries and joins [CSE 414 A Au 26]",
    ]


def test_reimport_keeps_effort_and_status(client):
    client.post("/api/calendar", files={"file": ("a.ics", EXAMPLE_1, "text/calendar")})
    item_id = EXPECTED_1[0]["id"]
    patched = client.patch(
        f"/api/items/{item_id}",
        json={"status": "done", "estimated_effort_hours": 3.5},
    )
    assert patched.status_code == 200
    again = client.post(
        "/api/calendar",
        files={"file": ("a.ics", EXAMPLE_1, "text/calendar")},
    )
    assert again.json()["created"] == 0
    assert again.json()["updated"] == 1
    stored = again.json()["items"][0]
    assert stored["status"] == "done"
    assert stored["estimated_effort_hours"] == 3.5
    assert len(client.get("/api/items").json()) == 1


def test_sample_calendar_matches_parser(client):
    raw = SAMPLE.read_text(encoding="utf-8")
    expected = {item["id"]: item for item in parse_ical(raw)}
    response = client.post("/api/calendar/sample")
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 6
    got = {item["id"]: item for item in body["items"]}
    assert set(got) == set(expected)
    for uid, item in expected.items():
        assert got[uid]["type"] == item["type"]
        assert got[uid]["locked"] == item["locked"]
        assert got[uid]["course"] == item["course"]
        assert got[uid]["due_or_start"] == item["due_or_start"]
        assert got[uid]["source"] == "canvas"
    weeks = client.get("/api/weeks").json()["weeks"]
    assert [week["week_start"] for week in weeks] == [
        "2026-10-19",
        "2026-10-26",
        "2026-11-02",
    ]


def test_url_import_uses_fetcher(client, monkeypatch):
    monkeypatch.setattr("main.fetch_ics", lambda url: EXAMPLE_2)
    response = client.post("/api/calendar", json={"url": "https://calendar.example.edu/feed.ics"})
    assert response.status_code == 200
    assert response.json()["items"][0]["locked"] is True


def test_rejects_a_private_feed_url(client):
    response = client.post("/api/calendar", json={"url": "http://127.0.0.1/secret.ics"})
    assert response.status_code == 400
    assert "public" in response.json()["detail"]


def test_rejects_a_file_that_is_not_ical(client):
    response = client.post(
        "/api/calendar",
        files={"file": ("notes.txt", "just some notes", "text/plain")},
    )
    assert response.status_code == 400


def test_manual_entry_and_exam_lock(client):
    created = client.post(
        "/api/items",
        json={
            "title": "CHEM 152 Final Exam",
            "type": "exam",
            "due_or_start": "2026-12-10T10:00",
            "description": "Cumulative",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["source"] == "manual"
    assert body["locked"] is True
    assert body["course"] == "CHEM 152"
    assert body["due_or_start"].startswith("2026-12-10T10:00:00")
    assert body["status"] == "open"

    personal = client.post(
        "/api/items",
        json={
            "title": "Call advisor",
            "course": "Advising",
            "type": "personal",
            "due_or_start": "2026-10-20T15:30",
            "estimated_effort_hours": 0.5,
        },
    )
    assert personal.status_code == 201
    assert personal.json()["locked"] is False
    assert personal.json()["course"] == "Advising"
    assert personal.json()["type"] == "personal"

    unlocked = client.patch(
        f"/api/items/{body['id']}",
        json={"locked": False},
    )
    assert unlocked.json()["locked"] is True

    weeks = client.get("/api/weeks").json()["weeks"]
    assert weeks[0]["week_start"] == "2026-10-19"
    assert weeks[-1]["week_start"] == "2026-12-07"


def test_clear_effort_and_delete(client):
    created = client.post(
        "/api/items",
        json={
            "title": "Reading notes",
            "type": "personal",
            "due_or_start": "2026-10-21T09:00",
            "estimated_effort_hours": 2,
        },
    )
    item_id = created.json()["id"]
    cleared = client.patch(f"/api/items/{item_id}", json={"estimated_effort_hours": None})
    assert cleared.json()["estimated_effort_hours"] is None
    assert client.delete(f"/api/items/{item_id}").status_code == 204
    assert client.get("/api/items").json() == []
    assert client.delete(f"/api/items/{item_id}").status_code == 404


def test_classify_endpoint(client):
    exam = client.get("/api/classify", params={"title": "MATH 207 Midterm Exam"}).json()
    assert exam["type"] == "exam"
    assert exam["locked"] is True
    assert exam["matched"] is True
    homework = client.get("/api/classify", params={"title": "HW3: joins"}).json()
    assert homework["type"] == "assignment"
    assert homework["locked"] is False
    assert homework["matched"] is True
    plain = client.get("/api/classify", params={"title": "grocery run"}).json()
    assert plain == {"type": "event", "locked": False, "matched": False}
    office = client.get("/api/classify", params={"title": "CSE 414 office hours"}).json()
    assert office["type"] == "event"
    assert office["matched"] is True


def test_profile_round_trip(client):
    payload = {
        "waking_hours": {"wake": "07:30", "sleep": "23:00"},
        "daily_capacity_hours": 5.5,
        "preferred_study_windows": [
            {"day": "mon", "start": "19:00", "end": "22:00"}
        ],
        "fixed_commitments": [
            {
                "title": "CSE 414 lecture",
                "course": "CSE 414",
                "day": "tue",
                "start": "10:00",
                "end": "11:20",
            }
        ],
    }
    saved = client.put("/api/profile", json=payload)
    assert saved.status_code == 200
    body = saved.json()
    assert body["daily_capacity_hours"] == 5.5
    assert body["fixed_commitments"][0]["id"]
    assert body["fixed_commitments"][0]["title"] == "CSE 414 lecture"
    assert client.get("/api/profile").json() == body

    invalid = client.put(
        "/api/profile",
        json={**payload, "waking_hours": {"wake": "23:00", "sleep": "07:00"}},
    )
    assert invalid.status_code == 422


def test_plan_versions_and_restart(client, tmp_path):
    item = client.post(
        "/api/items",
        json={
            "title": "HW1",
            "type": "assignment",
            "due_or_start": "2026-10-23T18:00",
        },
    ).json()
    block = {
        "item_id": item["id"],
        "start": "2026-10-21T19:00:00-07:00",
        "end": "2026-10-21T21:00:00-07:00",
        "kind": "study",
        "status": "scheduled",
        "reason": "Evening window",
    }
    first = client.post(
        "/api/plans",
        json={"week_start": "2026-10-19", "blocks": [block], "summary": "First pass"},
    )
    assert first.status_code == 200
    plan = first.json()
    assert plan["version"] == 1
    assert plan["previous_version"] is None
    assert plan["change_log"][0]["summary"] == "First pass"
    assert plan["blocks"][0]["item_id"] == item["id"]
    assert plan["blocks"][0]["kind"] == "study"

    missing = client.post(
        "/api/plans",
        json={
            "week_start": "2026-10-19",
            "blocks": [{**block, "item_id": "missing"}],
            "summary": "Bad link",
        },
    )
    assert missing.status_code == 400

    sunday = client.post(
        "/api/plans",
        json={"week_start": "2026-10-18", "blocks": [], "summary": "Wrong day"},
    )
    assert sunday.status_code == 400

    second = client.post(
        "/api/plans",
        json={"week_start": "2026-10-19", "blocks": [], "summary": "Cleared the week"},
    )
    assert second.json()["version"] == 2
    assert second.json()["previous_version"] == 1

    listed = client.get("/api/plans").json()
    assert [plan["version"] for plan in listed] == [1, 2]

    blocked = client.delete(f"/api/items/{item['id']}")
    assert blocked.status_code == 400

    state_path = Path(client.app.state.store.path)
    reopened = TestClient(create_app(state_path))
    reloaded = reopened.get("/api/plans").json()
    assert len(reloaded) == 2
    assert reopened.get("/api/items").json()[0]["title"] == "HW1"
    profile = reopened.get("/api/profile").json()
    assert profile["daily_capacity_hours"] == 4


def test_mark_block_done(client):
    item = client.post(
        "/api/items",
        json={
            "title": "HW1",
            "type": "assignment",
            "due_or_start": "2026-10-23T18:00",
        },
    ).json()
    created = client.post(
        "/api/plans",
        json={
            "week_start": "2026-10-19",
            "blocks": [
                {
                    "item_id": item["id"],
                    "start": "2026-10-21T19:00:00-07:00",
                    "end": "2026-10-21T21:00:00-07:00",
                    "kind": "study",
                    "status": "scheduled",
                    "reason": "Evening window",
                }
            ],
            "summary": "First pass",
        },
    )
    assert created.status_code == 200
    block_id = created.json()["blocks"][0]["id"]

    marked = client.post(f"/api/blocks/{block_id}/status", json={"status": "done"})
    assert marked.status_code == 200
    assert marked.json()["status"] == "done"
    assert marked.json()["id"] == block_id

    latest = client.get("/api/plans").json()[-1]
    assert latest["blocks"][0]["status"] == "done"
    assert latest["change_log"][-1]["summary"] == "Marked the study block done"

    again = client.post(f"/api/blocks/{block_id}/status", json={"status": "done"})
    assert again.status_code == 200
    assert again.json()["status"] == "done"

    missing = client.post("/api/blocks/missing-block/status", json={"status": "done"})
    assert missing.status_code == 404

    invalid = client.post(f"/api/blocks/{block_id}/status", json={"status": "open"})
    assert invalid.status_code == 422


def test_voice_source_round_trips_through_the_file(tmp_path):
    from store import Store

    path = tmp_path / "state.json"
    store = Store(path)
    store.add_item(
        Item(
            id="voice-1",
            title="Remember the lab quiz",
            course="CSE 414",
            type="quiz",
            due_or_start="2026-10-28T17:00:00-07:00",
            source="voice",
            estimated_effort_hours=1,
            locked=False,
            status="open",
            description="",
        )
    )
    reloaded = Store(path)
    item = reloaded.items()[0]
    assert item.source == "voice"
    assert item.type == "quiz"
