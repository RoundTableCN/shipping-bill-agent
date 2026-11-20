"""Compare OCR API, local parsing and a vision LLM against human labels."""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipping_agent.business.charge_mapper import default_mapper  # noqa: E402
from shipping_agent.business.pipeline import PipelineConfig, process_bundle  # noqa: E402
from shipping_agent.candidates import collect_candidates  # noqa: E402
from shipping_agent.io.context import ParseContext  # noqa: E402
from shipping_agent.io.dispatcher import parse_file  # noqa: E402
from shipping_agent.vision_extractor import VisionExtractor  # noqa: E402

MAPPER = default_mapper()

TRUTH = json.loads(
    (ROOT / "data" / "golden" / "human_verified.json").read_text(encoding="utf-8")
)

DOCS = {
    "PDF1": {
        "file": ROOT / "data" / "samples" / "sample_general_notice.pdf",
        "ocr_probe": ROOT / "out" / "ocr_probe" / "probe-20261112-173446.json",
        "ocr_label": "OCR API (text PDF)",
        "local": True,
    },
    "PDF2": {
        "file": ROOT / "data" / "samples" / "sample_debit_note.pdf",
        "ocr_probe": ROOT / "out" / "ocr_probe" / "probe-20261112-170606.json",
        "ocr_label": "OCR API (text PDF)",
        "local": True,
    },
    "PNG": {
        "file": ROOT / "data" / "samples" / "sample_carrier_invoice.png",
        "ocr_probe": ROOT / "out" / "ocr_probe" / "probe-20261112-171224.json",
        "ocr_label": "OCR API (image→PDF)",
        "local": False,
    },
}

TYPE_MAP = {
    "PAI-CARRIER-NOTICE": "Invoice",
    "PAI-COLOADER-NOTICE": "General Notice",
}


def norm_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def norm_amount(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def empty() -> dict:
    return {
        "document_type": None,
        "reference_no": None,
        "document_date": None,
        "currency": None,
        "charges": [],
        "total": None,
        "note": "",
    }


def extract_ocr(probe_path: Path) -> dict:
    if not probe_path.exists():
        item = empty()
        item["note"] = "probe missing"
        return item
    raw = json.loads(probe_path.read_text(encoding="utf-8"))
    items = (raw.get("data") or {}).get("list") or []
    if not items:
        item = empty()
        item["note"] = "data.list=[]"
        return item
    row = items[0]
    charges = [
        {
            "name": charge.get("chargeItem"),
            "amount": norm_amount(charge.get("amount")),
        }
        for charge in (row.get("chargeList") or [])
    ]
    return {
        "document_type": TYPE_MAP.get(row.get("fileType"), row.get("fileType")),
        "reference_no": row.get("invoiceNumber") or None,
        "document_date": None,
        "currency": None,
        "charges": charges,
        "total": None,
        "note": f"raw fileType={row.get('fileType')}",
    }


def extract_local(path: Path, name: str) -> dict:
    ctx = ParseContext(run_dir=ROOT / "out" / "comparison" / ".run" / name, ocr_mode="local")
    bundle = parse_file(path, ctx)
    result = process_bundle(bundle, collect_candidates(bundle), PipelineConfig())
    classification = result.extraction.classification
    charges = [
        {
            "name": charge.charge_item,
            "amount": charge.amount,
            "currency": charge.currency,
        }
        for charge in result.extraction.charges
    ]
    total = result.totals.totals.total
    currency = next((c["currency"] for c in charges if c["currency"]), None)
    return {
        "document_type": classification.document_type,
        "reference_no": classification.reference_no,
        "document_date": classification.document_date,
        "currency": currency,
        "charges": charges,
        "total": total,
        "note": f"ocr_mode={bundle.ocr_mode}",
    }


def extract_vision(extractor: VisionExtractor, path: Path) -> dict:
    result = extractor.extract(path, max_pages=3)
    if result.error:
        item = empty()
        item["note"] = f"vision error: {result.error}"
        return item
    data = result.data
    return {
        "document_type": data.document_type,
        "reference_no": data.reference_no,
        "document_date": data.document_date,
        "currency": data.currency,
        "charges": [
            {"name": charge.name, "amount": charge.amount} for charge in data.charges
        ],
        "total": data.total,
        "note": f"model={result.model}; {result.elapsed:.1f}s",
    }


def standard_names(charges: list[dict]) -> list[str]:
    names: list[str] = []
    for charge in charges:
        raw = charge.get("name")
        if not raw:
            continue
        standard, _ = MAPPER.standardize(str(raw))
        names.append(norm_text(standard or raw))
    return sorted(names)


def compare(truth: dict, source: dict) -> dict:
    expected_amounts = sorted(
        amount
        for amount in (norm_amount(c["amount"]) for c in truth["charges"])
        if amount is not None
    )
    actual_amounts = sorted(
        amount
        for amount in (norm_amount(c["amount"]) for c in source["charges"])
        if amount is not None
    )
    return {
        "document_type": norm_text(truth["document_type"]) == norm_text(source["document_type"]),
        "reference_no": norm_text(truth["reference_no"]) == norm_text(source["reference_no"]),
        "document_date": truth["document_date"] == source["document_date"],
        "currency": truth["currency"] == source["currency"],
        "charge_count": len(truth["charges"]) == len(source["charges"]),
        "charge_names": standard_names(truth["charges"]) == standard_names(source["charges"]),
        "charge_amounts": expected_amounts == actual_amounts,
        "total": norm_amount(truth["total"]) == norm_amount(source["total"]),
    }


def fmt(value, kind: str = "text") -> str:
    if value is None:
        return "null"
    if kind == "amount":
        amount = norm_amount(value)
        return str(amount) if amount is not None else str(value)
    if kind == "charges":
        return "; ".join(
            f"{c.get('name')} {norm_amount(c.get('amount'))}" for c in value
        ) or "—"
    if kind == "names":
        return "; ".join(standard_names(value)) or "—"
    return str(value)


def main() -> int:
    extractor = VisionExtractor()
    print(
        f"vision: base={extractor.config.base_url} model={extractor.config.model} "
        f"enabled={extractor.config.enabled}"
    )
    report: dict[str, dict] = {}
    lines = ["# OCR vs Local Parser vs Vision Model", ""]
    lines.append(
        f"- Vision model: `{extractor.config.model}` via `{extractor.config.base_url}`"
    )
    lines.append("- OCR: 已保存的真实探针响应（lorem/OSS）")
    lines.append("- Local: 项目本地解析 + 规则抽取")
    lines.append("- Truth: `data/golden/human_verified.json`（人工/本地解析对照）")
    lines.append("- 方法与限制: [COMPARISON_METHOD.md](COMPARISON_METHOD.md)")
    lines.append("- 字段口径: 3 个样本 × 8 个字段 = 24；严格字符串比较")
    lines.append("")

    summary = {
        "OCR API": {"matched": 0, "total": 0},
        "Local parser": {"matched": 0, "total": 0},
        "Vision": {"matched": 0, "total": 0},
    }

    for name, spec in DOCS.items():
        path = spec["file"]
        truth = TRUTH[name]
        ocr = extract_ocr(spec["ocr_probe"])
        local = extract_local(path, name) if spec["local"] else empty()
        vision = extract_vision(extractor, path)

        sources = {"OCR API": ocr, "Local parser": local, "Vision": vision}
        report[name] = {
            "truth": truth,
            "sources": {
                key: {
                    "fields": value,
                    "match": compare(truth, value),
                }
                for key, value in sources.items()
            },
        }

        for key, value in sources.items():
            matches = compare(truth, value)
            summary[key]["matched"] += sum(1 for ok in matches.values() if ok)
            summary[key]["total"] += len(matches)

        lines.append(f"## {name}")
        lines.append("")
        lines.append("| Field | Truth | OCR API | Local parser | DeepSeek Vision |")
        lines.append("|---|---|---|---|---|")
        rows = [
            ("document_type", "text"),
            ("reference_no", "text"),
            ("document_date", "text"),
            ("currency", "text"),
            ("charges", "charges"),
            ("charge_names", "names"),
            ("total", "amount"),
        ]
        def field_value(source: dict, field: str):
            # charge_names is derived from charges, not stored as its own key.
            return source.get("charges") if field == "charge_names" else source.get(field)

        for field, kind in rows:
            lines.append(
                "| {field} | {truth} | {ocr} | {local} | {vision} |".format(
                    field=field,
                    truth=fmt(field_value(truth, field), kind),
                    ocr=fmt(field_value(ocr, field), kind),
                    local=fmt(field_value(local, field), kind),
                    vision=fmt(field_value(vision, field), kind),
                )
            )
        lines.append("")
        lines.append(
            "| Match | OCR | Local | Vision |\n|---|---|---|---|\n"
            f"| fields matched | {sum(compare(truth, ocr).values())}/8 | "
            f"{sum(compare(truth, local).values())}/8 | "
            f"{sum(compare(truth, vision).values())}/8 |"
        )
        lines.append("")
        for key, value in sources.items():
            if value.get("note"):
                lines.append(f"- {key}: {value['note']}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Source | Fields matched | Total | Accuracy |")
    lines.append("|---|---:|---:|---:|")
    for key, value in summary.items():
        total = value["total"] or 1
        lines.append(
            f"| {key} | {value['matched']} | {value['total']} | "
            f"{value['matched'] / total:.1%} |"
        )
    lines.append("")

    out_dir = ROOT / "out" / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (ROOT / "docs" / "COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-12:]))
    print(f"\noutput: {out_dir / 'report.json'} and docs/COMPARISON.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
