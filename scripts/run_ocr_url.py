"""Run the real OCR client against a public URL, then the downstream Agent.

This performs a real OCR API call; the URL must be reachable by the OCR server.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.business.pipeline import PipelineConfig, process_bundle  # noqa: E402
from shipping_agent.candidates import collect_candidates  # noqa: E402
from shipping_agent.env import load_project_env  # noqa: E402
from shipping_agent.io.detect import detect_media_type_bytes  # noqa: E402
from shipping_agent.io.image_parser import _bundle_from_ocr  # noqa: E402
from shipping_agent.io.ocr_client import HttpOcrClient  # noqa: E402
from shipping_agent.io.text_normalize import file_id_for  # noqa: E402
from shipping_agent.output.serializer import write_output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real OCR URL -> Agent pipeline.")
    parser.add_argument("--url", required=True, help="public PDF/image URL")
    parser.add_argument(
        "--image",
        default=str(ROOT / "data" / "samples" / "sample_carrier_invoice.png"),
        help="local image used for source metadata only",
    )
    parser.add_argument("--out", default=str(ROOT / "out" / "real_ocr"))
    parser.add_argument("--accounting-entity", default="EXAMPLE FORWARDING INC.")
    parser.add_argument("--existing-bills", default=None)
    args = parser.parse_args(argv)
    load_project_env()

    image = Path(args.image)
    data = image.read_bytes()
    file_id = file_id_for(data)
    media_type = detect_media_type_bytes(data, image.name).value

    client = HttpOcrClient(
        os.getenv("OCR_ENDPOINT", "https://gateway.pltplt.com/ai/process"),
        task=os.getenv("OCR_TASK", "orderChange"),
        task_type=os.getenv("OCR_TASK_TYPE", ""),
    )
    ocr_result = client.extract(image, args.url)
    bundle = _bundle_from_ocr(
        file_id=file_id,
        file_name=image.name,
        media_type=media_type,
        result=ocr_result,
    )

    candidates = collect_candidates(bundle)
    result = process_bundle(
        bundle,
        candidates,
        PipelineConfig(
            existing_bills=args.existing_bills,
            accounting_entity=args.accounting_entity,
        ),
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "sample_carrier_invoice.json"
    write_output(result.records, json_path, mode="full")

    print(f"REAL OCR — fileType={ocr_result.file_type}")
    print(f"structured={len(ocr_result.structured)} candidates={len(candidates)}")
    print(f"records={len(result.records)}")
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
