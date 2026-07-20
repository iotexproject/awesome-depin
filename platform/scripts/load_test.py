#!/usr/bin/env python3
"""Concurrent, dependency-free Q-Tail HTTP load probe.

The default scenario exercises only idempotent public/read paths. It is safe to
run after every deploy and intentionally does not create users, orders, jobs, or
procurement evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urljoin


DEFAULT_PATHS = ("/", "/evidence", "/docs", "/pay/alipay.jpg", "/pay/wechat.jpg", "/evidence/gate2-summary.json")


@dataclass
class Result:
    path: str
    status: int
    duration_ms: float
    bytes_read: int
    error: str = ""


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[position]


def request_once(base_url: str, path: str, timeout: float) -> Result:
    started = time.perf_counter()
    request = urllib.request.Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        headers={"User-Agent": "qtail-production-load-probe/1.0", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return Result(path, response.status, (time.perf_counter() - started) * 1000, len(body))
    except urllib.error.HTTPError as error:
        return Result(path, error.code, (time.perf_counter() - started) * 1000, 0, str(error))
    except Exception as error:
        return Result(path, 0, (time.perf_counter() - started) * 1000, 0, f"{type(error).__name__}: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Q-Tail idempotent read-path load probe.")
    parser.add_argument("base_url")
    parser.add_argument("--requests", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float, default=1500.0)
    parser.add_argument("--paths", default=",".join(DEFAULT_PATHS))
    parser.add_argument("--json-out")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        raise SystemExit("requests and concurrency must be positive")
    paths = [value.strip() for value in args.paths.split(",") if value.strip()]
    if not paths:
        raise SystemExit("at least one path is required")

    health_preflight = request_once(args.base_url, "/api/health", args.timeout)
    if health_preflight.status != 200:
        raise SystemExit(f"health preflight failed: HTTP {health_preflight.status} {health_preflight.error}")

    started = time.perf_counter()
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(request_once, args.base_url, paths[index % len(paths)], args.timeout)
            for index in range(args.requests)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.perf_counter() - started
    durations = [result.duration_ms for result in results]
    failures = [result for result in results if result.status != 200]
    error_rate = len(failures) / len(results)
    by_path = {}
    for path in paths:
        subset = [result for result in results if result.path == path]
        subset_durations = [result.duration_ms for result in subset]
        by_path[path] = {
            "requests": len(subset),
            "failures": sum(result.status != 200 for result in subset),
            "p50_ms": percentile(subset_durations, 0.50),
            "p95_ms": percentile(subset_durations, 0.95),
            "max_ms": max(subset_durations, default=0.0),
        }
    report = {
        "status": "passed" if error_rate <= args.max_error_rate and percentile(durations, 0.95) <= args.max_p95_ms else "failed",
        "base_url": args.base_url,
        "scenario": "idempotent_public_and_read_paths",
        "health_preflight": health_preflight.__dict__,
        "requests": len(results),
        "concurrency": args.concurrency,
        "elapsed_seconds": elapsed,
        "requests_per_second": len(results) / elapsed,
        "error_rate": error_rate,
        "latency_ms": {
            "mean": statistics.fmean(durations),
            "p50": percentile(durations, 0.50),
            "p95": percentile(durations, 0.95),
            "p99": percentile(durations, 0.99),
            "max": max(durations),
        },
        "thresholds": {"max_error_rate": args.max_error_rate, "max_p95_ms": args.max_p95_ms},
        "by_path": by_path,
        "failure_samples": [result.__dict__ for result in failures[:20]],
        "boundary": "This probe preflights API/MySQL health once and load-tests cacheable/idempotent web paths. The separate Docker acceptance covers concurrent queue submission and Worker lease recovery; sustained model throughput and payment settlement require workload/merchant-specific tests.",
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.json_out:
        from pathlib import Path
        Path(args.json_out).write_text(output + "\n", encoding="utf-8")
    if report["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
