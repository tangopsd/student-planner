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


def test_typed_reschedule_updates_the_saved_week(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client.post(
        "/api/items",
        json={"title": "HW1", "type": "assignment", "due_or_start": "2026-10-23T18:00"},
    )
    planned = client.post(
        "/api/plan/gemini",
        json={"request": "Plan the week", "week_start": "2026-10-19"},
    )
    assert planned.status_code == 200
    response = client.post(
        "/api/voice",
        json={"text": "move HW1 to Wednesday", "week_start": "2026-10-19"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "move HW1 to Wednesday"
    assert body["valid"] is True, body["errors"]
    assert "Wednesday" in body["reply"]
    assert body["plan"]["blocks"][0]["start"].startswith("2026-10-21")
    assert len(client.get("/api/items").json()) == 1


def test_transcription_uses_the_next_model_when_one_is_busy(monkeypatch):
    from planning import gemini_plan
    from voice_io import transcribe_audio

    gemini_plan._preferred_model = None
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    seen = []

    class Response:
        text = "move saturday's assignment to tuesday"

    def generate(model, contents):
        del contents
        seen.append(model)
        if len(seen) == 1:
            raise RuntimeError(
                "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'high demand'}}"
            )
        return Response()

    text = transcribe_audio(b"abc", "audio/webm", generate=generate)
    assert text == "move saturday's assignment to tuesday"
    assert seen[0] == "gemini-3.6-flash"
    assert seen[1] != seen[0]
    gemini_plan._preferred_model = None


def test_transcription_hides_the_raw_overload_error(monkeypatch):
    from planning import gemini_plan
    from planning.gemini_plan import GeminiError
    from voice_io import transcribe_audio

    gemini_plan._preferred_model = None
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    def generate(model, contents):
        del model, contents
        raise RuntimeError("503 UNAVAILABLE. {'error': {'code': 503, 'message': 'high demand'}}")

    try:
        transcribe_audio(b"abc", "audio/webm", generate=generate)
    except GeminiError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected a transcription error")
    assert "503" not in message
    assert "UNAVAILABLE" not in message
    assert "busy" in message.lower()
    gemini_plan._preferred_model = None


def test_planner_skips_a_busy_model(monkeypatch):
    from planning import gemini_plan
    from planning.gemini_plan import GoogleGeminiModel

    gemini_plan._preferred_model = None
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    seen = []

    class Response:
        text = "ok"
        candidates = []

    class Models:
        def generate_content(self, model, contents, config):
            del contents, config
            seen.append(model)
            if model == "gemini-3.6-flash":
                raise RuntimeError("503 UNAVAILABLE high demand")
            return Response()

    class Client:
        models = Models()

    turn = GoogleGeminiModel(client=Client()).complete([{"role": "user", "text": "Plan the week"}])
    assert turn.text == "ok"
    assert seen[0] == "gemini-3.6-flash"
    assert seen[1] == "gemini-3.5-flash"
    gemini_plan._preferred_model = None


def test_function_calls_keep_the_thought_signature(monkeypatch):
    from planning import gemini_plan
    from planning.gemini_plan import GoogleGeminiModel

    gemini_plan._preferred_model = None
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    captured = {}

    class Response:
        text = "ok"
        candidates = []

    class Models:
        def generate_content(self, model, contents, config):
            del model, config
            captured["contents"] = contents
            return Response()

    class Client:
        models = Models()

    GoogleGeminiModel(client=Client()).complete(
        [
            {"role": "user", "text": "Plan the week"},
            {
                "role": "model",
                "text": "",
                "calls": [
                    {
                        "name": "list_items",
                        "args": {},
                        "thought_signature": b"sig",
                    }
                ],
            },
            {
                "role": "tool",
                "responses": [{"name": "list_items", "response": {"items": []}}],
            },
        ]
    )
    call_part = captured["contents"][1].parts[0]
    assert call_part.function_call.name == "list_items"
    assert call_part.thought_signature == b"sig"
    gemini_plan._preferred_model = None


def test_a_rejected_request_is_not_called_busy(monkeypatch):
    from planning import gemini_plan
    from planning.gemini_plan import GeminiError, GoogleGeminiModel

    gemini_plan._preferred_model = None
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    class Models:
        def generate_content(self, model, contents, config):
            del model, contents, config
            raise RuntimeError("400 INVALID_ARGUMENT. Function call is missing a thought_signature")

    class Client:
        models = Models()

    try:
        GoogleGeminiModel(client=Client()).complete([{"role": "user", "text": "Plan the week"}])
    except GeminiError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected a planner error")
    assert "busy" not in message.lower()
    assert "thought_signature" not in message
    assert "400" not in message
    gemini_plan._preferred_model = None


def test_empty_text_is_rejected(client):
    response = client.post("/api/voice", json={"text": "   "})
    assert response.status_code == 400
