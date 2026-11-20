"""Run the downstream agent on a manual OCR-like fixture for the CARRIER image.

This is NOT a real OCR call. It lets us verify the chain after OCR
(chargeList -> candidates -> extraction -> matching -> AR/AP -> JSON) while the
public OCR hosting is unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.business.pipeline import PipelineConfig, process_bundle  # noqa: E402
from shipping_agent.candidates import collect_candidates  # noqa: E402
from shipping_agent.io.context import ParseContext  # noqa: E402
from shipping_agent.io.dispatcher import parse_file  # noqa: E402
from shipping_agent.io.ocr_client import MockOcrClient, OcrResult  # noqa: E402
from shipping_agent.io.text_normalize import sha256_bytes  # noqa: E402
from shipping_agent.output.serializer import write_output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the agent on a manual OCR fixture (not a real OCR call)."
    )
    parser.add_argument(
        "--image",
        default=str(ROOT / "data" / "samples" / "sample_carrier_invoice.png"),
    )
    parser.add_argument(
        "--fixture",
        default=str(ROOT / "data" / "fixtures" / "ocr_mock_CARRIER.json"),
    )
    parser.add_argument("--out", default=str(ROOT / "out" / "manual_ocr"))
    parser.add_argument(
        "--accounting-entity",
        default="EXAMPLE FORWARDING INC.",
    )
    parser.add_argument("--existing-bills", default=None)
    args = parser.parse_args(argv)

    image = Path(args.image)
    fixture = Path(args.fixture)
    out_dir = Path(args.out)

    raw = json.loads(fixture.read_text(encoding="utf-8"))
    ocr_result = OcrResult.from_raw(raw, mode="mock")
    client = MockOcrClient({sha256_bytes(image.read_bytes()): ocr_result})

    ctx = ParseContext(
        run_dir=out_dir / ".run",
        ocr_mode="mock",
        ocr_client=client,
    )
    bundle = parse_file(image, ctx)
    candidates = collect_candidates(bundle)
    result = process_bundle(
        bundle,
        candidates,
        PipelineConfig(
            existing_bills=args.existing_bills,
            accounting_entity=args.accounting_entity,
        ),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "sample_carrier_invoice.json"
    audit_path = out_dir / "sample_carrier_invoice.audit.json"
    write_output(result.records, json_path, mode="full")
    write_output(result.records, audit_path, mode="full")

    print("MANUAL FIXTURE — not a real OCR API call")
    print(f"fixture: {fixture}")
    print(f"image:   {image}")
    print(f"records: {len(result.records)}")
    for record in result.records:
        validation = record.audit_trail.validation
        print(
            f"  {record.operation:14s} "
            f"{record.charge_details.charge_item!r} "
            f"{record.charge_details.amount} {record.charge_details.currency} "
            f"posting={record.financial_attributes.posting_type} "
            f"validation={'PASS' if validation and validation.passed else 'REVIEW'}"
        )
    print(f"\noutput: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
