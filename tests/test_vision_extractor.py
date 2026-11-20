"""Vision fallback protocol/config tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import shipping_agent.vision_extractor as vision_module
from shipping_agent.ai_config import AIConfig, save_ai_config
from shipping_agent.vision_extractor import VisionConfig, VisionExtractor

ENV_NAMES = (
    "VISION_BASE_URL",
    "VISION_MODEL",
    "VISION_API_KEY",
    "VISION_PROTOCOL",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_API_KEY",
    "LLM_PROVIDER",
)


def _clean_env(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_CONFIG_PATH", str(tmp_path / "ai_config.json"))


def test_saved_openai_compatible_config_enables_fallback(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    save_ai_config(
        AIConfig(
            provider="deepseek",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            source="custom",
        )
    )

    config = VisionConfig.from_env()

    assert config.enabled is True
    assert config.protocol == "openai"
    assert config.endpoint() == "https://api.deepseek.com/v1/chat/completions"


def test_saved_anthropic_config_uses_anthropic_protocol(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    save_ai_config(
        AIConfig(
            provider="anthropic",
            model="vision-test",
            base_url="https://api.example.com/anthropic",
            api_key="test-key",
            source="custom",
        )
    )

    config = VisionConfig.from_env()

    assert config.enabled is True
    assert config.protocol == "anthropic"
    assert config.endpoint() == "https://api.example.com/anthropic/v1/messages"


def test_explicit_protocol_wins_over_endpoint_guess(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("VISION_BASE_URL", "https://api.example.com/custom")
    monkeypatch.setenv("VISION_MODEL", "vision-test")
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.setenv("VISION_PROTOCOL", "openai")

    config = VisionConfig.from_env()

    assert config.protocol == "openai"
    assert config.endpoint() == "https://api.example.com/custom/chat/completions"


class FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"document_type":"Invoice",'
                            '"reference_no":"INV-DEMO-001",'
                            '"currency":"USD",'
                            '"charges":[{"name":"WHARFAGE","amount":21.9,'
                            '"currency":"USD"}],"total":26.9}'
                        )
                    }
                }
            ]
        }


def test_openai_vision_request_and_response(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (40, 20), "white").save(image_path)

    captured: dict = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(vision_module.requests, "post", fake_post)
    config = VisionConfig(
        base_url="https://api.example.com/v1",
        model="vision-test",
        api_key="test-key",
        protocol="openai",
    )

    result = VisionExtractor(config).extract(image_path)

    assert result.error is None
    assert result.data.reference_no == "INV-DEMO-001"
    assert str(result.data.total) == "26.9"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    content = captured["json"]["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_anthropic_endpoint_does_not_double_v1(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    config = VisionConfig(
        base_url="https://api.anthropic.com/v1",
        model="claude-test",
        api_key="test-key",
        protocol="anthropic",
    )

    assert config.endpoint() == "https://api.anthropic.com/v1/messages"
