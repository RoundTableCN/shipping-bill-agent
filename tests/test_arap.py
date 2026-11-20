from decimal import Decimal
from pathlib import Path

from shipping_agent.business.ar_ap import ArapEngine, EntityResolver
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.business.repository import ExistingBill
from shipping_agent.candidates import collect_candidates
from shipping_agent.extract.models import (
    DocumentClassification,
    ExtractedCharge,
)
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


def test_entity_alias_matching():
    resolver = EntityResolver()
    assert resolver.matches(
        "IMPORTER BETA", "IMPORTER BETA (SHANGHAI)"
    )
    assert resolver.matches(
        "CARRIER ALPHA LIMITED", "CARRIER ALPHA LIMITED (LAX)"
    )
    assert not resolver.matches("IMPORTER BETA", "CARRIER ALPHA LIMITED")


def test_invoice_is_ap_for_accounting_entity(fixtures_dir: Path, tmp_path: Path):
    result = _process(fixtures_dir / "formal_invoice.pdf", fixtures_dir, tmp_path)
    arap = result.arap[0]

    assert arap.posting_type == "AP"
    assert arap.candidate_posting_type == "AP"
    assert arap.accounting_status == "CONFIRMED"
    assert arap.payment_obligation is True
    assert arap.collection_right is False
    assert arap.charge_direction == "to_us"
    assert arap.confidence >= 0.85


def test_debit_note_without_payer_is_undetermined(
    samples_dir: Path, fixtures_dir: Path, tmp_path: Path
):
    result = _process(
        samples_dir / "sample_debit_note.pdf", fixtures_dir, tmp_path
    )
    arap = result.arap[0]

    assert arap.posting_type is None
    assert arap.candidate_posting_type is None
    assert arap.accounting_status == "PENDING_CONFIRMATION"
    assert arap.confidence == 0.0
    assert arap.charge_direction == "ambiguous"


def test_notice_has_no_posting(fixtures_dir: Path, tmp_path: Path):
    result = _process(fixtures_dir / "sample_prealert.eml", fixtures_dir, tmp_path)
    arap = result.arap[0]

    assert arap.posting_type is None
    assert arap.candidate_posting_type is None
    assert arap.accounting_status == "PENDING_CONFIRMATION"
    assert arap.confidence == 0.0


def test_statement_recipient_fallback_is_candidate_only(
    fixtures_dir: Path, tmp_path: Path
):
    result = _process(fixtures_dir / "statement.docx", fixtures_dir, tmp_path)
    arap = result.arap[0]

    assert arap.posting_type is None
    assert arap.candidate_posting_type == "AP"
    assert arap.accounting_status == "PENDING_CONFIRMATION"
    assert arap.confidence == 0.75
    assert arap.charge_direction == "ambiguous"


def test_explicit_payee_is_ar_confirmed():
    engine = ArapEngine(accounting_entity="IMPORTER BETA (SHANGHAI)")
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        payee="IMPORTER BETA (SHANGHAI)",
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
    )

    result = engine.evaluate(classification, charge)

    assert result.posting_type == "AR"
    assert result.accounting_status == "CONFIRMED"
    assert result.accounting_direction == "by_us"


def test_payer_payee_conflict_is_pending():
    engine = ArapEngine(accounting_entity="IMPORTER BETA (SHANGHAI)")
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        payer="IMPORTER BETA (SHANGHAI)",
        payee="IMPORTER BETA (SHANGHAI)",
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
    )

    result = engine.evaluate(classification, charge)

    assert result.posting_type is None
    assert result.accounting_status == "PENDING_CONFIRMATION"


def test_third_party_bill_is_not_pilot_posting():
    engine = ArapEngine(accounting_entity="IMPORTER BETA (SHANGHAI)")
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        issuer="CARRIER",
        recipient="EXAMPLE FORWARDING INC.",
        payer="EXAMPLE FORWARDING INC.",
        payee="CARRIER",
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Wharfage",
        amount=Decimal("21.90"),
        currency="USD",
    )

    result = engine.evaluate(classification, charge)

    assert result.posting_type is None
    assert result.candidate_posting_type is None
    assert result.accounting_status == "PENDING_CONFIRMATION"


def test_existing_posting_inherited_without_conflict():
    engine = ArapEngine(
        accounting_entity="IMPORTER BETA (SHANGHAI)"
    )
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
    )
    charge = ExtractedCharge(
        candidate_id="c1",
        charge_item="Handling Charge",
        amount=Decimal("65.00"),
        currency="USD",
    )
    existing = ExistingBill(
        bill_id="B1",
        posting_type="AP",
    )

    result = engine.evaluate(classification, charge, existing)

    assert result.posting_type == "AP"
    assert result.candidate_posting_type == "AP"
    assert result.accounting_status == "CONFIRMED"
    assert result.inherited_from_bill is True
    assert result.confidence >= 0.85
