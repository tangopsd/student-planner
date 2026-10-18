"""Load backend/.env into the process environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PLACEHOLDER = "your_key_here"


def load_project_env(path: Path | None = None) -> None:
    """Read GEMINI_API_KEY from backend/.env. A shell value already set wins.

    The placeholder is ignored so the desk keeps planning locally until a real
    key is saved in that file.
    """
    env_path = path or Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path, override=False)
    if os.environ.get("GEMINI_API_KEY", "").strip() == PLACEHOLDER:
        os.environ.pop("GEMINI_API_KEY", None)
