"""Extraction CLI (also used by scripts/extract_documents.py)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import simplejson

from ..ai_config import ensure_first_run_ai, has_saved_config
from ..candidates import collect_candidates
from ..cli import SUPPORTED_SUFFIXES
from ..io.context import ParseContext, ParseError
from ..io.dispatcher import parse_file
from ..io.ocr_factory import (
    build_hosting,
    build_ocr_client,
    build_url_ocr_client,
    ocr_setup_warning,
)
from ..io.url_fetcher import resolve_input
from .orchestrator import extract_document


def _iter_inputs(input_path: Path):
    if input_path.is_dir():
        for path in sorted(input_path.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield path
        return
    yield input_path


def _load_bills(path: str | None) -> list[dict]:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("bills", []))
    if isinstance(data, list):
        return data
    return []


def _find_existing_bill(bundle, bills: list[dict]) -> dict | None:
    haystack = f"{bundle.meta.get('subject', '')}\n{bundle.raw_text}"
    for bill in bills:
        reference = bill.get("reference_no")
        if reference and reference in haystack:
            return bill
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract document classification, charges and change intent."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="file or directory")
    source.add_argument(
        "--url", help="public http(s) URL; OCR API is attempted first"
    )
    parser.add_argument("--out", default="out/extract", help="output directory")
    parser.add_argument("--ocr-mode", choices=("mock", "local", "api"), default="mock")
    parser.add_argument("--existing-bills", default=None, help="existing_bills.json")
    parser.add_argument("--use-llm", action="store_true", help="use LangChain LLM extraction")
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
    bills = _load_bills(args.existing_bills)

    failures = 0
    for path in _iter_inputs(input_path):
        try:
            bundle = parse_file(path, ctx)
            candidates = collect_candidates(bundle)
            existing_bill = _find_existing_bill(bundle, bills)
            result = extract_document(
                bundle, candidates, existing_bill, use_llm=args.use_llm
            )
        except ParseError as exc:
            failures += 1
            print(f"FAIL  {path}  {exc.code}: {exc.message}")
            continue
        except Exception as exc:  # noqa: BLE001 - keep the batch running
            failures += 1
            print(f"FAIL  {path}  {type(exc).__name__}: {exc}")
            continue

        stem = path.stem.replace(" ", "_")
        out_path = out_dir / f"{stem}.extraction.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            simplejson.dumps(
                result.model_dump(mode="python"),
                use_decimal=True,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

        if not args.quiet:
            classification = result.classification
            print(
                f"OK    {path.name}  "
                f"type={classification.document_type}  "
                f"class={classification.document_class}  "
                f"status={classification.billing_status}  "
                f"charges={len(result.charges)}  "
                f"changes={len(result.change_intent)}  "
                f"source={result.source}"
            )
            for warning in result.warnings:
                print(f"      - {warning}")

    if not args.quiet:
        print(f"\nOutput: {out_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    from . import __name__ as _  # pragma: no cover

    sys.exit(main())
