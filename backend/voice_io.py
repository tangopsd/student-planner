"""Turn typed text or a recording into the words the planner should hear."""

from __future__ import annotations

import os

from planning.gemini_plan import DEFAULT_MODEL, GeminiError


def transcribe_audio(data: bytes, mime: str) -> str:
    """Transcribe a short recording with Gemini. Text input does not come through here."""
    if not data:
        raise GeminiError("That recording was empty.", 400)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiError(
            "Set GEMINI_API_KEY to transcribe audio. You can still type a request.",
            400,
        )
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_text(
                    text="Transcribe the speech. Return only the transcript, with no extra commentary.",
                ),
                types.Part.from_bytes(data=data, mime_type=mime or "audio/webm"),
            ],
        )
    except GeminiError:
        raise
    except Exception as exc:
        raise GeminiError(f"Gemini could not transcribe that recording: {exc}", 502) from exc
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise GeminiError("I didn't catch any words.", 400)
    return text[:4000]
