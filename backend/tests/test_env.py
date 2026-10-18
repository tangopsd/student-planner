"""backend/.env is loaded once at startup and never overrides the shell."""

import os

from env_load import load_project_env


def test_env_file_sets_the_gemini_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    load_project_env(env_file)
    assert os.environ["GEMINI_API_KEY"] == "test-key"


def test_placeholder_key_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=your_key_here\n", encoding="utf-8")
    load_project_env(env_file)
    assert "GEMINI_API_KEY" not in os.environ


def test_shell_key_wins_over_the_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=from-file\n", encoding="utf-8")
    load_project_env(env_file)
    assert os.environ["GEMINI_API_KEY"] == "from-shell"
