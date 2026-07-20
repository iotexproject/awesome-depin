from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from db import execute, fetch_one, initialize_schema, transaction
from data_retention import enqueue_expired_retention_requests, process_due_deletion_requests
from qtail_adapter import generate_package


BASE_DIR = Path(__file__).resolve().parents[1]
JOBS_DIR = Path(os.environ.get("QTAIL_JOBS_DIR", BASE_DIR / "var/jobs")).resolve()
CATALOG_DIR = Path(os.environ.get("QTAIL_SYNTHETIC_CATALOG_DIR", BASE_DIR / "var/catalog")).resolve()
HEALTH_FILE = Path(os.environ.get("QTAIL_WORKER_HEALTH_FILE", "/tmp/qtail-worker-heartbeat"))
POLL_SECONDS = max(0.1, float(os.environ.get("QTAIL_WORKER_POLL_SECONDS", "1")))
HEARTBEAT_SECONDS = max(1, int(os.environ.get("QTAIL_WORKER_HEARTBEAT_SECONDS", "15")))
LEASE_SECONDS = max(HEARTBEAT_SECONDS * 3, int(os.environ.get("QTAIL_WORKER_LEASE_SECONDS", "120")))
RETRY_BASE_SECONDS = max(1, int(os.environ.get("QTAIL_WORKER_RETRY_BASE_SECONDS", "5")))
TEST_DELAY_SECONDS = max(0.0, float(os.environ.get("QTAIL_WORKER_TEST_DELAY_SECONDS", "0")))
RETENTION_SWEEP_SECONDS = max(5, int(os.environ.get("QTAIL_RETENTION_SWEEP_SECONDS", "60")))
WORKER_ENABLED = os.environ.get("QTAIL_WORKER_ENABLED", "1") == "1"


def touch_health() -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")


def _audit(cursor, actor_user_id: str | None, event_type: str, object_id: str, payload: dict) -> None:
    cursor.execute(
        "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) "
        "VALUES (%s,%s,'generation_job',%s,%s)",
        (actor_user_id, event_type, object_id, json.dumps(payload, ensure_ascii=False, default=str)),
    )


def worker_is_paused(cursor=None) -> bool:
    if cursor is not None:
        cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key='worker_paused'")
        row = cursor.fetchone()
    else:
        row = fetch_one("SELECT setting_value FROM system_settings WHERE setting_key='worker_paused'")
    return bool(row and row["setting_value"] == "1")


def recover_expired_jobs() -> dict[str, int]:
    recovered = 0
    failed = 0
    with transaction() as connection:
        with connection.cursor() as cursor:
            if worker_is_paused(cursor):
                return {"recovered": 0, "failed": 0}
            cursor.execute(
                "SELECT id,user_id,attempt_count,max_attempts,worker_id FROM generation_jobs "
                "WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<UTC_TIMESTAMP() "
                "FOR UPDATE"
            )
            for job in cursor.fetchall():
                if int(job["attempt_count"]) >= int(job["max_attempts"]):
                    cursor.execute(
                        "UPDATE generation_jobs SET status='failed',worker_id=NULL,lease_expires_at=NULL,"
                        "heartbeat_at=NULL,error_message='Worker lease expired after maximum attempts',"
                        "last_error_at=UTC_TIMESTAMP(),completed_at=UTC_TIMESTAMP() WHERE id=%s",
                        (job["id"],),
                    )
                    _audit(cursor, job["user_id"], "generation.failed", job["id"], {"reason": "worker_lease_expired", "worker_id": job.get("worker_id")})
                    failed += 1
                else:
                    cursor.execute(
                        "UPDATE generation_jobs SET status='queued',worker_id=NULL,lease_expires_at=NULL,"
                        "heartbeat_at=NULL,next_attempt_at=UTC_TIMESTAMP(),error_message='Worker lease expired; job requeued',"
                        "last_error_at=UTC_TIMESTAMP() WHERE id=%s",
                        (job["id"],),
                    )
                    _audit(cursor, job["user_id"], "generation.requeued", job["id"], {"reason": "worker_lease_expired", "worker_id": job.get("worker_id")})
                    recovered += 1
    return {"recovered": recovered, "failed": failed}


def claim_job(worker_id: str, job_id: str | None = None) -> dict | None:
    lease_sql = f"DATE_ADD(UTC_TIMESTAMP(), INTERVAL {LEASE_SECONDS} SECOND)"
    with transaction() as connection:
        with connection.cursor() as cursor:
            if worker_is_paused(cursor):
                return None
            if job_id:
                cursor.execute(
                    "SELECT * FROM generation_jobs WHERE id=%s AND status='queued' AND next_attempt_at<=UTC_TIMESTAMP() "
                    "FOR UPDATE SKIP LOCKED",
                    (job_id,),
                )
            else:
                cursor.execute(
                    "SELECT * FROM generation_jobs WHERE status='queued' AND next_attempt_at<=UTC_TIMESTAMP() "
                    "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                )
            job = cursor.fetchone()
            if not job:
                return None
            cursor.execute(
                f"UPDATE generation_jobs SET status='running',attempt_count=attempt_count+1,worker_id=%s,"
                f"started_at=COALESCE(started_at,UTC_TIMESTAMP()),heartbeat_at=UTC_TIMESTAMP(),lease_expires_at={lease_sql},"
                "error_message=NULL WHERE id=%s AND status='queued'",
                (worker_id, job["id"]),
            )
            if cursor.rowcount != 1:
                return None
            job["status"] = "running"
            job["attempt_count"] = int(job["attempt_count"]) + 1
            job["worker_id"] = worker_id
            _audit(cursor, job["user_id"], "generation.started", job["id"], {"worker_id": worker_id, "attempt": job["attempt_count"]})
            return job


def _heartbeat(job_id: str, worker_id: str, stop: threading.Event) -> None:
    lease_sql = f"DATE_ADD(UTC_TIMESTAMP(), INTERVAL {LEASE_SECONDS} SECOND)"
    while not stop.wait(HEARTBEAT_SECONDS):
        updated = execute(
            f"UPDATE generation_jobs SET heartbeat_at=UTC_TIMESTAMP(),lease_expires_at={lease_sql} "
            "WHERE id=%s AND status='running' AND worker_id=%s",
            (job_id, worker_id),
        )
        touch_health()
        if updated != 1:
            stop.set()
            return


def _safe_input_path(job: dict) -> Path:
    candidate = Path(job.get("input_path") or (JOBS_DIR / job["id"] / job["filename"])).resolve()
    if not candidate.is_relative_to(JOBS_DIR) or not candidate.is_file():
        raise RuntimeError("Queued generation input is unavailable or outside the jobs volume")
    return candidate


def _summary(delivery: dict) -> dict:
    keys = ["delivery_report", "readme", "model_card", "synthetic_plan", "package_zip", "package_manifest", "trajectory_manifest", "effect_summary"]
    return {key: delivery.get(key) for key in keys if delivery.get(key) is not None}


def _complete_job(job: dict, worker_id: str, delivery: dict) -> None:
    package_path = Path(delivery["package_zip"]).resolve()
    if not package_path.is_relative_to(JOBS_DIR) or not package_path.is_file():
        raise RuntimeError("Generated package is unavailable or outside the jobs volume")
    output_json = json.dumps(_summary(delivery), ensure_ascii=False, default=str)
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status,worker_id FROM generation_jobs WHERE id=%s FOR UPDATE", (job["id"],))
            current = cursor.fetchone()
            if not current or current["status"] != "running" or current["worker_id"] != worker_id:
                raise RuntimeError("Generation lease was lost before completion")
            cursor.execute(
                "UPDATE generation_jobs SET status='completed',output_json=%s,output_path=%s,error_message=NULL,"
                "worker_id=NULL,lease_expires_at=NULL,heartbeat_at=NULL,completed_at=UTC_TIMESTAMP() WHERE id=%s",
                (output_json, str(package_path), job["id"]),
            )
            _audit(cursor, job["user_id"], "generation.completed", job["id"], {
                "worker_id": worker_id,
                "attempt": job["attempt_count"],
                "input_sha256": job["input_sha256"],
                "delivery_product": job.get("delivery_product") or "allocation_plan",
                "effect_summary": delivery.get("effect_summary"),
            })


def _fail_or_retry(job: dict, worker_id: str, error: Exception) -> str:
    message = f"{type(error).__name__}: {error}"[:2000]
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status,worker_id,attempt_count,max_attempts FROM generation_jobs WHERE id=%s FOR UPDATE", (job["id"],))
            current = cursor.fetchone()
            if not current or current["status"] != "running" or current["worker_id"] != worker_id:
                return "lease_lost"
            attempt = int(current["attempt_count"])
            max_attempts = int(current["max_attempts"])
            if attempt < max_attempts:
                delay = RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1))
                cursor.execute(
                    f"UPDATE generation_jobs SET status='queued',worker_id=NULL,lease_expires_at=NULL,heartbeat_at=NULL,"
                    f"next_attempt_at=DATE_ADD(UTC_TIMESTAMP(), INTERVAL {delay} SECOND),error_message=%s,"
                    "last_error_at=UTC_TIMESTAMP() WHERE id=%s",
                    (message, job["id"]),
                )
                _audit(cursor, job["user_id"], "generation.retry_scheduled", job["id"], {"attempt": attempt, "max_attempts": max_attempts, "delay_seconds": delay, "error": message[:1000]})
                return "queued"
            cursor.execute(
                "UPDATE generation_jobs SET status='failed',worker_id=NULL,lease_expires_at=NULL,heartbeat_at=NULL,"
                "error_message=%s,last_error_at=UTC_TIMESTAMP(),completed_at=UTC_TIMESTAMP() WHERE id=%s",
                (message, job["id"]),
            )
            _audit(cursor, job["user_id"], "generation.failed", job["id"], {"attempt": attempt, "max_attempts": max_attempts, "error": message[:1000]})
            return "failed"


def process_one(worker_id: str, job_id: str | None = None) -> dict | None:
    job = claim_job(worker_id, job_id)
    if not job:
        return None
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat, args=(job["id"], worker_id, heartbeat_stop), daemon=True)
    heartbeat.start()
    try:
        if TEST_DELAY_SECONDS:
            time.sleep(TEST_DELAY_SECONDS)
        input_path = _safe_input_path(job)
        delivery = generate_package(
            input_path,
            JOBS_DIR / job["id"] / "delivery",
            int(job["synthetic_budget"]),
            delivery_product=job.get("delivery_product") or "allocation_plan",
            trajectory_count=job.get("trajectory_count"),
            catalog_dir=CATALOG_DIR,
        )
        _complete_job(job, worker_id, delivery)
        return {"job_id": job["id"], "status": "completed"}
    except Exception as error:
        return {"job_id": job["id"], "status": _fail_or_retry(job, worker_id, error), "error": str(error)}
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)
        touch_health()


def process_retention_cycle(limit: int = 25) -> dict[str, int]:
    if worker_is_paused():
        return {"enqueued": 0, "completed": 0, "failed": 0}
    enqueued = enqueue_expired_retention_requests(limit)
    processed = process_due_deletion_requests(limit)
    return {"enqueued": enqueued, **processed}


def main() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    initialize_schema()
    worker_id = os.environ.get("QTAIL_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    stopping = threading.Event()
    last_retention_sweep = 0.0

    def stop_worker(_signum, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    print(json.dumps({"event": "worker.started", "worker_id": worker_id, "enabled": WORKER_ENABLED}), flush=True)
    while not stopping.is_set():
        touch_health()
        if not WORKER_ENABLED:
            stopping.wait(POLL_SECONDS)
            continue
        try:
            recovered = recover_expired_jobs()
            if recovered["recovered"] or recovered["failed"]:
                print(json.dumps({"event": "worker.recovered", **recovered}), flush=True)
            result = process_one(worker_id)
            if result:
                print(json.dumps({"event": "worker.job", **result}, ensure_ascii=False), flush=True)
            else:
                stopping.wait(POLL_SECONDS)
            now = time.monotonic()
            if now - last_retention_sweep >= RETENTION_SWEEP_SECONDS:
                retention = process_retention_cycle()
                last_retention_sweep = now
                if retention["enqueued"] or retention["completed"] or retention["failed"]:
                    print(json.dumps({"event": "worker.retention", **retention}), flush=True)
        except Exception as error:
            print(json.dumps({"event": "worker.loop_error", "error": f"{type(error).__name__}: {error}"}), file=sys.stderr, flush=True)
            stopping.wait(min(10, POLL_SECONDS * 2))
    print(json.dumps({"event": "worker.stopped", "worker_id": worker_id}), flush=True)


if __name__ == "__main__":
    main()
