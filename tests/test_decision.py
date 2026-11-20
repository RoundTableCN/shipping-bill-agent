from decimal import Decimal
from pathlib import Path

from shipping_agent.business.ar_ap import ArapResult
from shipping_agent.business.decision import DecisionConfig, decide
from shipping_agent.business.matcher import MatchResult
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import collect_candidates
from shipping_agent.extract.models import DocumentClassification, ExtractedCharge
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def _process(path: Path, fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    return process_bundle(
        bundle,
        candidates,
        PipelineConfig(existing_bills=str(fixtures_dir / "existing_bills.json")),
    )


def test_original_invoice_no_change(fixtures_dir: Path, tmp_path: Path):
    result = _process(fixtures_dir / "formal_invoice.pdf", fixtures_dir, tmp_path)
    assert [record.operation for record in result.records] == [
        "NO_CHANGE",
        "NO_CHANGE",
        "NO_CHANGE",
    ]


def test_revised_invoice_updates_only_changed_charge(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_revised.pdf", fixtures_dir, tmp_path
    )
    operations = [record.operation for record in result.records]
    assert operations == ["UPDATE", "NO_CHANGE", "NO_CHANGE"]

    update = result.records[0]
    assert update.charge_details.amount == Decimal("80.00")
    assert update.audit_trail.changes == ["amount"]
    assert "currency" in update.audit_trail.inherited_fields
    assert update.audit_trail.amount_changed is True


def test_create_invoice(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_create.pdf", fixtures_dir, tmp_path
    )
    assert [record.operation for record in result.records] == [
        "CREATE",
        "CREATE",
        "CREATE",
    ]
    assert result.records[0].financial_attributes.posting_type == "AP"


def test_notice_is_pending_review(fixtures_dir: Path, tmp_path: Path):
    result = _process(fixtures_dir / "sample_prealert.eml", fixtures_dir, tmp_path)
    record = result.records[0]
    assert record.operation == "PENDING_REVIEW"
    assert record.audit_trail.decision_status == "REVIEW"
    assert "E_DOC_NOT_BILLING" in record.audit_trail.validation.errors


def test_debit_note_without_arap_is_pending(
    samples_dir: Path, fixtures_dir: Path, tmp_path: Path
):
    result = _process(
        samples_dir / "sample_debit_note.pdf", fixtures_dir, tmp_path
    )
    assert all(record.operation == "PENDING_REVIEW" for record in result.records)
    assert "E_ARAP_UNDETERMINED" in result.records[0].audit_trail.validation.errors


def test_void_is_rejected():
    classification = DocumentClassification(
        document_class="billing",
        billing_status="void",
        confidence=0.9,
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
        confidence=0.9,
    )
    result = decide(
        classification,
        charge,
        MatchResult(candidate_id="c1", matched=False),
        ArapResult(confidence=0.0),
        [],
    )

    assert result.operation == "PENDING_REVIEW"
    assert result.decision_status == "REJECT"
    assert "E_DOC_VOID" in result.validation_errors


def test_low_extraction_confidence_goes_to_review():
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        confidence=0.95,
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
        confidence=0.5,
    )
    result = decide(
        classification,
        charge,
        MatchResult(candidate_id="c1", matched=False),
        ArapResult(posting_type="AP", accounting_status="CONFIRMED", confidence=0.9),
        [],
        DecisionConfig(),
    )

    assert result.operation == "PENDING_REVIEW"
    assert result.decision_status == "REVIEW"
    assert "W_LOW_EXTRACTION_CONFIDENCE" in result.validation_errors


def test_candidate_only_arap_blocks_create():
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        confidence=0.95,
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
        confidence=0.9,
    )
    result = decide(
        classification,
        charge,
        MatchResult(candidate_id="c1", matched=False),
        ArapResult(
            candidate_posting_type="AP",
            accounting_status="PENDING_CONFIRMATION",
            confidence=0.9,
        ),
        [],
    )

    assert result.operation == "PENDING_REVIEW"
    assert "E_ARAP_UNDETERMINED" in result.validation_errors


def test_statement_is_never_postable():
    classification = DocumentClassification(
        document_type="Statement",
        document_class="billing",
        billing_status="confirmed",
        confidence=0.95,
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
        confidence=0.9,
    )
    result = decide(
        classification,
        charge,
        MatchResult(candidate_id="c1", matched=False),
        ArapResult(confidence=0.0),
        [],
    )

    assert result.operation == "PENDING_REVIEW"
    assert "E_DOC_STATEMENT_NOT_POSTABLE" in result.validation_errors


def test_ambiguous_match_goes_to_review():
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        confidence=0.95,
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
        confidence=0.9,
    )
    result = decide(
        classification,
        charge,
        MatchResult(candidate_id="c1", matched=False, ambiguous=True),
        ArapResult(posting_type="AP", accounting_status="CONFIRMED", confidence=0.9),
        [],
    )

    assert result.operation == "PENDING_REVIEW"
    assert "W_MULTIPLE_MATCHES" in result.validation_errors
