"""Evaluate the pipeline against the golden set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.evaluation import evaluate, render_markdown  # noqa: E402
from shipping_agent.golden_cases import EXISTING_BILLS, GOLDEN_DIR  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate against golden snapshots.")
    parser.add_argument("--golden", default=str(GOLDEN_DIR))
    parser.add_argument("--existing-bills", default=str(EXISTING_BILLS))
    parser.add_argument("--out", default="out/eval")
    parser.add_argument("--ocr-mode", choices=("mock", "local", "api"), default="mock")
    args = parser.parse_args(argv)

    report = evaluate(
        golden_dir=args.golden,
        existing_bills=args.existing_bills,
        ocr_mode=args.ocr_mode,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")

    print("Field accuracy:")
    for field, data in report["fields"].items():
        print(f"  {field:16s} {data['accuracy']:.2%} ({data['correct']}/{data['total']})")
    print(
        f"Operation accuracy: {report['operation']['accuracy']:.2%} "
        f"({report['operation']['correct']}/{report['operation']['total']})"
    )
    print(
        f"AR/AP accuracy:     {report['arap']['accuracy']:.2%} "
        f"({report['arap']['correct']}/{report['arap']['total']})"
    )
    print(
        f"Hallucination rate: {report['hallucination']['rate']:.2%} "
        f"({report['hallucination']['not_found']}/{report['hallucination']['records_with_evidence']})"
    )
    print(
        f"Review rate:        {report['review']['rate']:.2%} "
        f"({report['review']['pending']}/{report['review']['total']})"
    )
    print(f"\nOutput: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
