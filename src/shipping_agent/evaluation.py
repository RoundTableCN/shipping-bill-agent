"""Golden-set evaluation metrics."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .business.pipeline import PipelineConfig, process_bundle
from .candidates import collect_candidates
from .extract.evidence import evidence_in_text
from .golden_cases import EXISTING_BILLS, GOLDEN_CASES, GOLDEN_DIR
from .io.context import ParseContext
from .io.dispatcher import parse_file
from .output.serializer import dumps

FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "document_type": ("document_info", "document_type"),
    "reference_no": ("document_info", "reference_no"),
    "document_date": ("document_info", "document_date"),
    "charge_item": ("charge_details", "charge_item"),
    "amount": ("charge_details", "amount"),
    "currency": ("charge_details", "currency"),
    "payment_term": ("charge_details", "payment_term"),
}


def _get(record: dict, path: tuple[str, ...]) -> Any:
    current: Any = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _equal(field: str, expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if field == "amount":
        return _as_decimal(expected) == _as_decimal(actual)
    return str(expected).strip() == str(actual).strip()


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total, 4) if total else 0.0


def _run_case(
    name: str,
    path: Path,
    *,
    existing_bills: Path,
    ocr_mode: str,
    run_dir: Path,
) -> tuple[list[dict], Any]:
    ctx = ParseContext(
        run_dir=run_dir, ocr_mode=ocr_mode, vision_fallback=False
    )
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    result = process_bundle(
        bundle,
        candidates,
        PipelineConfig(existing_bills=str(existing_bills)),
    )
    records = json.loads(dumps(result.records, mode="full"))
    return records, bundle


def evaluate(
    *,
    golden_dir: str | Path = GOLDEN_DIR,
    existing_bills: str | Path = EXISTING_BILLS,
    cases: dict[str, Path] | None = None,
    ocr_mode: str = "mock",
) -> dict[str, Any]:
    golden_dir = Path(golden_dir)
    existing_bills = Path(existing_bills)
    cases = cases or GOLDEN_CASES

    totals: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    operation_total = operation_correct = 0
    arap_total = arap_correct = 0
    hallucination_total = hallucination_bad = 0
    review_total = review_pending = 0
    per_case: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="shipping-eval-") as tmp:
        tmp_root = Path(tmp)
        for name, path in cases.items():
            expected_path = golden_dir / f"{name}.json"
            if not expected_path.exists():
                raise FileNotFoundError(f"missing golden file: {expected_path}")
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            actual, bundle = _run_case(
                name,
                path,
                existing_bills=existing_bills,
                ocr_mode=ocr_mode,
                run_dir=tmp_root / name,
            )

            case_operations: Counter[str] = Counter()
            for index in range(max(len(expected), len(actual))):
                exp = expected[index] if index < len(expected) else None
                act = actual[index] if index < len(actual) else None
                if exp is None or act is None:
                    for field in FIELD_PATHS:
                        totals[field] += 1
                    operation_total += 1
                    arap_total += 1
                    continue

                for field, path_keys in FIELD_PATHS.items():
                    totals[field] += 1
                    if _equal(field, _get(exp, path_keys), _get(act, path_keys)):
                        correct[field] += 1

                operation_total += 1
                exp_op = exp.get("operation")
                act_op = act.get("operation")
                if exp_op == act_op:
                    operation_correct += 1
                case_operations[act_op] += 1

                arap_total += 1
                exp_posting = _get(exp, ("financial_attributes", "posting_type"))
                act_posting = _get(act, ("financial_attributes", "posting_type"))
                if exp_posting == act_posting:
                    arap_correct += 1

                quote = _get(act, ("audit_trail", "source", "quote"))
                if quote:
                    hallucination_total += 1
                    if not evidence_in_text(quote, bundle):
                        hallucination_bad += 1

                if act_op == "PENDING_REVIEW":
                    review_pending += 1
                review_total += 1

            per_case.append(
                {
                    "name": name,
                    "records": len(actual),
                    "operations": dict(case_operations),
                }
            )

    field_report = {
        field: {
            "correct": correct[field],
            "total": totals[field],
            "accuracy": _accuracy(correct[field], totals[field]),
        }
        for field in FIELD_PATHS
    }

    return {
        "fields": field_report,
        "operation": {
            "correct": operation_correct,
            "total": operation_total,
            "accuracy": _accuracy(operation_correct, operation_total),
        },
        "arap": {
            "correct": arap_correct,
            "total": arap_total,
            "accuracy": _accuracy(arap_correct, arap_total),
        },
        "hallucination": {
            "records_with_evidence": hallucination_total,
            "not_found": hallucination_bad,
            "rate": _accuracy(hallucination_bad, hallucination_total),
        },
        "review": {
            "total": review_total,
            "pending": review_pending,
            "rate": _accuracy(review_pending, review_total),
        },
        "per_case": per_case,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Evaluation Report", ""]
    lines.append("## Field accuracy")
    lines.append("")
    lines.append("| Field | Correct | Total | Accuracy |")
    lines.append("|---|---:|---:|---:|")
    for field, data in report["fields"].items():
        lines.append(
            f"| {field} | {data['correct']} | {data['total']} | {data['accuracy']:.2%} |"
        )

    lines.append("")
    lines.append("## Decision metrics")
    lines.append("")
    lines.append("| Metric | Correct | Total | Accuracy |")
    lines.append("|---|---:|---:|---:|")
    for key, label in (("operation", "operation"), ("arap", "AR/AP")):
        data = report[key]
        lines.append(
            f"| {label} | {data['correct']} | {data['total']} | {data['accuracy']:.2%} |"
        )

    hall = report["hallucination"]
    review = report["review"]
    lines.append("")
    lines.append("## Quality")
    lines.append("")
    lines.append(
        f"- Hallucination rate: {hall['rate']:.2%} "
        f"({hall['not_found']}/{hall['records_with_evidence']})"
    )
    lines.append(
        f"- Review rate: {review['rate']:.2%} "
        f"({review['pending']}/{review['total']})"
    )

    lines.append("")
    lines.append("## Per case")
    lines.append("")
    lines.append("| Case | Records | Operations |")
    lines.append("|---|---:|---|")
    for case in report["per_case"]:
        lines.append(
            f"| {case['name']} | {case['records']} | {case['operations']} |"
        )
    return "\n".join(lines) + "\n"
