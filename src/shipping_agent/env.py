"""Project-local ``.env`` loading.

Environment variables always win over values from ``.env``.  Keeping this in
one place makes OCR, vision and LLM configuration behave the same way when the
project is copied to another machine.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_project_env(dotenv_path: str | Path | None = None) -> bool:
    """Load the project ``.env`` without overriding exported variables."""
    path = Path(dotenv_path) if dotenv_path else ROOT / ".env"
    if not path.exists():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - requirements.txt includes it
        return False
    load_dotenv(path, override=False)
    return True
