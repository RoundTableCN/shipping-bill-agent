from pathlib import Path

import pytest

from shipping_agent.candidates import collect_candidates
from shipping_agent.extract.llm import LLMConfig, LLMNotConfigured, build_chat_model
from shipping_agent.extract.orchestrator import extract_document
from shipping_agent.extract.prompts import (
    change_prompt,
    charge_prompt,
    classification_prompt,
)
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def test_prompts_are_langchain_templates():
    assert "text" in classification_prompt().input_variables
    assert "candidates" in charge_prompt().input_variables
    assert "existing_bill" in change_prompt().input_variables


def test_llm_config_disabled_without_env(monkeypatch, tmp_path):
    for key in (
        "LLM_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "VISION_MODEL",
        "LLM_PROVIDER",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AI_CONFIG_PATH", str(tmp_path / "missing-ai.json"))
    config = LLMConfig.from_env(tmp_path / "missing.env")
    assert config.enabled is False
    with pytest.raises(LLMNotConfigured):
        build_chat_model(config)


def test_llm_config_loads_dotenv(monkeypatch, tmp_path):
    for key in (
        "LLM_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "LLM_STRUCTURED_METHOD",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "VISION_MODEL",
        "LLM_PROVIDER",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AI_CONFIG_PATH", str(tmp_path / "missing-ai.json"))
    env = tmp_path / ".env"
    env.write_text(
        "LLM_MODEL=deepseek-flash\n"
        "OPENAI_API_KEY=sk-test\n"
        "OPENAI_BASE_URL=https://api.deepseek.com\n"
        "LLM_STRUCTURED_METHOD=function_calling\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env(env)

    assert config.model == "deepseek-flash"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://api.deepseek.com"
    assert config.structured_method == "function_calling"
    assert config.enabled is True


def test_build_chat_model_with_fake_key():
    model = build_chat_model(LLMConfig(model="gpt-4o-mini", api_key="test-key"))
    assert model is not None


def test_llm_falls_back_to_rules(fixtures_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "formal_invoice.pdf", ctx)
    candidates = collect_candidates(bundle)

    result = extract_document(
        bundle,
        candidates,
        use_llm=True,
        llm_config=LLMConfig(),  # deliberately not configured
    )

    assert result.source == "rules_fallback"
    assert any(w.startswith("LLM_FALLBACK:") for w in result.warnings)
    assert len(result.charges) == 3
