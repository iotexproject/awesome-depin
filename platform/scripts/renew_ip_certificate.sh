#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-qtail-production}"
CERTBOT_BIN="${CERTBOT_BIN:-/opt/qtail/certbot-venv/bin/certbot}"
CERTBOT_CONFIG_DIR="${QTAIL_CERTBOT_CONFIG_DIR:-/opt/qtail/certbot/config}"
CERTBOT_WORK_DIR="${QTAIL_CERTBOT_WORK_DIR:-/opt/qtail/certbot/work}"
CERTBOT_LOGS_DIR="${QTAIL_CERTBOT_LOGS_DIR:-/opt/qtail/certbot/logs}"
ACME_WEBROOT="${QTAIL_ACME_WEBROOT:-/opt/qtail/acme-webroot}"
MIN_VALIDITY_SECONDS="${QTAIL_CERT_MIN_VALIDITY_SECONDS:-172800}"

[[ -f "$ENV_FILE" ]] || { echo "Environment file not found: $ENV_FILE" >&2; exit 2; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[[ "${QTAIL_TLS_MODE:-domain_acme}" == "ip_certificate" ]] || {
  echo "IP certificate renewal skipped: QTAIL_TLS_MODE is not ip_certificate"
  exit 0
}
[[ -n "${QTAIL_PUBLIC_IP:-}" ]] || { echo "QTAIL_PUBLIC_IP is required" >&2; exit 2; }
[[ -x "$CERTBOT_BIN" ]] || { echo "Certbot executable not found: $CERTBOT_BIN" >&2; exit 2; }
[[ "$MIN_VALIDITY_SECONDS" =~ ^[0-9]+$ ]] || { echo "QTAIL_CERT_MIN_VALIDITY_SECONDS must be numeric" >&2; exit 2; }

if command -v flock >/dev/null 2>&1; then
  exec 7>"${CERT_RENEW_LOCK_FILE:-${TMPDIR:-/tmp}/qtail-ip-cert-renew.lock}"
  if ! flock -n 7; then
    echo "Q-Tail IP certificate renewal already running; overlapping invocation skipped"
    exit 0
  fi
fi

install -d -m 0755 "$ACME_WEBROOT"
install -d -m 0700 "$CERTBOT_CONFIG_DIR" "$CERTBOT_WORK_DIR" "$CERTBOT_LOGS_DIR"
certificate="$CERTBOT_CONFIG_DIR/live/$QTAIL_PUBLIC_IP/fullchain.pem"
before_sha256=""
if [[ -f "$certificate" ]]; then
  before_sha256="$(sha256sum "$certificate" | awk '{print $1}')"
fi

"$CERTBOT_BIN" certonly \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path "$ACME_WEBROOT" \
  --ip-address "$QTAIL_PUBLIC_IP" \
  --cert-name "$QTAIL_PUBLIC_IP" \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --keep-until-expiring \
  --config-dir "$CERTBOT_CONFIG_DIR" \
  --work-dir "$CERTBOT_WORK_DIR" \
  --logs-dir "$CERTBOT_LOGS_DIR"

private_key="$CERTBOT_CONFIG_DIR/live/$QTAIL_PUBLIC_IP/privkey.pem"
[[ -s "$certificate" && -s "$private_key" ]] || { echo "Renewed certificate files are missing" >&2; exit 1; }
openssl x509 -in "$certificate" -noout -checkend "$MIN_VALIDITY_SECONDS" >/dev/null || {
  echo "IP certificate has less than $MIN_VALIDITY_SECONDS seconds remaining" >&2
  exit 1
}
openssl x509 -in "$certificate" -noout -ext subjectAltName | grep -Fq "IP Address:$QTAIL_PUBLIC_IP" || {
  echo "IP certificate SAN does not match QTAIL_PUBLIC_IP" >&2
  exit 1
}

after_sha256="$(sha256sum "$certificate" | awk '{print $1}')"
if [[ "$after_sha256" != "$before_sha256" ]]; then
  ENV_FILE="$ENV_FILE" COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
    "$ROOT_DIR/scripts/production_stack.sh" restart-edge
  echo "PASS renewed IP certificate deployed to Caddy"
else
  echo "PASS IP certificate remains valid; renewal not yet due"
fi
echo "Certificate SHA-256: $after_sha256"
