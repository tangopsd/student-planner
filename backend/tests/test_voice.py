"""Typed and recorded requests go through the existing planner."""


def test_typed_request_returns_the_transcript_and_keeps_items(client, monkeypatch):
    seen = {}

    def fake(store, request, week_start=None, model=None):
        del store, model
        seen["request"] = request
        seen["week"] = week_start
        return {
            "week_start": week_start,
            "plan": None,
            "valid": True,
            "errors": [],
            "attempts": 1,
            "message": "Scheduled the week.",
        }

    monkeypatch.setattr("main.plan_week", fake)
    created = client.post(
        "/api/items",
        json={"title": "HW1", "type": "assignment", "due_or_start": "2026-10-23T18:00"},
    ).json()
    response = client.post(
        "/api/voice",
        json={"text": "Move HW1 to Tuesday", "week_start": "2026-10-19"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "Move HW1 to Tuesday"
    assert body["reply"] == "Scheduled the week."
    assert body["week_start"] == "2026-10-19"
    assert seen == {"request": "Move HW1 to Tuesday", "week": "2026-10-19"}
    stored = client.get("/api/items").json()
    assert len(stored) == 1
    assert stored[0]["id"] == created["id"]


def test_audio_without_a_key_does_not_plan(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    called = {"n": 0}

    def fake(*args, **kwargs):
        del args, kwargs
        called["n"] += 1
        return {}

    monkeypatch.setattr("main.plan_week", fake)
    response = client.post(
        "/api/voice",
        files={"audio": ("talk.webm", b"not-really-audio", "audio/webm")},
    )
    assert response.status_code == 400
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert called["n"] == 0


def test_audio_sends_the_transcript_to_the_planner(client, monkeypatch):
    monkeypatch.setattr("main.transcribe_audio", lambda data, mime: "Push the quiz to Friday")

    def fake(store, request, week_start=None, model=None):
        del store, week_start, model
        assert request == "Push the quiz to Friday"
        return {
            "week_start": "2026-10-19",
            "plan": None,
            "valid": True,
            "errors": [],
            "attempts": 1,
            "message": "Moved it.",
        }

    monkeypatch.setattr("main.plan_week", fake)
    response = client.post(
        "/api/voice",
        files={"audio": ("talk.webm", b"abc", "audio/webm")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "Push the quiz to Friday"
    assert body["reply"] == "Moved it."


def test_empty_text_is_rejected(client):
    response = client.post("/api/voice", json={"text": "   "})
    assert response.status_code == 400
