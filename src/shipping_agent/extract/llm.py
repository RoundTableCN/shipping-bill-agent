"""LLM configuration and ChatOpenAI factory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..ai_config import load_ai_config

ROOT = Path(__file__).resolve().parents[3]


class LLMNotConfigured(RuntimeError):
    pass


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = ""
    api_key: str = ""
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    structured_method: str = "function_calling"

    @classmethod
    def from_env(cls, dotenv_path: str | Path | None = None) -> "LLMConfig":
        path = Path(dotenv_path) if dotenv_path else ROOT / ".env"
        if path.exists():
            try:
                from dotenv import load_dotenv

                # Environment variables win over .env values.
                load_dotenv(path, override=False)
            except ImportError:
                pass

        platform = load_ai_config()
        if platform is not None:
            provider = platform.provider
            model = platform.model
            api_key = platform.api_key
            base_url = platform.base_url or None
        else:
            provider = "openai"
            model = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "")
            api_key = (
                os.getenv("OPENAI_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY", "")
            )
            base_url = (
                os.getenv("OPENAI_BASE_URL")
                or os.getenv("DEEPSEEK_BASE_URL")
                or None
            )

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            structured_method=os.getenv(
                "LLM_STRUCTURED_METHOD", "function_calling"
            ),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.model and self.api_key)


def build_chat_model(config: LLMConfig):
    if not config.enabled:
        raise LLMNotConfigured(
            "set LLM_MODEL and an API key (or configure the platform API), "
            "or run with the rule-based extractor"
        )

    if config.provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise LLMNotConfigured(
                "install langchain-anthropic to use an Anthropic-compatible API"
            ) from exc
        kwargs = {
            "model_name": config.model,
            "api_key": config.api_key,
            "temperature": config.temperature,
            "max_tokens_to_sample": config.max_tokens,
        }
        # The platform proxy enables thinking by default in some models;
        # thinking and forced tool_choice cannot be combined.  Real Anthropic
        # endpoints keep their default thinking behavior.
        base_lower = (config.base_url or "").lower()
        if "deepseek" in base_lower or os.getenv("LLM_DISABLE_THINKING", "0") == "1":
            kwargs["thinking"] = {"type": "disabled"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        # Proxy endpoints (including the current platform) may accept Bearer
        # auth instead of x-api-key.  Sending both is harmless for Anthropic.
        kwargs["default_headers"] = {
            "Authorization": f"Bearer {config.api_key}",
        }
        return ChatAnthropic(**kwargs)

    from langchain_openai import ChatOpenAI

    kwargs = {
        "model": config.model,
        "api_key": config.api_key,
        "temperature": config.temperature,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return ChatOpenAI(**kwargs)
