"""First-run AI API configuration.

Resolution order:

1. A saved local config (``~/.shipping_agent/ai_config.json`` by default).
2. Explicit generic settings (``LLM_PROVIDER``, ``LLM_BASE_URL``, ...).
3. The API currently exported by the hosting platform:
   ``ANTHROPIC_AUTH_TOKEN`` (Anthropic-compatible) or
   ``OPENAI_API_KEY`` / ``DEEPSEEK_API_KEY`` (OpenAI-compatible).
4. Nothing -> the agent runs with the rule extractor.

Secrets are stored outside the project (override with ``AI_CONFIG_PATH``).
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Provider = Literal["openai", "anthropic", "deepseek", "none"]
DEFAULT_CONFIG_PATH = Path.home() / ".shipping_agent" / "ai_config.json"


def config_path() -> Path:
    override = os.getenv("AI_CONFIG_PATH", "").strip()
    return Path(override) if override else DEFAULT_CONFIG_PATH


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


@dataclass
class AIConfig:
    provider: Provider = "openai"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    source: str = "platform"

    @property
    def enabled(self) -> bool:
        return self.provider != "none" and bool(self.model and self.api_key)

    def redacted(self) -> dict[str, str | bool]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
            "source": self.source,
            "enabled": self.enabled,
        }

    def to_llm_kwargs(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": self.api_key,
        }


def detect_platform_config() -> AIConfig | None:
    """Detect the API currently exported by the runtime/platform."""
    explicit_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit_provider in {"anthropic", "openai", "deepseek"}:
        if explicit_provider == "anthropic":
            key = _first_env("LLM_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
            base = _first_env(
                "LLM_BASE_URL", "ANTHROPIC_BASE_URL", default="https://api.anthropic.com"
            )
            model = _first_env("LLM_MODEL", "ANTHROPIC_MODEL", default="claude-sonnet-5-5")
        elif explicit_provider == "deepseek":
            key = _first_env("LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
            base = _first_env(
                "LLM_BASE_URL", "DEEPSEEK_BASE_URL", "OPENAI_BASE_URL",
                default="https://api.deepseek.com/v1",
            )
            model = _first_env(
                "LLM_MODEL", "DEEPSEEK_MODEL", "OPENAI_MODEL", default="deepseek-chat"
            )
        else:
            key = _first_env("LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
            base = _first_env(
                "LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL",
                default="https://api.deepseek.com/v1",
            )
            model = _first_env("LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL", default="deepseek-chat")
        if key:
            return AIConfig(explicit_provider, model, base, key, source="platform")

    # An explicitly exported OpenAI key wins; a DeepSeek-only key is exposed
    # as its own provider so the UI can show the actual supplier.
    openai_key = _first_env("OPENAI_API_KEY")
    if openai_key:
        return AIConfig(
            provider="openai",
            model=_first_env("LLM_MODEL", "OPENAI_MODEL", default="gpt-4o-mini"),
            base_url=_first_env(
                "OPENAI_BASE_URL",
                default="https://api.openai.com/v1",
            ),
            api_key=openai_key,
            source="platform",
        )

    deepseek_key = _first_env("DEEPSEEK_API_KEY")
    if deepseek_key:
        return AIConfig(
            provider="deepseek",
            model=_first_env("LLM_MODEL", "DEEPSEEK_MODEL", default="deepseek-chat"),
            base_url=_first_env(
                "DEEPSEEK_BASE_URL",
                default="https://api.deepseek.com/v1",
            ),
            api_key=deepseek_key,
            source="platform",
        )

    # The Claude Code platform exposes ANTHROPIC_* (often a proxy token).
    anthropic_key = _first_env("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
    if anthropic_key:
        return AIConfig(
            provider="anthropic",
            model=_first_env("ANTHROPIC_MODEL", "VISION_MODEL", default="claude-sonnet-5-5"),
            base_url=_first_env("ANTHROPIC_BASE_URL", default="https://api.anthropic.com"),
            api_key=anthropic_key,
            source="platform",
        )

    generic_key = _first_env("LLM_API_KEY")
    if generic_key:
        return AIConfig(
            provider="openai",
            model=_first_env("LLM_MODEL", default="deepseek-chat"),
            base_url=_first_env("LLM_BASE_URL", default="https://api.deepseek.com/v1"),
            api_key=generic_key,
            source="custom",
        )
    return None


def load_saved_config(path: str | Path | None = None) -> AIConfig | None:
    target = Path(path) if path else config_path()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    provider = str(data.get("provider", "")).lower()
    if provider not in {"openai", "anthropic", "deepseek", "none"}:
        return None
    config = AIConfig(
        provider=provider,  # type: ignore[arg-type]
        model=str(data.get("model", "")),
        base_url=str(data.get("base_url", "")),
        api_key=str(data.get("api_key", "")),
        source=str(data.get("source", "saved")) or "saved",
    )
    return config


def load_ai_config(path: str | Path | None = None) -> AIConfig | None:
    saved = load_saved_config(path)
    if saved is not None:
        return saved
    return detect_platform_config()


def has_saved_config(path: str | Path | None = None) -> bool:
    """True once the user has answered the first-run question."""
    return load_saved_config(path) is not None


def save_ai_config(config: AIConfig, path: str | Path | None = None) -> Path:
    target = Path(path) if path else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def clear_saved_config(path: str | Path | None = None) -> bool:
    target = Path(path) if path else config_path()
    if target.exists():
        target.unlink()
        return True
    return False


def _ask(prompt: str, default: str = "") -> str | None:
    try:
        value = input(prompt)
    except EOFError:
        return None
    return value.strip() or default


def prompt_first_run() -> AIConfig | None:
    """Interactive first-run question used by CLI entry points."""
    platform = detect_platform_config()
    print(f"config file: {config_path()}")
    if platform is not None:
        print(
            "platform API: "
            f"{platform.provider} / {platform.model} / {platform.base_url}"
        )
        choice = _ask(
            "Use [1] platform API, [2] custom API, [3] no AI (rules)? [1]: ",
            "1",
        )
    else:
        choice = _ask("Use [2] custom API, [3] no AI (rules)? [3]: ", "3")

    if choice is None:
        print("no interactive input; using rule extraction only")
        return None
    if choice == "1" and platform is not None:
        save_ai_config(platform)
        return platform
    if choice == "2":
        provider = _ask("provider [openai/anthropic] (openai): ", "openai")
        if provider is None:
            return None
        if provider not in {"openai", "anthropic"}:
            print("provider must be openai or anthropic")
            return None
        model = _ask("model: ")
        base_url = _ask("base URL: ")
        try:
            api_key = getpass.getpass("API key: ").strip()
        except EOFError:
            return None
        if not (model and base_url and api_key):
            print("model, base URL and API key are required")
            return None
        config = AIConfig(provider, model, base_url, api_key, source="custom")
        save_ai_config(config)
        return config
    if choice == "3":
        config = AIConfig(provider="none", source="first_run_none")
        save_ai_config(config)
        return config
    return None


def ensure_first_run_ai(interactive: bool | None = None) -> AIConfig | None:
    """Return a saved config, or ask once when running in a terminal."""
    saved = load_saved_config()
    if saved is not None:
        return saved
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        return None
    return prompt_first_run()
