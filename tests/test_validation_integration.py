from decimal import Decimal
from pathlib import Path

from shipping_agent.business import pipeline as pipeline_module
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.business.totals import TotalsResult
from shipping_agent.candidates import collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.models.output import DocumentTotals


def _process(path: Path, fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    return process_bundle(
        bundle,
        candidates,
        PipelineConfig(existing_bills=str(fixtures_dir / "existing_bills.json")),
    )


def test_valid_invoice_passes_validation(fixtures_dir: Path, tmp_path: Path):
    result = _process(fixtures_dir / "formal_invoice.pdf", fixtures_dir, tmp_path)

    assert result.validation.report.passed is True
    assert result.validation.report.errors == []
    assert result.totals.totals.total == Decimal("220.00")
    assert all(record.operation == "NO_CHANGE" for record in result.records)
    assert result.records[0].audit_trail.document_totals.total == Decimal("220.00")


def test_sum_mismatch_gates_create_to_pending(
    fixtures_dir: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        pipeline_module,
        "extract_document_totals",
        lambda bundle: TotalsResult(
            totals=DocumentTotals(total=Decimal("999.00")),
            warnings=[],
        ),
    )
    result = _process(
        fixtures_dir / "formal_invoice_create.pdf", fixtures_dir, tmp_path
    )

    assert result.validation.report.passed is False
    assert all(record.operation == "PENDING_REVIEW" for record in result.records)
    errors = result.records[0].audit_trail.validation.errors
    assert any("E_SUM_MISMATCH" in error for error in errors)


def test_excel_multi_currency_warning_flows_to_audit(
    fixtures_dir: Path, tmp_path: Path
):
    result = _process(fixtures_dir / "charges.xlsx", fixtures_dir, tmp_path)

    assert result.totals.totals.total is None
    assert all(record.operation == "PENDING_REVIEW" for record in result.records)
    warnings = result.records[0].audit_trail.validation.warnings
    assert any("W_MULTI_CURRENCY_TOTAL" in warning for warning in warnings)
