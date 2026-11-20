import json
from pathlib import Path

from shipping_agent.extract.cli import main


def test_extract_cli_pdf(samples_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(samples_dir / "sample_debit_note.pdf"),
            "--out",
            str(out),
            "--quiet",
        ]
    )
    assert code == 0

    data = json.loads((out / "sample_debit_note.extraction.json").read_text(encoding="utf-8"))
    assert data["classification"]["document_type"] == "Debit Note"
    assert data["classification"]["billing_status"] == "confirmed"
    assert len(data["charges"]) == 3


def test_extract_cli_revised_change_intent(fixtures_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(fixtures_dir / "formal_invoice_revised.pdf"),
            "--out",
            str(out),
            "--existing-bills",
            str(fixtures_dir / "existing_bills.json"),
            "--quiet",
        ]
    )
    assert code == 0

    data = json.loads(
        (out / "formal_invoice_revised.extraction.json").read_text(encoding="utf-8")
    )
    assert data["classification"]["document_type"] == "Invoice"
    assert len(data["change_intent"]) == 1
    assert data["change_intent"][0]["old_value"] == "USD 65.00"
    assert data["change_intent"][0]["new_value"] == "USD 80.00"
