import json
from pathlib import Path

from shipping_agent.build_cli import main


def test_build_cli_full(fixtures_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(fixtures_dir / "formal_invoice_create.pdf"),
            "--out",
            str(out),
            "--existing-bills",
            str(fixtures_dir / "existing_bills.json"),
            "--output-mode",
            "full",
            "--quiet",
        ]
    )
    assert code == 0

    data = json.loads(
        (out / "formal_invoice_create.json").read_text(encoding="utf-8")
    )
    assert [record["operation"] for record in data] == ["CREATE", "CREATE", "CREATE"]
    assert (out / "formal_invoice_create.pipeline.json").exists()


def test_build_cli_strict(fixtures_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(fixtures_dir / "formal_invoice_revised.pdf"),
            "--out",
            str(out),
            "--existing-bills",
            str(fixtures_dir / "existing_bills.json"),
            "--output-mode",
            "strict",
            "--quiet",
        ]
    )
    assert code == 0

    data = json.loads(
        (out / "formal_invoice_revised.json").read_text(encoding="utf-8")
    )
    assert set(data[0].keys()) == {
        "operation",
        "document_info",
        "transaction_party",
        "charge_details",
        "financial_attributes",
        "audit_trail",
    }
    assert set(data[0]["audit_trail"].keys()) == {"ai_reasoning"}
    assert (out / "formal_invoice_revised.audit.json").exists()


def test_build_cli_directory(fixtures_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(fixtures_dir),
            "--out",
            str(out),
            "--existing-bills",
            str(fixtures_dir / "existing_bills.json"),
            "--quiet",
        ]
    )
    assert code == 0
    assert (out / "formal_invoice.json").exists()
    assert (out / "formal_invoice_create.json").exists()
    assert (out / "formal_invoice_revised.json").exists()
    assert (out / "statement.json").exists()
    assert (out / "charges.json").exists()
