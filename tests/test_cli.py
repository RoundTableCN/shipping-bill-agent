import json
from pathlib import Path

from shipping_agent.cli import main


def test_cli_single_pdf(fixtures_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(fixtures_dir / "formal_invoice.pdf"),
            "--out",
            str(out),
            "--quiet",
        ]
    )
    assert code == 0

    bundle_path = out / "formal_invoice.bundle.json"
    candidates_path = out / "formal_invoice.candidates.json"
    assert bundle_path.exists() and candidates_path.exists()

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert bundle["media_type"] == "application/pdf"
    assert len(candidates) == 3
    assert candidates[0]["charge_raw"] == "HANDLING CHARGE"


def test_cli_eml(fixtures_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(fixtures_dir / "sample_prealert.eml"),
            "--out",
            str(out),
            "--quiet",
        ]
    )
    assert code == 0

    bundle = json.loads((out / "sample_prealert.bundle.json").read_text(encoding="utf-8"))
    candidates = json.loads(
        (out / "sample_prealert.candidates.json").read_text(encoding="utf-8")
    )
    assert bundle["media_type"] == "message/rfc822"
    assert len(candidates) == 1
    assert candidates[0]["source_kind"] == "email_body"
