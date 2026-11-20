"""Generate golden full-output snapshots for the core samples."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.business.pipeline import PipelineConfig, process_bundle  # noqa: E402
from shipping_agent.candidates import collect_candidates  # noqa: E402
from shipping_agent.io.context import ParseContext  # noqa: E402
from shipping_agent.io.dispatcher import parse_file  # noqa: E402
from shipping_agent.output.serializer import dumps  # noqa: E402

EXISTING_BILLS = ROOT / "data" / "fixtures" / "existing_bills.json"
OUT_DIR = ROOT / "data" / "golden" / "expected"

CASES = (
    ("sample_prealert", ROOT / "data" / "fixtures" / "sample_prealert.eml"),
    ("sample_general_notice", ROOT / "data" / "samples" / "sample_general_notice.pdf"),
    ("sample_debit_note", ROOT / "data" / "samples" / "sample_debit_note.pdf"),
    ("sample_carrier_invoice", ROOT / "data" / "samples" / "sample_carrier_invoice.png"),
    ("formal_invoice", ROOT / "data" / "fixtures" / "formal_invoice.pdf"),
    ("formal_invoice_revised", ROOT / "data" / "fixtures" / "formal_invoice_revised.pdf"),
    ("formal_invoice_create", ROOT / "data" / "fixtures" / "formal_invoice_create.pdf"),
    ("statement", ROOT / "data" / "fixtures" / "statement.docx"),
    ("charges", ROOT / "data" / "fixtures" / "charges.xlsx"),
)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ctx = ParseContext(
        run_dir=OUT_DIR / ".run", ocr_mode="mock", vision_fallback=False
    )
    config = PipelineConfig(existing_bills=str(EXISTING_BILLS))

    for name, path in CASES:
        bundle = parse_file(path, ctx)
        candidates = collect_candidates(bundle)
        result = process_bundle(bundle, candidates, config)
        text = dumps(result.records, mode="full")
        (OUT_DIR / f"{name}.json").write_text(text + "\n", encoding="utf-8")
        operations = [record.operation for record in result.records]
        print(f"wrote {name}.json  records={len(operations)}  operations={operations}")


if __name__ == "__main__":
    main()
