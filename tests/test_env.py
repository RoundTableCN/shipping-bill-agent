"""Project .env loading keeps exported variables authoritative."""

from __future__ import annotations

import os

from shipping_agent.env import load_project_env

KEY = "SHIPPING_AGENT_ENV_TEST"


def test_load_project_env_does_not_override_exported_value(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{KEY}=from_dotenv\n", encoding="utf-8")
    monkeypatch.delenv(KEY, raising=False)
    try:
        assert load_project_env(dotenv) is True
        assert os.environ[KEY] == "from_dotenv"

        monkeypatch.setenv(KEY, "from_export")
        assert load_project_env(dotenv) is True
        assert os.environ[KEY] == "from_export"
    finally:
        os.environ.pop(KEY, None)


def test_load_project_env_missing_file(tmp_path):
    assert load_project_env(tmp_path / "missing.env") is False
