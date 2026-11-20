from decimal import Decimal
from pathlib import Path

from shipping_agent.candidates import collect_candidates
from shipping_agent.extract.rules import RuleBasedExtractor
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def _extract(path: Path, tmp_path: Path, existing_bill=None):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    return RuleBasedExtractor().extract(bundle, candidates, existing_bill)


def test_debit_note_charges(samples_dir: Path, tmp_path: Path):
    result = _extract(samples_dir / "sample_debit_note.pdf", tmp_path)

    assert result.source == "rules"
    assert result.classification.document_type == "Debit Note"
    assert result.classification.billing_status == "confirmed"
    assert len(result.charges) == 3
    assert [c.charge_item for c in result.charges] == [
        "Handling Charge",
        "4 ADD'L DETENTION FREE TIME CHARGE",
        "Handling Charge",
    ]
    assert result.charges[1].candidate_standard_charge_name == (
        "Detention Free Time Extension Charge"
    )
    assert result.charges[1].mapping_status == "PENDING_CONFIRMATION"
    assert [c.amount for c in result.charges] == [
        Decimal("65.00"),
        Decimal("1310.40"),
        Decimal("35.00"),
    ]
    assert all(c.currency == "USD" for c in result.charges)
    assert all(c.evidence_quote for c in result.charges)
    assert all(0.0 <= c.confidence <= 1.0 for c in result.charges)


def test_prealert_charge_and_warnings(fixtures_dir: Path, tmp_path: Path):
    result = _extract(fixtures_dir / "sample_prealert.eml", tmp_path)

    assert result.classification.document_type == "PRE-ALERT"
    assert len(result.charges) == 1
    charge = result.charges[0]
    assert charge.charge_raw == "H/C"
    assert charge.charge_item == "H/C"
    assert charge.candidate_standard_charge_name == "Handling Charge"
    assert charge.mapping_status == "CANDIDATE"
    assert charge.amount == Decimal("50")
    assert charge.currency == "USD"
    assert charge.payment_term is None
    assert "W_CURRENCY_INFERRED: c001" in result.warnings
    assert "W_DOCUMENT_NOT_CONFIRMED" in " ".join(result.warnings)


def test_general_notice_charge(samples_dir: Path, tmp_path: Path):
    result = _extract(samples_dir / "sample_general_notice.pdf", tmp_path)

    assert result.classification.document_type == "General Notice"
    assert len(result.charges) == 1
    charge = result.charges[0]
    assert charge.charge_item == "On Carriage Additional - US Em"
    assert charge.charge_code_raw == "OCA17"
    assert charge.candidate_standard_charge_name == "On Carriage Additional"
    assert charge.mapping_status == "CANDIDATE"
    assert charge.amount == Decimal("245.0")
    assert charge.currency == "USD"
    assert any("W_DOCUMENT_NOT_CONFIRMED" in w for w in result.warnings)


def test_statement_word_charges(fixtures_dir: Path, tmp_path: Path):
    result = _extract(fixtures_dir / "statement.docx", tmp_path)

    assert result.classification.document_type == "Statement"
    assert result.classification.billing_status == "confirmed"
    assert [c.charge_item for c in result.charges] == [
        "Handling Charge",
        "Documentation Fee",
        "Trucking Charge",
    ]
    assert [c.amount for c in result.charges] == [
        Decimal("65.00"),
        Decimal("35.00"),
        Decimal("120.00"),
    ]


def test_revised_invoice_change_intent(fixtures_dir: Path, tmp_path: Path):
    existing = {
        "reference_no": "INV-FIXTURE-001",
        "charges": [{"charge_item": "Handling Charge", "amount": 65.00}],
    }
    result = _extract(
        fixtures_dir / "formal_invoice_revised.pdf", tmp_path, existing
    )

    assert result.classification.reference_no == "INV-FIXTURE-001"
    assert len(result.change_intent) == 1
    change = result.change_intent[0]
    assert change.field == "amount"
    assert change.charge_item == "HANDLING CHARGE"
    assert change.old_value == "USD 65.00"
    assert change.new_value == "USD 80.00"
    assert "CORRECTION" in (change.evidence_quote or "")
    assert change.confidence >= 0.9


def test_no_change_intent_for_original_invoice(fixtures_dir: Path, tmp_path: Path):
    result = _extract(fixtures_dir / "formal_invoice.pdf", tmp_path)
    assert result.change_intent == []
