"""Repo paths. State lives in one JSON file."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(os.environ.get("DESK_STATE_PATH", ROOT / "data" / "state.json"))
SAMPLE_ICS_PATH = ROOT / "data" / "sample-calendar.ics"
