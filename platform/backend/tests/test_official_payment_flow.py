from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_TOKEN", "integration-admin-token-at-least-32-characters")
os.environ.setdefault("APP_SECRET", "integration-app-secret-at-least-32-characters")

from app import create_app  # noqa: E402
from db import execute, fetch_one  # noqa: E402
from payment_providers import RefundStartResult  # noqa: E402


def private_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def public_pem(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def sign(key, payload: bytes) -> str:
    return base64.b64encode(key.sign(payload, padding.PKCS1v15(), hashes.SHA256())).decode("ascii")


class OfficialPaymentFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(initialize=True)
        cls.app.config.update(TESTING=True)

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.merchant_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        (root / "merchant.pem").write_bytes(private_pem(self.merchant_key))
        (root / "platform.pem").write_bytes(public_pem(self.platform_key))
        (root / "v3.key").write_bytes(b"0123456789abcdef0123456789abcdef")
        self.environment = {
            "PAYMENT_PUBLIC_URL": "https://pay.qtail.example",
            "ALIPAY_APP_ID": "2026000000000001",
            "ALIPAY_SELLER_ID": "2088000000000001",
            "ALIPAY_PRIVATE_KEY_FILE": str(root / "merchant.pem"),
            "ALIPAY_PUBLIC_KEY_FILE": str(root / "platform.pem"),
            "WECHATPAY_APP_ID": "wx-test-app",
            "WECHATPAY_MCH_ID": "1900000001",
            "WECHATPAY_MERCHANT_SERIAL": "MERCHANT-SERIAL",
            "WECHATPAY_PRIVATE_KEY_FILE": str(root / "merchant.pem"),
            "WECHATPAY_PLATFORM_SERIAL": "PLATFORM-SERIAL",
            "WECHATPAY_PLATFORM_PUBLIC_KEY_FILE": str(root / "platform.pem"),
            "WECHATPAY_API_V3_KEY_FILE": str(root / "v3.key"),
        }
        self.env_patch = patch.dict(os.environ, self.environment, clear=False)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tempdir.cleanup()

    def register(self, prefix: str):
        client = self.app.test_client()
        suffix = f"{prefix}-{time.time_ns()}"
        response = client.post("/api/auth/register", json={
            "name": "Official Payment Buyer", "company": "Payment Test Buyer",
            "email": f"{suffix}@example.com", "password": "buyer-password-2026",
        })
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return client, response.get_json()["user"]["id"]

    def insert_order(self, user_id: str, channel: str):
        order_id = str(uuid.uuid4())
        merchant_order_no = "QT" + uuid.uuid4().hex[:30]
        execute(
            "INSERT INTO payment_orders (id,merchant_order_no,user_id,plan_code,channel,payment_mode,amount_cents) "
            "VALUES (%s,%s,%s,'pro_monthly',%s,'official_merchant',99900)",
            (order_id, merchant_order_no, user_id, channel),
        )
        return order_id, merchant_order_no

    def alipay_form(self, merchant_order_no: str, notify_id: str, trade_no: str, amount="999.00"):
        values = {
            "notify_id": notify_id,
            "app_id": self.environment["ALIPAY_APP_ID"],
            "seller_id": self.environment["ALIPAY_SELLER_ID"],
            "out_trade_no": merchant_order_no,
            "trade_no": trade_no,
            "total_amount": amount,
            "trade_status": "TRADE_SUCCESS",
            "sign_type": "RSA2",
        }
        canonical = "&".join(f"{key}={values[key]}" for key in sorted(values) if key not in {"sign", "sign_type"})
        values["sign"] = sign(self.platform_key, canonical.encode())
        return values

    def wechat_event(self, event_type: str, resource: dict, event_id: str):
        nonce = "0123456789ab"
        associated = "qtail-callback"
        ciphertext = AESGCM(b"0123456789abcdef0123456789abcdef").encrypt(
            nonce.encode(), json.dumps(resource, separators=(",", ":")).encode(), associated.encode()
        )
        body = json.dumps({
            "id": event_id,
            "event_type": event_type,
            "resource_type": "encrypt-resource",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM", "ciphertext": base64.b64encode(ciphertext).decode(),
                "nonce": nonce, "associated_data": associated,
            },
        }, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        callback_nonce = "callback-nonce"
        headers = {
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Nonce": callback_nonce,
            "Wechatpay-Serial": self.environment["WECHATPAY_PLATFORM_SERIAL"],
            "Wechatpay-Signature": sign(self.platform_key, f"{timestamp}\n{callback_nonce}\n".encode() + body + b"\n"),
        }
        return body, headers

    def test_alipay_callback_grants_pro_once_and_rejects_amount_mismatch(self):
        client, user_id = self.register("alipay")
        order_id, merchant_order_no = self.insert_order(user_id, "alipay")
        trade_no = f"ALI{time.time_ns()}"
        first = client.post("/api/payments/alipay/notify", data=self.alipay_form(merchant_order_no, f"notify-{uuid.uuid4()}", trade_no))
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(fetch_one("SELECT status FROM payment_orders WHERE id=%s", (order_id,))["status"], "paid")
        initial_expiry = fetch_one("SELECT pro_expires_at FROM users WHERE id=%s", (user_id,))["pro_expires_at"]

        replay_form = self.alipay_form(merchant_order_no, f"notify-{uuid.uuid4()}", trade_no)
        replay = client.post("/api/payments/alipay/notify", data=replay_form)
        self.assertEqual(replay.status_code, 200, replay.get_data(as_text=True))
        self.assertEqual(fetch_one("SELECT pro_expires_at FROM users WHERE id=%s", (user_id,))["pro_expires_at"], initial_expiry)
        blocked_manual = client.post(
            f"/api/admin/payment-orders/{order_id}/confirm",
            headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]}, json={},
        )
        self.assertEqual(blocked_manual.status_code, 409, blocked_manual.get_data(as_text=True))

        other_order_id, other_merchant_no = self.insert_order(user_id, "alipay")
        mismatch = client.post(
            "/api/payments/alipay/notify",
            data=self.alipay_form(other_merchant_no, f"notify-{uuid.uuid4()}", f"ALI{time.time_ns()}", amount="0.01"),
        )
        self.assertEqual(mismatch.status_code, 400, mismatch.get_data(as_text=True))
        self.assertEqual(fetch_one("SELECT status FROM payment_orders WHERE id=%s", (other_order_id,))["status"], "pending")

    def test_wechat_verified_refund_callback_revokes_entitlement_once(self):
        client, user_id = self.register("wechat")
        order_id, merchant_order_no = self.insert_order(user_id, "wechat")
        transaction_id = f"WX{time.time_ns()}"
        payment_body, payment_headers = self.wechat_event("TRANSACTION.SUCCESS", {
            "mchid": self.environment["WECHATPAY_MCH_ID"], "appid": self.environment["WECHATPAY_APP_ID"],
            "out_trade_no": merchant_order_no, "transaction_id": transaction_id, "trade_state": "SUCCESS",
            "amount": {"total": 99900, "currency": "CNY"},
        }, f"payment-{uuid.uuid4()}")
        paid = client.post("/api/payments/wechat/notify", data=payment_body, headers=payment_headers, content_type="application/json")
        self.assertEqual(paid.status_code, 204, paid.get_data(as_text=True))

        requested = client.post(f"/api/payment-orders/{order_id}/refund-requests", json={"reason": "官方商户回调原路退款集成测试。"})
        self.assertEqual(requested.status_code, 201, requested.get_data(as_text=True))
        refund = requested.get_json()["refund_request"]
        with patch("app.initiate_refund", return_value=RefundStartResult("processing", "50300000000000000001", "50300000000000000001")):
            approved = client.post(
                f"/api/admin/refund-requests/{refund['id']}/approve",
                headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]}, json={},
            )
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        self.assertEqual(approved.get_json()["refund_request"]["status"], "processing")
        refund_body, refund_headers = self.wechat_event("REFUND.SUCCESS", {
            "mchid": self.environment["WECHATPAY_MCH_ID"], "out_trade_no": merchant_order_no,
            "transaction_id": transaction_id, "out_refund_no": refund["merchant_refund_no"],
            "refund_id": "50300000000000000001", "refund_status": "SUCCESS",
            "amount": {"total": 99900, "refund": 99900, "currency": "CNY"},
        }, f"refund-{uuid.uuid4()}")
        completed = client.post("/api/payments/wechat/notify", data=refund_body, headers=refund_headers, content_type="application/json")
        self.assertEqual(completed.status_code, 204, completed.get_data(as_text=True))
        self.assertEqual(fetch_one("SELECT status FROM refund_requests WHERE id=%s", (refund["id"],))["status"], "completed")
        self.assertEqual(fetch_one("SELECT status FROM payment_orders WHERE id=%s", (order_id,))["status"], "refunded")
        self.assertEqual(fetch_one("SELECT plan FROM users WHERE id=%s", (user_id,))["plan"], "free")
        replay = client.post("/api/payments/wechat/notify", data=refund_body, headers=refund_headers, content_type="application/json")
        self.assertEqual(replay.status_code, 204, replay.get_data(as_text=True))
        self.assertEqual(fetch_one("SELECT plan FROM users WHERE id=%s", (user_id,))["plan"], "free")


if __name__ == "__main__":
    unittest.main()
