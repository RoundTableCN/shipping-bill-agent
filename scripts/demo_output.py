"""Generate strict/full output artifacts for the sample PRE-ALERT record."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.examples import sample_prealert_record  # noqa: E402
from shipping_agent.output.serializer import write_output  # noqa: E402
from shipping_agent.validate.schema import validate_full, validate_strict  # noqa: E402


def main() -> None:
    out_dir = ROOT / "out" / "p0_demo"
    record = sample_prealert_record()

    strict = write_output(
        [record],
        out_dir / "strict.json",
        mode="strict",
        audit_path=out_dir / "audit.json",
    )
    full = write_output([record], out_dir / "full.json", mode="full")

    strict_data = json.loads(strict["output"].read_text(encoding="utf-8"))
    full_data = json.loads(full["output"].read_text(encoding="utf-8"))
    validate_strict(strict_data)
    validate_full(full_data)

    print(f"strict: {strict['output']}")
    print(f"audit : {strict['audit']}")
    print(f"full  : {full['output']}")
    print(f"strict top-level keys: {list(strict_data[0].keys())}")
    print(f"amount type after json.loads: {type(strict_data[0]['charge_details']['amount']).__name__}")


if __name__ == "__main__":
    main()
