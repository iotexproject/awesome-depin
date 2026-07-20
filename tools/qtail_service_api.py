#!/usr/bin/env python3
"""Local HTTP API for Q-Tail PT-heavy-tail synthetic data service.

Endpoints:
- GET /health
- POST /generate with JSON:
  {
    "csv_text": "task,count,success_rate,difficulty\n...",
    "filename": "customer.csv",
    "synthetic_budget": 100000,
    "top_k": 128
  }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from qtail_data_engine import DEFAULT_PT_SOURCE  # noqa: E402
from qtail_openx_service_model import build_service_package  # noqa: E402


DEFAULT_PORT = 8223
RUNS_DIR = ROOT / "results" / "qtail_service_api_runs"
ACCESS_REQUESTS_DIR = ROOT / "results" / "qtail_api_access_requests"
INCREMENTAL_REPORT = ROOT / "results" / "openx_incremental_training_snapshot" / "openx_demo_training_report.json"
INCREMENTAL_ROWS = ROOT / "results" / "openx_incremental_training_snapshot" / "openx_shard_training_rows.csv"
STRONG_REPORT = ROOT / "results" / "openx_strong_training" / "openx_demo_training_report.json"
STRONG_ROWS = ROOT / "results" / "openx_strong_training" / "openx_shard_training_rows.csv"
STRONG_COMPLETE = ROOT / "results" / "openx_strong_training" / "STRONG_TRAINING_COMPLETE"
FULL_DEMO_REPORT = ROOT / "results" / "openx_demo_training_full_demo" / "openx_demo_training_report.json"
FULL_DEMO_ROWS = ROOT / "results" / "openx_demo_training_full_demo" / "openx_shard_training_rows.csv"


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str, default: str = "customer.csv") -> str:
    value = value or default
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    if not value:
        value = default
    return value if value.endswith(".csv") else f"{value}.csv"


def clean_text(value: object, *, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def validate_access_request(payload: dict) -> dict:
    fields = {
        "company": clean_text(payload.get("company"), limit=160),
        "contact_name": clean_text(payload.get("contact_name"), limit=80),
        "email": clean_text(payload.get("email"), limit=160).lower(),
        "role": clean_text(payload.get("role"), limit=100),
        "use_case": clean_text(payload.get("use_case"), limit=120),
        "data_format": clean_text(payload.get("data_format"), limit=120),
        "monthly_volume": clean_text(payload.get("monthly_volume"), limit=120),
        "pilot_goal": clean_text(payload.get("pilot_goal"), limit=1200),
    }
    missing = [key for key in ("company", "contact_name", "email", "use_case", "pilot_goal") if not fields[key]]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["email"]):
        raise ValueError("email is invalid")
    return fields


def save_access_request(payload: dict) -> dict:
    fields = validate_access_request(payload)
    submitted_at = now_iso()
    fingerprint = hashlib.sha256(
        f"{submitted_at}|{fields['company']}|{fields['email']}".encode("utf-8")
    ).hexdigest()[:10].upper()
    request_id = f"QTA-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{fingerprint}"
    record = {
        "request_id": request_id,
        "status": "received",
        "submitted_at": submitted_at,
        "requested_service": "qtail_pt_heavy_tail_synthetic_data_api",
        "requested_training_source": "strong_openx_snapshot",
        **fields,
    }
    if not payload.get("dry_run"):
        ACCESS_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
        (ACCESS_REQUESTS_DIR / f"{request_id}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {**record, "persisted": not bool(payload.get("dry_run"))}


def choose_training_sources() -> tuple[Path, Path, str]:
    if STRONG_COMPLETE.exists() and STRONG_REPORT.exists() and STRONG_ROWS.exists():
        return STRONG_REPORT, STRONG_ROWS, "strong_openx_snapshot"
    if INCREMENTAL_REPORT.exists() and INCREMENTAL_ROWS.exists():
        return INCREMENTAL_REPORT, INCREMENTAL_ROWS, "incremental_openx_snapshot"
    return FULL_DEMO_REPORT, FULL_DEMO_ROWS, "full_demo_openx_snapshot"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_runs(limit: int = 20) -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    responses = sorted(RUNS_DIR.glob("*/api_response.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for response_path in responses[:limit]:
        payload = load_json(response_path)
        effect = payload.get("effect_summary") or {}
        decision = effect.get("decision") or {}
        rows.append({
            "run_id": payload.get("run_id") or response_path.parent.name,
            "ok": payload.get("ok"),
            "training_source": payload.get("training_source"),
            "output_dir": payload.get("output_dir"),
            "delivery_report": payload.get("delivery_report"),
            "readme": payload.get("readme"),
            "synthetic_plan": payload.get("synthetic_plan"),
            "package_zip": payload.get("package_zip"),
            "winner": decision.get("winner"),
            "passed": decision.get("passed"),
            "tail_success_gain_pp": effect.get("tail_success_gain_pp"),
            "tail_success_relative_gain_pct": effect.get("tail_success_relative_gain_pct"),
            "cvar20_gain_pp": effect.get("cvar20_gain_pp"),
            "tail_data_share_gain_pp": effect.get("tail_data_share_gain_pp"),
            "aligned_with_pt_tail_goal": effect.get("aligned_with_pt_tail_goal"),
            "api_response": str(response_path),
        })
    return rows


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class QTailServiceHandler(BaseHTTPRequestHandler):
    server_version = "QTailServiceAPI/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[%s] %s\n" % (datetime.now().isoformat(timespec="seconds"), fmt % args))

    def do_OPTIONS(self) -> None:
        json_response(self, 200, {"ok": True})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/runs":
            json_response(self, 200, {"ok": True, "runs_dir": str(RUNS_DIR), "runs": list_runs()})
            return
        if path == "/api-docs":
            json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "qtail_pt_tail_synthetic_data_service",
                    "stage": "private_preview",
                    "training_source": "strong_openx_snapshot",
                    "endpoints": {
                        "health": "GET /health",
                        "generate": "POST /generate",
                        "apply": "POST /access-requests",
                        "runs": "GET /runs",
                    },
                    "generate_contract": {
                        "required": ["csv_text"],
                        "optional": ["filename", "synthetic_budget", "top_k"],
                        "outputs": ["synthetic_plan", "model_card", "delivery_report", "package_zip"],
                    },
                    "claim_boundary": [
                        "The API generates PT-heavy-tail allocation and scenario specifications.",
                        "It does not render robot trajectories or prove downstream policy gains without same-policy training.",
                    ],
                },
            )
            return
        if path != "/health":
            json_response(self, 404, {"ok": False, "error": "not_found"})
            return
        report, rows, source = choose_training_sources()
        json_response(
            self,
            200,
            {
                "ok": True,
                "service": "qtail_pt_tail_synthetic_data_service",
                "training_source": source,
                "training_report": str(report),
                "training_rows": str(rows),
                "training_report_exists": report.exists(),
                "training_rows_exists": rows.exists(),
                "runs_dir": str(RUNS_DIR),
                "access_request_endpoint": "/access-requests",
                "api_docs_endpoint": "/api-docs",
            },
        )

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/access-requests":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0:
                    raise ValueError("empty request body")
                if content_length > 64 * 1024:
                    raise ValueError("request body too large; max 64 KiB")
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                record = save_access_request(payload)
                json_response(
                    self,
                    201,
                    {
                        "ok": True,
                        "request_id": record["request_id"],
                        "status": record["status"],
                        "submitted_at": record["submitted_at"],
                        "persisted": record["persisted"],
                        "next_step": "Coherent Technology reviews the pilot scope before issuing production credentials.",
                    },
                )
            except Exception as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if path != "/generate":
            json_response(self, 404, {"ok": False, "error": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                raise ValueError("empty request body")
            if content_length > 20 * 1024 * 1024:
                raise ValueError("request body too large; max 20 MiB")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            csv_text = str(payload.get("csv_text") or "")
            if not csv_text.strip():
                raise ValueError("csv_text is required")
            filename = safe_name(str(payload.get("filename") or "customer.csv"))
            synthetic_budget = float(payload.get("synthetic_budget") or 100_000)
            top_k = int(payload.get("top_k") or 128)

            run_id = f"{now_slug()}_{filename.replace('.csv', '')}"
            out_dir = RUNS_DIR / run_id
            out_dir.mkdir(parents=True, exist_ok=True)
            input_path = out_dir / filename
            input_path.write_text(csv_text, encoding="utf-8")
            training_report, training_rows, training_source = choose_training_sources()
            delivery = build_service_package(
                input_path=input_path,
                out_dir=out_dir,
                training_report_path=training_report,
                training_rows_path=training_rows,
                synthetic_budget=synthetic_budget,
                pt_source=DEFAULT_PT_SOURCE,
                top_k=top_k,
                require_pass=False,
            )
            response = {
                "ok": True,
                "run_id": run_id,
                "training_source": training_source,
                "output_dir": str(out_dir),
                "delivery_report": delivery["delivery_report"],
                "readme": delivery["readme"],
                "model_card": delivery["model_card"],
                "synthetic_plan": delivery["synthetic_plan"],
                "package_zip": delivery["package_zip"],
                "package_manifest": delivery["customer_package"]["manifest"],
                "effect_summary": delivery["effect_summary"],
            }
            (out_dir / "api_response.json").write_text(json.dumps(response, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            subprocess.run(["python3", "tools/qtail_openx_progress_manifest.py"], cwd=ROOT, check=False)
            json_response(self, 200, response)
        except Exception as exc:
            json_response(self, 400, {"ok": False, "error": str(exc)})


def run(port: int) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), QTailServiceHandler)
    print(f"Q-Tail service API listening on http://127.0.0.1:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local Q-Tail synthetic-data service API.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    run(args.port)


if __name__ == "__main__":
    main()
