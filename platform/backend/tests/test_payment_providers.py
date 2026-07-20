from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from payment_providers import (
    PaymentNotification,
    PaymentVerificationError,
    RefundNotification,
    create_checkout,
    initiate_refund,
    verify_alipay_notification,
    verify_wechat_notification,
)


def private_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def public_pem(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def sign(key, payload: bytes) -> str:
    return base64.b64encode(key.sign(payload, padding.PKCS1v15(), hashes.SHA256())).decode("ascii")


class PaymentProviderCryptoTest(unittest.TestCase):
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

    def alipay_form(self, **changes):
        values = {
            "notify_id": "notify-alipay-1",
            "app_id": self.environment["ALIPAY_APP_ID"],
            "seller_id": self.environment["ALIPAY_SELLER_ID"],
            "out_trade_no": "QT012345678901234567890123456789",
            "trade_no": "20260716000000000001",
            "total_amount": "999.00",
            "trade_status": "TRADE_SUCCESS",
            "sign_type": "RSA2",
        }
        values.update(changes)
        canonical = "&".join(f"{key}={values[key]}" for key in sorted(values) if key not in {"sign", "sign_type"})
        values["sign"] = sign(self.platform_key, canonical.encode())
        return values

    def wechat_event(self, event_type: str, resource: dict, event_id: str):
        nonce = "0123456789ab"
        associated = "transaction"
        ciphertext = AESGCM(b"0123456789abcdef0123456789abcdef").encrypt(
            nonce.encode(), json.dumps(resource, separators=(",", ":")).encode(), associated.encode()
        )
        envelope = {
            "id": event_id,
            "event_type": event_type,
            "resource_type": "encrypt-resource",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "ciphertext": base64.b64encode(ciphertext).decode(),
                "nonce": nonce,
                "associated_data": associated,
            },
        }
        body = json.dumps(envelope, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        nonce_header = "callback-nonce"
        signature = sign(self.platform_key, f"{timestamp}\n{nonce_header}\n".encode() + body + b"\n")
        headers = {
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Nonce": nonce_header,
            "Wechatpay-Serial": self.environment["WECHATPAY_PLATFORM_SERIAL"],
            "Wechatpay-Signature": signature,
        }
        return body, headers

    def test_alipay_rsa2_notification_and_amount_tamper(self):
        form = self.alipay_form()
        notification = verify_alipay_notification(form)
        self.assertIsInstance(notification, PaymentNotification)
        self.assertEqual(notification.amount_cents, 99900)
        form["total_amount"] = "0.01"
        with self.assertRaises(PaymentVerificationError):
            verify_alipay_notification(form)
        with self.assertRaises(PaymentVerificationError):
            verify_alipay_notification(self.alipay_form(total_amount="999.001"))

    def test_wechat_payment_signature_decryption_and_replay_window(self):
        body, headers = self.wechat_event("TRANSACTION.SUCCESS", {
            "mchid": self.environment["WECHATPAY_MCH_ID"],
            "appid": self.environment["WECHATPAY_APP_ID"],
            "out_trade_no": "QT012345678901234567890123456789",
            "transaction_id": "42000000000000000001",
            "trade_state": "SUCCESS",
            "amount": {"total": 99900, "currency": "CNY"},
        }, "wechat-event-1")
        notification = verify_wechat_notification(body, headers)
        self.assertIsInstance(notification, PaymentNotification)
        self.assertEqual(notification.amount_cents, 99900)
        with self.assertRaises(PaymentVerificationError):
            verify_wechat_notification(body, headers, now_timestamp=int(headers["Wechatpay-Timestamp"]) + 301)
        tampered = body.replace(b"wechat-event-1", b"wechat-event-2")
        with self.assertRaises(PaymentVerificationError):
            verify_wechat_notification(tampered, headers)
        invalid_envelope = json.loads(body)
        invalid_envelope["resource"]["ciphertext"] = base64.b64encode(b"not-valid-gcm-ciphertext").decode()
        invalid_body = json.dumps(invalid_envelope, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        invalid_headers = {
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Nonce": "valid-signature-invalid-ciphertext",
            "Wechatpay-Serial": self.environment["WECHATPAY_PLATFORM_SERIAL"],
        }
        invalid_headers["Wechatpay-Signature"] = sign(
            self.platform_key,
            f"{timestamp}\n{invalid_headers['Wechatpay-Nonce']}\n".encode() + invalid_body + b"\n",
        )
        with self.assertRaises(PaymentVerificationError):
            verify_wechat_notification(invalid_body, invalid_headers)

    def test_wechat_refund_notification(self):
        body, headers = self.wechat_event("REFUND.SUCCESS", {
            "mchid": self.environment["WECHATPAY_MCH_ID"],
            "out_trade_no": "QT012345678901234567890123456789",
            "transaction_id": "42000000000000000001",
            "out_refund_no": "RF012345678901234567890123456789",
            "refund_id": "50300000000000000001",
            "refund_status": "SUCCESS",
            "amount": {"total": 99900, "refund": 99900, "currency": "CNY"},
        }, "wechat-refund-event-1")
        notification = verify_wechat_notification(body, headers)
        self.assertIsInstance(notification, RefundNotification)
        self.assertEqual(notification.refund_status, "SUCCESS")

    def test_wechat_outbound_request_uses_official_five_line_signature(self):
        response_body = b'{"code_url":"weixin://wxpay/test-code"}'
        response_timestamp = str(int(time.time()))
        response_nonce = "response-nonce"
        response_headers = {
            "Wechatpay-Timestamp": response_timestamp,
            "Wechatpay-Nonce": response_nonce,
            "Wechatpay-Serial": self.environment["WECHATPAY_PLATFORM_SERIAL"],
            "Wechatpay-Signature": sign(self.platform_key, f"{response_timestamp}\n{response_nonce}\n".encode() + response_body + b"\n"),
        }

        def fake_http(request, timeout=15):
            authorization = request.headers["Authorization"]
            fields = dict(re.findall(r'(mchid|nonce_str|timestamp|serial_no|signature)="([^"]+)"', authorization))
            message = (
                f"POST\n/v3/pay/transactions/native\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode()
                + request.data + b"\n"
            )
            self.merchant_key.public_key().verify(
                base64.b64decode(fields["signature"]), message, padding.PKCS1v15(), hashes.SHA256()
            )
            return 200, response_headers, response_body

        with patch("payment_providers._http_request", side_effect=fake_http):
            checkout = create_checkout("wechat", "QT012345678901234567890123456789", 99900, "Q-Tail Pro")
        self.assertEqual(checkout.checkout_url, "weixin://wxpay/test-code")

    def test_alipay_outbound_checkout_and_refund_verify_signed_responses(self):
        calls = []

        def fake_http(request, timeout=15):
            params = urllib.parse.parse_qs(request.data.decode(), strict_parsing=True)
            flattened = {key: values[0] for key, values in params.items()}
            signature = flattened.pop("sign")
            canonical = "&".join(f"{key}={flattened[key]}" for key in sorted(flattened))
            self.merchant_key.public_key().verify(
                base64.b64decode(signature), canonical.encode(), padding.PKCS1v15(), hashes.SHA256()
            )
            calls.append(flattened["method"])
            if flattened["method"] == "alipay.trade.precreate":
                key = "alipay_trade_precreate_response"
                payload = '{"code":"10000","msg":"Success","out_trade_no":"QT012345678901234567890123456789","qr_code":"https://qr.alipay.example/test"}'
            else:
                key = "alipay_trade_refund_response"
                payload = '{"code":"10000","msg":"Success","trade_no":"20260716000000000001","fund_change":"Y"}'
            response_signature = sign(self.platform_key, payload.encode())
            body = f'{{"{key}":{payload},"sign":"{response_signature}"}}'.encode()
            return 200, {}, body

        with patch("payment_providers._http_request", side_effect=fake_http):
            checkout = create_checkout("alipay", "QT012345678901234567890123456789", 99900, "Q-Tail Pro")
            refund = initiate_refund(
                "alipay", "QT012345678901234567890123456789", "20260716000000000001",
                "RF012345678901234567890123456789", 99900, "Integration refund",
            )
        self.assertEqual(checkout.checkout_url, "https://qr.alipay.example/test")
        self.assertEqual(refund.status, "completed")
        self.assertEqual(calls, ["alipay.trade.precreate", "alipay.trade.refund"])

    def test_wechat_outbound_refund_keeps_idempotent_merchant_refund_number(self):
        response_body = b'{"refund_id":"50300000000000000001","out_refund_no":"RF012345678901234567890123456789","status":"PROCESSING"}'
        response_timestamp = str(int(time.time()))
        response_nonce = "refund-response-nonce"
        response_headers = {
            "Wechatpay-Timestamp": response_timestamp,
            "Wechatpay-Nonce": response_nonce,
            "Wechatpay-Serial": self.environment["WECHATPAY_PLATFORM_SERIAL"],
            "Wechatpay-Signature": sign(self.platform_key, f"{response_timestamp}\n{response_nonce}\n".encode() + response_body + b"\n"),
        }

        def fake_http(request, timeout=15):
            payload = json.loads(request.data)
            self.assertEqual(payload["out_refund_no"], "RF012345678901234567890123456789")
            self.assertEqual(payload["amount"], {"refund": 99900, "total": 99900, "currency": "CNY"})
            authorization = request.headers["Authorization"]
            fields = dict(re.findall(r'(mchid|nonce_str|timestamp|serial_no|signature)="([^"]+)"', authorization))
            message = (
                f"POST\n/v3/refund/domestic/refunds\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode()
                + request.data + b"\n"
            )
            self.merchant_key.public_key().verify(
                base64.b64decode(fields["signature"]), message, padding.PKCS1v15(), hashes.SHA256()
            )
            return 200, response_headers, response_body

        with patch("payment_providers._http_request", side_effect=fake_http):
            result = initiate_refund(
                "wechat", "QT012345678901234567890123456789", "42000000000000000001",
                "RF012345678901234567890123456789", 99900, "Integration refund",
            )
        self.assertEqual(result.status, "processing")
        self.assertEqual(result.provider_refund_id, "50300000000000000001")


if __name__ == "__main__":
    unittest.main()
