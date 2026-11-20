"""Generate JSON Schemas for strict and full output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.validate.schema import full_schema, strict_schema  # noqa: E402


def main() -> None:
    out_dir = ROOT / "schemas"
    out_dir.mkdir(parents=True, exist_ok=True)

    strict_path = out_dir / "output.schema.json"
    full_path = out_dir / "output.full.schema.json"

    strict_path.write_text(
        json.dumps(strict_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    full_path.write_text(
        json.dumps(full_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {strict_path}")
    print(f"wrote {full_path}")


if __name__ == "__main__":
    main()
