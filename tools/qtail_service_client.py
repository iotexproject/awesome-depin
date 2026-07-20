#!/usr/bin/env python3
"""CLI client for the local Q-Tail synthetic-data service API."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "http://127.0.0.1:8223/generate"


def post_json(endpoint: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode("utf-8")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API request failed: HTTP {exc.code}: {text}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"API request failed: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a customer CSV to the local Q-Tail service API.")
    parser.add_argument("--input", required=True, help="Customer CSV path.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Q-Tail API /generate endpoint.")
    parser.add_argument("--synthetic-budget", type=float, default=100_000.0, help="Synthetic data budget.")
    parser.add_argument("--top-k", type=int, default=128, help="Maximum task profiles.")
    parser.add_argument("--out", default="", help="Optional response JSON path.")
    args = parser.parse_args()

    input_path = Path(args.input)
    csv_text = input_path.read_text(encoding="utf-8")
    payload = {
        "filename": input_path.name,
        "csv_text": csv_text,
        "synthetic_budget": args.synthetic_budget,
        "top_k": args.top_k,
    }
    result = post_json(args.endpoint, payload)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    print(text, end="")
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
