"""Turn typed text or a recording into the words the planner should hear."""

from __future__ import annotations

import os
from typing import Any, Callable

from planning.gemini_plan import (
    BUSY_MESSAGE,
    GeminiError,
    model_sequence,
    remember_model,
    retryable_model_error,
)


def transcribe_audio(
    data: bytes,
    mime: str,
    generate: Callable[[str, list], Any] | None = None,
) -> str:
    """Transcribe a short recording with Gemini. Text input does not come through here."""
    if not data:
        raise GeminiError("That recording was empty.", 400)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiError(
            "Set GEMINI_API_KEY to transcribe audio. You can still type a request.",
            400,
        )
    from google.genai import types

    contents = [
        types.Part.from_text(
            text="Transcribe the speech. Return only the transcript, with no extra commentary.",
        ),
        types.Part.from_bytes(data=data, mime_type=mime or "audio/webm"),
    ]
    if generate is None:
        from google import genai

        client = genai.Client(api_key=key)

        def generate(model: str, parts: list) -> Any:
            return client.models.generate_content(model=model, contents=parts)

    saw_response = False
    last_error: Exception | None = None
    for name in model_sequence():
        try:
            response = generate(name, contents)
        except GeminiError:
            raise
        except Exception as exc:
            last_error = exc
            if retryable_model_error(exc):
                continue
            raise GeminiError(
                "Gemini could not transcribe that recording. Try again, or type the request.",
                502,
            ) from exc
        saw_response = True
        text = (getattr(response, "text", None) or "").strip()
        if text:
            remember_model(name)
            return text[:4000]
    if saw_response:
        raise GeminiError("I didn't catch any words.", 400)
    raise GeminiError(BUSY_MESSAGE, 503) from last_error
