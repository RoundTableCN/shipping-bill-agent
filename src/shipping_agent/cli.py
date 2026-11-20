"""Command line entry point: parse files and emit bundle/candidate JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .candidates import collect_candidates
from .io.context import ParseContext, ParseError
from .io.detect import MediaType, detect_media_type
from .io.dispatcher import parse_file
from .io.ocr_factory import (
    build_hosting,
    build_ocr_client,
    build_url_ocr_client,
    ocr_setup_warning,
)
from .io.url_fetcher import resolve_input

SUPPORTED_SUFFIXES = {
    ".pdf", ".eml", ".xlsx", ".xlsm", ".xls", ".docx", ".doc",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp",
    ".html", ".htm", ".csv", ".tsv", ".txt",
}


def _iter_inputs(input_path: Path):
    if input_path.is_dir():
        for path in sorted(input_path.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield path
    else:
        yield input_path


def _dump_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse shipping documents into bundles and candidates.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="file or directory")
    source.add_argument(
        "--url", help="public http(s) URL; OCR API is attempted first"
    )
    parser.add_argument("--out", default="out/parse", help="output directory")
    parser.add_argument(
        "--ocr-mode",
        choices=("mock", "local", "api"),
        default="mock",
        help="OCR mode; mock works offline",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    run_dir = out_dir / ".run"
    try:
        input_path = resolve_input(args.url or args.input, run_dir)
    except ParseError as exc:
        print(f"FAIL  {args.url or args.input}  {exc.code}: {exc.message}")
        return 1
    ctx = ParseContext(
        run_dir=run_dir,
        ocr_mode=args.ocr_mode,
        ocr_client=build_ocr_client(args.ocr_mode),
        hosting=build_hosting(args.ocr_mode),
    )
    if args.url:
        # A public URL can be fetched by the OCR server directly.  OCR is
        # always attempted first for URL input, independent of --ocr-mode.
        ctx.source_url = args.url.strip()
        ctx.ocr_mode = "api"
        ctx.ocr_client = build_url_ocr_client()
    setup_warning = None if args.url else ocr_setup_warning(args.ocr_mode)
    if setup_warning:
        print(f"WARN  {setup_warning}")

    failures = 0
    for path in _iter_inputs(input_path):
        try:
            media = detect_media_type(path)
            bundle = parse_file(path, ctx)
            candidates = collect_candidates(bundle)
        except ParseError as exc:
            failures += 1
            print(f"FAIL  {path}  {exc.code}: {exc.message}")
            continue
        except Exception as exc:  # noqa: BLE001 - CLI should not abort the batch
            failures += 1
            print(f"FAIL  {path}  {type(exc).__name__}: {exc}")
            continue

        stem = path.stem.replace(" ", "_")
        _dump_json(out_dir / f"{stem}.bundle.json", bundle.model_dump(mode="json"))
        _dump_json(
            out_dir / f"{stem}.candidates.json",
            [candidate.model_dump(mode="python") for candidate in candidates],
        )

        if not args.quiet:
            print(
                f"OK    {path.name}  [{media.value}]  "
                f"tables={len(bundle.tables)}  candidates={len(candidates)}  "
                f"warnings={len(bundle.warnings)}"
            )
            for warning in bundle.warnings:
                print(f"      - {warning.code}: {warning.message}")

    if not args.quiet:
        print(f"\nOutput: {out_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
