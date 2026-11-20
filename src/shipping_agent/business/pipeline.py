"""End-to-end P2 pipeline: extract -> match -> AR/AP -> decide -> output."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from ..extract.llm import LLMConfig
from ..extract.models import ExtractionResult
from ..extract.orchestrator import extract_document
from ..models.base import StrictModel
from ..models.bundle import DocumentBundle
from ..models.candidate import RawChargeLine
from ..models.output import OutputRecord, ValidationReport
from .ar_ap import ArapEngine, ArapResult, EntityResolver
from .assembler import assemble_records
from .decision import DecisionConfig, DecisionResult, decide
from .duplicate import DuplicateReport, dedupe_candidates
from .matcher import MatchResult, Matcher
from .repository import BillRepository
from .totals import TotalsResult, extract_document_totals
from ..validate.rules import (
    ValidationIssue,
    ValidationResult,
    validate_all,
    validate_charge,
    validate_classification,
    validate_totals,
)


def _report(issues: list[ValidationIssue]) -> ValidationReport:
    errors = [
        f"{issue.code}: {issue.message}"
        for issue in issues
        if issue.severity == "error"
    ]
    warnings = [
        f"{issue.code}: {issue.message}"
        for issue in issues
        if issue.severity == "warning"
    ]
    return ValidationReport(
        passed=not errors,
        errors=list(dict.fromkeys(errors)),
        warnings=list(dict.fromkeys(warnings)),
    )


class PipelineConfig(StrictModel):
    existing_bills: str | None = None
    accounting_entity: str | None = None
    match_mode: str = "strict"
    use_llm: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_structured_method: str = "function_calling"
    decision: DecisionConfig = Field(default_factory=DecisionConfig)


class PipelineResult(StrictModel):
    records: list[OutputRecord] = Field(default_factory=list)
    extraction: ExtractionResult
    matches: list[MatchResult] = Field(default_factory=list)
    arap: list[ArapResult] = Field(default_factory=list)
    decisions: list[DecisionResult] = Field(default_factory=list)
    duplicates: DuplicateReport = Field(default_factory=DuplicateReport)
    totals: TotalsResult = Field(default_factory=TotalsResult)
    validation: ValidationResult = Field(default_factory=ValidationResult)


def process_bundle(
    bundle: DocumentBundle,
    candidates: list[RawChargeLine],
    config: PipelineConfig | None = None,
) -> PipelineResult:
    config = config or PipelineConfig()
    duplicates = dedupe_candidates(candidates)
    llm_config = None
    if (
        config.llm_provider
        or config.llm_model
        or config.llm_api_key
        or config.llm_base_url
    ):
        env = LLMConfig.from_env()
        llm_config = LLMConfig(
            provider=config.llm_provider or env.provider,
            model=config.llm_model or env.model,
            api_key=config.llm_api_key or env.api_key,
            base_url=config.llm_base_url or env.base_url,
            structured_method=config.llm_structured_method or env.structured_method,
        )

    extraction = extract_document(
        bundle,
        duplicates.kept,
        use_llm=config.use_llm,
        llm_config=llm_config,
    )
    totals_result = extract_document_totals(bundle)
    validation = validate_all(
        extraction.classification,
        extraction.charges,
        duplicates.kept,
        totals_result.totals,
    )
    if bundle.ocr_mode == "vision":
        # A vision-model fallback is useful for routing, but it is not an
        # OCR-verified source. Force human review instead of auto-posting.
        validation.report.errors.append(
            "E_VISION_FALLBACK_REVIEW: vision fallback requires manual review"
        )
        validation.report.passed = False
        validation.report.warnings.append(
            "W_VISION_FALLBACK: OCR was empty; values came from the vision model"
        )

    history_checked = bool(config.existing_bills)
    if config.existing_bills:
        repository = BillRepository.from_file(config.existing_bills)
    else:
        repository = BillRepository([])

    matcher = Matcher(repository, mode=config.match_mode)
    matches = matcher.match(extraction.classification, extraction.charges)

    resolver = EntityResolver()
    arap_engine = ArapEngine(
        resolver=resolver,
        accounting_entity=config.accounting_entity,
    )
    base_issues = [
        *validate_classification(extraction.classification),
        *validate_totals(extraction.charges, totals_result.totals),
    ]
    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in duplicates.kept
    }
    vision_errors = [
        error
        for error in validation.report.errors
        if error.startswith("E_VISION_FALLBACK_REVIEW")
    ]
    validation_by_id: dict[str, ValidationReport] = {}
    for charge in extraction.charges:
        issues = [
            *base_issues,
            *validate_charge(
                charge, candidate_by_id.get(charge.candidate_id)
            ),
        ]
        report = _report(issues)
        for error in vision_errors:
            if error not in report.errors:
                report.errors.append(error)
        report.passed = not report.errors
        validation_by_id[charge.candidate_id] = report

    arap_results: list[ArapResult] = []
    decisions: list[DecisionResult] = []
    for charge, match in zip(extraction.charges, matches):
        existing_bill = match.bill if match.matched else None
        arap = arap_engine.evaluate(
            extraction.classification, charge, existing_bill
        )
        arap_results.append(arap)
        decisions.append(
            decide(
                extraction.classification,
                charge,
                match,
                arap,
                extraction.change_intent,
                config.decision,
                validation_by_id.get(charge.candidate_id),
                history_checked=history_checked,
            )
        )

    records = assemble_records(
        extraction.classification,
        extraction,
        matches,
        arap_results,
        decisions,
        duplicates.kept,
        ocr_mode=bundle.ocr_mode,
        extra_warnings=[*duplicates.warnings, *totals_result.warnings],
        document_totals=totals_result.totals,
        validation=validation.report,
        validation_by_id=validation_by_id,
        history_checked=history_checked,
    )

    return PipelineResult(
        records=records,
        extraction=extraction,
        matches=matches,
        arap=arap_results,
        decisions=decisions,
        duplicates=duplicates,
        totals=totals_result,
        validation=validation,
    )
