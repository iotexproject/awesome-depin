# Q-Tail official merchant payment runbook

This runbook enables the already-implemented Alipay RSA2 and WeChat Pay API v3 paths. It does not claim that a real settlement or refund happened. Keep `PAYMENT_MODE=manual_qr_verification` until the final low-value live test is reconciled in both merchant consoles.

## Inputs the account owner must supply

Alipay:

- An activated web/face-to-face merchant application and its `ALIPAY_APP_ID`.
- The merchant's `ALIPAY_SELLER_ID`.
- The application RSA2 private key and the matching Alipay public key. Do not send either key in chat or put it in `.env`.
- Permission for `alipay.trade.precreate` and `alipay.trade.refund` as required by the signed product.

WeChat Pay:

- An activated direct merchant account, `WECHATPAY_MCH_ID`, and bound `WECHATPAY_APP_ID`.
- The merchant API certificate private key and `WECHATPAY_MERCHANT_SERIAL`.
- The current WeChat Pay platform public key/certificate and its exact `WECHATPAY_PLATFORM_SERIAL` or public-key ID.
- A 32-byte API v3 key.
- Native payment and domestic refund API permissions.

Shared:

- A real domain whose `https://<domain>/api/payments/.../notify` endpoints are reachable on port 443 from the public internet.
- On mainland-hosted origins, completed ICP/access filing and security-group/WAF rules that do not block distributed certificate validation or payment callbacks.

## Secret files

Create a host directory outside the release tree, then place exactly these files in it:

```text
/opt/qtail/secrets/payment/
  alipay_private_key.pem
  alipay_public_key.pem
  wechatpay_private_key.pem
  wechatpay_platform_public_key.pem
  wechatpay_api_v3.key
```

On Linux the API container runs as uid 10001. The production preflight requires the files to be owned by that uid and inaccessible to group/others:

```bash
chown -R 10001:10001 /opt/qtail/secrets/payment
chmod 700 /opt/qtail/secrets/payment
chmod 400 /opt/qtail/secrets/payment/*
```

The API v3 key file must contain exactly 32 bytes with no trailing newline. Never add these files to a release archive, image, Git repository, shell history, or support ticket.

## Environment

Set these values in the root-owned production environment file:

```dotenv
PAYMENT_MODE=official_merchant
PAYMENT_PUBLIC_URL=https://pay.example.com
QTAIL_PAYMENT_SECRETS_DIR=/opt/qtail/secrets/payment

ALIPAY_APP_ID=...
ALIPAY_SELLER_ID=...
ALIPAY_GATEWAY_URL=https://openapi.alipay.com/gateway.do

WECHATPAY_APP_ID=...
WECHATPAY_MCH_ID=...
WECHATPAY_MERCHANT_SERIAL=...
WECHATPAY_PLATFORM_SERIAL=...
WECHATPAY_API_BASE=https://api.mch.weixin.qq.com
```

`PAYMENT_PUBLIC_URL` must exactly equal `https://QTAIL_DOMAIN`. The service never accepts private keys inline in environment variables.

## Callback URLs

- Alipay: `https://<domain>/api/payments/alipay/notify`
- WeChat payment and refund: `https://<domain>/api/payments/wechat/notify`

The callback handlers verify signatures before touching an order. They then check app/merchant identity, platform certificate serial, merchant order number, CNY amount and business status. WeChat resources are decrypted with AES-256-GCM. `(channel, event_id)` is unique, and a second event for the same provider transaction cannot add Pro time again.

## Activation sequence

1. Leave `PAYMENT_MODE=manual_qr_verification` and deploy the release.
2. Install the merchant values and secret files.
3. Run `ENV_FILE=/etc/qtail/qtail.env scripts/server_preflight.sh`; fix every failure.
4. Confirm both callback URLs return a controlled `400/503` to unsigned probes, never `200`.
5. Set `PAYMENT_MODE=official_merchant` and restart with `scripts/production_stack.sh start`.
6. Use a new buyer account to pay the smallest merchant-approved amount in a controlled live test environment. Verify one `paid` order, one provider event and exactly one 30-day entitlement grant.
7. Submit and approve a refund. For WeChat, an accepted request remains `processing` until a signed success callback confirms the result. For Alipay, the signed synchronous response can complete it. Verify the merchant console, bank/settlement ledger, platform order, refund record and Pro entitlement agree.
8. Save redacted screenshots/merchant references and audit hashes. Never label mock-key or Docker results as real settlement evidence.

## Rotation and rollback

- Update the WeChat platform key and serial before the old platform certificate expires, then restart the API and run a signed callback test.
- Rotate merchant private keys using the merchant platforms' overlap procedure. Replace mounted files atomically; do not edit a key in place.
- If signature failures, amount mismatches or callback latency alarms appear, immediately set `PAYMENT_MODE=manual_qr_verification`, restart, and investigate. Existing official orders remain auditable; do not confirm them with the manual admin endpoint.
- Retry a failed refund with the same `merchant_refund_no`. Changing it can create a second channel refund.

## Claim boundary

Local RSA/AES fixtures and Docker tests prove implementation behavior only. Production payment completion requires real merchant credentials, a valid HTTPS callback domain, low-value live payment/refund, merchant-console reconciliation and an operator-signed acceptance record.
