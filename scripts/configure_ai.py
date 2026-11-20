"""First-run AI API configuration.

Examples:
    python scripts/configure_ai.py --show
    python scripts/configure_ai.py --use-platform
    python scripts/configure_ai.py --provider openai \
      --model gpt-4o-mini --base-url https://api.openai.com/v1 --api-key sk-...
    python scripts/configure_ai.py --clear
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.ai_config import (  # noqa: E402
    AIConfig,
    clear_saved_config,
    config_path,
    detect_platform_config,
    load_saved_config,
    save_ai_config,
)


def _print_config(config: AIConfig | None) -> None:
    if config is None:
        print("AI API: not configured")
        return
    print("AI API:")
    for key, value in config.redacted().items():
        print(f"  {key}: {value}")


def _interactive() -> int:
    platform = detect_platform_config()
    saved = load_saved_config()
    print(f"config file: {config_path()}")
    print("saved:")
    _print_config(saved)
    print("platform default:")
    _print_config(platform)

    if platform is not None:
        choice = input(
            "Use [1] platform API, [2] custom API, [3] no AI (rules), [4] clear? [1]: "
        ).strip() or "1"
    else:
        choice = input(
            "Use [2] custom API, [3] no AI (rules), [4] clear? [3]: "
        ).strip() or "3"

    if choice == "1" and platform is not None:
        print(f"saved: {save_ai_config(platform)}")
        return 0
    if choice == "2":
        provider = input(
            "provider [deepseek/openai/anthropic] (deepseek): "
        ).strip() or "deepseek"
        if provider not in {"deepseek", "openai", "anthropic"}:
            print("provider must be openai or anthropic")
            return 2
        model = input("model: ").strip()
        base_url = input("base URL: ").strip()
        api_key = getpass.getpass("API key: ").strip()
        if not (model and base_url and api_key):
            print("model, base URL and API key are required")
            return 2
        print(
            f"saved: {save_ai_config(AIConfig(provider, model, base_url, api_key, source='custom'))}"
        )
        return 0
    if choice == "3":
        print(
            "saved: "
            f"{save_ai_config(AIConfig(provider='none', source='first_run_none'))}"
        )
        return 0
    if choice == "4":
        print("cleared" if clear_saved_config() else "nothing to clear")
        return 0
    print("invalid choice")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configure the AI API.")
    parser.add_argument("--show", action="store_true", help="show saved/platform config")
    parser.add_argument("--use-platform", action="store_true", help="save the platform API")
    parser.add_argument("--provider", choices=("deepseek", "openai", "anthropic"))
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    parser.add_argument("--no-ai", action="store_true", help="save rules-only mode")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)

    if args.clear:
        print("cleared" if clear_saved_config() else "nothing to clear")
        return 0
    if args.no_ai:
        print(
            "saved: "
            f"{save_ai_config(AIConfig(provider='none', source='first_run_none'))}"
        )
        return 0
    if args.use_platform:
        platform = detect_platform_config()
        if platform is None:
            print("no platform API detected")
            return 1
        print(f"saved: {save_ai_config(platform)}")
        return 0
    if args.provider or args.model or args.base_url or args.api_key:
        if not (args.provider and args.model and args.base_url and args.api_key):
            print("--provider, --model, --base-url and --api-key are all required")
            return 2
        print(
            f"saved: {save_ai_config(AIConfig(args.provider, args.model, args.base_url, args.api_key, source='custom'))}"
        )
        return 0
    if args.show or not sys.stdin.isatty():
        print(f"config file: {config_path()}")
        _print_config(load_saved_config())
        print("platform default:")
        _print_config(detect_platform_config())
        return 0
    return _interactive()


if __name__ == "__main__":
    raise SystemExit(main())
