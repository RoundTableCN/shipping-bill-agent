"""UI-facing service functions (no Streamlit imports)."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import simplejson

from .business.pipeline import PipelineConfig, PipelineResult, process_bundle
from .candidates import collect_candidates
from .io.context import ParseContext
from .io.dispatcher import parse_file
from .io.ocr_factory import build_hosting, build_ocr_client, build_url_ocr_client
from .io.text_normalize import safe_filename
from .io.url_fetcher import download_url
from .models.bundle import DocumentBundle
from .output.serializer import dumps


@dataclass
class Analysis:
    name: str
    bundle: DocumentBundle
    pipeline: PipelineResult


def analyze_path(
    path: str | Path,
    *,
    existing_bills: str | Path | None = None,
    accounting_entity: str | None = None,
    match_mode: str = "strict",
    ocr_mode: str = "mock",
    use_llm: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_structured_method: str = "function_calling",
    run_dir: str | Path | None = None,
    source_url: str | None = None,
    ocr_client=None,
) -> Analysis:
    path = Path(path)
    run = Path(run_dir) if run_dir else Path(tempfile.mkdtemp(prefix="shipping-ui-"))
    effective_ocr_mode = "api" if source_url else ocr_mode
    ctx = ParseContext(
        run_dir=run,
        ocr_mode=effective_ocr_mode,
        ocr_client=ocr_client or build_ocr_client(effective_ocr_mode),
        hosting=build_hosting(effective_ocr_mode),
        source_url=source_url,
    )
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    result = process_bundle(
        bundle,
        candidates,
        PipelineConfig(
            existing_bills=str(existing_bills) if existing_bills else None,
            accounting_entity=accounting_entity,
            match_mode=match_mode,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_structured_method=llm_structured_method,
        ),
    )
    return Analysis(name=path.name, bundle=bundle, pipeline=result)


def analyze_url(
    url: str,
    *,
    existing_bills: str | Path | None = None,
    accounting_entity: str | None = None,
    match_mode: str = "strict",
    ocr_mode: str = "mock",
    use_llm: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_structured_method: str = "function_calling",
) -> Analysis:
    """Download a public URL and run the normal file pipeline."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="shipping-url-"))
    try:
        path = download_url(url, tmp_dir / "downloads")
        return analyze_path(
            path,
            existing_bills=existing_bills,
            accounting_entity=accounting_entity,
            match_mode=match_mode,
            ocr_mode=ocr_mode,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_structured_method=llm_structured_method,
            run_dir=tmp_dir / "run",
            source_url=url,
            ocr_client=build_url_ocr_client(),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def analyze_bytes(
    data: bytes,
    name: str,
    *,
    existing_bills: str | Path | None = None,
    accounting_entity: str | None = None,
    match_mode: str = "strict",
    ocr_mode: str = "mock",
    use_llm: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_structured_method: str = "function_calling",
) -> Analysis:
    tmp_dir = Path(tempfile.mkdtemp(prefix="shipping-ui-"))
    try:
        path = tmp_dir / safe_filename(name, fallback="upload")
        path.write_bytes(data)
        return analyze_path(
            path,
            existing_bills=existing_bills,
            accounting_entity=accounting_entity,
            match_mode=match_mode,
            ocr_mode=ocr_mode,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_structured_method=llm_structured_method,
            run_dir=tmp_dir / "run",
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def summary_rows(analysis: Analysis) -> list[dict]:
    rows: list[dict] = []
    for record in analysis.pipeline.records:
        validation = record.audit_trail.validation
        rows.append(
            {
                "operation": record.operation,
                "document_type": record.document_info.document_type,
                "reference_no": record.document_info.reference_no,
                "charge_item": record.charge_details.charge_item,
                "amount": (
                    float(record.charge_details.amount)
                    if record.charge_details.amount is not None
                    else None
                ),
                "currency": record.charge_details.currency,
                "payment_term": record.charge_details.payment_term,
                "posting_type": record.financial_attributes.posting_type,
                "decision_status": record.audit_trail.decision_status,
                "validation": "PASS" if validation and validation.passed else "REVIEW",
                "errors": "; ".join(validation.errors) if validation else "",
            }
        )
    return rows


def records_payload(analysis: Analysis, mode: str = "full") -> str:
    return dumps(analysis.pipeline.records, mode=mode) + "\n"


def audit_payload(analysis: Analysis) -> str:
    data = [
        record.audit_trail.model_dump(mode="python")
        for record in analysis.pipeline.records
    ]
    return (
        simplejson.dumps(
            data,
            use_decimal=True,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def classification_payload(analysis: Analysis) -> dict:
    return _jsonable(
        analysis.pipeline.extraction.classification.model_dump(mode="python")
    )


def extraction_payload(analysis: Analysis) -> dict:
    return {
        "classification": classification_payload(analysis),
        "charges": [
            _jsonable(charge.model_dump(mode="python"))
            for charge in analysis.pipeline.extraction.charges
        ],
        "change_intent": [
            _jsonable(change.model_dump(mode="python"))
            for change in analysis.pipeline.extraction.change_intent
        ],
        "validation": _jsonable(
            analysis.pipeline.validation.report.model_dump(mode="python")
        ),
        "totals": _jsonable(
            analysis.pipeline.totals.totals.model_dump(mode="python")
        ),
    }
