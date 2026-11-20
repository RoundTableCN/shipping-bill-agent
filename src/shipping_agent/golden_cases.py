"""Shared golden-sample definitions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXISTING_BILLS = ROOT / "data" / "fixtures" / "existing_bills.json"
GOLDEN_DIR = ROOT / "data" / "golden" / "expected"

GOLDEN_CASES: dict[str, Path] = {
    "sample_prealert": ROOT / "data" / "fixtures" / "sample_prealert.eml",
    "sample_general_notice": ROOT / "data" / "samples" / "sample_general_notice.pdf",
    "sample_debit_note": ROOT / "data" / "samples" / "sample_debit_note.pdf",
    "sample_carrier_invoice": ROOT / "data" / "samples" / "sample_carrier_invoice.png",
    "formal_invoice": ROOT / "data" / "fixtures" / "formal_invoice.pdf",
    "formal_invoice_revised": ROOT / "data" / "fixtures" / "formal_invoice_revised.pdf",
    "formal_invoice_create": ROOT / "data" / "fixtures" / "formal_invoice_create.pdf",
    "statement": ROOT / "data" / "fixtures" / "statement.docx",
    "charges": ROOT / "data" / "fixtures" / "charges.xlsx",
}
