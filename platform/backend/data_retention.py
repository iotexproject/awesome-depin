from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from db import execute, fetch_all, fetch_one, transaction


BASE_DIR = Path(__file__).resolve().parents[1]
JOBS_DIR = Path(os.environ.get("QTAIL_JOBS_DIR", BASE_DIR / "var/jobs")).resolve()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def delete_job_payload(job_id: str) -> dict:
    """Delete one job's payload while returning an immutable deletion receipt.

    The database record, input hash, rights attestation, audit events, Gate
    evidence, and contract snapshot remain available. Only customer-provided
    input and generated delivery files under the guarded job directory are
    removed.
    """

    job_dir = (JOBS_DIR / job_id).resolve()
    if not job_dir.is_relative_to(JOBS_DIR) or job_dir.parent != JOBS_DIR:
        raise RuntimeError("Deletion target is outside the guarded jobs volume")

    files: list[dict] = []
    total_bytes = 0
    if job_dir.exists():
        for candidate in sorted(job_dir.rglob("*"), key=lambda item: item.as_posix()):
            if candidate.is_symlink():
                files.append({"path": candidate.relative_to(job_dir).as_posix(), "type": "symlink", "bytes": 0})
                continue
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(job_dir):
                raise RuntimeError("Deletion manifest encountered a file outside the guarded job directory")
            size = candidate.stat().st_size
            total_bytes += size
            files.append({
                "path": candidate.relative_to(job_dir).as_posix(),
                "type": "file",
                "bytes": size,
                "sha256": _file_sha256(candidate),
            })

    manifest = {
        "schema_version": "2026-07-15-v1",
        "job_id": job_id,
        "payload_present_before_deletion": job_dir.exists(),
        "file_count": sum(1 for item in files if item["type"] == "file"),
        "bytes_deleted": total_bytes,
        "files": files,
        "retained_metadata": [
            "generation_job",
            "input_sha256",
            "data_rights_attestation_sha256",
            "audit_events",
            "procurement_evidence_hashes",
            "contract_snapshot_hash",
        ],
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {**manifest, "manifest_sha256": manifest_sha256}


def complete_deletion_request(request_id: str, *, processor: str, review_note: str) -> dict:
    request_row = fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,))
    if not request_row:
        return {"result": "not_found", "request": None}
    if request_row["status"] == "completed":
        return {"result": "reused", "request": request_row}
    if request_row["status"] == "processing":
        recovered = execute(
            "UPDATE data_deletion_requests SET status='requested',review_note='Recovered stale deletion processor' "
            "WHERE id=%s AND status='processing' AND reviewed_at<UTC_TIMESTAMP()-INTERVAL 15 MINUTE",
            (request_id,),
        )
        if recovered != 1:
            return {"result": "busy", "request": request_row}
        request_row = fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,))
    if request_row["status"] != "requested":
        return {"result": "invalid_state", "request": request_row}

    claimed = execute(
        "UPDATE data_deletion_requests SET status='processing',review_note=%s,reviewed_at=UTC_TIMESTAMP() "
        "WHERE id=%s AND status='requested'",
        (review_note, request_id),
    )
    if claimed != 1:
        current = fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,))
        return {"result": "busy", "request": current}

    try:
        receipt = delete_job_payload(request_row["generation_job_id"])
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE data_deletion_requests SET status='completed',deletion_manifest=%s,deletion_sha256=%s,"
                    "files_deleted=%s,bytes_deleted=%s,review_note=%s,reviewed_at=COALESCE(reviewed_at,UTC_TIMESTAMP()),completed_at=UTC_TIMESTAMP() "
                    "WHERE id=%s AND status='processing'",
                    (
                        json.dumps(receipt, ensure_ascii=False),
                        receipt["manifest_sha256"],
                        receipt["file_count"],
                        receipt["bytes_deleted"],
                        review_note,
                        request_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Deletion request state changed before completion could be recorded")
                cursor.execute(
                    "UPDATE generation_jobs SET input_path=NULL,output_path=NULL WHERE id=%s",
                    (request_row["generation_job_id"],),
                )
                cursor.execute(
                    "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) "
                    "VALUES (%s,'data_deletion.completed','data_deletion_request',%s,%s)",
                    (
                        request_row["user_id"],
                        request_id,
                        json.dumps({
                            "generation_job_id": request_row["generation_job_id"],
                            "processor": processor,
                            "deletion_sha256": receipt["manifest_sha256"],
                            "files_deleted": receipt["file_count"],
                            "bytes_deleted": receipt["bytes_deleted"],
                        }, ensure_ascii=False),
                    ),
                )
    except Exception as error:
        execute(
            "UPDATE data_deletion_requests SET status='requested',review_note=%s WHERE id=%s AND status='processing'",
            (f"Deletion execution failed: {type(error).__name__}: {error}"[:2000], request_id),
        )
        raise

    return {
        "result": "completed",
        "request": fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,)),
        "receipt": receipt,
    }


def enqueue_expired_retention_requests(limit: int = 25) -> int:
    rows = fetch_all(
        "SELECT j.id,j.user_id FROM generation_jobs j "
        "JOIN generation_data_rights r ON r.generation_job_id=j.id "
        "LEFT JOIN data_deletion_requests d ON d.generation_job_id=j.id "
        "WHERE j.status IN ('completed','failed') "
        "AND TIMESTAMPADD(DAY,r.retention_days,r.accepted_at)<=UTC_TIMESTAMP() "
        "AND (d.id IS NULL OR d.status='rejected') ORDER BY r.accepted_at LIMIT %s",
        (int(limit),),
    )
    enqueued = 0
    for row in rows:
        request_id = str(uuid.uuid4())
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM data_deletion_requests WHERE generation_job_id=%s FOR UPDATE", (row["id"],))
                existing = cursor.fetchone()
                if existing and existing["status"] != "rejected":
                    continue
                if existing:
                    cursor.execute(
                        "UPDATE data_deletion_requests SET request_source='retention',reason='Agreed retention period expired',"
                        "status='requested',due_at=UTC_TIMESTAMP(),deletion_manifest=NULL,deletion_sha256=NULL,files_deleted=0,bytes_deleted=0,"
                        "review_note=NULL,requested_at=UTC_TIMESTAMP(),reviewed_at=NULL,completed_at=NULL WHERE id=%s",
                        (existing["id"],),
                    )
                    request_id = existing["id"]
                else:
                    cursor.execute(
                        "INSERT INTO data_deletion_requests (id,generation_job_id,user_id,request_source,reason,due_at) "
                        "VALUES (%s,%s,%s,'retention','Agreed retention period expired',UTC_TIMESTAMP())",
                        (request_id, row["id"], row["user_id"]),
                    )
                cursor.execute(
                    "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) "
                    "VALUES (%s,'data_deletion.retention_enqueued','data_deletion_request',%s,%s)",
                    (row["user_id"], request_id, json.dumps({"generation_job_id": row["id"]})),
                )
                enqueued += 1
    return enqueued


def process_due_deletion_requests(limit: int = 25) -> dict:
    request_rows = fetch_all(
        "SELECT id FROM data_deletion_requests WHERE status='requested' AND due_at<=UTC_TIMESTAMP() "
        "ORDER BY due_at LIMIT %s",
        (int(limit),),
    )
    completed = 0
    failed = 0
    for row in request_rows:
        try:
            result = complete_deletion_request(
                row["id"],
                processor="retention_worker",
                review_note="Automatically completed at the contractual deletion deadline.",
            )
            if result["result"] in {"completed", "reused"}:
                completed += 1
        except Exception:
            failed += 1
    return {"completed": completed, "failed": failed}
