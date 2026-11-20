"""Probe the OCR API with a public PDF/image URL and save the raw response.

Usage:
    python scripts/ocr_probe.py --url https://public.example/bill.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "https://gateway.pltplt.com/ai/process"


def probe(
    file_url: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    task: str = "orderChange",
    task_type: str = "",
    timeout: tuple[int, int] = (10, 300),
    out_dir: Path | None = None,
) -> dict:
    payload = {
        "file": file_url,
        "task": task,
        "callBack": "",
        "taskType": task_type,
    }
    started = time.time()
    response = requests.post(endpoint, json=payload, timeout=timeout)
    elapsed = time.time() - started
    response.raise_for_status()

    try:
        raw = response.json()
    except ValueError:
        raw = {"_non_json_body": response.text}

    print(f"status: {response.status_code}")
    print(f"elapsed: {elapsed:.2f}s")
    print(f"content-type: {response.headers.get('content-type')}")
    print(f"payload: {json.dumps(payload, ensure_ascii=False)}")
    if isinstance(raw, dict):
        print(f"top-level keys: {list(raw.keys())}")
        print(json.dumps(raw, ensure_ascii=False, indent=2)[:4000])
        if any(key in raw for key in ("task_id", "taskId", "status")):
            print("\nNOTE: response looks async/task-based; inspect the raw JSON.")
    else:
        print(json.dumps(raw, ensure_ascii=False, indent=2)[:4000])

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = out_dir / f"probe-{stamp}.json"
        path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nsaved: {path}")

    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe the OCR API.")
    parser.add_argument("--url", required=True, help="public PDF/image URL")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--task", default="orderChange")
    parser.add_argument("--task-type", default="")
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument("--read-timeout", type=int, default=300)
    parser.add_argument("--out", default=str(ROOT / "out" / "ocr_probe"))
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)

    probe(
        args.url,
        endpoint=args.endpoint,
        task=args.task,
        task_type=args.task_type,
        timeout=(args.connect_timeout, args.read_timeout),
        out_dir=Path(args.out),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
