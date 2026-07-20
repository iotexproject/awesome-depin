from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PAYMENT_MODES = {"manual_qr_verification", "official_merchant"}
CHANNELS = {"alipay", "wechat"}


class PaymentConfigurationError(RuntimeError):
    pass


class PaymentVerificationError(ValueError):
    pass


class PaymentProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaymentNotification:
    channel: str
    event_id: str
    merchant_order_no: str
    provider_transaction_id: str
    amount_cents: int
    currency: str
    payload_sha256: str
    signature_serial: str | None = None


@dataclass(frozen=True)
class RefundNotification:
    channel: str
    event_id: str
    merchant_order_no: str
    merchant_refund_no: str
    provider_refund_id: str
    refund_status: str
    amount_cents: int
    currency: str
    payload_sha256: str
    signature_serial: str | None = None


@dataclass(frozen=True)
class CheckoutResult:
    checkout_url: str
    provider_reference: str | None = None


@dataclass(frozen=True)
class RefundStartResult:
    status: str
    provider_refund_id: str
    provider_reference: str | None = None


def payment_mode() -> str:
    mode = os.environ.get("PAYMENT_MODE", "manual_qr_verification").strip()
    if mode not in PAYMENT_MODES:
        raise PaymentConfigurationError("PAYMENT_MODE must be manual_qr_verification or official_merchant")
    return mode


def channel_configuration(channel: str) -> dict:
    if channel not in CHANNELS:
        raise PaymentConfigurationError("Unsupported payment channel")
    common = ["PAYMENT_PUBLIC_URL"]
    required = {
        "alipay": ["ALIPAY_APP_ID", "ALIPAY_SELLER_ID", "ALIPAY_PRIVATE_KEY_FILE", "ALIPAY_PUBLIC_KEY_FILE"],
        "wechat": [
            "WECHATPAY_APP_ID",
            "WECHATPAY_MCH_ID",
            "WECHATPAY_MERCHANT_SERIAL",
            "WECHATPAY_PRIVATE_KEY_FILE",
            "WECHATPAY_PLATFORM_SERIAL",
            "WECHATPAY_PLATFORM_PUBLIC_KEY_FILE",
            "WECHATPAY_API_V3_KEY_FILE",
        ],
    }[channel]
    missing = [name for name in common + required if not os.environ.get(name, "").strip()]
    for name in [item for item in required if item.endswith("_FILE")]:
        value = os.environ.get(name, "").strip()
        if value and ("-----BEGIN" in value or not Path(value).is_file()):
            missing.append(name)
    public_url = os.environ.get("PAYMENT_PUBLIC_URL", "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(public_url)
    if public_url and (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password):
        missing.append("PAYMENT_PUBLIC_URL(https_required)")
    return {"channel": channel, "ready": not missing, "missing": sorted(set(missing))}


def require_channel_configuration(channel: str) -> None:
    state = channel_configuration(channel)
    if not state["ready"]:
        raise PaymentConfigurationError(f"{channel} merchant configuration is incomplete: {', '.join(state['missing'])}")


def _read_secret_file(name: str) -> bytes:
    path_text = os.environ.get(name, "").strip()
    if not path_text or "-----BEGIN" in path_text:
        raise PaymentConfigurationError(f"{name} must point to a mounted secret file")
    path = Path(path_text)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PaymentConfigurationError(f"Unable to read {name}") from exc


def _private_key(name: str):
    try:
        return serialization.load_pem_private_key(_read_secret_file(name), password=None)
    except (TypeError, ValueError) as exc:
        raise PaymentConfigurationError(f"{name} is not a valid unencrypted PEM private key") from exc


def _public_key(name: str):
    payload = _read_secret_file(name)
    try:
        if b"BEGIN CERTIFICATE" in payload:
            return x509.load_pem_x509_certificate(payload).public_key()
        return serialization.load_pem_public_key(payload)
    except (TypeError, ValueError) as exc:
        raise PaymentConfigurationError(f"{name} is not a valid PEM public key or certificate") from exc


def _api_v3_key() -> bytes:
    key = _read_secret_file("WECHATPAY_API_V3_KEY_FILE").strip()
    if len(key) != 32:
        raise PaymentConfigurationError("WECHATPAY_API_V3_KEY_FILE must contain exactly 32 bytes")
    return key


def _sign_rsa2(payload: bytes, private_key_file: str) -> str:
    signature = _private_key(private_key_file).sign(payload, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def _verify_rsa2(payload: bytes, signature_text: str, public_key_file: str) -> None:
    try:
        signature = base64.b64decode(signature_text, validate=True)
        _public_key(public_key_file).verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise PaymentVerificationError("Invalid provider signature") from exc


def _money_to_cents(value: object) -> int:
    try:
        raw_amount = Decimal(str(value))
        amount = raw_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise PaymentVerificationError("Invalid payment amount") from exc
    if not raw_amount.is_finite() or raw_amount != amount or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise PaymentVerificationError("Invalid payment amount precision")
    return int(amount * 100)


def _cents_to_money(value: int) -> str:
    return f"{Decimal(int(value)) / Decimal(100):.2f}"


def _single_value_form(form: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in form.items():
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise PaymentVerificationError("Duplicate notification field")
            value = value[0]
        result[str(key)] = str(value)
    return result


def verify_alipay_notification(form: Mapping[str, object], raw_body: bytes = b"") -> PaymentNotification:
    require_channel_configuration("alipay")
    values = _single_value_form(form)
    signature = values.get("sign", "")
    if values.get("sign_type", "RSA2").upper() != "RSA2" or not signature:
        raise PaymentVerificationError("Alipay RSA2 signature is required")
    canonical = "&".join(
        f"{key}={values[key]}" for key in sorted(values) if key not in {"sign", "sign_type"} and values[key] != ""
    )
    _verify_rsa2(canonical.encode("utf-8"), signature, "ALIPAY_PUBLIC_KEY_FILE")

    required = ["notify_id", "app_id", "seller_id", "out_trade_no", "trade_no", "total_amount", "trade_status"]
    if any(not values.get(name) for name in required):
        raise PaymentVerificationError("Alipay notification is missing required fields")
    if values["app_id"] != os.environ["ALIPAY_APP_ID"].strip():
        raise PaymentVerificationError("Alipay app_id mismatch")
    if values["seller_id"] != os.environ["ALIPAY_SELLER_ID"].strip():
        raise PaymentVerificationError("Alipay seller_id mismatch")
    if values["trade_status"] not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        raise PaymentVerificationError("Alipay trade is not settled")
    return PaymentNotification(
        channel="alipay",
        event_id=values["notify_id"],
        merchant_order_no=values["out_trade_no"],
        provider_transaction_id=values["trade_no"],
        amount_cents=_money_to_cents(values["total_amount"]),
        currency="CNY",
        payload_sha256=hashlib.sha256(raw_body or canonical.encode("utf-8")).hexdigest(),
    )


def _casefold_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def _verify_wechat_signature(raw_body: bytes, headers: Mapping[str, str], now_timestamp: int | None = None) -> str:
    values = _casefold_headers(headers)
    timestamp_text = values.get("wechatpay-timestamp", "")
    nonce = values.get("wechatpay-nonce", "")
    serial = values.get("wechatpay-serial", "")
    signature = values.get("wechatpay-signature", "")
    if not all((timestamp_text, nonce, serial, signature)):
        raise PaymentVerificationError("Missing WeChat Pay signature headers")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise PaymentVerificationError("Invalid WeChat Pay timestamp") from exc
    tolerance = int(os.environ.get("WECHATPAY_CALLBACK_TOLERANCE_SECONDS", "300"))
    now_value = int(time.time()) if now_timestamp is None else int(now_timestamp)
    if tolerance < 1 or abs(now_value - timestamp) > tolerance:
        raise PaymentVerificationError("Stale WeChat Pay notification")
    expected_serial = os.environ["WECHATPAY_PLATFORM_SERIAL"].strip()
    if serial != expected_serial:
        raise PaymentVerificationError("WeChat Pay platform certificate serial mismatch")
    message = f"{timestamp_text}\n{nonce}\n".encode("utf-8") + raw_body + b"\n"
    _verify_rsa2(message, signature, "WECHATPAY_PLATFORM_PUBLIC_KEY_FILE")
    return serial


def _decrypt_wechat_resource(event: dict) -> dict:
    resource = event.get("resource")
    if not isinstance(resource, dict) or resource.get("algorithm") != "AEAD_AES_256_GCM":
        raise PaymentVerificationError("Unsupported WeChat Pay encrypted resource")
    try:
        ciphertext = base64.b64decode(str(resource["ciphertext"]), validate=True)
        nonce = str(resource["nonce"]).encode("utf-8")
        associated = str(resource.get("associated_data") or "").encode("utf-8")
        plaintext = AESGCM(_api_v3_key()).decrypt(nonce, ciphertext, associated)
        payload = json.loads(plaintext)
    except (KeyError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, InvalidTag) as exc:
        raise PaymentVerificationError("Unable to decrypt WeChat Pay resource") from exc
    if not isinstance(payload, dict):
        raise PaymentVerificationError("Invalid WeChat Pay resource payload")
    return payload


def verify_wechat_notification(
    raw_body: bytes,
    headers: Mapping[str, str],
    now_timestamp: int | None = None,
) -> PaymentNotification | RefundNotification:
    require_channel_configuration("wechat")
    serial = _verify_wechat_signature(raw_body, headers, now_timestamp)
    try:
        event = json.loads(raw_body)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaymentVerificationError("Invalid WeChat Pay notification JSON") from exc
    if not isinstance(event, dict) or not event.get("id") or not event.get("event_type"):
        raise PaymentVerificationError("Invalid WeChat Pay notification envelope")
    payload = _decrypt_wechat_resource(event)
    if payload.get("mchid") != os.environ["WECHATPAY_MCH_ID"].strip():
        raise PaymentVerificationError("WeChat Pay merchant id mismatch")
    payload_sha256 = hashlib.sha256(raw_body).hexdigest()
    event_type = str(event["event_type"])

    if event_type == "TRANSACTION.SUCCESS":
        amount = payload.get("amount")
        if payload.get("appid") != os.environ["WECHATPAY_APP_ID"].strip():
            raise PaymentVerificationError("WeChat Pay app id mismatch")
        if payload.get("trade_state") != "SUCCESS" or not isinstance(amount, dict):
            raise PaymentVerificationError("WeChat Pay trade is not settled")
        if amount.get("currency") != "CNY":
            raise PaymentVerificationError("WeChat Pay currency mismatch")
        required = [payload.get("out_trade_no"), payload.get("transaction_id")]
        if not all(required) or not isinstance(amount.get("total"), int):
            raise PaymentVerificationError("WeChat Pay notification is missing required fields")
        return PaymentNotification(
            channel="wechat",
            event_id=str(event["id"]),
            merchant_order_no=str(payload["out_trade_no"]),
            provider_transaction_id=str(payload["transaction_id"]),
            amount_cents=int(amount["total"]),
            currency="CNY",
            payload_sha256=payload_sha256,
            signature_serial=serial,
        )

    if event_type.startswith("REFUND."):
        amount = payload.get("amount")
        status = str(payload.get("refund_status", ""))
        if status not in {"SUCCESS", "CLOSED", "ABNORMAL"} or not isinstance(amount, dict):
            raise PaymentVerificationError("Invalid WeChat Pay refund state")
        currency = str(amount.get("currency") or "CNY")
        required = [payload.get("out_trade_no"), payload.get("out_refund_no"), payload.get("refund_id")]
        if not all(required) or not isinstance(amount.get("refund"), int):
            raise PaymentVerificationError("WeChat Pay refund notification is missing required fields")
        return RefundNotification(
            channel="wechat",
            event_id=str(event["id"]),
            merchant_order_no=str(payload["out_trade_no"]),
            merchant_refund_no=str(payload["out_refund_no"]),
            provider_refund_id=str(payload["refund_id"]),
            refund_status=status,
            amount_cents=int(amount["refund"]),
            currency=currency,
            payload_sha256=payload_sha256,
            signature_serial=serial,
        )
    raise PaymentVerificationError("Unsupported WeChat Pay event type")


def _http_request(request: urllib.request.Request, timeout: int = 15) -> tuple[int, Mapping[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read(2048)
        raise PaymentProviderError(f"Provider HTTP {exc.code}: {body.decode('utf-8', errors='replace')[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PaymentProviderError("Payment provider request failed") from exc


def _extract_alipay_response(body: bytes, response_key: str) -> dict:
    text = body.decode("utf-8")
    try:
        envelope = json.loads(text)
        signature = str(envelope["sign"])
        marker = json.dumps(response_key, ensure_ascii=False) + ":"
        start = text.index(marker) + len(marker)
        while start < len(text) and text[start].isspace():
            start += 1
        response_value, consumed = json.JSONDecoder().raw_decode(text[start:])
        signed_text = text[start : start + consumed]
    except (UnicodeDecodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise PaymentVerificationError("Invalid Alipay response envelope") from exc
    _verify_rsa2(signed_text.encode("utf-8"), signature, "ALIPAY_PUBLIC_KEY_FILE")
    if not isinstance(response_value, dict):
        raise PaymentVerificationError("Invalid Alipay response payload")
    return response_value


def _alipay_call(method: str, biz_content: dict, response_key: str) -> dict:
    require_channel_configuration("alipay")
    params = {
        "app_id": os.environ["ALIPAY_APP_ID"].strip(),
        "method": method,
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": os.environ["PAYMENT_PUBLIC_URL"].strip().rstrip("/") + "/api/payments/alipay/notify",
        "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
    }
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["sign"] = _sign_rsa2(canonical.encode("utf-8"), "ALIPAY_PRIVATE_KEY_FILE")
    gateway = os.environ.get("ALIPAY_GATEWAY_URL", "https://openapi.alipay.com/gateway.do").strip()
    request = urllib.request.Request(
        gateway,
        data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8", "Accept": "application/json"},
        method="POST",
    )
    status, _, body = _http_request(request)
    if status != 200:
        raise PaymentProviderError(f"Alipay returned HTTP {status}")
    response = _extract_alipay_response(body, response_key)
    if response.get("code") != "10000":
        raise PaymentProviderError(f"Alipay rejected request: {response.get('sub_code') or response.get('code')}")
    return response


def _verify_wechat_response(body: bytes, headers: Mapping[str, str]) -> None:
    values = _casefold_headers(headers)
    serial = values.get("wechatpay-serial", "")
    timestamp = values.get("wechatpay-timestamp", "")
    nonce = values.get("wechatpay-nonce", "")
    signature = values.get("wechatpay-signature", "")
    if serial != os.environ["WECHATPAY_PLATFORM_SERIAL"].strip() or not all((timestamp, nonce, signature)):
        raise PaymentVerificationError("Invalid WeChat Pay response signature headers")
    message = f"{timestamp}\n{nonce}\n".encode("utf-8") + body + b"\n"
    _verify_rsa2(message, signature, "WECHATPAY_PLATFORM_PUBLIC_KEY_FILE")


def _wechat_call(method: str, path: str, payload: dict) -> dict:
    require_channel_configuration("wechat")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    message = f"{method}\n{path}\n{timestamp}\n{nonce}\n".encode("utf-8") + body + b"\n"
    signature = _sign_rsa2(message, "WECHATPAY_PRIVATE_KEY_FILE")
    authorization = (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{os.environ["WECHATPAY_MCH_ID"].strip()}",'
        f'nonce_str="{nonce}",timestamp="{timestamp}",'
        f'serial_no="{os.environ["WECHATPAY_MERCHANT_SERIAL"].strip()}",signature="{signature}"'
    )
    base = os.environ.get("WECHATPAY_API_BASE", "https://api.mch.weixin.qq.com").strip().rstrip("/")
    request = urllib.request.Request(
        base + path,
        data=body,
        headers={"Authorization": authorization, "Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    status, headers, response_body = _http_request(request)
    _verify_wechat_response(response_body, headers)
    if status not in {200, 201, 202}:
        raise PaymentProviderError(f"WeChat Pay returned HTTP {status}")
    try:
        response = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise PaymentVerificationError("Invalid WeChat Pay response JSON") from exc
    if not isinstance(response, dict):
        raise PaymentVerificationError("Invalid WeChat Pay response payload")
    return response


def create_checkout(channel: str, merchant_order_no: str, amount_cents: int, subject: str) -> CheckoutResult:
    if channel == "alipay":
        response = _alipay_call(
            "alipay.trade.precreate",
            {"out_trade_no": merchant_order_no, "total_amount": _cents_to_money(amount_cents), "subject": subject},
            "alipay_trade_precreate_response",
        )
        checkout_url = str(response.get("qr_code") or "")
        if not checkout_url:
            raise PaymentProviderError("Alipay did not return a QR checkout URL")
        return CheckoutResult(checkout_url, str(response.get("out_trade_no") or merchant_order_no))
    if channel == "wechat":
        response = _wechat_call(
            "POST",
            "/v3/pay/transactions/native",
            {
                "appid": os.environ["WECHATPAY_APP_ID"].strip(),
                "mchid": os.environ["WECHATPAY_MCH_ID"].strip(),
                "description": subject,
                "out_trade_no": merchant_order_no,
                "notify_url": os.environ["PAYMENT_PUBLIC_URL"].strip().rstrip("/") + "/api/payments/wechat/notify",
                "amount": {"total": int(amount_cents), "currency": "CNY"},
            },
        )
        checkout_url = str(response.get("code_url") or "")
        if not checkout_url:
            raise PaymentProviderError("WeChat Pay did not return a Native checkout URL")
        return CheckoutResult(checkout_url)
    raise PaymentConfigurationError("Unsupported payment channel")


def initiate_refund(
    channel: str,
    merchant_order_no: str,
    provider_transaction_id: str | None,
    merchant_refund_no: str,
    amount_cents: int,
    reason: str,
) -> RefundStartResult:
    if channel == "alipay":
        response = _alipay_call(
            "alipay.trade.refund",
            {
                "out_trade_no": merchant_order_no,
                "refund_amount": _cents_to_money(amount_cents),
                "refund_reason": reason[:200],
                "out_request_no": merchant_refund_no,
            },
            "alipay_trade_refund_response",
        )
        reference = str(response.get("trade_no") or provider_transaction_id or merchant_order_no)
        return RefundStartResult("completed", reference, reference)
    if channel == "wechat":
        payload = {
            "out_refund_no": merchant_refund_no,
            "reason": reason[:80],
            "notify_url": os.environ["PAYMENT_PUBLIC_URL"].strip().rstrip("/") + "/api/payments/wechat/notify",
            "amount": {"refund": int(amount_cents), "total": int(amount_cents), "currency": "CNY"},
        }
        if provider_transaction_id:
            payload["transaction_id"] = provider_transaction_id
        else:
            payload["out_trade_no"] = merchant_order_no
        response = _wechat_call("POST", "/v3/refund/domestic/refunds", payload)
        status = str(response.get("status") or "PROCESSING")
        if status not in {"SUCCESS", "PROCESSING"}:
            raise PaymentProviderError(f"WeChat Pay refund state is {status}")
        provider_refund_id = str(response.get("refund_id") or "")
        if not provider_refund_id:
            raise PaymentProviderError("WeChat Pay did not return a refund id")
        return RefundStartResult("completed" if status == "SUCCESS" else "processing", provider_refund_id, provider_refund_id)
    raise PaymentConfigurationError("Unsupported payment channel")
