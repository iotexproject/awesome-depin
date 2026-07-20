from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def database_config() -> dict:
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "qtail"),
        "password": os.environ.get("MYSQL_PASSWORD", "qtail_dev_password"),
        "database": os.environ.get("MYSQL_DATABASE", "qtail"),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
        "connect_timeout": 5,
        "init_command": "SET time_zone = '+00:00'",
    }


def connect():
    return pymysql.connect(**database_config())


@contextmanager
def transaction():
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def fetch_one(sql: str, params: tuple | list = ()):
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()


def fetch_all(sql: str, params: tuple | list = ()):
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


def execute(sql: str, params: tuple | list = ()) -> int:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount


def _schema_statements() -> list[str]:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    return [statement.strip() for statement in text.split(";") if statement.strip()]


def _apply_compatible_migrations(cursor) -> None:
    """Apply additive/enum migrations needed by existing named Docker volumes."""
    cursor.execute(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='payment_orders' AND COLUMN_NAME='status'"
    )
    row = cursor.fetchone()
    if row and "refunded" not in row["COLUMN_TYPE"]:
        cursor.execute(
            "ALTER TABLE payment_orders MODIFY COLUMN status "
            "ENUM('pending','under_review','paid','rejected','expired','refunded') NOT NULL DEFAULT 'pending'"
        )

    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='payment_orders'"
    )
    payment_columns = {item["COLUMN_NAME"] for item in cursor.fetchall()}
    payment_additive_columns = {
        "merchant_order_no": "VARCHAR(32) NULL AFTER id",
        "payment_mode": "ENUM('manual_qr_verification','official_merchant') NOT NULL DEFAULT 'manual_qr_verification' AFTER channel",
        "provider_transaction_id": "VARCHAR(128) NULL AFTER payment_reference",
        "provider_event_id": "VARCHAR(190) NULL AFTER provider_transaction_id",
        "provider_payload_sha256": "CHAR(64) NULL AFTER provider_event_id",
        "provider_verified_at": "DATETIME NULL AFTER provider_payload_sha256",
        "checkout_url": "TEXT NULL AFTER provider_verified_at",
    }
    for column_name, definition in payment_additive_columns.items():
        if column_name not in payment_columns:
            cursor.execute(f"ALTER TABLE payment_orders ADD COLUMN {column_name} {definition}")
    cursor.execute(
        "UPDATE payment_orders SET merchant_order_no=CONCAT('QT',SUBSTRING(REPLACE(id,'-',''),1,30)) "
        "WHERE merchant_order_no IS NULL OR merchant_order_no=''"
    )
    cursor.execute("ALTER TABLE payment_orders MODIFY COLUMN merchant_order_no VARCHAR(32) NOT NULL")
    cursor.execute(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='payment_orders' AND INDEX_NAME='uq_payment_merchant_order' LIMIT 1"
    )
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE payment_orders ADD UNIQUE INDEX uq_payment_merchant_order (merchant_order_no)")

    cursor.execute(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='refund_requests' AND COLUMN_NAME='status'"
    )
    refund_status = cursor.fetchone()
    if refund_status and ("processing" not in refund_status["COLUMN_TYPE"] or "failed" not in refund_status["COLUMN_TYPE"]):
        cursor.execute(
            "ALTER TABLE refund_requests MODIFY COLUMN status "
            "ENUM('requested','approved','processing','rejected','failed','completed') NOT NULL DEFAULT 'requested'"
        )
    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='refund_requests'"
    )
    refund_columns = {item["COLUMN_NAME"] for item in cursor.fetchall()}
    refund_additive_columns = {
        "merchant_refund_no": "VARCHAR(64) NULL AFTER id",
        "provider_refund_id": "VARCHAR(128) NULL AFTER refund_reference",
        "provider_event_id": "VARCHAR(190) NULL AFTER provider_refund_id",
        "provider_payload_sha256": "CHAR(64) NULL AFTER provider_event_id",
        "provider_verified_at": "DATETIME NULL AFTER provider_payload_sha256",
    }
    for column_name, definition in refund_additive_columns.items():
        if column_name not in refund_columns:
            cursor.execute(f"ALTER TABLE refund_requests ADD COLUMN {column_name} {definition}")
    cursor.execute(
        "UPDATE refund_requests SET merchant_refund_no=CONCAT('RF',SUBSTRING(REPLACE(id,'-',''),1,30)) "
        "WHERE merchant_refund_no IS NULL OR merchant_refund_no=''"
    )
    cursor.execute("ALTER TABLE refund_requests MODIFY COLUMN merchant_refund_no VARCHAR(64) NOT NULL")
    cursor.execute(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='refund_requests' AND INDEX_NAME='uq_refund_merchant_order' LIMIT 1"
    )
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE refund_requests ADD UNIQUE INDEX uq_refund_merchant_order (merchant_refund_no)")

    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='generation_jobs'"
    )
    generation_columns = {item["COLUMN_NAME"] for item in cursor.fetchall()}
    additive_columns = {
        "input_path": "TEXT NULL AFTER input_sha256",
        "delivery_product": "VARCHAR(64) NOT NULL DEFAULT 'allocation_plan' AFTER synthetic_budget",
        "trajectory_count": "SMALLINT UNSIGNED NULL AFTER delivery_product",
        "attempt_count": "TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER error_message",
        "max_attempts": "TINYINT UNSIGNED NOT NULL DEFAULT 3 AFTER attempt_count",
        "next_attempt_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER max_attempts",
        "worker_id": "VARCHAR(190) NULL AFTER next_attempt_at",
        "lease_expires_at": "DATETIME NULL AFTER worker_id",
        "heartbeat_at": "DATETIME NULL AFTER lease_expires_at",
        "last_error_at": "DATETIME NULL AFTER heartbeat_at",
    }
    for column_name, definition in additive_columns.items():
        if column_name not in generation_columns:
            cursor.execute(f"ALTER TABLE generation_jobs ADD COLUMN {column_name} {definition}")

    cursor.execute(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='generation_jobs' AND INDEX_NAME='idx_generation_queue' LIMIT 1"
    )
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE generation_jobs ADD INDEX idx_generation_queue (status,next_attempt_at,created_at)")

    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='procurement_gate_evidence'"
    )
    evidence_columns = {item["COLUMN_NAME"] for item in cursor.fetchall()}
    evidence_additive_columns = {
        "evidence_scope": "ENUM('simulation','buyer_external') NOT NULL DEFAULT 'simulation' AFTER evidence_sha256",
        "contract_eligible": "BOOLEAN NOT NULL DEFAULT FALSE AFTER evidence_scope",
        "verification_reference": "VARCHAR(255) NULL AFTER review_note",
        "reviewer_name": "VARCHAR(190) NULL AFTER verification_reference",
        "review_attestation_sha256": "CHAR(64) NULL AFTER reviewer_name",
    }
    for column_name, definition in evidence_additive_columns.items():
        if column_name not in evidence_columns:
            cursor.execute(f"ALTER TABLE procurement_gate_evidence ADD COLUMN {column_name} {definition}")

    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='procurement_contracts'"
    )
    contract_columns = {item["COLUMN_NAME"] for item in cursor.fetchall()}
    contract_additive_columns = {
        "executed_document_sha256": "CHAR(64) NULL AFTER contract_reference",
        "provider_signatory": "VARCHAR(190) NULL AFTER executed_document_sha256",
        "provider_signature_sha256": "CHAR(64) NULL AFTER provider_signatory",
        "buyer_signatory": "VARCHAR(190) NULL AFTER provider_signature_sha256",
        "buyer_signature_sha256": "CHAR(64) NULL AFTER buyer_signatory",
        "effective_date": "DATE NULL AFTER buyer_signatory",
        "execution_attestation_sha256": "CHAR(64) NULL AFTER effective_date",
    }
    for column_name, definition in contract_additive_columns.items():
        if column_name not in contract_columns:
            cursor.execute(f"ALTER TABLE procurement_contracts ADD COLUMN {column_name} {definition}")


def initialize_schema(retries: int = 30, delay_seconds: float = 1.0) -> None:
    last_error = None
    for _ in range(retries):
        try:
            with transaction() as connection:
                with connection.cursor() as cursor:
                    for statement in _schema_statements():
                        cursor.execute(statement)
                    _apply_compatible_migrations(cursor)
            return
        except Exception as exc:  # MySQL may still be starting in Docker.
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(f"MySQL schema initialization failed: {last_error}")
