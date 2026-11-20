"""First-run AI API detection, persistence and provider selection."""

from __future__ import annotations

from pathlib import Path

from shipping_agent.ai_config import (
    AIConfig,
    detect_platform_config,
    ensure_first_run_ai,
    load_ai_config,
    prompt_first_run,
    save_ai_config,
)
from shipping_agent.extract.llm import LLMConfig, build_chat_model

ENV_KEYS = (
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "VISION_MODEL",
)


def _clear(monkeypatch, tmp_path: Path) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AI_CONFIG_PATH", str(tmp_path / "ai_config.json"))


def test_detect_platform_anthropic(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-123")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-flash[1M]")

    config = detect_platform_config()

    assert config is not None
    assert config.provider == "anthropic"
    assert config.model == "deepseek-flash[1M]"
    assert config.api_key == "token-123"
    assert config.source == "platform"


def test_explicit_openai_key_wins_over_platform_anthropic(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "platform-token")
    monkeypatch.setenv("OPENAI_API_KEY", "custom-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

    config = detect_platform_config()

    assert config is not None
    assert config.provider == "openai"
    assert config.model == "gpt-4o-mini"
    assert config.api_key == "custom-token"


def test_detect_deepseek_only(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-token")

    config = detect_platform_config()

    assert config is not None
    assert config.provider == "deepseek"
    assert config.model == "deepseek-chat"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_key == "deepseek-token"


def test_detect_explicit_deepseek_provider(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-token")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

    config = detect_platform_config()

    assert config is not None
    assert config.provider == "deepseek"
    assert config.model == "deepseek-reasoner"


def test_build_deepseek_chat_model():
    model = build_chat_model(
        LLMConfig(
            provider="deepseek",
            model="deepseek-chat",
            api_key="test-token",
            base_url="https://api.deepseek.com/v1",
        )
    )
    assert model.__class__.__name__ == "ChatOpenAI"


def test_saved_config_round_trip_and_redaction(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    config = AIConfig(
        provider="openai",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        source="custom",
    )

    path = save_ai_config(config)
    loaded = load_ai_config()

    assert path.exists()
    assert loaded is not None
    assert loaded.provider == "openai"
    assert loaded.api_key == "secret"
    assert loaded.redacted()["api_key_set"] is True
    assert "secret" not in str(loaded.redacted())


def test_llm_config_uses_platform_anthropic(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-123")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-flash[1M]")

    config = LLMConfig.from_env(tmp_path / "missing.env")

    assert config.provider == "anthropic"
    assert config.enabled is True
    assert config.model == "deepseek-flash[1M]"


def test_no_ai_choice_is_persisted_and_blocks_platform_detection(
    monkeypatch, tmp_path
):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "platform-token")
    save_ai_config(AIConfig(provider="none", source="first_run_none"))

    loaded = load_ai_config()
    config = LLMConfig.from_env(tmp_path / "missing.env")

    assert loaded is not None
    assert loaded.provider == "none"
    assert loaded.enabled is False
    assert config.enabled is False


def test_first_run_noninteractive_falls_back_to_rules(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "platform-token")

    assert ensure_first_run_ai(interactive=False) is None


def test_first_run_prompt_can_choose_platform(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "platform-token")
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")

    config = prompt_first_run()

    assert config is not None
    assert config.provider == "anthropic"
    assert load_ai_config().provider == "anthropic"


def test_first_run_prompt_can_choose_rules_only(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "3")

    config = prompt_first_run()

    assert config is not None
    assert config.provider == "none"
    assert load_ai_config().provider == "none"


def test_build_anthropic_chat_model():
    model = build_chat_model(
        LLMConfig(
            provider="anthropic",
            model="deepseek-flash[1M]",
            api_key="test-token",
            base_url="https://api.deepseek.com/anthropic",
        )
    )
    assert model.__class__.__name__ == "ChatAnthropic"
