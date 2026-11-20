from decimal import Decimal
from pathlib import Path

from shipping_agent.business.matcher import Matcher
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.business.repository import BillRepository, ExistingBill, ExistingCharge
from shipping_agent.candidates import collect_candidates
from shipping_agent.extract.models import DocumentClassification, ExtractedCharge
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def _process(path: Path, fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    config = PipelineConfig(existing_bills=str(fixtures_dir / "existing_bills.json"))
    return process_bundle(bundle, candidates, config)


def _bill() -> ExistingBill:
    return ExistingBill(
        bill_id="B1",
        reference_no="REF-X",
        charges=[
            ExistingCharge(
                line_id="L1",
                charge_item="Handling Charge",
                amount=Decimal("35.00"),
                currency="USD",
            ),
            ExistingCharge(
                line_id="L2",
                charge_item="Handling Charge",
                amount=Decimal("40.00"),
                currency="USD",
            ),
        ],
    )


def test_original_invoice_matches(fixtures_dir: Path, tmp_path: Path):
    result = _process(fixtures_dir / "formal_invoice.pdf", fixtures_dir, tmp_path)

    assert len(result.matches) == 3
    assert all(match.matched for match in result.matches)
    assert all(match.rule == "STRICT_L1" for match in result.matches)
    assert all(match.bill.bill_id == "BILL-FIX-001" for match in result.matches)
    assert not any(match.amount_changed for match in result.matches)


def test_revised_invoice_amount_changed(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_revised.pdf", fixtures_dir, tmp_path
    )

    handling = result.matches[0]
    assert handling.matched
    assert handling.rule == "STRICT_L1"
    assert handling.amount_changed is True
    assert handling.line.amount == Decimal("65.00")
    assert result.extraction.charges[0].amount == Decimal("80.00")


def test_create_invoice_no_match(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_create.pdf", fixtures_dir, tmp_path
    )

    assert all(not match.matched for match in result.matches)
    assert all(not match.ambiguous for match in result.matches)


def test_one_to_one_with_distinct_amounts():
    repo = BillRepository([_bill()])
    matcher = Matcher(repo, mode="strict")
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        reference_no="REF-X",
    )
    charges = [
        ExtractedCharge(
            candidate_id="c1",
            charge_item="Handling Charge",
            amount=Decimal("35.00"),
            currency="USD",
        ),
        ExtractedCharge(
            candidate_id="c2",
            charge_item="Handling Charge",
            amount=Decimal("40.00"),
            currency="USD",
        ),
    ]

    results = matcher.match(classification, charges)

    assert [result.matched for result in results] == [True, True]
    assert results[0].line.line_id == "L1"
    assert results[1].line.line_id == "L2"
    assert results[0].line.line_id != results[1].line.line_id


def test_identical_lines_are_ambiguous():
    repo = BillRepository(
        [
            ExistingBill(
                bill_id="B2",
                reference_no="REF-Y",
                charges=[
                    ExistingCharge(
                        line_id="A",
                        charge_item="Handling Charge",
                        amount=Decimal("35.00"),
                        currency="USD",
                    ),
                    ExistingCharge(
                        line_id="B",
                        charge_item="Handling Charge",
                        amount=Decimal("35.00"),
                        currency="USD",
                    ),
                ],
            )
        ]
    )
    matcher = Matcher(repo, mode="strict")
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        reference_no="REF-Y",
    )
    charges = [
        ExtractedCharge(
            candidate_id="c1",
            charge_item="Handling Charge",
            amount=Decimal("35.00"),
            currency="USD",
        )
    ]

    result = matcher.match(classification, charges)[0]

    assert result.matched is False
    assert result.ambiguous is True
    assert len(result.candidates) == 2


def test_enhanced_mode_matches_renamed_charge():
    repo = BillRepository(
        [
            ExistingBill(
                bill_id="B3",
                reference_no="REF-Z",
                charges=[
                    ExistingCharge(
                        line_id="Z1",
                        charge_item="Handling Charge",
                        amount=Decimal("65.00"),
                        currency="USD",
                    )
                ],
            )
        ]
    )
    matcher = Matcher(repo, mode="enhanced")
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        reference_no="REF-Z",
    )
    charges = [
        ExtractedCharge(
            candidate_id="c1",
            charge_item="Handling Charge Revised",
            amount=Decimal("80.00"),
            currency="USD",
        )
    ]

    result = matcher.match(classification, charges)[0]

    assert result.matched is True
    assert result.rule == "ENHANCED_E1"
    assert result.amount_changed is True
