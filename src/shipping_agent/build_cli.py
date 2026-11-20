"""Build final standard JSON from documents (P2 CLI)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import simplejson

from .ai_config import ensure_first_run_ai, has_saved_config
from .business.pipeline import PipelineConfig, process_bundle
from .candidates import collect_candidates
from .cli import SUPPORTED_SUFFIXES
from .io.context import ParseContext, ParseError
from .io.dispatcher import parse_file
from .io.ocr_factory import (
    build_hosting,
    build_ocr_client,
    build_url_ocr_client,
    ocr_setup_warning,
)
from .io.url_fetcher import resolve_input
from .output.serializer import write_output


def _iter_inputs(input_path: Path):
    if input_path.is_dir():
        for path in sorted(input_path.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield path
        return
    yield input_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the final standard JSON records."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="file or directory")
    source.add_argument(
        "--url", help="public http(s) URL; OCR API is attempted first"
    )
    parser.add_argument("--out", default="out/final", help="output directory")
    parser.add_argument("--existing-bills", default=None, help="existing_bills.json")
    parser.add_argument("--accounting-entity", default=None)
    parser.add_argument("--match-mode", choices=("strict", "enhanced"), default="strict")
    parser.add_argument("--output-mode", choices=("full", "strict"), default="full")
    parser.add_argument("--ocr-mode", choices=("mock", "local", "api"), default="mock")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.use_llm and not has_saved_config():
        ai_config = ensure_first_run_ai()
        if ai_config is None or not ai_config.enabled:
            print("WARN  AI API not configured; using rule extraction only.")
            args.use_llm = False

    out_dir = Path(args.out)
    try:
        input_path = resolve_input(args.url or args.input, out_dir / ".run")
    except ParseError as exc:
        print(f"FAIL  {args.url or args.input}  {exc.code}: {exc.message}")
        return 1
    ctx = ParseContext(
        run_dir=out_dir / ".run",
        ocr_mode=args.ocr_mode,
        ocr_client=build_ocr_client(args.ocr_mode),
        hosting=build_hosting(args.ocr_mode),
    )
    if args.url:
        ctx.source_url = args.url.strip()
        ctx.ocr_mode = "api"
        ctx.ocr_client = build_url_ocr_client()
    setup_warning = None if args.url else ocr_setup_warning(args.ocr_mode)
    if setup_warning:
        print(f"WARN  {setup_warning}")
    config = PipelineConfig(
        existing_bills=args.existing_bills,
        accounting_entity=args.accounting_entity,
        match_mode=args.match_mode,
        use_llm=args.use_llm,
    )

    failures = 0
    for path in _iter_inputs(input_path):
        try:
            bundle = parse_file(path, ctx)
            candidates = collect_candidates(bundle)
            result = process_bundle(bundle, candidates, config)
        except ParseError as exc:
            failures += 1
            print(f"FAIL  {path}  {exc.code}: {exc.message}")
            continue
        except Exception as exc:  # noqa: BLE001 - keep the batch running
            failures += 1
            print(f"FAIL  {path}  {type(exc).__name__}: {exc}")
            continue

        stem = path.stem.replace(" ", "_")
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{stem}.json"
        audit_path = out_dir / f"{stem}.audit.json"
        write_output(
            result.records,
            json_path,
            mode=args.output_mode,
            audit_path=audit_path if args.output_mode == "strict" else None,
        )

        pipeline_path = out_dir / f"{stem}.pipeline.json"
        pipeline_path.write_text(
            simplejson.dumps(
                {
                    "classification": result.extraction.classification.model_dump(
                        mode="python"
                    ),
                    "charges": [
                        charge.model_dump(mode="python")
                        for charge in result.extraction.charges
                    ],
                    "change_intent": [
                        change.model_dump(mode="python")
                        for change in result.extraction.change_intent
                    ],
                    "matches": [
                        {
                            "candidate_id": match.candidate_id,
                            "matched": match.matched,
                            "rule": match.rule,
                            "ambiguous": match.ambiguous,
                            "bill_id": match.bill.bill_id if match.bill else None,
                            "line_id": match.line.line_id if match.line else None,
                            "amount_changed": match.amount_changed,
                            "notes": match.notes,
                        }
                        for match in result.matches
                    ],
                    "arap": [arap.model_dump(mode="python") for arap in result.arap],
                    "decisions": [
                        decision.model_dump(mode="python")
                        for decision in result.decisions
                    ],
                    "duplicates": result.duplicates.model_dump(mode="python"),
                },
                use_decimal=True,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

        if not args.quiet:
            counts: dict[str, int] = {}
            for record in result.records:
                counts[record.operation] = counts.get(record.operation, 0) + 1
            print(
                f"OK    {path.name}  type={result.extraction.classification.document_type}  "
                f"status={result.extraction.classification.billing_status}  "
                f"records={len(result.records)}  {counts}"
            )
            for warning in result.duplicates.warnings:
                print(f"      - {warning}")

    if not args.quiet:
        print(f"\nOutput: {out_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
