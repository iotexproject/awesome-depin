from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import uuid
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache, wraps
from pathlib import Path

import pymysql
from flask import Flask, Response, g, jsonify, request, send_file

from db import execute, fetch_all, fetch_one, initialize_schema, transaction
from data_retention import complete_deletion_request
from gates import evaluate_request
from payment_providers import (
    PaymentConfigurationError,
    PaymentNotification,
    PaymentProviderError,
    PaymentVerificationError,
    RefundNotification,
    channel_configuration,
    create_checkout,
    initiate_refund,
    payment_mode,
    require_channel_configuration,
    verify_alipay_notification,
    verify_wechat_notification,
)
from procurement import GATE_DEFINITIONS, evaluate_gate_evidence
from security import hash_token, new_api_key, new_session_token, password_hash, password_matches, validate_security_configuration
from trajectory_delivery import DELIVERY_PRODUCT as TRAJECTORY_DELIVERY_PRODUCT, validate_trajectory_request


BASE_DIR = Path(__file__).resolve().parents[1]
JOBS_DIR = Path(os.environ.get("QTAIL_JOBS_DIR", BASE_DIR / "var/jobs")).resolve()
CATALOG_DIR = Path(os.environ.get("QTAIL_SYNTHETIC_CATALOG_DIR", BASE_DIR / "var/catalog")).resolve()
SYNTHETIC_CATALOGS = (
    {
        "slug": "metaworld-sawyer-v0.1.0",
        "title": "MetaWorld Sawyer 长尾轨迹样包 v0.1.0",
        "filename": "qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz",
        "bytes": 56_447_787,
        "sha256": "c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0",
        "dataset_manifest_sha256": "003d5d62c92237412f86d72e796c4a5570e3a9760b1d40fee8c0f7f826f3c13a",
        "embodiment": "MetaWorld Sawyer abstraction / MuJoCo 3.10",
        "formats": ["LeRobotDataset v3", "RLDS-compatible TFRecord"],
        "tasks": ["reach-v3", "button-press-v3", "pick-place-v3"],
        "trajectory_count": 64,
        "frame_count": 3285,
        "evidence_scope": "simulation",
        "buyer_gate_passed": False,
        "claim_boundary": "Q-Tail 自主模拟技术样包；不是买方指定生产后端、真实机器人或采购验收证据。",
    },
)
COOKIE_NAME = "qtail_session"
SESSION_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
PRO_PRICE_CENTS = int(os.environ.get("PRO_PRICE_CENTS", "99900"))
PRO_DAILY_GENERATION_LIMIT = int(os.environ.get("PRO_DAILY_GENERATION_LIMIT", "50"))
MAX_ACTIVE_GENERATIONS_PER_USER = int(os.environ.get("MAX_ACTIVE_GENERATIONS_PER_USER", "5"))
GENERATION_MAX_ATTEMPTS = int(os.environ.get("QTAIL_WORKER_MAX_ATTEMPTS", "3"))
LEGAL_DOCUMENT_VERSIONS = {"terms": "2026-07-15", "privacy": "2026-07-15", "dpa": "2026-07-15-v1"}
DATA_RIGHTS_ATTESTATION_VERSION = "2026-07-15-v1"
DEPLOYMENT_BOUNDARIES = {"qtail_cloud", "customer_vpc", "on_prem"}
DATA_SOURCE_TYPES = {"customer_owned", "licensed", "public_open", "synthetic"}
EVIDENCE_SCOPES = {"simulation", "buyer_external"}
DELIVERY_PRODUCTS = {"allocation_plan", TRAJECTORY_DELIVERY_PRODUCT}

STATUS_LABELS = {
    "received": "审核中",
    "approved": "已批准",
    "rejected": "已拒绝",
    "pending": "待付款",
    "under_review": "核验中",
    "paid": "已支付",
    "expired": "已过期",
    "refunded": "已退款",
    "requested": "待处理",
    "processing": "删除中",
    "issued": "已开票",
    "cancelled": "已取消",
    "queued": "排队中",
    "running": "生成中",
    "completed": "已完成",
    "failed": "失败",
    "active": "验证中",
    "contract_ready": "合同就绪",
    "contracted": "已签约",
    "closed": "已关闭",
    "ready": "待签署",
    "signed": "已签署",
    "void": "已作废",
}
CHANNEL_LABELS = {"wechat": "微信支付", "alipay": "支付宝"}
REFUND_STATUS_LABELS = {"requested": "待处理", "approved": "已批准", "processing": "渠道处理中", "rejected": "已拒绝", "failed": "渠道异常", "completed": "已完成"}


class DailyQuotaExceeded(Exception):
    pass


class ActiveQueueLimitExceeded(Exception):
    pass


def _insert_provider_event(cursor, notification, event_type: str, status: str, failure_code: str | None, order_id=None, refund_id=None) -> None:
    cursor.execute(
        "INSERT INTO payment_provider_events "
        "(id,channel,event_id,event_type,order_id,refund_id,provider_transaction_id,payload_sha256,signature_serial,status,failure_code,processed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())",
        (
            str(uuid.uuid4()), notification.channel, notification.event_id, event_type, order_id, refund_id,
            getattr(notification, "provider_transaction_id", None) or getattr(notification, "provider_refund_id", None),
            notification.payload_sha256, notification.signature_serial, status, failure_code,
        ),
    )


def _duplicate_provider_event(channel: str, event_id: str):
    row = fetch_one(
        "SELECT status,failure_code,order_id,refund_id FROM payment_provider_events WHERE channel=%s AND event_id=%s",
        (channel, event_id),
    )
    if not row:
        raise RuntimeError("Provider event uniqueness conflict without an existing event")
    return {"accepted": row["status"] == "accepted", "reused": True, "failure_code": row.get("failure_code"), "order_id": row.get("order_id"), "refund_id": row.get("refund_id")}


def settle_official_payment(notification: PaymentNotification) -> dict:
    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status,failure_code,order_id FROM payment_provider_events WHERE channel=%s AND event_id=%s FOR UPDATE",
                    (notification.channel, notification.event_id),
                )
                event = cursor.fetchone()
                if event:
                    return {"accepted": event["status"] == "accepted", "reused": True, "failure_code": event.get("failure_code"), "order_id": event.get("order_id")}
                cursor.execute("SELECT * FROM payment_orders WHERE merchant_order_no=%s FOR UPDATE", (notification.merchant_order_no,))
                order = cursor.fetchone()
                failure_code = None
                if not order:
                    failure_code = "merchant_order_not_found"
                elif order["payment_mode"] != "official_merchant":
                    failure_code = "manual_order_callback_forbidden"
                elif order["channel"] != notification.channel:
                    failure_code = "payment_channel_mismatch"
                elif order["currency"] != notification.currency:
                    failure_code = "payment_currency_mismatch"
                elif int(order["amount_cents"]) != int(notification.amount_cents):
                    failure_code = "payment_amount_mismatch"
                elif order.get("provider_transaction_id") and order["provider_transaction_id"] != notification.provider_transaction_id:
                    failure_code = "provider_transaction_mismatch"
                elif order["status"] not in {"pending", "under_review", "paid", "refunded"}:
                    failure_code = "payment_order_state_invalid"
                if failure_code:
                    _insert_provider_event(cursor, notification, "payment", "rejected", failure_code, order_id=order and order["id"])
                    return {"accepted": False, "reused": False, "failure_code": failure_code, "order_id": order and order["id"]}

                cursor.execute(
                    "SELECT id FROM payment_orders WHERE provider_transaction_id=%s AND id<>%s LIMIT 1 FOR UPDATE",
                    (notification.provider_transaction_id, order["id"]),
                )
                if cursor.fetchone():
                    failure_code = "provider_transaction_reused"
                    _insert_provider_event(cursor, notification, "payment", "rejected", failure_code, order_id=order["id"])
                    return {"accepted": False, "reused": False, "failure_code": failure_code, "order_id": order["id"]}

                newly_paid = order["status"] in {"pending", "under_review"}
                if newly_paid:
                    cursor.execute(
                        "UPDATE payment_orders SET status='paid',payment_reference=%s,provider_transaction_id=%s,"
                        "provider_event_id=%s,provider_payload_sha256=%s,provider_verified_at=UTC_TIMESTAMP(),"
                        "paid_at=UTC_TIMESTAMP(),reviewed_at=UTC_TIMESTAMP(),review_note='Official merchant callback verified' WHERE id=%s",
                        (
                            notification.provider_transaction_id, notification.provider_transaction_id, notification.event_id,
                            notification.payload_sha256, order["id"],
                        ),
                    )
                    cursor.execute(
                        "UPDATE users SET plan='pro',pro_expires_at=IF(pro_expires_at IS NOT NULL AND pro_expires_at>UTC_TIMESTAMP(),"
                        "DATE_ADD(pro_expires_at,INTERVAL 30 DAY),DATE_ADD(UTC_TIMESTAMP(),INTERVAL 30 DAY)) WHERE id=%s",
                        (order["user_id"],),
                    )
                _insert_provider_event(cursor, notification, "payment", "accepted", None, order_id=order["id"])
                return {"accepted": True, "reused": not newly_paid, "order_id": order["id"], "user_id": order["user_id"]}
    except pymysql.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            return _duplicate_provider_event(notification.channel, notification.event_id)
        raise


def _revoke_refunded_entitlement(cursor, user_id: str) -> None:
    cursor.execute(
        "UPDATE users SET "
        "plan=IF(pro_expires_at>DATE_ADD(UTC_TIMESTAMP(),INTERVAL 30 DAY),'pro','free'),"
        "pro_expires_at=IF(pro_expires_at>DATE_ADD(UTC_TIMESTAMP(),INTERVAL 30 DAY),DATE_SUB(pro_expires_at,INTERVAL 30 DAY),NULL) "
        "WHERE id=%s",
        (user_id,),
    )
    cursor.execute("SELECT plan FROM users WHERE id=%s", (user_id,))
    if cursor.fetchone()["plan"] == "free":
        cursor.execute("UPDATE api_keys SET status='revoked' WHERE user_id=%s AND status='active'", (user_id,))


def settle_official_refund(notification: RefundNotification) -> dict:
    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status,failure_code,refund_id FROM payment_provider_events WHERE channel=%s AND event_id=%s FOR UPDATE",
                    (notification.channel, notification.event_id),
                )
                event = cursor.fetchone()
                if event:
                    return {"accepted": event["status"] == "accepted", "reused": True, "failure_code": event.get("failure_code"), "refund_id": event.get("refund_id")}
                cursor.execute("SELECT * FROM refund_requests WHERE merchant_refund_no=%s FOR UPDATE", (notification.merchant_refund_no,))
                refund = cursor.fetchone()
                order = None
                if refund:
                    cursor.execute("SELECT * FROM payment_orders WHERE id=%s FOR UPDATE", (refund["order_id"],))
                    order = cursor.fetchone()
                failure_code = None
                if not refund or not order:
                    failure_code = "merchant_refund_not_found"
                elif order["merchant_order_no"] != notification.merchant_order_no:
                    failure_code = "refund_order_mismatch"
                elif order["payment_mode"] != "official_merchant" or order["channel"] != notification.channel:
                    failure_code = "refund_channel_mismatch"
                elif order["currency"] != notification.currency or int(refund["amount_cents"]) != int(notification.amount_cents):
                    failure_code = "refund_amount_mismatch"
                elif refund.get("provider_refund_id") and refund["provider_refund_id"] != notification.provider_refund_id:
                    failure_code = "provider_refund_mismatch"
                if failure_code:
                    _insert_provider_event(cursor, notification, "refund", "rejected", failure_code, order_id=order and order["id"], refund_id=refund and refund["id"])
                    return {"accepted": False, "reused": False, "failure_code": failure_code, "refund_id": refund and refund["id"]}

                already_completed = refund["status"] == "completed"
                if notification.refund_status == "SUCCESS" and not already_completed:
                    cursor.execute(
                        "UPDATE refund_requests SET status='completed',refund_reference=%s,provider_refund_id=%s,"
                        "provider_event_id=%s,provider_payload_sha256=%s,provider_verified_at=UTC_TIMESTAMP(),"
                        "review_note='Official original-channel refund callback verified',completed_at=UTC_TIMESTAMP() WHERE id=%s",
                        (notification.provider_refund_id, notification.provider_refund_id, notification.event_id, notification.payload_sha256, refund["id"]),
                    )
                    cursor.execute(
                        "UPDATE payment_orders SET status='refunded',review_note='Official original-channel refund callback verified',reviewed_at=UTC_TIMESTAMP() WHERE id=%s",
                        (order["id"],),
                    )
                    _revoke_refunded_entitlement(cursor, order["user_id"])
                elif notification.refund_status in {"CLOSED", "ABNORMAL"} and not already_completed:
                    cursor.execute(
                        "UPDATE refund_requests SET status='failed',provider_refund_id=%s,provider_event_id=%s,"
                        "provider_payload_sha256=%s,provider_verified_at=UTC_TIMESTAMP(),review_note=%s WHERE id=%s",
                        (
                            notification.provider_refund_id, notification.event_id, notification.payload_sha256,
                            f"Official refund state: {notification.refund_status}", refund["id"],
                        ),
                    )
                _insert_provider_event(cursor, notification, "refund", "accepted", None, order_id=order["id"], refund_id=refund["id"])
                return {"accepted": True, "reused": already_completed, "refund_id": refund["id"], "order_id": order["id"], "user_id": order["user_id"]}
    except pymysql.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            return _duplicate_provider_event(notification.channel, notification.event_id)
        raise


def start_official_refund(request_id: str) -> dict:
    refund = fetch_one(
        "SELECT r.*,p.channel,p.payment_mode,p.merchant_order_no,p.provider_transaction_id,p.status AS order_status "
        "FROM refund_requests r JOIN payment_orders p ON p.id=r.order_id WHERE r.id=%s",
        (request_id,),
    )
    if not refund:
        return {"ok": False, "code": "refund_request_not_found"}
    if refund["payment_mode"] != "official_merchant":
        return {"ok": False, "code": "manual_refund_required"}
    if refund["status"] == "completed":
        return {"ok": True, "status": "completed", "reused": True}
    if refund["status"] == "processing":
        return {"ok": True, "status": "processing", "reused": True}
    if refund["status"] not in {"approved", "failed"} or refund["order_status"] != "paid":
        return {"ok": False, "code": "invalid_refund_state"}
    invoice = fetch_one("SELECT id FROM invoice_requests WHERE order_id=%s AND status='issued' LIMIT 1", (refund["order_id"],))
    if invoice:
        return {"ok": False, "code": "invoice_cancellation_required", "action_required": True}
    require_channel_configuration(refund["channel"])
    result = initiate_refund(
        refund["channel"], refund["merchant_order_no"], refund.get("provider_transaction_id"),
        refund["merchant_refund_no"], int(refund["amount_cents"]), refund["reason"],
    )
    if result.status == "processing":
        execute(
            "UPDATE refund_requests SET status='processing',provider_refund_id=%s,refund_reference=%s,"
            "provider_verified_at=UTC_TIMESTAMP(),review_note='Official original-channel refund accepted; awaiting verified callback' WHERE id=%s AND status IN ('approved','failed')",
            (result.provider_refund_id, result.provider_reference, request_id),
        )
        return {"ok": True, "status": "processing", "provider_refund_id": result.provider_refund_id}

    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM refund_requests WHERE id=%s FOR UPDATE", (request_id,))
            current = cursor.fetchone()
            if current["status"] == "completed":
                return {"ok": True, "status": "completed", "reused": True}
            cursor.execute("SELECT * FROM payment_orders WHERE id=%s FOR UPDATE", (current["order_id"],))
            order = cursor.fetchone()
            if not order or order["status"] != "paid":
                return {"ok": False, "code": "order_not_refundable"}
            cursor.execute(
                "UPDATE refund_requests SET status='completed',refund_reference=%s,provider_refund_id=%s,"
                "provider_verified_at=UTC_TIMESTAMP(),review_note='Official original-channel refund response verified',completed_at=UTC_TIMESTAMP() WHERE id=%s",
                (result.provider_reference, result.provider_refund_id, request_id),
            )
            cursor.execute(
                "UPDATE payment_orders SET status='refunded',review_note='Official original-channel refund response verified',reviewed_at=UTC_TIMESTAMP() WHERE id=%s",
                (order["id"],),
            )
            _revoke_refunded_entitlement(cursor, order["user_id"])
    return {"ok": True, "status": "completed", "provider_refund_id": result.provider_refund_id}


def create_app(*, initialize: bool = True) -> Flask:
    validate_security_configuration()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    if initialize:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        initialize_schema()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.errorhandler(413)
    def too_large(_error):
        return error_response("请求体过大，最大 20 MiB", 413, "payload_too_large")

    @app.post("/api/payments/alipay/notify")
    def alipay_payment_notify():
        raw_body = request.get_data(cache=True)
        try:
            notification = verify_alipay_notification(request.form.to_dict(flat=False), raw_body)
            result = settle_official_payment(notification)
        except PaymentConfigurationError:
            return Response("failure", status=503, mimetype="text/plain")
        except PaymentVerificationError:
            return Response("failure", status=400, mimetype="text/plain")
        if not result["accepted"]:
            audit(None, "payment_provider.event_rejected", "payment_provider_event", notification.event_id, {"channel": notification.channel, "failure_code": result.get("failure_code"), "payload_sha256": notification.payload_sha256})
            return Response("failure", status=400, mimetype="text/plain")
        audit(None, "payment_provider.event_accepted", "payment_order", result.get("order_id") or "unknown", {"channel": notification.channel, "event_id": notification.event_id, "payload_sha256": notification.payload_sha256, "reused": result.get("reused", False)})
        return Response("success", status=200, mimetype="text/plain")

    @app.post("/api/payments/wechat/notify")
    def wechat_payment_notify():
        raw_body = request.get_data(cache=True)
        try:
            notification = verify_wechat_notification(raw_body, request.headers)
            if isinstance(notification, PaymentNotification):
                result = settle_official_payment(notification)
                object_type = "payment_order"
                object_id = result.get("order_id")
            else:
                result = settle_official_refund(notification)
                object_type = "refund_request"
                object_id = result.get("refund_id")
        except PaymentConfigurationError:
            return jsonify({"code": "FAIL", "message": "Merchant callback is not configured"}), 503
        except PaymentVerificationError:
            return jsonify({"code": "FAIL", "message": "Invalid callback"}), 400
        if not result["accepted"]:
            audit(None, "payment_provider.event_rejected", "payment_provider_event", notification.event_id, {"channel": notification.channel, "failure_code": result.get("failure_code"), "payload_sha256": notification.payload_sha256})
            return jsonify({"code": "FAIL", "message": "Order verification failed"}), 400
        audit(None, "payment_provider.event_accepted", object_type, object_id or "unknown", {"channel": notification.channel, "event_id": notification.event_id, "payload_sha256": notification.payload_sha256, "reused": result.get("reused", False)})
        return Response(status=204)

    @app.get("/api/health")
    def health():
        row = fetch_one("SELECT 1 AS ok")
        return jsonify({"ok": bool(row and row["ok"]), "service": "qtail-platform-api", "database": "mysql"})

    @app.get("/api/admin/health")
    @require_admin
    def admin_health():
        metrics = fetch_one(
            "SELECT "
            "(SELECT COUNT(*) FROM users) AS users_total,"
            "(SELECT COUNT(*) FROM users WHERE pro_expires_at > UTC_TIMESTAMP()) AS pro_active,"
            "(SELECT COUNT(*) FROM generation_jobs WHERE status='queued') AS jobs_queued,"
            "(SELECT COUNT(*) FROM generation_jobs WHERE status='running') AS jobs_running,"
            "(SELECT COUNT(*) FROM generation_jobs WHERE status='failed' AND created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR) AS jobs_failed_24h,"
            "(SELECT COUNT(*) FROM payment_orders WHERE status='under_review') AS payments_under_review,"
            "(SELECT COUNT(*) FROM invoice_requests WHERE status='requested') AS invoices_pending,"
            "(SELECT COUNT(*) FROM refund_requests WHERE status IN ('requested','approved','processing','failed')) AS refunds_pending,"
            "(SELECT COUNT(*) FROM procurement_gate_evidence WHERE status='received') AS evidence_under_review,"
            "(SELECT COUNT(*) FROM buyer_compliance_profiles WHERE status='received') AS compliance_under_review,"
            "(SELECT COUNT(*) FROM data_deletion_requests WHERE status IN ('requested','processing')) AS deletions_pending,"
            "(SELECT COUNT(*) FROM data_deletion_requests WHERE status='requested' AND due_at<=UTC_TIMESTAMP()) AS deletions_overdue,"
            "(SELECT COUNT(*) FROM generation_jobs j JOIN generation_data_rights r ON r.generation_job_id=j.id LEFT JOIN data_deletion_requests d ON d.generation_job_id=j.id WHERE j.status IN ('completed','failed') AND TIMESTAMPADD(DAY,r.retention_days,r.accepted_at)<=UTC_TIMESTAMP() AND (d.id IS NULL OR d.status='rejected')) AS retention_payloads_due,"
            "(SELECT TIMESTAMPDIFF(SECOND,MIN(created_at),UTC_TIMESTAMP()) FROM generation_jobs WHERE status='queued') AS oldest_queued_seconds,"
            "(SELECT setting_value='1' FROM system_settings WHERE setting_key='worker_paused') AS worker_paused,"
            "(SELECT TIMESTAMPDIFF(SECOND,updated_at,UTC_TIMESTAMP()) FROM system_settings WHERE setting_key='worker_paused' AND setting_value='1') AS worker_pause_age_seconds,"
            "(SELECT MAX(created_at) FROM audit_events) AS latest_audit_at"
        )
        package_count = 0
        package_bytes = 0
        for path in JOBS_DIR.glob("**/*"):
            if path.is_file():
                package_count += 1
                package_bytes += path.stat().st_size
        return jsonify({
            "ok": True,
            "service": "qtail-platform-api",
            "database": "mysql",
            "metrics": metrics,
            "delivery_storage": {"files": package_count, "bytes": package_bytes},
            "checked_at": datetime.now(UTC).isoformat(),
        })

    @app.post("/api/auth/register")
    def register():
        payload = json_payload()
        email = clean(payload.get("email"), 190).lower()
        name = clean(payload.get("name"), 120)
        company = clean(payload.get("company"), 190)
        password = str(payload.get("password") or "")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return error_response("请输入有效邮箱", 400, "invalid_email")
        if len(password) < 10:
            return error_response("密码至少需要 10 个字符", 400, "weak_password")
        if not name or not company:
            return error_response("姓名和公司不能为空", 400, "missing_profile")
        user_id = str(uuid.uuid4())
        try:
            execute(
                "INSERT INTO users (id,email,password_hash,name,company) VALUES (%s,%s,%s,%s,%s)",
                (user_id, email, password_hash(password), name, company),
            )
        except pymysql.err.IntegrityError:
            return error_response("该邮箱已注册", 409, "email_exists")
        user = fetch_one("SELECT * FROM users WHERE id=%s", (user_id,))
        response = jsonify({"ok": True, "user": public_user(user)})
        attach_session(response, user_id)
        audit(user_id, "user.registered", "user", user_id, {"email": email, "company": company})
        return response, 201

    @app.post("/api/auth/login")
    def login():
        payload = json_payload()
        email = clean(payload.get("email"), 190).lower()
        password = str(payload.get("password") or "")
        user = fetch_one("SELECT * FROM users WHERE email=%s", (email,))
        if not user or user["account_status"] != "active" or not password_matches(user["password_hash"], password):
            return error_response("邮箱或密码错误", 401, "invalid_credentials")
        response = jsonify({"ok": True, "user": public_user(user)})
        attach_session(response, user["id"])
        audit(user["id"], "user.logged_in", "user", user["id"], {})
        return response

    @app.get("/api/auth/me")
    @require_user
    def me():
        return jsonify({"ok": True, "user": public_user(g.user)})

    @app.post("/api/auth/logout")
    def logout():
        token = request.cookies.get(COOKIE_NAME)
        if token:
            execute("UPDATE sessions SET revoked_at=UTC_TIMESTAMP() WHERE token_hash=%s", (hash_token(token),))
        response = jsonify({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/api/account/export")
    @require_user
    def export_account():
        user_id = g.user["id"]
        applications = fetch_all(
            "SELECT id,role,use_case,data_format,monthly_volume,pilot_goal,status,review_note,created_at,reviewed_at FROM api_access_applications WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        orders = fetch_all(
            "SELECT id,merchant_order_no,plan_code,channel,payment_mode,amount_cents,currency,status,payment_reference,provider_transaction_id,provider_event_id,provider_payload_sha256,provider_verified_at,review_note,submitted_at,paid_at,created_at FROM payment_orders WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        invoices = fetch_all(
            "SELECT id,order_id,invoice_title,taxpayer_id,invoice_email,status,invoice_number,invoice_document_url,cancellation_reference,review_note,requested_at,reviewed_at,issued_at,cancelled_at FROM invoice_requests WHERE user_id=%s ORDER BY requested_at",
            (user_id,),
        )
        refunds = fetch_all(
            "SELECT id,merchant_refund_no,order_id,amount_cents,reason,status,refund_reference,provider_refund_id,provider_event_id,provider_payload_sha256,provider_verified_at,review_note,requested_at,reviewed_at,completed_at FROM refund_requests WHERE user_id=%s ORDER BY requested_at",
            (user_id,),
        )
        provider_events = fetch_all(
            "SELECT id,channel,event_id,event_type,order_id,refund_id,provider_transaction_id,payload_sha256,signature_serial,status,failure_code,received_at,processed_at "
            "FROM payment_provider_events WHERE order_id IN (SELECT id FROM payment_orders WHERE user_id=%s) "
            "OR refund_id IN (SELECT id FROM refund_requests WHERE user_id=%s) ORDER BY received_at",
            (user_id, user_id),
        )
        jobs = fetch_all(
            "SELECT id,filename,robot_model,control_frequency_hz,sensors,training_format,production_backend,synthetic_budget,delivery_product,trajectory_count,status,gate_evaluation,input_sha256,created_at,started_at,completed_at FROM generation_jobs WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        cases = fetch_all(
            "SELECT id,generation_job_id,title,buyer_owner,pilot_scope,status,created_at,updated_at FROM procurement_cases WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        contracts = fetch_all(
            "SELECT id,case_id,version,status,contract_reference,executed_document_sha256,provider_signatory,provider_signature_sha256,buyer_signatory,buyer_signature_sha256,effective_date,execution_attestation_sha256,issued_at,signed_at FROM procurement_contracts WHERE user_id=%s ORDER BY issued_at",
            (user_id,),
        )
        compliance_profile = fetch_one("SELECT * FROM buyer_compliance_profiles WHERE user_id=%s", (user_id,))
        legal_acceptances = fetch_all(
            "SELECT document_code,document_version,acceptance_sha256,accepted_at,revoked_at FROM legal_acceptances WHERE user_id=%s ORDER BY accepted_at",
            (user_id,),
        )
        data_rights = fetch_all(
            "SELECT generation_job_id,source_type,license_basis,contains_personal_data,retention_days,attestation_version,attestation_sha256,accepted_at FROM generation_data_rights WHERE user_id=%s ORDER BY accepted_at",
            (user_id,),
        )
        deletion_requests = fetch_all(
            "SELECT id,generation_job_id,request_source,reason,status,due_at,deletion_sha256,files_deleted,bytes_deleted,review_note,requested_at,reviewed_at,completed_at FROM data_deletion_requests WHERE user_id=%s ORDER BY requested_at",
            (user_id,),
        )
        return jsonify({
            "ok": True,
            "exported_at": datetime.now(UTC).isoformat(),
            "account": public_user(g.user),
            "api_access_applications": [json_safe_row(item) for item in applications],
            "payment_orders": [json_safe_row(item) for item in orders],
            "invoice_requests": [json_safe_row(item) for item in invoices],
            "refund_requests": [json_safe_row(item) for item in refunds],
            "payment_provider_events": [json_safe_row(item) for item in provider_events],
            "generation_jobs": [json_safe_row(item) for item in jobs],
            "generation_data_rights": [json_safe_row(item) for item in data_rights],
            "data_deletion_requests": [json_safe_row(item) for item in deletion_requests],
            "compliance_profile": json_safe_row(compliance_profile) if compliance_profile else None,
            "legal_acceptances": [json_safe_row(item) for item in legal_acceptances],
            "procurement_cases": [json_safe_row(item) for item in cases],
            "procurement_contracts": [json_safe_row(item) for item in contracts],
            "retention_note": "Security, payment, audit, and contract records may be retained where required for legal claims, accounting, fraud prevention, or contract performance.",
        })

    @app.delete("/api/account")
    @require_user
    def close_account():
        payload = json_payload()
        password = str(payload.get("password") or "")
        confirmation = clean(payload.get("confirmation"), 80)
        if confirmation != "CLOSE MY ACCOUNT":
            return error_response("请输入指定的账户注销确认语", 400, "invalid_confirmation")
        if not password_matches(g.user["password_hash"], password):
            return error_response("密码错误", 403, "invalid_password")
        user_id = g.user["id"]
        active_jobs = fetch_one(
            "SELECT COUNT(*) AS count FROM generation_jobs WHERE user_id=%s AND status IN ('queued','running')",
            (user_id,),
        )
        if active_jobs and int(active_jobs["count"]):
            return error_response("仍有排队或运行中的生成任务，请等待任务结束后再注销账户", 409, "active_generations_exist")
        anonymized_email = f"deleted-{user_id}@qtail.invalid"
        replacement_password = password_hash(new_session_token()[0])
        event = json.dumps({"anonymized_email": anonymized_email}, ensure_ascii=False)
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE sessions SET revoked_at=COALESCE(revoked_at,UTC_TIMESTAMP()) WHERE user_id=%s", (user_id,))
                cursor.execute("UPDATE api_keys SET status='revoked' WHERE user_id=%s AND status='active'", (user_id,))
                cursor.execute("UPDATE api_access_applications SET status='rejected',review_note='Account closed',reviewed_at=UTC_TIMESTAMP() WHERE user_id=%s AND status='received'", (user_id,))
                cursor.execute("UPDATE payment_orders SET status='expired',review_note='Account closed',reviewed_at=UTC_TIMESTAMP() WHERE user_id=%s AND status IN ('pending','under_review')", (user_id,))
                cursor.execute("UPDATE procurement_contracts SET status='void' WHERE user_id=%s AND status='ready'", (user_id,))
                cursor.execute("UPDATE procurement_cases SET status='closed' WHERE user_id=%s AND status='active'", (user_id,))
                cursor.execute("UPDATE legal_acceptances SET revoked_at=COALESCE(revoked_at,UTC_TIMESTAMP()) WHERE user_id=%s", (user_id,))
                cursor.execute("UPDATE buyer_compliance_profiles SET status='rejected',organization_legal_name='已注销企业',security_contact_email=%s,review_note='Account closed',reviewed_at=UTC_TIMESTAMP() WHERE user_id=%s", (anonymized_email, user_id))
                cursor.execute(
                    "INSERT INTO data_deletion_requests (id,generation_job_id,user_id,request_source,reason,due_at) "
                    "SELECT UUID(),j.id,j.user_id,'account_closure','Account closure payload deletion',UTC_TIMESTAMP() "
                    "FROM generation_jobs j WHERE j.user_id=%s AND j.status IN ('completed','failed') "
                    "ON DUPLICATE KEY UPDATE "
                    "request_source=IF(data_deletion_requests.status='completed',data_deletion_requests.request_source,'account_closure'),"
                    "reason=IF(data_deletion_requests.status='completed',data_deletion_requests.reason,'Account closure payload deletion'),"
                    "due_at=IF(data_deletion_requests.status='completed',data_deletion_requests.due_at,UTC_TIMESTAMP()),"
                    "status=IF(data_deletion_requests.status='completed','completed','requested')",
                    (user_id,),
                )
                cursor.execute(
                    "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) VALUES (%s,'user.account_closed','user',%s,%s)",
                    (user_id, user_id, event),
                )
                cursor.execute(
                    "UPDATE users SET email=%s,password_hash=%s,name='已注销用户',company='已注销',account_status='disabled',plan='free',pro_expires_at=NULL WHERE id=%s",
                    (anonymized_email, replacement_password, user_id),
                )
        response = jsonify({
            "ok": True,
            "status": "closed",
            "retention_note": "Transactional, audit, and signed-contract evidence is retained only where required for accounting, security, claims, or legal obligations.",
        })
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/api/compliance")
    @require_user
    def get_compliance():
        state = contract_compliance_state(g.user["id"])
        return jsonify({
            "ok": True,
            "profile": state["profile"],
            "legal_acceptances": state["legal_acceptances"],
            "required_documents": LEGAL_DOCUMENT_VERSIONS,
            "ready_for_contract": state["ready"],
            "missing_documents": state["missing_documents"],
        })

    @app.put("/api/compliance")
    @require_user
    def submit_compliance():
        payload = json_payload()
        organization_legal_name = clean(payload.get("organization_legal_name"), 190)
        security_contact_email = clean(payload.get("security_contact_email"), 190).lower()
        deployment_boundary = clean(payload.get("deployment_boundary"), 40)
        data_residency = clean(payload.get("data_residency"), 190)
        try:
            retention_days = int(payload.get("retention_days"))
            deletion_sla_days = int(payload.get("deletion_sla_days"))
        except (TypeError, ValueError):
            return error_response("保存期限与删除 SLA 必须是整数天", 400, "invalid_retention")
        if not organization_legal_name or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", security_contact_email):
            return error_response("请填写企业法定名称和有效安全联系人邮箱", 400, "invalid_compliance_contact")
        if deployment_boundary not in DEPLOYMENT_BOUNDARIES:
            return error_response("部署边界无效", 400, "invalid_deployment_boundary")
        if not data_residency:
            return error_response("数据驻留区域不能为空", 400, "missing_data_residency")
        if retention_days < 7 or retention_days > 3650 or deletion_sla_days < 1 or deletion_sla_days > 90:
            return error_response("保存期限须为 7–3650 天，删除 SLA 须为 1–90 天", 400, "invalid_retention")
        required_attestations = {
            "source_rights_confirmed": payload.get("source_rights_confirmed") is True,
            "derivative_rights_confirmed": payload.get("derivative_rights_confirmed") is True,
            "restricted_data_excluded": payload.get("restricted_data_excluded") is True,
            "subprocessor_reviewed": payload.get("subprocessor_reviewed") is True,
            "terms": payload.get("terms_accepted") is True,
            "privacy": payload.get("privacy_acknowledged") is True,
            "dpa": payload.get("dpa_accepted") is True,
        }
        missing = [name for name, accepted in required_attestations.items() if not accepted]
        if missing:
            return error_response("必须完成全部数据权利、隐私和协议确认", 422, "compliance_attestations_required", {"missing": missing})

        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version FROM buyer_compliance_profiles WHERE user_id=%s FOR UPDATE", (g.user["id"],))
                existing = cursor.fetchone()
                version = int(existing["version"] if existing else 0) + 1
                canonical_profile = {
                    "version": version,
                    "organization_legal_name": organization_legal_name,
                    "security_contact_email": security_contact_email,
                    "deployment_boundary": deployment_boundary,
                    "data_residency": data_residency,
                    "retention_days": retention_days,
                    "deletion_sla_days": deletion_sla_days,
                    "source_rights_confirmed": True,
                    "derivative_rights_confirmed": True,
                    "restricted_data_excluded": True,
                    "subprocessor_reviewed": True,
                    "document_versions": LEGAL_DOCUMENT_VERSIONS,
                }
                canonical_json = json.dumps(canonical_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                profile_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
                cursor.execute(
                    "INSERT INTO buyer_compliance_profiles "
                    "(user_id,version,organization_legal_name,security_contact_email,deployment_boundary,data_residency,retention_days,deletion_sla_days,source_rights_confirmed,derivative_rights_confirmed,restricted_data_excluded,subprocessor_reviewed,profile_sha256,status,submitted_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,TRUE,TRUE,TRUE,%s,'received',UTC_TIMESTAMP()) "
                    "ON DUPLICATE KEY UPDATE version=VALUES(version),organization_legal_name=VALUES(organization_legal_name),security_contact_email=VALUES(security_contact_email),deployment_boundary=VALUES(deployment_boundary),data_residency=VALUES(data_residency),retention_days=VALUES(retention_days),deletion_sla_days=VALUES(deletion_sla_days),source_rights_confirmed=TRUE,derivative_rights_confirmed=TRUE,restricted_data_excluded=TRUE,subprocessor_reviewed=TRUE,profile_sha256=VALUES(profile_sha256),status='received',review_note=NULL,submitted_at=UTC_TIMESTAMP(),reviewed_at=NULL",
                    (g.user["id"], version, organization_legal_name, security_contact_email, deployment_boundary, data_residency, retention_days, deletion_sla_days, profile_sha256),
                )
                for document_code, document_version in LEGAL_DOCUMENT_VERSIONS.items():
                    acceptance_payload = {
                        "user_id": g.user["id"],
                        "document_code": document_code,
                        "document_version": document_version,
                    }
                    acceptance_json = json.dumps(acceptance_payload, sort_keys=True, separators=(",", ":"))
                    acceptance_sha256 = hashlib.sha256(acceptance_json.encode("utf-8")).hexdigest()
                    cursor.execute(
                        "INSERT INTO legal_acceptances (id,user_id,document_code,document_version,acceptance_sha256,context_json) "
                        "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE revoked_at=NULL",
                        (str(uuid.uuid4()), g.user["id"], document_code, document_version, acceptance_sha256, json.dumps({"profile_sha256": profile_sha256})),
                    )
                cursor.execute(
                    "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) VALUES (%s,'compliance.submitted','buyer_compliance_profile',%s,%s)",
                    (g.user["id"], g.user["id"], json.dumps({"version": version, "profile_sha256": profile_sha256}, ensure_ascii=False)),
                )
        state = contract_compliance_state(g.user["id"])
        return jsonify({"ok": True, "profile": state["profile"], "legal_acceptances": state["legal_acceptances"], "ready_for_contract": state["ready"]})

    @app.get("/api/dashboard")
    @require_user
    def dashboard():
        application = latest_application(g.user["id"])
        key_count = fetch_one("SELECT COUNT(*) AS count FROM api_keys WHERE user_id=%s AND status='active'", (g.user["id"],))["count"]
        generation_count = fetch_one("SELECT COUNT(*) AS count FROM generation_jobs WHERE user_id=%s", (g.user["id"],))["count"]
        procurement = fetch_one("SELECT COUNT(*) AS count,SUM(status IN ('contract_ready','contracted')) AS ready FROM procurement_cases WHERE user_id=%s", (g.user["id"],))
        compliance = contract_compliance_state(g.user["id"])
        return jsonify({"ok": True, "api_application": serialize_application(application), "api_key_count": key_count, "generation_count": generation_count, "procurement_case_count": procurement["count"], "contract_ready_count": int(procurement["ready"] or 0), "compliance": {"status": compliance["profile"]["status"] if compliance["profile"] else "not_submitted", "ready_for_contract": compliance["ready"]}})

    @app.get("/api/api-access")
    @require_user
    def get_api_access():
        application = latest_application(g.user["id"])
        keys = fetch_all("SELECT id,label,key_prefix,created_at,last_used_at,status FROM api_keys WHERE user_id=%s ORDER BY created_at DESC", (g.user["id"],))
        return jsonify({"ok": True, "application": serialize_application(application), "keys": [serialize_api_key(item) for item in keys]})

    @app.post("/api/api-access")
    @require_user
    def apply_api_access():
        existing = latest_application(g.user["id"])
        if existing and existing["status"] in {"received", "approved"}:
            return error_response("已有进行中的 API 申请", 409, "application_exists")
        payload = json_payload()
        fields = {
            "role": clean(payload.get("role"), 120),
            "use_case": clean(payload.get("use_case"), 300),
            "data_format": clean(payload.get("data_format"), 160),
            "monthly_volume": clean(payload.get("monthly_volume"), 160),
            "pilot_goal": clean(payload.get("pilot_goal"), 2000),
        }
        missing = [key for key, value in fields.items() if not value]
        if missing:
            return error_response(f"缺少字段：{', '.join(missing)}", 400, "missing_fields")
        application_id = str(uuid.uuid4())
        execute(
            "INSERT INTO api_access_applications (id,user_id,role,use_case,data_format,monthly_volume,pilot_goal) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (application_id, g.user["id"], fields["role"], fields["use_case"], fields["data_format"], fields["monthly_volume"], fields["pilot_goal"]),
        )
        audit(g.user["id"], "api_access.applied", "api_access_application", application_id, fields)
        return jsonify({"ok": True, "application": serialize_application(fetch_one("SELECT * FROM api_access_applications WHERE id=%s", (application_id,)))}), 201

    @app.post("/api/api-keys")
    @require_user
    def create_api_key_route():
        if not is_pro(g.user):
            return error_response("创建 API 密钥需要有效 Pro 会员", 402, "pro_required")
        application = latest_application(g.user["id"])
        if not application or application["status"] != "approved":
            return error_response("API 申请批准后才能创建密钥", 403, "api_access_not_approved")
        label = clean(json_payload().get("label"), 120) or "Default key"
        raw, prefix, key_hash = new_api_key()
        key_id = str(uuid.uuid4())
        execute(
            "INSERT INTO api_keys (id,user_id,label,key_prefix,key_hash,scopes) VALUES (%s,%s,%s,%s,%s,%s)",
            (key_id, g.user["id"], label, prefix, key_hash, json.dumps(["generate", "runs:read"])),
        )
        audit(g.user["id"], "api_key.created", "api_key", key_id, {"label": label, "prefix": prefix})
        return jsonify({"ok": True, "api_key": raw, "key": serialize_api_key(fetch_one("SELECT * FROM api_keys WHERE id=%s", (key_id,)))}), 201

    @app.get("/api/billing")
    @require_user
    def billing():
        orders = fetch_all("SELECT * FROM payment_orders WHERE user_id=%s ORDER BY created_at DESC LIMIT 30", (g.user["id"],))
        invoices = fetch_all("SELECT * FROM invoice_requests WHERE user_id=%s ORDER BY requested_at DESC LIMIT 30", (g.user["id"],))
        refunds = fetch_all("SELECT * FROM refund_requests WHERE user_id=%s ORDER BY requested_at DESC LIMIT 30", (g.user["id"],))
        mode = payment_mode()
        return jsonify({
            "ok": True,
            "plan": {"code": "pro_monthly", "name": "Q-Tail Pro 月度计划", "price_cents": PRO_PRICE_CENTS, "currency": "CNY", "duration_days": 30},
            "orders": [serialize_order(item) for item in orders],
            "invoice_requests": [serialize_invoice_request(item) for item in invoices],
            "refund_requests": [serialize_refund_request(item) for item in refunds],
            "payment_mode": mode,
            "payment_channels": {channel: channel_configuration(channel) for channel in sorted(CHANNEL_LABELS)},
        })

    @app.post("/api/payment-orders")
    @require_user
    def create_payment_order():
        payload = json_payload()
        channel = payload.get("channel")
        if channel not in CHANNEL_LABELS:
            return error_response("支付渠道无效", 400, "invalid_channel")
        try:
            mode = payment_mode()
            if mode == "official_merchant":
                require_channel_configuration(channel)
        except PaymentConfigurationError:
            return error_response("官方商户支付尚未完成安全配置", 503, "merchant_payment_not_configured")
        existing = fetch_one("SELECT * FROM payment_orders WHERE user_id=%s AND status IN ('pending','under_review') ORDER BY created_at DESC LIMIT 1", (g.user["id"],))
        if existing:
            if existing["payment_mode"] != "official_merchant" or existing.get("checkout_url"):
                return jsonify({"ok": True, "order": serialize_order(existing), "reused": True})
            try:
                checkout = create_checkout(existing["channel"], existing["merchant_order_no"], int(existing["amount_cents"]), "Q-Tail Pro 月度计划")
            except (PaymentConfigurationError, PaymentProviderError, PaymentVerificationError):
                return error_response("支付渠道暂时无法创建安全收银台，请稍后重试", 502, "provider_checkout_unavailable", {"order": serialize_order(existing)})
            execute("UPDATE payment_orders SET checkout_url=%s,review_note=NULL WHERE id=%s", (checkout.checkout_url, existing["id"]))
            return jsonify({"ok": True, "order": serialize_order(fetch_one("SELECT * FROM payment_orders WHERE id=%s", (existing["id"],))), "reused": True})
        order_id = str(uuid.uuid4())
        merchant_order_no = "QT" + uuid.uuid4().hex[:30]
        execute(
            "INSERT INTO payment_orders (id,merchant_order_no,user_id,plan_code,channel,payment_mode,amount_cents) VALUES (%s,%s,%s,'pro_monthly',%s,%s,%s)",
            (order_id, merchant_order_no, g.user["id"], channel, mode, PRO_PRICE_CENTS),
        )
        audit(g.user["id"], "payment_order.created", "payment_order", order_id, {"channel": channel, "amount_cents": PRO_PRICE_CENTS, "payment_mode": mode, "merchant_order_no": merchant_order_no})
        if mode == "official_merchant":
            try:
                checkout = create_checkout(channel, merchant_order_no, PRO_PRICE_CENTS, "Q-Tail Pro 月度计划")
                execute("UPDATE payment_orders SET checkout_url=%s WHERE id=%s", (checkout.checkout_url, order_id))
            except (PaymentConfigurationError, PaymentProviderError, PaymentVerificationError):
                execute("UPDATE payment_orders SET review_note='Official checkout creation failed; safe to retry' WHERE id=%s", (order_id,))
                order = fetch_one("SELECT * FROM payment_orders WHERE id=%s", (order_id,))
                return error_response("支付渠道暂时无法创建安全收银台，请稍后重试", 502, "provider_checkout_unavailable", {"order": serialize_order(order)})
        return jsonify({"ok": True, "order": serialize_order(fetch_one("SELECT * FROM payment_orders WHERE id=%s", (order_id,)))}), 201

    @app.post("/api/payment-orders/<order_id>/submit")
    @require_user
    def submit_payment_order(order_id: str):
        reference = clean(json_payload().get("payment_reference"), 255)
        if len(reference) < 4:
            return error_response("请填写付款备注或交易单号", 400, "missing_payment_reference")
        order = fetch_one("SELECT * FROM payment_orders WHERE id=%s AND user_id=%s", (order_id, g.user["id"]))
        if not order:
            return error_response("订单不存在", 404, "order_not_found")
        if order.get("payment_mode") != "manual_qr_verification":
            return error_response("官方商户订单由验签回调自动确认，不接受人工交易参考号", 409, "official_payment_reference_forbidden")
        if order["status"] not in {"pending", "under_review"}:
            return error_response("当前订单状态不可提交", 409, "invalid_order_state")
        execute("UPDATE payment_orders SET status='under_review',payment_reference=%s,submitted_at=UTC_TIMESTAMP() WHERE id=%s", (reference, order_id))
        audit(g.user["id"], "payment_order.submitted", "payment_order", order_id, {"reference": reference})
        return jsonify({"ok": True, "order": serialize_order(fetch_one("SELECT * FROM payment_orders WHERE id=%s", (order_id,)))})

    @app.post("/api/payment-orders/<order_id>/invoice-requests")
    @require_user
    def create_invoice_request(order_id: str):
        order = fetch_one("SELECT * FROM payment_orders WHERE id=%s AND user_id=%s", (order_id, g.user["id"]))
        if not order:
            return error_response("订单不存在", 404, "order_not_found")
        if order["status"] != "paid":
            return error_response("只有已核验到账且未退款的订单可以申请发票", 409, "order_not_invoice_eligible")
        existing = fetch_one("SELECT * FROM invoice_requests WHERE order_id=%s AND status IN ('requested','issued') ORDER BY requested_at DESC LIMIT 1", (order_id,))
        if existing:
            return error_response("该订单已有处理中或已开具的发票记录", 409, "invoice_request_exists")
        payload = json_payload()
        title = clean(payload.get("invoice_title"), 190)
        taxpayer_id = clean(payload.get("taxpayer_id"), 32).upper()
        email = clean(payload.get("invoice_email"), 190).lower()
        if len(title) < 2:
            return error_response("请填写准确的发票抬头", 400, "invalid_invoice_title")
        if not re.fullmatch(r"[A-Z0-9]{15,20}", taxpayer_id):
            return error_response("纳税人识别号应为 15–20 位字母或数字", 400, "invalid_taxpayer_id")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return error_response("请填写有效的收票邮箱", 400, "invalid_invoice_email")
        request_id = str(uuid.uuid4())
        execute(
            "INSERT INTO invoice_requests (id,order_id,user_id,invoice_title,taxpayer_id,invoice_email) VALUES (%s,%s,%s,%s,%s,%s)",
            (request_id, order_id, g.user["id"], title, taxpayer_id, email),
        )
        audit(g.user["id"], "invoice_request.created", "invoice_request", request_id, {"order_id": order_id, "invoice_title": title})
        return jsonify({"ok": True, "invoice_request": serialize_invoice_request(fetch_one("SELECT * FROM invoice_requests WHERE id=%s", (request_id,)))}), 201

    @app.post("/api/payment-orders/<order_id>/refund-requests")
    @require_user
    def create_refund_request(order_id: str):
        order = fetch_one("SELECT * FROM payment_orders WHERE id=%s AND user_id=%s", (order_id, g.user["id"]))
        if not order:
            return error_response("订单不存在", 404, "order_not_found")
        if order["status"] != "paid":
            return error_response("只有已核验到账且未退款的订单可以申请退款", 409, "order_not_refund_eligible")
        if fetch_one("SELECT id FROM refund_requests WHERE order_id=%s", (order_id,)):
            return error_response("该订单已有退款申请", 409, "refund_request_exists")
        reason = clean(json_payload().get("reason"), 2000)
        if len(reason) < 8:
            return error_response("请填写至少 8 个字符的退款原因", 400, "refund_reason_too_short")
        request_id = str(uuid.uuid4())
        merchant_refund_no = "RF" + uuid.uuid4().hex[:30]
        execute(
            "INSERT INTO refund_requests (id,merchant_refund_no,order_id,user_id,amount_cents,reason) VALUES (%s,%s,%s,%s,%s,%s)",
            (request_id, merchant_refund_no, order_id, g.user["id"], order["amount_cents"], reason),
        )
        audit(g.user["id"], "refund_request.created", "refund_request", request_id, {"order_id": order_id, "amount_cents": order["amount_cents"]})
        return jsonify({"ok": True, "refund_request": serialize_refund_request(fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,)))}), 201

    @app.get("/api/generations")
    @require_user_or_api_key
    def list_generations():
        rows = fetch_all("SELECT * FROM generation_jobs WHERE user_id=%s ORDER BY created_at DESC LIMIT 100", (g.user["id"],))
        return jsonify({"ok": True, "jobs": [serialize_job(row) for row in rows]})

    @app.get("/api/catalogs")
    @require_user_or_api_key
    def list_synthetic_catalogs():
        if not is_pro(g.user):
            return error_response("合成轨迹目录需要有效 Pro 会员", 402, "pro_required")
        return jsonify({"ok": True, "catalogs": [serialize_synthetic_catalog(item) for item in SYNTHETIC_CATALOGS]})

    @app.get("/api/catalogs/<slug>/download")
    @require_user_or_api_key
    def download_synthetic_catalog(slug: str):
        if not is_pro(g.user):
            return error_response("下载合成轨迹样包需要有效 Pro 会员", 402, "pro_required")
        catalog = next((item for item in SYNTHETIC_CATALOGS if item["slug"] == slug), None)
        if not catalog:
            return error_response("合成轨迹样包不存在", 404, "catalog_not_found")
        status = synthetic_catalog_file_status(catalog)
        if not status["available"]:
            return error_response("合成轨迹样包暂不可用，完整性检查未通过", 503, "catalog_unavailable", {"integrity_status": status["integrity_status"]})
        audit(
            g.user["id"], "synthetic_catalog.downloaded", "synthetic_catalog", slug,
            {"sha256": catalog["sha256"], "bytes": catalog["bytes"], "evidence_scope": catalog["evidence_scope"], "auth_type": getattr(g, "auth_type", "unknown")},
        )
        if getattr(g, "api_key_id", None):
            execute("UPDATE api_keys SET last_used_at=UTC_TIMESTAMP() WHERE id=%s", (g.api_key_id,))
        response = send_file(
            status["path"], as_attachment=True, download_name=catalog["filename"],
            mimetype="application/gzip", etag=catalog["sha256"], conditional=True,
        )
        response.headers["X-Content-SHA256"] = catalog["sha256"]
        response.headers["X-QTail-Evidence-Scope"] = catalog["evidence_scope"]
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get("/api/generations/<job_id>")
    @require_user_or_api_key
    def get_generation(job_id: str):
        job = fetch_one("SELECT * FROM generation_jobs WHERE id=%s AND user_id=%s", (job_id, g.user["id"]))
        if not job:
            return error_response("生成任务不存在", 404, "generation_not_found")
        return jsonify({"ok": True, **serialize_job(job)})

    @app.post("/api/generations/<job_id>/deletion-request")
    @require_user
    def request_generation_deletion(job_id: str):
        job = fetch_one("SELECT * FROM generation_jobs WHERE id=%s AND user_id=%s", (job_id, g.user["id"]))
        if not job:
            return error_response("生成任务不存在", 404, "generation_not_found")
        if job["status"] not in {"completed", "failed"}:
            return error_response("只能删除已完成或已失败任务的输入与交付载荷", 409, "generation_not_terminal")
        reason = clean(json_payload().get("reason"), 2000)
        if len(reason) < 8:
            return error_response("请填写至少 8 个字符的删除原因", 400, "deletion_reason_too_short")
        compliance = fetch_one("SELECT deletion_sla_days FROM buyer_compliance_profiles WHERE user_id=%s", (g.user["id"],))
        deletion_sla_days = int(compliance["deletion_sla_days"] if compliance else 30)
        due_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=deletion_sla_days)
        request_id = str(uuid.uuid4())
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM data_deletion_requests WHERE generation_job_id=%s FOR UPDATE", (job_id,))
                existing = cursor.fetchone()
                if existing and existing["status"] == "completed":
                    return error_response("该任务载荷已删除", 409, "payload_already_deleted", {"deletion_sha256": existing["deletion_sha256"]})
                if existing and existing["status"] in {"requested", "processing"}:
                    return jsonify({"ok": True, "deletion_request": serialize_deletion_request(existing), "reused": True})
                if existing:
                    request_id = existing["id"]
                    cursor.execute(
                        "UPDATE data_deletion_requests SET request_source='buyer',reason=%s,status='requested',due_at=%s,"
                        "deletion_manifest=NULL,deletion_sha256=NULL,files_deleted=0,bytes_deleted=0,review_note=NULL,"
                        "requested_at=UTC_TIMESTAMP(),reviewed_at=NULL,completed_at=NULL WHERE id=%s",
                        (reason, due_at, request_id),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO data_deletion_requests (id,generation_job_id,user_id,request_source,reason,due_at) "
                        "VALUES (%s,%s,%s,'buyer',%s,%s)",
                        (request_id, job_id, g.user["id"], reason, due_at),
                    )
                cursor.execute(
                    "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) "
                    "VALUES (%s,'data_deletion.requested','data_deletion_request',%s,%s)",
                    (g.user["id"], request_id, json.dumps({"generation_job_id": job_id, "due_at": due_at.isoformat()}, ensure_ascii=False)),
                )
        row = fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,))
        return jsonify({"ok": True, "deletion_request": serialize_deletion_request(row)}), 201

    @app.post("/api/generations")
    @require_user_or_api_key
    def create_generation():
        if not is_pro(g.user):
            return error_response("生成任务需要有效 Pro 会员", 402, "pro_required")
        payload = json_payload()
        delivery_product = clean(payload.get("delivery_product") or "allocation_plan", 64)
        if delivery_product not in DELIVERY_PRODUCTS:
            return error_response("交付产品无效", 400, "invalid_delivery_product")
        trajectory_request = None
        if delivery_product == TRAJECTORY_DELIVERY_PRODUCT:
            try:
                trajectory_request = validate_trajectory_request(payload)
            except ValueError as exc:
                return error_response(str(exc), 422, "trajectory_contract_invalid")
        try:
            data_rights = normalize_data_rights_attestation(payload.get("data_rights"))
        except ValueError as exc:
            return error_response(str(exc), 422, "data_rights_attestation_required")
        csv_text = str(payload.get("csv_text") or "")
        if len(csv_text.encode("utf-8")) > 10 * 1024 * 1024:
            return error_response("CSV 最大 10 MiB", 413, "csv_too_large")
        gate_evaluation = evaluate_request(payload)
        if not gate_evaluation["request_allowed"]:
            return error_response("任务未通过 Gate 0/1 输入契约检查", 422, "gate_validation_failed", {"gates": gate_evaluation})
        try:
            synthetic_budget = int(payload.get("synthetic_budget") or 100000)
            control_frequency_hz = float(payload.get("control_frequency_hz"))
        except (TypeError, ValueError):
            return error_response("控制频率与合成预算必须是数值", 400, "invalid_numeric_field")
        if synthetic_budget < 100 or synthetic_budget > 10_000_000:
            return error_response("合成预算范围为 100–10,000,000", 400, "invalid_budget")
        if control_frequency_hz < 1 or control_frequency_hz > 1000:
            return error_response("控制频率范围为 1–1000 Hz", 400, "invalid_control_frequency")
        filename = safe_filename(payload.get("filename"))
        job_id = str(uuid.uuid4())
        input_sha256 = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        api_key_id = getattr(g, "api_key_id", None)
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        input_path = job_dir / filename
        try:
            input_path.write_text(csv_text, encoding="utf-8")
            rights_canonical = json.dumps(data_rights, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            rights_sha256 = hashlib.sha256(rights_canonical.encode("utf-8")).hexdigest()
            event_json = json.dumps({
                "input_sha256": input_sha256,
                "gate_evaluation": gate_evaluation,
                "data_rights_sha256": rights_sha256,
                "delivery_product": delivery_product,
                "trajectory_request": trajectory_request,
            }, ensure_ascii=False, default=str)
            with transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO api_usage_daily (user_id,usage_date,generation_count) VALUES (%s,UTC_DATE(),0) "
                        "ON DUPLICATE KEY UPDATE generation_count=generation_count",
                        (g.user["id"],),
                    )
                    cursor.execute(
                        "SELECT generation_count FROM api_usage_daily WHERE user_id=%s AND usage_date=UTC_DATE() FOR UPDATE",
                        (g.user["id"],),
                    )
                    usage = cursor.fetchone()
                    if int(usage["generation_count"]) >= PRO_DAILY_GENERATION_LIMIT:
                        raise DailyQuotaExceeded()
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM generation_jobs WHERE user_id=%s AND status IN ('queued','running')",
                        (g.user["id"],),
                    )
                    if int(cursor.fetchone()["count"]) >= MAX_ACTIVE_GENERATIONS_PER_USER:
                        raise ActiveQueueLimitExceeded()
                    cursor.execute(
                        "INSERT INTO generation_jobs (id,user_id,api_key_id,filename,robot_model,control_frequency_hz,sensors,training_format,production_backend,synthetic_budget,delivery_product,trajectory_count,status,gate_evaluation,input_sha256,input_path,max_attempts) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s)",
                        (job_id, g.user["id"], api_key_id, filename, clean(payload.get("robot_model"), 160), control_frequency_hz, clean(payload.get("sensors"), 255), clean(payload.get("training_format"), 120), clean(payload.get("production_backend"), 160), synthetic_budget, delivery_product, trajectory_request["trajectory_count"] if trajectory_request else None, json.dumps(gate_evaluation, ensure_ascii=False), input_sha256, str(input_path.resolve()), GENERATION_MAX_ATTEMPTS),
                    )
                    cursor.execute(
                        "INSERT INTO generation_data_rights (generation_job_id,user_id,source_type,license_basis,contains_personal_data,retention_days,source_rights_confirmed,derivative_rights_confirmed,restricted_data_excluded,attestation_version,attestation_sha256) "
                        "VALUES (%s,%s,%s,%s,FALSE,%s,TRUE,TRUE,TRUE,%s,%s)",
                        (job_id, g.user["id"], data_rights["source_type"], data_rights["license_basis"], data_rights["retention_days"], DATA_RIGHTS_ATTESTATION_VERSION, rights_sha256),
                    )
                    cursor.execute(
                        "UPDATE api_usage_daily SET generation_count=generation_count+1 WHERE user_id=%s AND usage_date=UTC_DATE()",
                        (g.user["id"],),
                    )
                    if api_key_id:
                        cursor.execute("UPDATE api_keys SET last_used_at=UTC_TIMESTAMP() WHERE id=%s", (api_key_id,))
                    cursor.execute(
                        "INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) "
                        "VALUES (%s,'generation.queued','generation_job',%s,%s)",
                        (g.user["id"], job_id, event_json),
                    )
        except DailyQuotaExceeded:
            shutil.rmtree(job_dir, ignore_errors=True)
            return error_response("今日生成配额已用完", 429, "daily_quota_exceeded")
        except ActiveQueueLimitExceeded:
            shutil.rmtree(job_dir, ignore_errors=True)
            return error_response("当前排队或运行任务过多，请等待已有任务完成", 429, "active_queue_limit_exceeded")
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        job = fetch_one("SELECT * FROM generation_jobs WHERE id=%s", (job_id,))
        response = serialize_job(job)
        response.update({"ok": True, "job_id": job_id, "gate_evaluation": gate_evaluation})
        result = jsonify(response)
        result.headers["Location"] = f"/api/generations/{job_id}"
        return result, 202

    @app.get("/downloads/<job_id>")
    @require_user_or_api_key
    def download_job(job_id: str):
        job = fetch_one("SELECT * FROM generation_jobs WHERE id=%s AND user_id=%s", (job_id, g.user["id"]))
        deleted = fetch_one(
            "SELECT deletion_sha256,completed_at FROM data_deletion_requests WHERE generation_job_id=%s AND status='completed'",
            (job_id,),
        )
        if job and deleted:
            return error_response("任务输入与交付载荷已按删除流程移除", 410, "payload_deleted", {"deletion_sha256": deleted["deletion_sha256"], "completed_at": iso(deleted["completed_at"])})
        if not job or job["status"] != "completed" or not job["output_path"]:
            return error_response("交付包不存在", 404, "package_not_found")
        path = Path(job["output_path"]).resolve()
        if not path.is_relative_to(JOBS_DIR) or not path.exists():
            return error_response("交付包不可用", 404, "package_unavailable")
        return send_file(path, as_attachment=True, download_name=f"qtail-{job_id[:8]}-delivery.zip")

    @app.get("/api/procurement-cases")
    @require_user
    def list_procurement_cases():
        rows = fetch_all("SELECT * FROM procurement_cases WHERE user_id=%s ORDER BY created_at DESC", (g.user["id"],))
        completed_jobs = fetch_all(
            "SELECT j.id,j.filename,j.robot_model,j.training_format,j.delivery_product,j.trajectory_count,j.created_at FROM generation_jobs j WHERE j.user_id=%s AND j.status='completed' "
            "AND NOT EXISTS (SELECT 1 FROM data_deletion_requests d WHERE d.generation_job_id=j.id AND d.status='completed') ORDER BY j.created_at DESC LIMIT 100",
            (g.user["id"],),
        )
        return jsonify({
            "ok": True,
            "cases": [serialize_procurement_case(row) for row in rows],
            "eligible_jobs": [{"id": row["id"], "filename": row["filename"], "robot_model": row["robot_model"], "training_format": row["training_format"], "delivery_product": row["delivery_product"], "trajectory_count": row["trajectory_count"], "created_at": iso(row["created_at"])} for row in completed_jobs],
            "gate_definitions": GATE_DEFINITIONS,
        })

    @app.post("/api/procurement-cases")
    @require_user
    def create_procurement_case():
        if not is_pro(g.user):
            return error_response("创建采购验证项目需要有效 Pro 会员", 402, "pro_required")
        payload = json_payload()
        generation_job_id = clean(payload.get("generation_job_id"), 36)
        title = clean(payload.get("title"), 190)
        buyer_owner = clean(payload.get("buyer_owner"), 190)
        pilot_scope = clean(payload.get("pilot_scope"), 4000)
        if not all((generation_job_id, title, buyer_owner, pilot_scope)):
            return error_response("任务、项目名称、买方负责人和试点范围不能为空", 400, "missing_fields")
        job = fetch_one(
            "SELECT j.* FROM generation_jobs j WHERE j.id=%s AND j.user_id=%s AND j.status='completed' "
            "AND NOT EXISTS (SELECT 1 FROM data_deletion_requests d WHERE d.generation_job_id=j.id AND d.status='completed')",
            (generation_job_id, g.user["id"]),
        )
        if not job:
            return error_response("只能从本人已完成的生成任务创建采购验证项目", 404, "generation_job_not_eligible")
        job_gates = parse_json(job.get("gate_evaluation")) or {}
        if job_gates.get("gate0", {}).get("status") != "passed":
            return error_response("生成任务尚未通过 Gate 0", 422, "gate0_not_passed")
        case_id = str(uuid.uuid4())
        try:
            execute(
                "INSERT INTO procurement_cases (id,user_id,generation_job_id,title,buyer_owner,pilot_scope) VALUES (%s,%s,%s,%s,%s,%s)",
                (case_id, g.user["id"], generation_job_id, title, buyer_owner, pilot_scope),
            )
        except pymysql.err.IntegrityError:
            return error_response("该生成任务已建立采购验证项目", 409, "procurement_case_exists")
        audit(g.user["id"], "procurement_case.created", "procurement_case", case_id, {"generation_job_id": generation_job_id, "title": title})
        row = fetch_one("SELECT * FROM procurement_cases WHERE id=%s", (case_id,))
        return jsonify({"ok": True, "case": serialize_procurement_case(row)}), 201

    @app.post("/api/procurement-cases/<case_id>/gates/<int:gate_number>/evidence")
    @require_user
    def submit_procurement_evidence(case_id: str, gate_number: int):
        if not is_pro(g.user):
            return error_response("提交采购证据需要有效 Pro 会员", 402, "pro_required")
        if gate_number not in {1, 2, 3}:
            return error_response("Gate 编号必须为 1–3", 400, "invalid_gate_number")
        case = fetch_one("SELECT * FROM procurement_cases WHERE id=%s AND user_id=%s", (case_id, g.user["id"]))
        if not case:
            return error_response("采购验证项目不存在", 404, "procurement_case_not_found")
        if case["status"] in {"contracted", "closed"}:
            return error_response("当前项目状态不可继续提交证据", 409, "procurement_case_closed")
        payload = normalize_evidence_payload(gate_number, json_payload())
        evidence_scope = payload["evidence_scope"]
        approved = latest_approved_gate(case_id, gate_number)
        if approved and (bool(approved.get("contract_eligible")) or evidence_scope != "buyer_external"):
            return error_response(f"Gate {gate_number} 已审核通过；只有补交买方外部证据时才能再次提交", 409, "gate_already_approved")
        if gate_number > 1:
            previous = latest_contract_eligible_gate(case_id, gate_number - 1) if evidence_scope == "buyer_external" else latest_approved_gate(case_id, gate_number - 1)
            if previous is None:
                code = "previous_gate_external_evidence_required" if evidence_scope == "buyer_external" else "previous_gate_not_approved"
                return error_response(
                    f"Gate {gate_number - 1} {'买方外部证据' if evidence_scope == 'buyer_external' else '证据'}经运营审核通过后才能提交 Gate {gate_number}",
                    409,
                    code,
                )
        evaluation = evaluate_gate_evidence(gate_number, payload)
        if evaluation["status"] != "passed":
            return error_response("证据尚未满足自动阈值检查", 422, "gate_thresholds_not_met", {"evaluation": evaluation})
        evidence_canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence_id = str(uuid.uuid4())
        evidence_sha256 = hashlib.sha256(evidence_canonical.encode("utf-8")).hexdigest()
        execute(
            "INSERT INTO procurement_gate_evidence (id,case_id,user_id,gate_number,evidence_json,evidence_sha256,evidence_scope,contract_eligible,automated_status,automated_findings) VALUES (%s,%s,%s,%s,%s,%s,%s,FALSE,'passed',%s)",
            (evidence_id, case_id, g.user["id"], gate_number, evidence_canonical, evidence_sha256, evidence_scope, json.dumps(evaluation, ensure_ascii=False)),
        )
        audit(g.user["id"], "procurement_evidence.submitted", "procurement_gate_evidence", evidence_id, {"case_id": case_id, "gate_number": gate_number, "evidence_sha256": evidence_sha256, "evidence_scope": evidence_scope})
        return jsonify({"ok": True, "evidence": serialize_procurement_evidence(fetch_one("SELECT * FROM procurement_gate_evidence WHERE id=%s", (evidence_id,))), "evaluation": evaluation}), 201

    @app.post("/api/admin/procurement-evidence/<evidence_id>/approve")
    @require_admin
    def admin_approve_procurement_evidence(evidence_id: str):
        evidence = fetch_one("SELECT * FROM procurement_gate_evidence WHERE id=%s", (evidence_id,))
        if not evidence:
            return error_response("采购证据不存在", 404, "procurement_evidence_not_found")
        if evidence["status"] != "received":
            return error_response("只有待审核证据可以批准", 409, "invalid_evidence_state")
        if evidence["automated_status"] != "passed":
            return error_response("自动阈值未通过的证据不可批准", 422, "automated_check_failed")
        external = evidence.get("evidence_scope") == "buyer_external"
        previous = latest_contract_eligible_gate(evidence["case_id"], evidence["gate_number"] - 1) if external and evidence["gate_number"] > 1 else latest_approved_gate(evidence["case_id"], evidence["gate_number"] - 1) if evidence["gate_number"] > 1 else True
        if evidence["gate_number"] > 1 and previous is None:
            code = "previous_gate_external_evidence_required" if external else "previous_gate_not_approved"
            return error_response("前一道 Gate 尚未通过相同证据级别的运营审核", 409, code)
        payload = json_payload()
        note = clean(payload.get("review_note"), 2000) or "Procurement evidence approved"
        verification_reference = None
        reviewer_name = None
        review_attestation_sha256 = None
        contract_eligible = False
        if external:
            verification_reference = clean(payload.get("verification_reference"), 255)
            reviewer_name = clean(payload.get("reviewer_name"), 190)
            if len(verification_reference) < 8 or len(reviewer_name) < 2 or len(note) < 8:
                return error_response("批准买方外部证据必须填写核验引用、审核人和具体审核说明", 400, "external_evidence_verification_required")
            review_attestation = json.dumps({
                "evidence_sha256": evidence["evidence_sha256"],
                "evidence_scope": evidence["evidence_scope"],
                "verification_reference": verification_reference,
                "reviewer_name": reviewer_name,
                "review_note": note,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            review_attestation_sha256 = hashlib.sha256(review_attestation.encode("utf-8")).hexdigest()
            contract_eligible = True
        execute(
            "UPDATE procurement_gate_evidence SET status='approved',contract_eligible=%s,reviewed_at=UTC_TIMESTAMP(),review_note=%s,verification_reference=%s,reviewer_name=%s,review_attestation_sha256=%s WHERE id=%s",
            (contract_eligible, note, verification_reference, reviewer_name, review_attestation_sha256, evidence_id),
        )
        if evidence["gate_number"] == 3 and procurement_case_all_gates_contract_eligible(evidence["case_id"]):
            case = fetch_one("SELECT user_id FROM procurement_cases WHERE id=%s", (evidence["case_id"],))
            if case and contract_compliance_state(case["user_id"])["ready"]:
                execute("UPDATE procurement_cases SET status='contract_ready' WHERE id=%s", (evidence["case_id"],))
        audit(None, "procurement_evidence.approved", "procurement_gate_evidence", evidence_id, {"case_id": evidence["case_id"], "gate_number": evidence["gate_number"], "evidence_scope": evidence.get("evidence_scope"), "contract_eligible": contract_eligible, "verification_reference": verification_reference, "review_attestation_sha256": review_attestation_sha256})
        return jsonify({"ok": True, "evidence": serialize_procurement_evidence(fetch_one("SELECT * FROM procurement_gate_evidence WHERE id=%s", (evidence_id,)))})

    @app.post("/api/admin/procurement-evidence/<evidence_id>/reject")
    @require_admin
    def admin_reject_procurement_evidence(evidence_id: str):
        evidence = fetch_one("SELECT * FROM procurement_gate_evidence WHERE id=%s", (evidence_id,))
        if not evidence:
            return error_response("采购证据不存在", 404, "procurement_evidence_not_found")
        if evidence["status"] != "received":
            return error_response("只有待审核证据可以拒绝", 409, "invalid_evidence_state")
        note = clean(json_payload().get("review_note"), 2000) or "Procurement evidence rejected"
        execute("UPDATE procurement_gate_evidence SET status='rejected',reviewed_at=UTC_TIMESTAMP(),review_note=%s WHERE id=%s", (note, evidence_id))
        audit(None, "procurement_evidence.rejected", "procurement_gate_evidence", evidence_id, {"case_id": evidence["case_id"], "gate_number": evidence["gate_number"], "review_note": note})
        return jsonify({"ok": True})

    @app.post("/api/admin/procurement-cases/<case_id>/issue-contract")
    @require_admin
    def admin_issue_procurement_contract(case_id: str):
        case = fetch_one("SELECT * FROM procurement_cases WHERE id=%s", (case_id,))
        if not case:
            return error_response("采购验证项目不存在", 404, "procurement_case_not_found")
        if not procurement_case_all_gates_approved(case_id):
            return error_response("Gate 1–3 全部批准后才能生成合同就绪记录", 409, "gates_not_approved")
        missing_external_gates = procurement_case_missing_contract_evidence(case_id)
        if missing_external_gates:
            return error_response(
                "模拟或公共基准证据只能记录技术进度；Gate 1–3 均需经运营核验的买方外部证据才能生成合同",
                409,
                "external_evidence_required",
                {"missing_gates": missing_external_gates},
            )
        compliance = contract_compliance_state(case["user_id"])
        if not compliance["ready"]:
            return error_response("数据权利、DPA 和安全边界资料经审核后才能生成合同", 409, "compliance_not_approved", {"profile": compliance["profile"], "missing_documents": compliance["missing_documents"]})
        job_rights = fetch_one("SELECT attestation_sha256 FROM generation_data_rights WHERE generation_job_id=%s", (case["generation_job_id"],))
        if not job_rights:
            return error_response("来源生成任务缺少版本化数据权利声明", 409, "generation_data_rights_missing")
        existing = fetch_one("SELECT * FROM procurement_contracts WHERE case_id=%s AND status IN ('ready','signed') ORDER BY version DESC LIMIT 1", (case_id,))
        if existing:
            return jsonify({"ok": True, "contract": serialize_procurement_contract(existing), "reused": True})
        snapshot = procurement_acceptance_snapshot(case_id)
        version_row = fetch_one("SELECT COALESCE(MAX(version),0)+1 AS version FROM procurement_contracts WHERE case_id=%s", (case_id,))
        contract_id = str(uuid.uuid4())
        execute(
            "INSERT INTO procurement_contracts (id,case_id,user_id,version,acceptance_snapshot) VALUES (%s,%s,%s,%s,%s)",
            (contract_id, case_id, case["user_id"], version_row["version"], json.dumps(snapshot, ensure_ascii=False)),
        )
        execute("UPDATE procurement_cases SET status='contract_ready' WHERE id=%s", (case_id,))
        audit(None, "procurement_contract.issued", "procurement_contract", contract_id, {"case_id": case_id, "version": version_row["version"]})
        return jsonify({"ok": True, "contract": serialize_procurement_contract(fetch_one("SELECT * FROM procurement_contracts WHERE id=%s", (contract_id,)))}), 201

    @app.get("/api/procurement-contracts/<contract_id>/draft")
    @require_user
    def download_procurement_contract_draft(contract_id: str):
        contract = fetch_one("SELECT * FROM procurement_contracts WHERE id=%s AND user_id=%s", (contract_id, g.user["id"]))
        if not contract:
            return error_response("采购合同草案不存在", 404, "procurement_contract_not_found")
        case = fetch_one("SELECT * FROM procurement_cases WHERE id=%s AND user_id=%s", (contract["case_id"], g.user["id"]))
        job = fetch_one("SELECT * FROM generation_jobs WHERE id=%s AND user_id=%s", (case["generation_job_id"], g.user["id"])) if case else None
        draft = render_procurement_contract_draft(contract, case, job, g.user)
        response = Response(draft, content_type="text/markdown; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="qtail-procurement-draft-v{int(contract["version"])}.md"'
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/api/admin/procurement-contracts/<contract_id>/mark-signed")
    @require_admin
    def admin_mark_procurement_contract_signed(contract_id: str):
        contract = fetch_one("SELECT * FROM procurement_contracts WHERE id=%s", (contract_id,))
        if not contract:
            return error_response("采购合同记录不存在", 404, "procurement_contract_not_found")
        payload = json_payload()
        reference = clean(payload.get("contract_reference"), 255)
        if len(reference) < 4:
            return error_response("必须填写外部签署合同编号或存档引用", 400, "contract_reference_required")
        if contract["status"] != "ready":
            return error_response("只有待签署合同可以标记为已签署", 409, "invalid_contract_state")
        snapshot = parse_json(contract["acceptance_snapshot"]) or {}
        if not contract_snapshot_is_contract_eligible(contract):
            return error_response("旧版或模拟验收快照不能标记为真实签署合同", 409, "external_evidence_required")
        executed_document_sha256 = clean(payload.get("executed_document_sha256"), 64).lower()
        provider_signatory = clean(payload.get("provider_signatory"), 190)
        provider_signature_sha256 = clean(payload.get("provider_signature_sha256"), 64).lower()
        buyer_signatory = clean(payload.get("buyer_signatory"), 190)
        buyer_signature_sha256 = clean(payload.get("buyer_signature_sha256"), 64).lower()
        effective_date_text = clean(payload.get("effective_date"), 10)
        try:
            effective_date = date.fromisoformat(effective_date_text)
        except ValueError:
            effective_date = None
        if (
            not is_sha256(executed_document_sha256)
            or len(provider_signatory) < 2
            or not is_sha256(provider_signature_sha256)
            or len(buyer_signatory) < 2
            or not is_sha256(buyer_signature_sha256)
            or not effective_date
        ):
            return error_response(
                "标记已签署必须填写执行合同 SHA-256、双方签署人、双方独立签署凭证 SHA-256 和有效日期",
                400,
                "executed_contract_metadata_required",
            )
        if hmac.compare_digest(provider_signature_sha256, buyer_signature_sha256):
            return error_response(
                "服务方与采购方必须分别提供不同的签署凭证 SHA-256",
                400,
                "independent_signature_proofs_required",
            )
        snapshot_canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        execution_attestation = json.dumps({
            "acceptance_snapshot_sha256": hashlib.sha256(snapshot_canonical.encode("utf-8")).hexdigest(),
            "buyer_signatory": buyer_signatory,
            "buyer_signature_sha256": buyer_signature_sha256,
            "contract_reference": reference,
            "effective_date": effective_date.isoformat(),
            "executed_document_sha256": executed_document_sha256,
            "provider_signatory": provider_signatory,
            "provider_signature_sha256": provider_signature_sha256,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        execution_attestation_sha256 = hashlib.sha256(execution_attestation.encode("utf-8")).hexdigest()
        execute(
            "UPDATE procurement_contracts SET status='signed',contract_reference=%s,executed_document_sha256=%s,provider_signatory=%s,provider_signature_sha256=%s,buyer_signatory=%s,buyer_signature_sha256=%s,effective_date=%s,execution_attestation_sha256=%s,signed_at=UTC_TIMESTAMP() WHERE id=%s",
            (reference, executed_document_sha256, provider_signatory, provider_signature_sha256, buyer_signatory, buyer_signature_sha256, effective_date, execution_attestation_sha256, contract_id),
        )
        execute("UPDATE procurement_cases SET status='contracted' WHERE id=%s", (contract["case_id"],))
        audit(None, "procurement_contract.signed", "procurement_contract", contract_id, {"case_id": contract["case_id"], "contract_reference": reference, "executed_document_sha256": executed_document_sha256, "provider_signatory": provider_signatory, "provider_signature_sha256": provider_signature_sha256, "buyer_signatory": buyer_signatory, "buyer_signature_sha256": buyer_signature_sha256, "effective_date": effective_date.isoformat(), "execution_attestation_sha256": execution_attestation_sha256})
        return jsonify({"ok": True, "contract": serialize_procurement_contract(fetch_one("SELECT * FROM procurement_contracts WHERE id=%s", (contract_id,)))})

    @app.post("/api/admin/compliance-profiles/<user_id>/approve")
    @require_admin
    def admin_approve_compliance(user_id: str):
        profile = fetch_one("SELECT * FROM buyer_compliance_profiles WHERE user_id=%s", (user_id,))
        if not profile:
            return error_response("合规资料不存在", 404, "compliance_profile_not_found")
        if profile["status"] != "received":
            return error_response("只有待审核合规资料可以批准", 409, "invalid_compliance_state")
        note = clean(json_payload().get("review_note"), 2000) or "Data rights and security boundary approved"
        execute("UPDATE buyer_compliance_profiles SET status='approved',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE user_id=%s", (note, user_id))
        for case in fetch_all("SELECT id FROM procurement_cases WHERE user_id=%s AND status='active'", (user_id,)):
            if procurement_case_all_gates_contract_eligible(case["id"]):
                execute("UPDATE procurement_cases SET status='contract_ready' WHERE id=%s", (case["id"],))
        audit(None, "compliance.approved", "buyer_compliance_profile", user_id, {"version": int(profile["version"]), "profile_sha256": profile["profile_sha256"]})
        return jsonify({"ok": True, "profile": contract_compliance_state(user_id)["profile"]})

    @app.post("/api/admin/compliance-profiles/<user_id>/reject")
    @require_admin
    def admin_reject_compliance(user_id: str):
        profile = fetch_one("SELECT * FROM buyer_compliance_profiles WHERE user_id=%s", (user_id,))
        if not profile:
            return error_response("合规资料不存在", 404, "compliance_profile_not_found")
        if profile["status"] != "received":
            return error_response("只有待审核合规资料可以拒绝", 409, "invalid_compliance_state")
        note = clean(json_payload().get("review_note"), 2000) or "Data rights or security boundary requires revision"
        execute("UPDATE buyer_compliance_profiles SET status='rejected',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE user_id=%s", (note, user_id))
        audit(None, "compliance.rejected", "buyer_compliance_profile", user_id, {"version": int(profile["version"]), "review_note": note})
        return jsonify({"ok": True, "profile": contract_compliance_state(user_id)["profile"]})

    @app.post("/api/admin/api-access/<application_id>/approve")
    @require_admin
    def admin_approve_application(application_id: str):
        application = fetch_one("SELECT * FROM api_access_applications WHERE id=%s", (application_id,))
        if not application:
            return error_response("申请不存在", 404, "application_not_found")
        execute("UPDATE api_access_applications SET status='approved',reviewed_at=UTC_TIMESTAMP(),review_note=%s WHERE id=%s", (clean(json_payload().get("review_note"), 2000) or "Approved", application_id))
        audit(None, "api_access.approved", "api_access_application", application_id, {})
        return jsonify({"ok": True})

    @app.post("/api/admin/api-access/<application_id>/reject")
    @require_admin
    def admin_reject_application(application_id: str):
        application = fetch_one("SELECT * FROM api_access_applications WHERE id=%s", (application_id,))
        if not application:
            return error_response("申请不存在", 404, "application_not_found")
        note = clean(json_payload().get("review_note"), 2000) or "Rejected by operator"
        execute("UPDATE api_access_applications SET status='rejected',reviewed_at=UTC_TIMESTAMP(),review_note=%s WHERE id=%s", (note, application_id))
        audit(None, "api_access.rejected", "api_access_application", application_id, {"review_note": note})
        return jsonify({"ok": True})

    @app.post("/api/admin/payment-orders/<order_id>/confirm")
    @require_admin
    def admin_confirm_payment(order_id: str):
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM payment_orders WHERE id=%s FOR UPDATE", (order_id,))
                order = cursor.fetchone()
                if not order:
                    return error_response("订单不存在", 404, "order_not_found")
                if order.get("payment_mode") != "manual_qr_verification":
                    return error_response("官方商户订单只能由验签回调确认到账", 409, "official_payment_manual_confirmation_forbidden")
                if order["status"] not in {"under_review", "paid"}:
                    return error_response("只有已提交核验的订单才能确认到账", 409, "payment_not_submitted")
                if order["status"] != "paid":
                    cursor.execute("UPDATE payment_orders SET status='paid',paid_at=UTC_TIMESTAMP(),reviewed_at=UTC_TIMESTAMP(),review_note=%s WHERE id=%s", (clean(json_payload().get("review_note"), 2000) or "Manually verified", order_id))
                    cursor.execute("UPDATE users SET plan='pro',pro_expires_at=IF(pro_expires_at IS NOT NULL AND pro_expires_at>UTC_TIMESTAMP(),DATE_ADD(pro_expires_at,INTERVAL 30 DAY),DATE_ADD(UTC_TIMESTAMP(),INTERVAL 30 DAY)) WHERE id=%s", (order["user_id"],))
        audit(None, "payment_order.confirmed", "payment_order", order_id, {})
        return jsonify({"ok": True, "order": serialize_order(fetch_one("SELECT * FROM payment_orders WHERE id=%s", (order_id,)))})

    @app.post("/api/admin/payment-orders/<order_id>/reject")
    @require_admin
    def admin_reject_payment(order_id: str):
        order = fetch_one("SELECT * FROM payment_orders WHERE id=%s", (order_id,))
        if not order:
            return error_response("订单不存在", 404, "order_not_found")
        if order["status"] == "paid":
            return error_response("已支付订单不可拒绝", 409, "paid_order_immutable")
        note = clean(json_payload().get("review_note"), 2000) or "Payment could not be verified"
        execute("UPDATE payment_orders SET status='rejected',reviewed_at=UTC_TIMESTAMP(),review_note=%s WHERE id=%s", (note, order_id))
        audit(None, "payment_order.rejected", "payment_order", order_id, {"review_note": note})
        return jsonify({"ok": True})

    @app.post("/api/admin/invoice-requests/<request_id>/issue")
    @require_admin
    def admin_issue_invoice(request_id: str):
        invoice = fetch_one("SELECT * FROM invoice_requests WHERE id=%s", (request_id,))
        if not invoice:
            return error_response("发票申请不存在", 404, "invoice_request_not_found")
        if invoice["status"] != "requested":
            return error_response("只有待处理发票申请可以标记为已开票", 409, "invalid_invoice_state")
        payload = json_payload()
        invoice_number = clean(payload.get("invoice_number"), 120)
        document_url = clean(payload.get("invoice_document_url"), 1000)
        if len(invoice_number) < 4:
            return error_response("必须填写真实发票号码或税务平台引用", 400, "invoice_number_required")
        if document_url and not document_url.startswith("https://"):
            return error_response("发票文件链接必须使用 HTTPS", 400, "invalid_invoice_document_url")
        note = clean(payload.get("review_note"), 2000) or "Invoice issuance recorded after external tax-system verification"
        execute(
            "UPDATE invoice_requests SET status='issued',invoice_number=%s,invoice_document_url=%s,review_note=%s,reviewed_at=UTC_TIMESTAMP(),issued_at=UTC_TIMESTAMP() WHERE id=%s",
            (invoice_number, document_url or None, note, request_id),
        )
        audit(None, "invoice_request.issued", "invoice_request", request_id, {"order_id": invoice["order_id"], "invoice_number": invoice_number})
        return jsonify({"ok": True, "invoice_request": serialize_invoice_request(fetch_one("SELECT * FROM invoice_requests WHERE id=%s", (request_id,)))})

    @app.post("/api/admin/invoice-requests/<request_id>/reject")
    @require_admin
    def admin_reject_invoice(request_id: str):
        invoice = fetch_one("SELECT * FROM invoice_requests WHERE id=%s", (request_id,))
        if not invoice:
            return error_response("发票申请不存在", 404, "invoice_request_not_found")
        if invoice["status"] != "requested":
            return error_response("只有待处理发票申请可以拒绝", 409, "invalid_invoice_state")
        note = clean(json_payload().get("review_note"), 2000) or "Invoice request rejected; buyer information requires correction"
        execute("UPDATE invoice_requests SET status='rejected',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s", (note, request_id))
        audit(None, "invoice_request.rejected", "invoice_request", request_id, {"order_id": invoice["order_id"], "review_note": note})
        return jsonify({"ok": True})

    @app.post("/api/admin/invoice-requests/<request_id>/cancel")
    @require_admin
    def admin_cancel_invoice(request_id: str):
        invoice = fetch_one("SELECT * FROM invoice_requests WHERE id=%s", (request_id,))
        if not invoice:
            return error_response("发票申请不存在", 404, "invoice_request_not_found")
        if invoice["status"] != "issued":
            return error_response("只有已开具发票可以记录红冲/作废", 409, "invalid_invoice_state")
        payload = json_payload()
        reference = clean(payload.get("cancellation_reference"), 255)
        if len(reference) < 4:
            return error_response("必须填写真实红冲或作废凭证引用", 400, "invoice_cancellation_reference_required")
        note = clean(payload.get("review_note"), 2000) or "External invoice cancellation/red-letter record verified"
        execute("UPDATE invoice_requests SET status='cancelled',cancellation_reference=%s,review_note=%s,reviewed_at=UTC_TIMESTAMP(),cancelled_at=UTC_TIMESTAMP() WHERE id=%s", (reference, note, request_id))
        audit(None, "invoice_request.cancelled", "invoice_request", request_id, {"order_id": invoice["order_id"], "cancellation_reference": reference})
        return jsonify({"ok": True, "invoice_request": serialize_invoice_request(fetch_one("SELECT * FROM invoice_requests WHERE id=%s", (request_id,)))})

    @app.post("/api/admin/refund-requests/<request_id>/approve")
    @require_admin
    def admin_approve_refund(request_id: str):
        refund = fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,))
        if not refund:
            return error_response("退款申请不存在", 404, "refund_request_not_found")
        if refund["status"] not in {"requested", "approved"}:
            return error_response("只有待处理退款申请可以批准", 409, "invalid_refund_state")
        note = clean(json_payload().get("review_note"), 2000) or "Refund approved; awaiting original-channel settlement"
        if refund["status"] == "requested":
            execute("UPDATE refund_requests SET status='approved',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s", (note, request_id))
        audit(None, "refund_request.approved", "refund_request", request_id, {"order_id": refund["order_id"], "amount_cents": refund["amount_cents"]})
        order = fetch_one("SELECT payment_mode FROM payment_orders WHERE id=%s", (refund["order_id"],))
        automatic = None
        if order and order["payment_mode"] == "official_merchant":
            try:
                automatic = start_official_refund(request_id)
            except (PaymentConfigurationError, PaymentProviderError, PaymentVerificationError):
                execute("UPDATE refund_requests SET review_note='Official refund initiation failed; retry with the same merchant refund number' WHERE id=%s", (request_id,))
                return error_response("官方原路退款暂时未被渠道受理；已保留同一退款单号，可安全重试", 502, "provider_refund_unavailable", {"refund_request": serialize_refund_request(fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,)))})
        return jsonify({"ok": True, "refund_request": serialize_refund_request(fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,))), "automatic_refund": automatic})

    @app.post("/api/admin/refund-requests/<request_id>/initiate")
    @require_admin
    def admin_initiate_refund(request_id: str):
        try:
            result = start_official_refund(request_id)
        except (PaymentConfigurationError, PaymentProviderError, PaymentVerificationError):
            execute("UPDATE refund_requests SET review_note='Official refund initiation failed; retry with the same merchant refund number' WHERE id=%s", (request_id,))
            return error_response("官方原路退款暂时未被渠道受理；请使用同一退款单号重试", 502, "provider_refund_unavailable")
        if not result["ok"]:
            code = result["code"]
            messages = {
                "refund_request_not_found": ("退款申请不存在", 404),
                "manual_refund_required": ("人工二维码订单必须人工核验原路退款", 409),
                "invoice_cancellation_required": ("已开票订单必须先记录真实红冲/作废凭证", 409),
                "invalid_refund_state": ("当前退款状态不可发起渠道退款", 409),
                "order_not_refundable": ("订单当前不可退款", 409),
            }
            message, status = messages.get(code, ("无法发起退款", 409))
            return error_response(message, status, code)
        audit(None, "refund_request.provider_initiated", "refund_request", request_id, result)
        return jsonify({"ok": True, "refund_request": serialize_refund_request(fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,))), "automatic_refund": result})

    @app.post("/api/admin/refund-requests/<request_id>/reject")
    @require_admin
    def admin_reject_refund(request_id: str):
        refund = fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,))
        if not refund:
            return error_response("退款申请不存在", 404, "refund_request_not_found")
        if refund["status"] != "requested":
            return error_response("只有待处理退款申请可以拒绝", 409, "invalid_refund_state")
        note = clean(json_payload().get("review_note"), 2000) or "Refund request rejected after review"
        execute("UPDATE refund_requests SET status='rejected',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s", (note, request_id))
        audit(None, "refund_request.rejected", "refund_request", request_id, {"order_id": refund["order_id"], "review_note": note})
        return jsonify({"ok": True})

    @app.post("/api/admin/refund-requests/<request_id>/complete")
    @require_admin
    def admin_complete_refund(request_id: str):
        payload = json_payload()
        reference = clean(payload.get("refund_reference"), 255)
        if len(reference) < 4:
            return error_response("必须填写原支付渠道的真实退款参考号", 400, "refund_reference_required")
        completed_user_id = None
        completed_order_id = None
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM refund_requests WHERE id=%s FOR UPDATE", (request_id,))
                refund = cursor.fetchone()
                if not refund:
                    return error_response("退款申请不存在", 404, "refund_request_not_found")
                if refund["status"] == "completed":
                    return jsonify({"ok": True, "refund_request": serialize_refund_request(refund), "reused": True})
                if refund["status"] != "approved":
                    return error_response("只有已批准退款可以记录完成", 409, "invalid_refund_state")
                cursor.execute("SELECT id FROM invoice_requests WHERE order_id=%s AND status='issued' LIMIT 1", (refund["order_id"],))
                if cursor.fetchone():
                    return error_response("已开票订单必须先记录真实红冲/作废凭证", 409, "invoice_cancellation_required")
                cursor.execute("SELECT * FROM payment_orders WHERE id=%s FOR UPDATE", (refund["order_id"],))
                order = cursor.fetchone()
                if not order or order["status"] != "paid":
                    return error_response("订单当前不可完成退款", 409, "order_not_refundable")
                if order.get("payment_mode") != "manual_qr_verification":
                    return error_response("官方商户退款只能由已验签渠道响应或回调完成", 409, "official_refund_manual_completion_forbidden")
                note = clean(payload.get("review_note"), 2000) or "Original-channel refund settlement verified"
                cursor.execute("UPDATE refund_requests SET status='completed',refund_reference=%s,review_note=%s,completed_at=UTC_TIMESTAMP() WHERE id=%s", (reference, note, request_id))
                cursor.execute("UPDATE payment_orders SET status='refunded',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s", (note, order["id"]))
                _revoke_refunded_entitlement(cursor, order["user_id"])
                completed_user_id = order["user_id"]
                completed_order_id = order["id"]
        audit(None, "refund_request.completed", "refund_request", request_id, {"order_id": completed_order_id, "user_id": completed_user_id, "refund_reference": reference})
        return jsonify({"ok": True, "refund_request": serialize_refund_request(fetch_one("SELECT * FROM refund_requests WHERE id=%s", (request_id,)))})

    @app.post("/api/admin/data-deletion-requests/<request_id>/complete")
    @require_admin
    def admin_complete_data_deletion(request_id: str):
        note = clean(json_payload().get("review_note"), 2000) or "Deletion scope verified and payload removal executed"
        result = complete_deletion_request(request_id, processor="operator", review_note=note)
        if result["result"] == "not_found":
            return error_response("数据删除申请不存在", 404, "deletion_request_not_found")
        if result["result"] == "invalid_state":
            return error_response("当前删除申请状态不可执行", 409, "invalid_deletion_state")
        if result["result"] == "busy":
            return error_response("删除申请正在由其他处理器执行", 409, "deletion_request_busy")
        return jsonify({
            "ok": True,
            "deletion_request": serialize_deletion_request(result["request"]),
            "reused": result["result"] == "reused",
        })

    @app.post("/api/admin/data-deletion-requests/<request_id>/reject")
    @require_admin
    def admin_reject_data_deletion(request_id: str):
        deletion = fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,))
        if not deletion:
            return error_response("数据删除申请不存在", 404, "deletion_request_not_found")
        if deletion["status"] != "requested":
            return error_response("只有待处理删除申请可以退回", 409, "invalid_deletion_state")
        note = clean(json_payload().get("review_note"), 2000)
        if len(note) < 8:
            return error_response("退回删除申请必须填写具体原因", 400, "deletion_rejection_note_required")
        execute(
            "UPDATE data_deletion_requests SET status='rejected',review_note=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s AND status='requested'",
            (note, request_id),
        )
        audit(None, "data_deletion.rejected", "data_deletion_request", request_id, {"generation_job_id": deletion["generation_job_id"], "review_note": note})
        return jsonify({"ok": True, "deletion_request": serialize_deletion_request(fetch_one("SELECT * FROM data_deletion_requests WHERE id=%s", (request_id,)))})

    @app.get("/api/admin/summary")
    @require_admin
    def admin_summary():
        applications = fetch_all(
            "SELECT a.*,u.name AS user_name,u.email,u.company FROM api_access_applications a JOIN users u ON u.id=a.user_id WHERE a.status='received' ORDER BY a.created_at ASC LIMIT 100"
        )
        payments = fetch_all(
            "SELECT p.*,u.name AS user_name,u.email,u.company FROM payment_orders p JOIN users u ON u.id=p.user_id WHERE p.status='under_review' ORDER BY p.submitted_at ASC LIMIT 100"
        )
        invoice_requests = fetch_all(
            "SELECT i.*,p.amount_cents,p.currency,u.name AS user_name,u.email,u.company FROM invoice_requests i JOIN payment_orders p ON p.id=i.order_id JOIN users u ON u.id=i.user_id WHERE i.status='requested' ORDER BY i.requested_at ASC LIMIT 100"
        )
        refund_requests = fetch_all(
            "SELECT r.*,p.channel,p.payment_mode,p.payment_reference,u.name AS user_name,u.email,u.company FROM refund_requests r JOIN payment_orders p ON p.id=r.order_id JOIN users u ON u.id=r.user_id WHERE r.status IN ('requested','approved','processing','failed') ORDER BY r.requested_at ASC LIMIT 100"
        )
        procurement_evidence = fetch_all(
            "SELECT e.*,c.title AS case_title,u.name AS user_name,u.email,u.company FROM procurement_gate_evidence e JOIN procurement_cases c ON c.id=e.case_id JOIN users u ON u.id=e.user_id WHERE e.status='received' ORDER BY e.created_at ASC LIMIT 100"
        )
        compliance_profiles = fetch_all(
            "SELECT cp.*,u.name AS user_name,u.email,u.company FROM buyer_compliance_profiles cp JOIN users u ON u.id=cp.user_id WHERE cp.status='received' ORDER BY cp.submitted_at ASC LIMIT 100"
        )
        deletion_requests = fetch_all(
            "SELECT d.*,j.filename,u.name AS user_name,u.email,u.company FROM data_deletion_requests d "
            "JOIN generation_jobs j ON j.id=d.generation_job_id JOIN users u ON u.id=d.user_id "
            "WHERE d.status IN ('requested','processing') ORDER BY d.due_at ASC LIMIT 100"
        )
        contract_ready_cases = fetch_all(
            "SELECT c.*,u.name AS user_name,u.email,u.company FROM procurement_cases c JOIN users u ON u.id=c.user_id WHERE c.status='contract_ready' AND NOT EXISTS (SELECT 1 FROM procurement_contracts pc WHERE pc.case_id=c.id AND pc.status IN ('ready','signed')) ORDER BY c.updated_at ASC LIMIT 100"
        )
        contract_ready_cases = [item for item in contract_ready_cases if procurement_case_all_gates_contract_eligible(item["id"])]
        ready_contracts = fetch_all(
            "SELECT pc.*,c.title AS case_title,u.name AS user_name,u.email,u.company FROM procurement_contracts pc JOIN procurement_cases c ON c.id=pc.case_id JOIN users u ON u.id=pc.user_id WHERE pc.status='ready' ORDER BY pc.issued_at ASC LIMIT 100"
        )
        ready_contracts = [item for item in ready_contracts if contract_snapshot_is_contract_eligible(item)]
        metrics = fetch_one(
            "SELECT (SELECT COUNT(*) FROM users) AS users,(SELECT COUNT(*) FROM users WHERE plan='pro' AND pro_expires_at>UTC_TIMESTAMP()) AS active_pro,(SELECT COUNT(*) FROM generation_jobs) AS generations,(SELECT COUNT(*) FROM api_keys WHERE status='active') AS active_api_keys,(SELECT COUNT(*) FROM procurement_cases) AS procurement_cases,"
            "(SELECT COUNT(*) FROM procurement_cases c WHERE "
            "(c.status='contract_ready' AND (SELECT COUNT(DISTINCT e.gate_number) FROM procurement_gate_evidence e WHERE e.case_id=c.id AND e.status='approved' AND e.evidence_scope='buyer_external' AND e.contract_eligible=TRUE)=3) "
            "OR (c.status='contracted' AND EXISTS (SELECT 1 FROM procurement_contracts pc WHERE pc.case_id=c.id AND pc.status='signed' AND pc.executed_document_sha256 IS NOT NULL AND pc.provider_signature_sha256 IS NOT NULL AND pc.buyer_signature_sha256 IS NOT NULL AND pc.execution_attestation_sha256 IS NOT NULL))) AS contract_ready,"
            "(SELECT COUNT(*) FROM invoice_requests WHERE status='requested') AS invoices_pending,(SELECT COUNT(*) FROM refund_requests WHERE status IN ('requested','approved','processing','failed')) AS refunds_pending,(SELECT COUNT(*) FROM buyer_compliance_profiles WHERE status='received') AS compliance_pending,(SELECT COUNT(*) FROM data_deletion_requests WHERE status IN ('requested','processing')) AS deletions_pending"
        )
        return jsonify({
            "ok": True,
            "metrics": metrics,
            "applications": [serialize_admin_application(item) for item in applications],
            "payments": [serialize_admin_order(item) for item in payments],
            "invoice_requests": [serialize_admin_invoice_request(item) for item in invoice_requests],
            "refund_requests": [serialize_admin_refund_request(item) for item in refund_requests],
            "procurement_evidence": [serialize_admin_procurement_evidence(item) for item in procurement_evidence],
            "compliance_profiles": [serialize_admin_compliance_profile(item) for item in compliance_profiles],
            "deletion_requests": [serialize_admin_deletion_request(item) for item in deletion_requests],
            "contract_ready_cases": [serialize_admin_procurement_case(item) for item in contract_ready_cases],
            "ready_contracts": [serialize_admin_procurement_contract(item) for item in ready_contracts],
        })

    return app


@lru_cache(maxsize=16)
def _catalog_file_sha256(path_text: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def synthetic_catalog_file_status(catalog: dict) -> dict:
    path = (CATALOG_DIR / catalog["filename"]).resolve()
    if not path.is_relative_to(CATALOG_DIR):
        return {"available": False, "integrity_status": "unsafe_path", "path": None}
    try:
        stat = path.stat()
    except OSError:
        return {"available": False, "integrity_status": "missing", "path": None}
    if not path.is_file():
        return {"available": False, "integrity_status": "not_a_file", "path": None}
    if stat.st_size != int(catalog["bytes"]):
        return {"available": False, "integrity_status": "size_mismatch", "path": None}
    actual_sha256 = _catalog_file_sha256(str(path), stat.st_size, stat.st_mtime_ns)
    if not hmac.compare_digest(actual_sha256, catalog["sha256"]):
        return {"available": False, "integrity_status": "sha256_mismatch", "path": None}
    return {"available": True, "integrity_status": "verified", "path": path}


def serialize_synthetic_catalog(catalog: dict) -> dict:
    status = synthetic_catalog_file_status(catalog)
    return {
        **catalog,
        "available": status["available"],
        "integrity_status": status["integrity_status"],
        "download_url": f"/api/catalogs/{catalog['slug']}/download" if status["available"] else None,
    }


def json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def clean(value, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def is_sha256(value) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def safe_filename(value) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "customer_tasks.csv")).strip("._") or "customer_tasks.csv"
    return name[:240] if name.endswith(".csv") else f"{name[:236]}.csv"


def error_response(message: str, status: int, code: str, details: dict | None = None):
    error = {"code": code, "message": message}
    if details:
        error.update(details)
    return jsonify({"ok": False, "error": error}), status


def attach_session(response, user_id: str) -> None:
    token, token_hash_value, expires_at = new_session_token()
    session_id = str(uuid.uuid4())
    execute("INSERT INTO sessions (id,user_id,token_hash,expires_at) VALUES (%s,%s,%s,%s)", (session_id, user_id, token_hash_value, expires_at))
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=SESSION_SECURE, samesite="Lax", path="/", max_age=14 * 24 * 60 * 60)


def authenticated_user():
    raw_api_key = request.headers.get("X-API-Key", "").strip()
    if raw_api_key:
        row = fetch_one("SELECT u.*,k.id AS api_key_id FROM api_keys k JOIN users u ON u.id=k.user_id WHERE k.key_hash=%s AND k.status='active' AND (k.expires_at IS NULL OR k.expires_at>UTC_TIMESTAMP())", (hash_token(raw_api_key),))
        if row and row["account_status"] == "active":
            g.api_key_id = row.pop("api_key_id")
            g.auth_type = "api_key"
            return row
        return None
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    row = fetch_one("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>UTC_TIMESTAMP() AND u.account_status='active'", (hash_token(token),))
    if row:
        g.auth_type = "session"
        execute("UPDATE sessions SET last_seen_at=UTC_TIMESTAMP() WHERE token_hash=%s", (hash_token(token),))
    return row


def require_user(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        g.user = authenticated_user()
        if not g.user or getattr(g, "auth_type", "") != "session":
            return error_response("请先登录", 401, "authentication_required")
        return handler(*args, **kwargs)
    return wrapped


def require_user_or_api_key(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        g.user = authenticated_user()
        if not g.user:
            return error_response("需要登录会话或有效 API 密钥", 401, "authentication_required")
        return handler(*args, **kwargs)
    return wrapped


def require_admin(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        configured = os.environ.get("ADMIN_TOKEN", "")
        supplied = request.headers.get("X-Admin-Token", "")
        if not configured or not hmac.compare_digest(configured, supplied):
            return error_response("管理员凭据无效", 403, "admin_required")
        return handler(*args, **kwargs)
    return wrapped


def is_pro(user: dict) -> bool:
    expires = user.get("pro_expires_at")
    now_utc_naive = datetime.now(UTC).replace(tzinfo=None)
    return user.get("plan") == "pro" and isinstance(expires, datetime) and expires > now_utc_naive


def public_user(user: dict) -> dict:
    return {
        "id": user["id"], "email": user["email"], "name": user["name"], "company": user["company"],
        "plan": user["plan"], "pro_expires_at": iso(user.get("pro_expires_at")), "is_pro": is_pro(user), "created_at": iso(user.get("created_at")),
    }


def latest_application(user_id: str):
    return fetch_one("SELECT * FROM api_access_applications WHERE user_id=%s ORDER BY created_at DESC LIMIT 1", (user_id,))


def serialize_application(row):
    if not row:
        return None
    return {"id": row["id"], "role": row["role"], "use_case": row["use_case"], "data_format": row["data_format"], "monthly_volume": row["monthly_volume"], "pilot_goal": row["pilot_goal"], "status": row["status"], "status_label": STATUS_LABELS[row["status"]], "review_note": row.get("review_note"), "created_at": iso(row["created_at"]), "reviewed_at": iso(row.get("reviewed_at"))}


def serialize_api_key(row):
    return {"id": row["id"], "label": row["label"], "prefix": row["key_prefix"], "status": row["status"], "created_at": iso(row["created_at"]), "last_used_at": iso(row.get("last_used_at"))}


def serialize_order(row):
    return {
        "id": row["id"], "merchant_order_no": row.get("merchant_order_no"), "plan": row["plan_code"],
        "channel": row["channel"], "channel_label": CHANNEL_LABELS[row["channel"]],
        "payment_mode": row.get("payment_mode", "manual_qr_verification"), "amount_cents": row["amount_cents"],
        "currency": row["currency"], "status": row["status"], "status_label": STATUS_LABELS[row["status"]],
        "payment_reference": row.get("payment_reference"), "provider_transaction_id": row.get("provider_transaction_id"),
        "provider_verified_at": iso(row.get("provider_verified_at")), "checkout_url": row.get("checkout_url"),
        "created_at": iso(row["created_at"]), "submitted_at": iso(row.get("submitted_at")), "paid_at": iso(row.get("paid_at")),
    }


def serialize_invoice_request(row):
    return {
        "id": row["id"], "order_id": row["order_id"], "invoice_title": row["invoice_title"],
        "taxpayer_id": row["taxpayer_id"], "invoice_email": row["invoice_email"],
        "status": row["status"], "status_label": STATUS_LABELS[row["status"]],
        "invoice_number": row.get("invoice_number"), "invoice_document_url": row.get("invoice_document_url"),
        "cancellation_reference": row.get("cancellation_reference"), "review_note": row.get("review_note"),
        "requested_at": iso(row["requested_at"]), "reviewed_at": iso(row.get("reviewed_at")),
        "issued_at": iso(row.get("issued_at")), "cancelled_at": iso(row.get("cancelled_at")),
    }


def serialize_refund_request(row):
    return {
        "id": row["id"], "order_id": row["order_id"], "amount_cents": int(row["amount_cents"]),
        "reason": row["reason"], "status": row["status"], "status_label": REFUND_STATUS_LABELS[row["status"]],
        "merchant_refund_no": row.get("merchant_refund_no"), "refund_reference": row.get("refund_reference"),
        "provider_refund_id": row.get("provider_refund_id"), "provider_verified_at": iso(row.get("provider_verified_at")),
        "review_note": row.get("review_note"),
        "requested_at": iso(row["requested_at"]), "reviewed_at": iso(row.get("reviewed_at")),
        "completed_at": iso(row.get("completed_at")),
    }


def serialize_deletion_request(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "generation_job_id": row["generation_job_id"],
        "request_source": row["request_source"],
        "reason": row["reason"],
        "status": row["status"],
        "status_label": STATUS_LABELS[row["status"]],
        "due_at": iso(row["due_at"]),
        "deletion_sha256": row.get("deletion_sha256"),
        "files_deleted": int(row.get("files_deleted") or 0),
        "bytes_deleted": int(row.get("bytes_deleted") or 0),
        "review_note": row.get("review_note"),
        "requested_at": iso(row["requested_at"]),
        "reviewed_at": iso(row.get("reviewed_at")),
        "completed_at": iso(row.get("completed_at")),
        "deletion_manifest": parse_json(row.get("deletion_manifest")),
    }


def serialize_admin_application(row):
    data = serialize_application(row)
    data["applicant"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def serialize_admin_order(row):
    data = serialize_order(row)
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def serialize_admin_invoice_request(row):
    data = serialize_invoice_request(row)
    data["amount_cents"] = int(row["amount_cents"])
    data["currency"] = row["currency"]
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def serialize_admin_refund_request(row):
    data = serialize_refund_request(row)
    data["channel_label"] = CHANNEL_LABELS[row["channel"]]
    data["payment_mode"] = row.get("payment_mode", "manual_qr_verification")
    data["payment_reference"] = row.get("payment_reference")
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    invoice = fetch_one("SELECT id,status,invoice_number FROM invoice_requests WHERE order_id=%s ORDER BY requested_at DESC LIMIT 1", (row["order_id"],))
    data["invoice"] = {"id": invoice["id"], "status": invoice["status"], "status_label": STATUS_LABELS[invoice["status"]], "invoice_number": invoice.get("invoice_number")} if invoice else None
    return data


def serialize_admin_deletion_request(row):
    data = serialize_deletion_request(row)
    data["filename"] = row["filename"]
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def parse_json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def serialize_job(row):
    rights = fetch_one("SELECT * FROM generation_data_rights WHERE generation_job_id=%s", (row["id"],))
    deletion = fetch_one("SELECT * FROM data_deletion_requests WHERE generation_job_id=%s", (row["id"],))
    payload_deleted = bool(deletion and deletion["status"] == "completed")
    return {
        "id": row["id"],
        "job_id": row["id"],
        "filename": row["filename"],
        "robot_model": row["robot_model"],
        "control_frequency_hz": float(row["control_frequency_hz"]),
        "sensors": row["sensors"],
        "training_format": row["training_format"],
        "production_backend": row["production_backend"],
        "synthetic_budget": int(row["synthetic_budget"]),
        "delivery_product": row.get("delivery_product") or "allocation_plan",
        "delivery_product_label": "按需模拟轨迹批次" if row.get("delivery_product") == TRAJECTORY_DELIVERY_PRODUCT else "长尾分配计划",
        "trajectory_count": int(row["trajectory_count"]) if row.get("trajectory_count") is not None else None,
        "status": row["status"],
        "status_label": STATUS_LABELS[row["status"]],
        "gate_evaluation": parse_json(row["gate_evaluation"]),
        "data_rights": serialize_generation_data_rights(rights),
        "deletion_request": serialize_deletion_request(deletion),
        "payload_deleted": payload_deleted,
        "output": parse_json(row.get("output_json")),
        "error_message": row.get("error_message"),
        "attempt_count": int(row.get("attempt_count") or 0),
        "max_attempts": int(row.get("max_attempts") or GENERATION_MAX_ATTEMPTS),
        "created_at": iso(row["created_at"]),
        "started_at": iso(row.get("started_at")),
        "completed_at": iso(row.get("completed_at")),
        "next_attempt_at": iso(row.get("next_attempt_at")),
        "status_url": f"/api/generations/{row['id']}",
        "download_url": f"/downloads/{row['id']}" if row["status"] == "completed" and not payload_deleted else None,
    }


def normalize_data_rights_attestation(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("每次生成必须提交版本化的数据权利声明")
    source_type = clean(value.get("source_type"), 40)
    license_basis = clean(value.get("license_basis"), 500)
    try:
        retention_days = int(value.get("retention_days"))
    except (TypeError, ValueError) as exc:
        raise ValueError("数据权利声明中的保存期限必须是整数天") from exc
    if source_type not in DATA_SOURCE_TYPES:
        raise ValueError("数据来源类型无效")
    if len(license_basis) < 4:
        raise ValueError("请填写数据所有权、许可或公开来源依据")
    if retention_days < 7 or retention_days > 3650:
        raise ValueError("任务数据保存期限须为 7–3650 天")
    if value.get("contains_personal_data") is True:
        raise ValueError("当前共享入口不接受含个人信息的数据；请先约定 DPA 与私有/VPC 部署边界")
    missing = [
        name for name in ("source_rights_confirmed", "derivative_rights_confirmed", "restricted_data_excluded")
        if value.get(name) is not True
    ]
    if missing:
        raise ValueError(f"数据权利声明未完成：{', '.join(missing)}")
    return {
        "source_type": source_type,
        "license_basis": license_basis,
        "contains_personal_data": False,
        "retention_days": retention_days,
        "source_rights_confirmed": True,
        "derivative_rights_confirmed": True,
        "restricted_data_excluded": True,
        "attestation_version": DATA_RIGHTS_ATTESTATION_VERSION,
    }


def serialize_generation_data_rights(row):
    if not row:
        return None
    return {
        "source_type": row["source_type"],
        "license_basis": row["license_basis"],
        "contains_personal_data": bool(row["contains_personal_data"]),
        "retention_days": int(row["retention_days"]),
        "source_rights_confirmed": bool(row["source_rights_confirmed"]),
        "derivative_rights_confirmed": bool(row["derivative_rights_confirmed"]),
        "restricted_data_excluded": bool(row["restricted_data_excluded"]),
        "attestation_version": row["attestation_version"],
        "attestation_sha256": row["attestation_sha256"],
        "accepted_at": iso(row["accepted_at"]),
    }


def serialize_compliance_profile(row):
    if not row:
        return None
    return {
        "version": int(row["version"]),
        "organization_legal_name": row["organization_legal_name"],
        "security_contact_email": row["security_contact_email"],
        "deployment_boundary": row["deployment_boundary"],
        "data_residency": row["data_residency"],
        "retention_days": int(row["retention_days"]),
        "deletion_sla_days": int(row["deletion_sla_days"]),
        "source_rights_confirmed": bool(row["source_rights_confirmed"]),
        "derivative_rights_confirmed": bool(row["derivative_rights_confirmed"]),
        "restricted_data_excluded": bool(row["restricted_data_excluded"]),
        "subprocessor_reviewed": bool(row["subprocessor_reviewed"]),
        "profile_sha256": row["profile_sha256"],
        "status": row["status"],
        "status_label": STATUS_LABELS[row["status"]],
        "review_note": row.get("review_note"),
        "submitted_at": iso(row["submitted_at"]),
        "reviewed_at": iso(row.get("reviewed_at")),
    }


def serialize_legal_acceptance(row):
    return {
        "document_code": row["document_code"],
        "document_version": row["document_version"],
        "acceptance_sha256": row["acceptance_sha256"],
        "accepted_at": iso(row["accepted_at"]),
        "revoked_at": iso(row.get("revoked_at")),
    }


def contract_compliance_state(user_id: str) -> dict:
    profile_row = fetch_one("SELECT * FROM buyer_compliance_profiles WHERE user_id=%s", (user_id,))
    acceptance_rows = fetch_all(
        "SELECT * FROM legal_acceptances WHERE user_id=%s AND revoked_at IS NULL ORDER BY accepted_at",
        (user_id,),
    )
    current = {(row["document_code"], row["document_version"]) for row in acceptance_rows}
    missing_documents = [code for code, version in LEGAL_DOCUMENT_VERSIONS.items() if (code, version) not in current]
    profile = serialize_compliance_profile(profile_row)
    return {
        "ready": bool(profile and profile["status"] == "approved" and not missing_documents),
        "profile": profile,
        "legal_acceptances": [serialize_legal_acceptance(row) for row in acceptance_rows],
        "missing_documents": missing_documents,
    }


def normalize_evidence_payload(gate_number: int, payload: dict) -> dict:
    evidence_scope = clean(payload.get("evidence_scope"), 32) or "simulation"
    common = {
        "evidence_scope": evidence_scope,
        "evidence_issuer": clean(payload.get("evidence_issuer"), 190),
        "evidence_artifact_sha256": clean(payload.get("evidence_artifact_sha256"), 64).lower(),
        "buyer_signoff_sha256": clean(payload.get("buyer_signoff_sha256"), 64).lower(),
        "evidence_observed_at": clean(payload.get("evidence_observed_at"), 40),
    }
    if gate_number == 1:
        return {
            **common,
            "trajectory_count": numeric_value(payload.get("trajectory_count")),
            "schema_validation_passed": payload.get("schema_validation_passed") is True,
            "sample_playback_passed": payload.get("sample_playback_passed") is True,
            "dataset_manifest_sha256": clean(payload.get("dataset_manifest_sha256"), 64).lower(),
            "production_log_url": clean(payload.get("production_log_url"), 1000),
            "evidence_notes": clean(payload.get("evidence_notes"), 4000),
        }
    if gate_number == 2:
        return {
            **common,
            "same_policy": payload.get("same_policy") is True,
            "same_budget": payload.get("same_budget") is True,
            "baseline_name": clean(payload.get("baseline_name"), 190),
            "tail_sr_gain_pp": numeric_value(payload.get("tail_sr_gain_pp")),
            "ci95_lower_pp": numeric_value(payload.get("ci95_lower_pp")),
            "overall_gain_pp": numeric_value(payload.get("overall_gain_pp")),
            "head_gain_pp": numeric_value(payload.get("head_gain_pp")),
            "evaluation_episodes": numeric_value(payload.get("evaluation_episodes")),
            "evaluation_report_url": clean(payload.get("evaluation_report_url"), 1000),
            "evidence_notes": clean(payload.get("evidence_notes"), 4000),
        }
    if gate_number == 3:
        return {
            **common,
            "tail_task_count": numeric_value(payload.get("tail_task_count")),
            "simulation_episodes_per_condition": numeric_value(payload.get("simulation_episodes_per_condition")),
            "real_robot_trials_per_task": numeric_value(payload.get("real_robot_trials_per_task")),
            "unit_cost_reduction_pct": numeric_value(payload.get("unit_cost_reduction_pct")),
            "safety_review_passed": payload.get("safety_review_passed") is True,
            "buyer_acceptance_owner": clean(payload.get("buyer_acceptance_owner"), 190),
            "validation_report_url": clean(payload.get("validation_report_url"), 1000),
            "evidence_notes": clean(payload.get("evidence_notes"), 4000),
        }
    raise ValueError("invalid_gate_number")


def numeric_value(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def latest_approved_gate(case_id: str, gate_number: int):
    return fetch_one(
        "SELECT * FROM procurement_gate_evidence WHERE case_id=%s AND gate_number=%s AND status='approved' ORDER BY reviewed_at DESC,(evidence_scope='buyer_external') DESC,created_at DESC,id DESC LIMIT 1",
        (case_id, gate_number),
    )


def latest_contract_eligible_gate(case_id: str, gate_number: int):
    return fetch_one(
        "SELECT * FROM procurement_gate_evidence WHERE case_id=%s AND gate_number=%s AND status='approved' AND evidence_scope='buyer_external' AND contract_eligible=TRUE ORDER BY reviewed_at DESC,created_at DESC,id DESC LIMIT 1",
        (case_id, gate_number),
    )


def latest_gate_evidence(case_id: str, gate_number: int):
    return fetch_one(
        "SELECT * FROM procurement_gate_evidence WHERE case_id=%s AND gate_number=%s ORDER BY created_at DESC,(evidence_scope='buyer_external') DESC,updated_at DESC,id DESC LIMIT 1",
        (case_id, gate_number),
    )


def procurement_case_all_gates_approved(case_id: str) -> bool:
    return all(latest_approved_gate(case_id, gate_number) is not None for gate_number in (1, 2, 3))


def procurement_case_missing_contract_evidence(case_id: str) -> list[int]:
    return [gate_number for gate_number in (1, 2, 3) if latest_contract_eligible_gate(case_id, gate_number) is None]


def procurement_case_all_gates_contract_eligible(case_id: str) -> bool:
    return not procurement_case_missing_contract_evidence(case_id)


def contract_snapshot_is_contract_eligible(contract_row) -> bool:
    snapshot = parse_json(contract_row.get("acceptance_snapshot")) or {}
    gates = snapshot.get("approved_gates") or []
    return len(gates) == 3 and all(
        gate.get("evidence_scope") == "buyer_external"
        and gate.get("contract_eligible") is True
        and is_sha256(gate.get("review_attestation_sha256"))
        for gate in gates
    )


def serialize_procurement_evidence(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "gate_number": int(row["gate_number"]),
        "evidence": parse_json(row["evidence_json"]),
        "evidence_sha256": row["evidence_sha256"],
        "evidence_scope": row.get("evidence_scope") or "simulation",
        "evidence_scope_label": "买方外部证据" if row.get("evidence_scope") == "buyer_external" else "模拟/基准证据",
        "contract_eligible": bool(row.get("contract_eligible")),
        "automated_status": row["automated_status"],
        "automated_findings": parse_json(row["automated_findings"]),
        "status": row["status"],
        "status_label": STATUS_LABELS[row["status"]],
        "review_note": row.get("review_note"),
        "verification_reference": row.get("verification_reference"),
        "reviewer_name": row.get("reviewer_name"),
        "review_attestation_sha256": row.get("review_attestation_sha256"),
        "created_at": iso(row["created_at"]),
        "reviewed_at": iso(row.get("reviewed_at")),
    }


def serialize_procurement_contract(row):
    if not row:
        return None
    execution_verified = bool(
        is_sha256(row.get("executed_document_sha256"))
        and is_sha256(row.get("provider_signature_sha256"))
        and is_sha256(row.get("buyer_signature_sha256"))
        and not hmac.compare_digest(row["provider_signature_sha256"], row["buyer_signature_sha256"])
        and is_sha256(row.get("execution_attestation_sha256"))
    )
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "version": int(row["version"]),
        "status": row["status"],
        "status_label": "旧签署引用（缺少双方独立签署凭证）" if row["status"] == "signed" and not execution_verified else STATUS_LABELS[row["status"]],
        "acceptance_snapshot": parse_json(row["acceptance_snapshot"]),
        "contract_reference": row.get("contract_reference"),
        "executed_document_sha256": row.get("executed_document_sha256"),
        "provider_signatory": row.get("provider_signatory"),
        "provider_signature_sha256": row.get("provider_signature_sha256"),
        "buyer_signatory": row.get("buyer_signatory"),
        "buyer_signature_sha256": row.get("buyer_signature_sha256"),
        "effective_date": iso(row.get("effective_date")),
        "execution_attestation_sha256": row.get("execution_attestation_sha256"),
        "execution_verified": execution_verified,
        "issued_at": iso(row["issued_at"]),
        "signed_at": iso(row.get("signed_at")),
        "draft_download_url": f'/api/procurement-contracts/{row["id"]}/draft',
    }


def render_procurement_contract_draft(contract, case, job, user) -> str:
    snapshot = parse_json(contract["acceptance_snapshot"]) or {}
    canonical_snapshot = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_sha256 = hashlib.sha256(canonical_snapshot.encode("utf-8")).hexdigest()
    gate_lines = []
    compliance = snapshot.get("compliance") or {}
    compliance_profile = compliance.get("profile") or {}
    job_data_rights = snapshot.get("generation_data_rights") or {}
    accepted_documents = ", ".join(
        f'{item.get("document_code")}@{item.get("document_version")}'
        for item in compliance.get("legal_acceptances", [])
    ) or "未记录"
    for gate in snapshot.get("approved_gates", []):
        gate_lines.extend([
            f'### Gate {gate.get("gate_number")} · {gate.get("label") or "验收"}',
            "",
            f'- 证据 SHA-256：`{gate.get("evidence_sha256") or "未记录"}`',
            f'- 证据级别：{gate.get("evidence_scope") or "未记录"}',
            f'- 买方签署件 SHA-256：`{(gate.get("evidence") or {}).get("buyer_signoff_sha256") or "未记录"}`',
            f'- 运营核验引用：{gate.get("verification_reference") or "未记录"}',
            f'- 运营核验 SHA-256：`{gate.get("review_attestation_sha256") or "未记录"}`',
            f'- 审核时间：{gate.get("approved_at") or "未记录"}',
            f'- 已审核字段：`{json.dumps(gate.get("evidence") or {}, ensure_ascii=False, sort_keys=True)}`',
            "",
        ])
    status_note = (
        f'系统已记录外部签署引用 `{contract.get("contract_reference")}`；签署效力和正文以外部归档件为准。'
        if contract.get("status") == "signed"
        else "本文件尚未签署，仅用于双方商务、法务和采购评审。"
    )
    lines = [
        "# Q-Tail 数据服务采购与验收条款（协商草案）",
        "",
        "> 重要：本文件由已审核 Gate 快照自动生成，是协商/SOW 草案，不是已签署合同，不代表付款到账、真实买方签字或法律审批完成。",
        "",
        f'- 草案版本：v{int(contract["version"])}',
        f'- 合同记录 ID：`{contract["id"]}`',
        f'- 采购项目 ID：`{contract["case_id"]}`',
        f'- 验收快照 SHA-256：`{snapshot_sha256}`',
        f'- 系统状态：{STATUS_LABELS.get(contract.get("status"), contract.get("status"))}',
        f'- 状态说明：{status_note}',
        f'- 执行合同 SHA-256：`{contract.get("executed_document_sha256") or "尚未记录"}`',
        f'- 服务方签署凭证 SHA-256：`{contract.get("provider_signature_sha256") or "尚未记录"}`',
        f'- 采购方签署凭证 SHA-256：`{contract.get("buyer_signature_sha256") or "尚未记录"}`',
        f'- 执行核验 SHA-256：`{contract.get("execution_attestation_sha256") or "尚未记录"}`',
        f'- 双方签署人：{contract.get("provider_signatory") or "待签署"} / {contract.get("buyer_signatory") or "待签署"}',
        f'- 合同有效日期：{iso(contract.get("effective_date")) or "待签署"}',
        "",
        "## 1. 合同主体",
        "",
        "- 服务方：Coherent (Beijing) Technology Co., Ltd.（注册地址、统一社会信用代码、联系人及送达信息待法务核验后补齐）",
        f'- 采购方：{user.get("company") or "待补充"}',
        f'- 采购方负责人：{case.get("buyer_owner") if case else user.get("name") or "待补充"}',
        f'- 账户联系人：{user.get("name") or "待补充"} / {user.get("email") or "待补充"}',
        "",
        "## 2. 项目范围",
        "",
        f'- 项目名称：{case.get("title") if case else snapshot.get("title") or "待补充"}',
        f'- 试点范围：{case.get("pilot_scope") if case else "待补充"}',
        f'- 来源生成任务：`{job.get("id") if job else snapshot.get("generation_job_id") or "待补充"}`',
        f'- 机器人构型：{job.get("robot_model") if job else "待补充"}',
        f'- 控制频率：{job.get("control_frequency_hz") if job else "待补充"} Hz',
        f'- 传感器：{job.get("sensors") if job else "待补充"}',
        f'- 训练格式：{job.get("training_format") if job else "待补充"}',
        f'- 生产后端：{job.get("production_backend") if job else "待补充"}',
        "",
        "## 3. 交付物与声明边界",
        "",
        "1. Q-Tail 长尾任务分配计划、风险评分、场景规格、版本清单和审计包。",
        "2. Gate 1 客户专属可训练轨迹只有在约定生产后端真实执行、格式/回放通过且证据获批时才构成交付。",
        "3. 公共 Open X 适配、MetaWorld 对照和本地仿真不自动证明客户真机、客户策略、实际成本或采购验收。",
        "4. 未在本草案和最终签署 SOW 中明确列出的模型训练、标注、真机运维、SLA 或知识产权转让均不默认包含。",
        "",
        "## 4. Gate 验收快照",
        "",
        "Gate 0 已记录为声明边界通过。以下 Gate 1–3 条目来自平台运营审核记录；外部证据原件、授权和真实性仍由签约双方确认。",
        "",
        *gate_lines,
        "## 5. 商务条款（签署前必填）",
        "",
        "- 合同总价/税率/含税口径：____",
        "- 付款节点与收款账户：____",
        "- 发票类型、项目和抬头：____",
        "- 交付周期、里程碑和变更流程：____",
        "- 数据保留/删除期限：____",
        "- 服务可用性、支持窗口与违约责任：____",
        "",
        "## 6. 数据、知识产权与安全",
        "",
        f'- 合规资料 SHA-256：`{compliance_profile.get("profile_sha256") or "未记录"}`',
        f'- 来源权利声明 SHA-256：`{job_data_rights.get("attestation_sha256") or "未记录"}`',
        f'- 来源/许可依据：{job_data_rights.get("source_type") or "待补充"} / {job_data_rights.get("license_basis") or "待补充"}',
        f'- 部署边界：{compliance_profile.get("deployment_boundary") or "待补充"}',
        f'- 数据驻留：{compliance_profile.get("data_residency") or "待补充"}',
        f'- 保存/删除：{compliance_profile.get("retention_days") or "待补充"} 天 / {compliance_profile.get("deletion_sla_days") or "待补充"} 天 SLA',
        f'- 已接受文件版本：{accepted_documents}',
        "",
        "采购方保证其上传数据和机器人日志具有合法处理授权，并已确认衍生处理权和受限数据排除。采购方保留客户数据权利；Q-Tail 软件、模型、方法及通用改进归其权利人所有。客户专属交付、衍生数据、再许可、保密等级、跨境、分包和安全事件通知以最终签署条款为准。",
        "",
        "## 7. 签署与归档",
        "",
        "本草案必须经双方有权代表签署或通过双方认可的电子签约系统归档后方可生效。平台只能保存外部合同编号/存档引用，不生成或冒充签名。",
        "",
        "- 服务方授权代表：____  日期：____",
        "- 采购方授权代表：____  日期：____",
        "- 外部合同编号/电子签约存档：____",
        "",
    ]
    return "\n".join(str(item) for item in lines)


def serialize_procurement_case(row):
    job = fetch_one("SELECT id,filename,robot_model,training_format,status,gate_evaluation,created_at,completed_at FROM generation_jobs WHERE id=%s", (row["generation_job_id"],))
    gate0_status = "approved" if job and (parse_json(job.get("gate_evaluation")) or {}).get("gate0", {}).get("status") == "passed" else "blocked"
    gates = [{"gate_number": 0, "label": GATE_DEFINITIONS[0]["label"], "status": gate0_status, "acceptance": GATE_DEFINITIONS[0]["acceptance"], "evidence": None}]
    previous_approved = gate0_status == "approved"
    for gate_number in (1, 2, 3):
        evidence = latest_gate_evidence(row["id"], gate_number)
        serialized = serialize_procurement_evidence(evidence)
        status = serialized["status"] if serialized else ("open" if previous_approved else "locked")
        gates.append({"gate_number": gate_number, "label": GATE_DEFINITIONS[gate_number]["label"], "status": status, "acceptance": GATE_DEFINITIONS[gate_number]["acceptance"], "evidence": serialized})
        previous_approved = bool(serialized and serialized["status"] == "approved")
    contract = fetch_one("SELECT * FROM procurement_contracts WHERE case_id=%s ORDER BY version DESC LIMIT 1", (row["id"],))
    compliance = contract_compliance_state(row["user_id"])
    missing_contract_gates = procurement_case_missing_contract_evidence(row["id"])
    serialized_contract = serialize_procurement_contract(contract)
    return {
        "id": row["id"],
        "title": row["title"],
        "buyer_owner": row["buyer_owner"],
        "pilot_scope": row["pilot_scope"],
        "status": row["status"],
        "status_label": (
            "待补买方外部证据"
            if row["status"] == "contract_ready" and missing_contract_gates
            else "旧合同引用（外部证据未验证）"
            if row["status"] == "contracted" and (missing_contract_gates or not serialized_contract or not serialized_contract["execution_verified"])
            else STATUS_LABELS[row["status"]]
        ),
        "generation_job": {
            "id": job["id"], "filename": job["filename"], "robot_model": job["robot_model"], "training_format": job["training_format"], "created_at": iso(job["created_at"]), "completed_at": iso(job.get("completed_at")),
        } if job else None,
        "gates": gates,
        "contract_evidence": {"ready": not missing_contract_gates, "missing_gates": missing_contract_gates},
        "compliance": {"ready_for_contract": compliance["ready"], "profile": compliance["profile"], "missing_documents": compliance["missing_documents"]},
        "contract": serialized_contract,
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
    }


def procurement_acceptance_snapshot(case_id: str) -> dict:
    case = fetch_one("SELECT * FROM procurement_cases WHERE id=%s", (case_id,))
    compliance = contract_compliance_state(case["user_id"]) if case else {"ready": False, "profile": None, "legal_acceptances": [], "missing_documents": list(LEGAL_DOCUMENT_VERSIONS)}
    data_rights = fetch_one("SELECT * FROM generation_data_rights WHERE generation_job_id=%s", (case["generation_job_id"],)) if case else None
    evidence = []
    for gate_number in (1, 2, 3):
        row = latest_contract_eligible_gate(case_id, gate_number)
        if row:
            evidence.append({
                "gate_number": gate_number,
                "label": GATE_DEFINITIONS[gate_number]["label"],
                "evidence_sha256": row["evidence_sha256"],
                "evidence_scope": row.get("evidence_scope") or "simulation",
                "contract_eligible": bool(row.get("contract_eligible")),
                "verification_reference": row.get("verification_reference"),
                "reviewer_name": row.get("reviewer_name"),
                "review_attestation_sha256": row.get("review_attestation_sha256"),
                "approved_at": iso(row.get("reviewed_at")),
                "evidence": parse_json(row["evidence_json"]),
            })
    return {
        "case_id": case_id,
        "title": case["title"] if case else None,
        "generation_job_id": case["generation_job_id"] if case else None,
        "gate0": "passed",
        "approved_gates": evidence,
        "generation_data_rights": serialize_generation_data_rights(data_rights),
        "compliance": {
            "ready_for_contract": compliance["ready"],
            "profile": compliance["profile"],
            "legal_acceptances": compliance["legal_acceptances"],
            "missing_documents": compliance["missing_documents"],
        },
        "claim_boundary": "Contract readiness requires reviewed buyer-external evidence for Gate 1–3; it still does not replace the externally executed procurement contract.",
        "generated_at": datetime.now(UTC).isoformat(),
    }


def serialize_admin_procurement_evidence(row):
    data = serialize_procurement_evidence(row)
    data["case_title"] = row["case_title"]
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def serialize_admin_compliance_profile(row):
    data = serialize_compliance_profile(row)
    data["user_id"] = row["user_id"]
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def serialize_admin_procurement_case(row):
    data = serialize_procurement_case(row)
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def serialize_admin_procurement_contract(row):
    data = serialize_procurement_contract(row)
    data["case_title"] = row["case_title"]
    data["buyer"] = {"name": row["user_name"], "email": row["email"], "company": row["company"]}
    return data


def summarize_delivery(delivery: dict) -> dict:
    keys = ["delivery_report", "readme", "model_card", "synthetic_plan", "package_zip", "package_manifest", "trajectory_manifest", "effect_summary"]
    return {key: delivery.get(key) for key in keys if delivery.get(key) is not None}


def audit(actor_user_id, event_type: str, object_type: str, object_id: str, event: dict) -> None:
    execute("INSERT INTO audit_events (actor_user_id,event_type,object_type,object_id,event_json) VALUES (%s,%s,%s,%s,%s)", (actor_user_id, event_type, object_type, object_id, json.dumps(event, ensure_ascii=False, default=str)))


def iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat() + ("Z" if isinstance(value, datetime) else "")
    return value


def json_safe_row(row: dict) -> dict:
    return {
        key: parse_json(value) if key.endswith("_json") or key == "gate_evaluation" else iso(value)
        for key, value in row.items()
    }


app = create_app(initialize=os.environ.get("SKIP_DB_INIT") != "1")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8787")), debug=os.environ.get("FLASK_DEBUG") == "1")
