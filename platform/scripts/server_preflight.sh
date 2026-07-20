#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PLATFORM_DIR/.env}"
OPERATIONS_ENV_FILE="${OPERATIONS_ENV_FILE:-}"
PREFLIGHT_MODE="${PREFLIGHT_MODE:-production}"
MIN_FREE_DISK_GIB="${MIN_FREE_DISK_GIB:-40}"
MIN_HOST_MEMORY_GIB="${MIN_HOST_MEMORY_GIB:-12}"
EXPECTED_PUBLIC_IP="${EXPECTED_PUBLIC_IP:-}"

fail() { echo "FAIL $*" >&2; exit 1; }
pass() { echo "PASS $*"; }

[[ "$PREFLIGHT_MODE" == "production" || "$PREFLIGHT_MODE" == "local" ]] || \
  fail "PREFLIGHT_MODE must be production or local"
[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"

for command in docker curl openssl python3 shasum sha256sum; do
  command -v "$command" >/dev/null || fail "required command is missing: $command"
done
docker info >/dev/null 2>&1 || fail "Docker engine is unavailable"
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is unavailable"
pass "Docker engine and required host commands"

if [[ "$(uname -s)" == "Linux" ]]; then
  env_mode="$(stat -c '%a' "$ENV_FILE")"
else
  env_mode="$(stat -f '%Lp' "$ENV_FILE")"
fi
(( (8#$env_mode & 077) == 0 )) || fail "$ENV_FILE must not be readable or writable by group/others (mode is $env_mode)"
pass "environment file permissions ($env_mode)"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -n "$OPERATIONS_ENV_FILE" ]]; then
  [[ -f "$OPERATIONS_ENV_FILE" ]] || fail "operations environment not found: $OPERATIONS_ENV_FILE"
  if [[ "$(uname -s)" == "Linux" ]]; then
    operations_mode="$(stat -c '%a' "$OPERATIONS_ENV_FILE")"
  else
    operations_mode="$(stat -f '%Lp' "$OPERATIONS_ENV_FILE")"
  fi
  (( (8#$operations_mode & 077) == 0 )) || \
    fail "$OPERATIONS_ENV_FILE must not be readable or writable by group/others (mode is $operations_mode)"
  set -a
  # shellcheck disable=SC1090
  source "$OPERATIONS_ENV_FILE"
  set +a
  pass "operations environment permissions ($operations_mode)"
fi

for flag in REQUIRE_ALERT_WEBHOOK REQUIRE_OFFSITE_BACKUP OFFSITE_VERIFY_DOWNLOAD REQUIRE_SYNTHETIC_CATALOG; do
  value="${!flag:-0}"
  [[ "$value" == "0" || "$value" == "1" ]] || fail "$flag must be 0 or 1"
done
if [[ "${REQUIRE_ALERT_WEBHOOK:-0}" == "1" && -z "${ALERT_WEBHOOK_URL:-}" ]]; then
  fail "ALERT_WEBHOOK_URL is required when REQUIRE_ALERT_WEBHOOK=1"
fi
if [[ -n "${ALERT_WEBHOOK_URL:-}" && "$ALERT_WEBHOOK_URL" != https://* ]]; then
  fail "ALERT_WEBHOOK_URL must use HTTPS"
fi
if [[ -n "${MONITOR_HEARTBEAT_URL:-}" && "$MONITOR_HEARTBEAT_URL" != https://* ]]; then
  fail "MONITOR_HEARTBEAT_URL must use HTTPS"
fi
if [[ "${REQUIRE_OFFSITE_BACKUP:-0}" == "1" && -z "${OFFSITE_BACKUP_URI:-}" ]]; then
  fail "OFFSITE_BACKUP_URI is required when REQUIRE_OFFSITE_BACKUP=1"
fi
if [[ -n "${OFFSITE_BACKUP_URI:-}" ]]; then
  [[ -n "${BACKUP_ENCRYPTION_PASSWORD:-}" ]] || fail "offsite backup requires BACKUP_ENCRYPTION_PASSWORD"
  case "$OFFSITE_BACKUP_URI" in
    file:///*)
      ;;
    s3://*)
      command -v aws >/dev/null 2>&1 || fail "aws CLI is required for s3:// offsite backup"
      ;;
    oss://*)
      command -v ossutil >/dev/null 2>&1 || fail "ossutil is required for oss:// offsite backup"
      ;;
    *)
      fail "OFFSITE_BACKUP_URI must use file://, s3://, or oss://"
      ;;
  esac
fi
if [[ -n "${BACKUP_READ_GROUP:-}" ]]; then
  command -v getent >/dev/null 2>&1 || fail "getent is required for BACKUP_READ_GROUP"
  getent group "$BACKUP_READ_GROUP" >/dev/null 2>&1 || fail "BACKUP_READ_GROUP does not exist"
fi
pass "external alert and offsite-backup configuration"

if [[ "${REQUIRE_SYNTHETIC_CATALOG:-0}" == "1" ]]; then
  catalog_dir="${QTAIL_SYNTHETIC_CATALOG_HOST_DIR:-$PLATFORM_DIR/var/catalog}"
  if [[ "$catalog_dir" != /* ]]; then
    catalog_dir="$PLATFORM_DIR/${catalog_dir#./}"
  fi
  if [[ "$PREFLIGHT_MODE" == "production" ]]; then
    [[ "${QTAIL_SYNTHETIC_CATALOG_HOST_DIR:-}" == /* ]] || \
      fail "QTAIL_SYNTHETIC_CATALOG_HOST_DIR must be absolute in production when the catalog is required"
  fi
  catalog_filename="${QTAIL_SYNTHETIC_CATALOG_FILENAME:-qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz}"
  catalog_expected_bytes="${QTAIL_SYNTHETIC_CATALOG_BYTES:-56447787}"
  catalog_expected_sha256="${QTAIL_SYNTHETIC_CATALOG_SHA256:-c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0}"
  [[ "$catalog_filename" == "qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz" ]] || fail "unexpected synthetic catalog filename"
  [[ "$catalog_expected_bytes" =~ ^[0-9]+$ ]] || fail "QTAIL_SYNTHETIC_CATALOG_BYTES must be an integer"
  [[ "$catalog_expected_sha256" =~ ^[0-9a-f]{64}$ ]] || fail "QTAIL_SYNTHETIC_CATALOG_SHA256 must be lowercase SHA-256"
  catalog_file="$catalog_dir/$catalog_filename"
  [[ -d "$catalog_dir" ]] || fail "required synthetic catalog directory is missing: $catalog_dir"
  [[ -f "$catalog_file" ]] || fail "required synthetic catalog is missing: $catalog_file"
  if [[ "$(uname -s)" == "Linux" ]]; then
    catalog_actual_bytes="$(stat -c '%s' "$catalog_file")"
    catalog_dir_mode="$(stat -c '%a' "$catalog_dir")"
    catalog_file_mode="$(stat -c '%a' "$catalog_file")"
  else
    catalog_actual_bytes="$(stat -f '%z' "$catalog_file")"
    catalog_dir_mode="$(stat -f '%Lp' "$catalog_dir")"
    catalog_file_mode="$(stat -f '%Lp' "$catalog_file")"
  fi
  # API/Worker run as an unprivileged uid that does not share the host root
  # group. A root-readable bind mount can therefore exist while the application
  # sees the catalog as missing. Require traverse/list permission on the mount
  # root and read permission on the public sample file before Compose starts.
  catalog_dir_other="${catalog_dir_mode: -1}"
  catalog_file_other="${catalog_file_mode: -1}"
  (( (8#$catalog_dir_other & 5) == 5 )) || \
    fail "synthetic catalog directory must be readable/traversable by the non-root container user (mode is $catalog_dir_mode)"
  (( (8#$catalog_file_other & 4) == 4 )) || \
    fail "synthetic catalog file must be readable by the non-root container user (mode is $catalog_file_mode)"
  [[ "$catalog_actual_bytes" == "$catalog_expected_bytes" ]] || fail "synthetic catalog byte size mismatch"
  catalog_actual_sha256="$(sha256sum "$catalog_file" | awk '{print $1}')"
  [[ "$catalog_actual_sha256" == "$catalog_expected_sha256" ]] || fail "synthetic catalog SHA-256 mismatch"
  pass "required synthetic catalog integrity and container readability ($catalog_actual_bytes bytes, $catalog_actual_sha256; modes $catalog_dir_mode/$catalog_file_mode)"
else
  pass "synthetic catalog is optional for this preflight"
fi

required_values=(APP_ENV APP_SECRET ADMIN_TOKEN SESSION_COOKIE_SECURE MYSQL_DATABASE MYSQL_USER MYSQL_PASSWORD MYSQL_ROOT_PASSWORD QTAIL_DOMAIN)
for name in "${required_values[@]}"; do
  [[ -n "${!name:-}" ]] || fail "$name is empty"
done

[[ "$APP_ENV" == "production" ]] || fail "APP_ENV must be production"
[[ "$SESSION_COOKIE_SECURE" == "1" ]] || fail "SESSION_COOKIE_SECURE must be 1"
[[ "${QTAIL_FAKE_GENERATOR:-0}" == "0" ]] || fail "QTAIL_FAKE_GENERATOR must be 0"
[[ "${QTAIL_WORKER_ENABLED:-1}" == "1" ]] || fail "QTAIL_WORKER_ENABLED must be 1"
ingress_mode="${QTAIL_INGRESS_MODE:-caddy}"
[[ "$ingress_mode" == "caddy" || "$ingress_mode" == "cloudflare" ]] || \
  fail "QTAIL_INGRESS_MODE must be caddy or cloudflare"
tls_mode="${QTAIL_TLS_MODE:-domain_acme}"
alt_https_port="${QTAIL_ALT_HTTPS_PORT:-}"
if [[ "$ingress_mode" == "caddy" ]]; then
  [[ "$tls_mode" == "domain_acme" || "$tls_mode" == "ip_certificate" ]] || \
    fail "QTAIL_TLS_MODE must be domain_acme or ip_certificate"
  if [[ -n "$alt_https_port" ]]; then
    [[ "$alt_https_port" =~ ^[0-9]+$ ]] && (( alt_https_port >= 1024 && alt_https_port <= 65535 )) || \
      fail "QTAIL_ALT_HTTPS_PORT must be an integer from 1024 through 65535"
    [[ "$alt_https_port" != "${HTTP_PORT:-80}" && "$alt_https_port" != "${HTTPS_PORT:-443}" ]] || \
      fail "QTAIL_ALT_HTTPS_PORT must differ from HTTP_PORT and HTTPS_PORT"
  fi
else
  [[ "$tls_mode" == "domain_acme" ]] || fail "Cloudflare ingress requires QTAIL_TLS_MODE=domain_acme"
  [[ -z "$alt_https_port" ]] || fail "QTAIL_ALT_HTTPS_PORT is only valid for Caddy ingress"
fi
if [[ "$tls_mode" == "ip_certificate" ]]; then
  [[ -n "${QTAIL_PUBLIC_IP:-}" ]] || fail "QTAIL_PUBLIC_IP is required for IP TLS"
  python3 - "$QTAIL_PUBLIC_IP" <<'PY' >/dev/null || fail "QTAIL_PUBLIC_IP must be a public IPv4 address"
import ipaddress
import sys

value = ipaddress.ip_address(sys.argv[1])
if value.version != 4 or not value.is_global:
    raise SystemExit(1)
PY
  certbot_config_dir="${QTAIL_CERTBOT_CONFIG_DIR:-/opt/qtail/certbot/config}"
  acme_webroot="${QTAIL_ACME_WEBROOT:-/opt/qtail/acme-webroot}"
  ip_certificate="$certbot_config_dir/live/$QTAIL_PUBLIC_IP/fullchain.pem"
  ip_private_key="$certbot_config_dir/live/$QTAIL_PUBLIC_IP/privkey.pem"
  [[ -s "$ip_certificate" && -s "$ip_private_key" ]] || fail "IP certificate files are missing"
  [[ -d "$acme_webroot" ]] || fail "QTAIL_ACME_WEBROOT does not exist"
  openssl x509 -in "$ip_certificate" -noout -checkend "${QTAIL_CERT_MIN_VALIDITY_SECONDS:-172800}" >/dev/null || \
    fail "IP certificate expires inside the configured safety window"
  openssl x509 -in "$ip_certificate" -noout -ext subjectAltName | grep -Fq "IP Address:$QTAIL_PUBLIC_IP" || \
    fail "IP certificate SAN does not match QTAIL_PUBLIC_IP"
  cert_public_sha="$(openssl x509 -in "$ip_certificate" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
  key_public_sha="$(openssl pkey -in "$ip_private_key" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
  [[ -n "$cert_public_sha" && "$cert_public_sha" == "$key_public_sha" ]] || fail "IP certificate and private key do not match"
fi
[[ "${#APP_SECRET}" -ge 32 ]] || fail "APP_SECRET must be at least 32 characters"
[[ "${#ADMIN_TOKEN}" -ge 32 ]] || fail "ADMIN_TOKEN must be at least 32 characters"
[[ "${#MYSQL_PASSWORD}" -ge 20 ]] || fail "MYSQL_PASSWORD must be at least 20 characters"
[[ "${#MYSQL_ROOT_PASSWORD}" -ge 20 ]] || fail "MYSQL_ROOT_PASSWORD must be at least 20 characters"

payment_mode="${PAYMENT_MODE:-manual_qr_verification}"
[[ "$payment_mode" == "manual_qr_verification" || "$payment_mode" == "official_merchant" ]] || \
  fail "PAYMENT_MODE must be manual_qr_verification or official_merchant"
if [[ "$payment_mode" == "official_merchant" ]]; then
  [[ "$tls_mode" == "domain_acme" ]] || fail "official merchant payment requires an owned HTTPS domain, not the IP-certificate mode"
  payment_required_values=(PAYMENT_PUBLIC_URL ALIPAY_APP_ID ALIPAY_SELLER_ID WECHATPAY_APP_ID WECHATPAY_MCH_ID WECHATPAY_MERCHANT_SERIAL WECHATPAY_PLATFORM_SERIAL)
  for name in "${payment_required_values[@]}"; do
    [[ -n "${!name:-}" ]] || fail "$name is required for official merchant payment mode"
  done
  [[ "$PAYMENT_PUBLIC_URL" == "https://$QTAIL_DOMAIN" ]] || \
    fail "PAYMENT_PUBLIC_URL must exactly match https://QTAIL_DOMAIN"
  payment_secret_dir="${QTAIL_PAYMENT_SECRETS_DIR:-$PLATFORM_DIR/var/secrets/payment}"
  if [[ "$payment_secret_dir" != /* ]]; then
    payment_secret_dir="$PLATFORM_DIR/${payment_secret_dir#./}"
  fi
  payment_secret_files=(alipay_private_key.pem alipay_public_key.pem wechatpay_private_key.pem wechatpay_platform_public_key.pem wechatpay_api_v3.key)
  for filename in "${payment_secret_files[@]}"; do
    secret_file="$payment_secret_dir/$filename"
    [[ -s "$secret_file" ]] || fail "official payment secret file is missing: $secret_file"
    if [[ "$(uname -s)" == "Linux" ]]; then
      secret_mode="$(stat -c '%a' "$secret_file")"
      secret_owner="$(stat -c '%u' "$secret_file")"
      [[ "$secret_owner" == "10001" ]] || fail "$secret_file must be owned by container uid 10001"
    else
      secret_mode="$(stat -f '%Lp' "$secret_file")"
    fi
    (( (8#$secret_mode & 077) == 0 )) || fail "$secret_file must not be accessible by group/others (mode is $secret_mode)"
  done
  [[ "$(wc -c < "$payment_secret_dir/wechatpay_api_v3.key" | tr -d ' ')" == "32" ]] || \
    fail "wechatpay_api_v3.key must contain exactly 32 bytes"
  openssl pkey -in "$payment_secret_dir/alipay_private_key.pem" -noout >/dev/null 2>&1 || fail "invalid Alipay private key"
  openssl pkey -in "$payment_secret_dir/wechatpay_private_key.pem" -noout >/dev/null 2>&1 || fail "invalid WeChat Pay private key"
  openssl pkey -pubin -in "$payment_secret_dir/alipay_public_key.pem" -noout >/dev/null 2>&1 || fail "invalid Alipay public key"
  if ! openssl pkey -pubin -in "$payment_secret_dir/wechatpay_platform_public_key.pem" -noout >/dev/null 2>&1; then
    openssl x509 -in "$payment_secret_dir/wechatpay_platform_public_key.pem" -noout >/dev/null 2>&1 || fail "invalid WeChat Pay platform public key/certificate"
  fi
fi

for value in "$APP_SECRET" "$ADMIN_TOKEN" "$MYSQL_PASSWORD" "$MYSQL_ROOT_PASSWORD"; do
  case "$value" in
    *replace-with*|*change-me*|*unsafe*|*example*|*password*)
      fail "placeholder or weak literal detected in production secret values"
      ;;
  esac
done
[[ "${MYSQL_BIND_HOST:-127.0.0.1}" == "127.0.0.1" ]] || fail "MYSQL_BIND_HOST must remain 127.0.0.1"
[[ "${WEB_BIND_HOST:-127.0.0.1}" == "127.0.0.1" ]] || fail "WEB_BIND_HOST must remain 127.0.0.1"
if [[ "$ingress_mode" == "cloudflare" ]]; then
  tunnel_token="${CLOUDFLARE_TUNNEL_TOKEN:-}"
  tunnel_token_file="${CLOUDFLARE_TUNNEL_TOKEN_FILE:-$PLATFORM_DIR/var/secrets/cloudflare_tunnel_token}"
  if [[ "$tunnel_token_file" != /* ]]; then
    tunnel_token_file="$PLATFORM_DIR/${tunnel_token_file#./}"
  fi
  export CLOUDFLARE_TUNNEL_TOKEN_FILE="$tunnel_token_file"
  if [[ -z "$tunnel_token" && -s "$tunnel_token_file" ]]; then
    if [[ "$(uname -s)" == "Linux" ]]; then
      tunnel_token_file_mode="$(stat -c '%a' "$tunnel_token_file")"
    else
      tunnel_token_file_mode="$(stat -f '%Lp' "$tunnel_token_file")"
    fi
    (( (8#$tunnel_token_file_mode & 077) == 0 )) || \
      fail "$tunnel_token_file must not be accessible by group/others (mode is $tunnel_token_file_mode)"
    tunnel_token="$(<"$tunnel_token_file")"
  fi
  [[ "${#tunnel_token}" -ge 80 ]] || fail "CLOUDFLARE_TUNNEL_TOKEN is missing or too short"
  case "$tunnel_token" in
    *replace-with*|*change-me*|*example*) fail "placeholder Cloudflare Tunnel token detected" ;;
  esac
fi
pass "production secrets, payment mode, cookies, generator mode, and private upstream bindings"

if [[ "$PREFLIGHT_MODE" == "production" ]]; then
  if [[ "$tls_mode" == "domain_acme" ]]; then
    [[ "$QTAIL_DOMAIN" != "localhost" && "$QTAIL_DOMAIN" != *.example.com ]] || fail "QTAIL_DOMAIN must be a real production domain"
  fi
  if [[ "$ingress_mode" == "caddy" ]]; then
    [[ "${HTTP_PORT:-80}" == "80" && "${HTTPS_PORT:-443}" == "443" ]] || fail "production Caddy edge must publish ports 80 and 443"
    if [[ "$tls_mode" == "ip_certificate" && -n "$EXPECTED_PUBLIC_IP" ]]; then
      [[ "$QTAIL_PUBLIC_IP" == "$EXPECTED_PUBLIC_IP" ]] || fail "QTAIL_PUBLIC_IP does not match EXPECTED_PUBLIC_IP"
    fi
  elif [[ -n "$EXPECTED_PUBLIC_IP" ]]; then
    fail "EXPECTED_PUBLIC_IP is not valid for Cloudflare ingress; DNS resolves to Cloudflare, not the origin host"
  fi
fi

if [[ "$tls_mode" == "ip_certificate" ]]; then
  resolved_ips="$QTAIL_PUBLIC_IP"
else
  resolved_ips="$(python3 - "$QTAIL_DOMAIN" <<'PY'
import socket, sys
try:
    values = sorted({item[4][0] for item in socket.getaddrinfo(sys.argv[1], None, socket.AF_INET, socket.SOCK_STREAM)})
except socket.gaierror:
    values = []
print("\n".join(values))
PY
)"
fi
if [[ "$PREFLIGHT_MODE" == "production" ]]; then
  [[ -n "$resolved_ips" ]] || fail "QTAIL_DOMAIN does not resolve to an IPv4 address"
  if [[ "$ingress_mode" == "caddy" && "$tls_mode" == "domain_acme" && -n "$EXPECTED_PUBLIC_IP" ]]; then
    grep -Fxq "$EXPECTED_PUBLIC_IP" <<< "$resolved_ips" || \
      fail "QTAIL_DOMAIN does not resolve to EXPECTED_PUBLIC_IP=$EXPECTED_PUBLIC_IP"
  fi
  pass "domain resolves (${resolved_ips//$'\n'/, })"
else
  pass "local-mode domain resolution check (${resolved_ips:-not required})"
fi

available_kib="$(df -Pk "$PLATFORM_DIR" | awk 'NR==2 {print $4}')"
required_kib="$((MIN_FREE_DISK_GIB * 1024 * 1024))"
(( available_kib >= required_kib )) || fail "free disk is below ${MIN_FREE_DISK_GIB} GiB"

memory_bytes="$(docker info --format '{{.MemTotal}}')"
required_memory_bytes="$((MIN_HOST_MEMORY_GIB * 1024 * 1024 * 1024))"
(( memory_bytes >= required_memory_bytes )) || fail "Docker memory is below ${MIN_HOST_MEMORY_GIB} GiB"
pass "capacity floor (${MIN_FREE_DISK_GIB} GiB free disk, ${MIN_HOST_MEMORY_GIB} GiB Docker memory)"

for path in \
  "$PLATFORM_DIR/public/pay/alipay.jpg" \
  "$PLATFORM_DIR/public/pay/wechat.jpg" \
  "$PLATFORM_DIR/../data/uploaded_data.csv" \
  "$PLATFORM_DIR/../results/openx_strong_training/openx_demo_training_report.json" \
  "$PLATFORM_DIR/../results/openx_strong_training/openx_shard_training_rows.csv"; do
  [[ -s "$path" ]] || fail "required runtime/evidence asset is missing or empty: $path"
done
pass "payment and model runtime assets"

python3 "$PLATFORM_DIR/scripts/verify_buyer_pilot_kit.py" >/dev/null
pass "buyer procurement pilot kit integrity and non-evidence defaults"

compose=(docker compose -p qtail-preflight --env-file "$ENV_FILE"
  -f "$PLATFORM_DIR/docker-compose.yml"
  -f "$PLATFORM_DIR/docker-compose.production.yml")
host_profile="${QTAIL_HOST_PROFILE:-standard}"
case "$host_profile" in
  standard) ;;
  ecs-small) compose+=(-f "$PLATFORM_DIR/docker-compose.ecs-small.yml") ;;
  *) fail "QTAIL_HOST_PROFILE must be standard or ecs-small" ;;
esac
if [[ "$ingress_mode" == "caddy" ]]; then
  compose+=(-f "$PLATFORM_DIR/docker-compose.edge.yml")
  if [[ "$tls_mode" == "ip_certificate" ]]; then
    compose+=(-f "$PLATFORM_DIR/docker-compose.ip-tls.yml")
  fi
  if [[ -n "$alt_https_port" ]]; then
    compose+=(-f "$PLATFORM_DIR/docker-compose.alt-https.yml")
  fi
else
  compose+=(-f "$PLATFORM_DIR/docker-compose.cloudflare.yml")
fi
"${compose[@]}" config --quiet
pass "production Compose rendering"

if [[ "$ingress_mode" == "caddy" ]]; then
  if [[ "$tls_mode" == "ip_certificate" ]]; then
    docker run --rm \
      -v "$PLATFORM_DIR/deploy/caddy/Caddyfile.ip:/etc/caddy/Caddyfile:ro" \
      -v "$certbot_config_dir:/etc/letsencrypt:ro" \
      -v "$acme_webroot:/srv/acme:ro" \
      -e "QTAIL_PUBLIC_IP=$QTAIL_PUBLIC_IP" \
      caddy:2.10.2-alpine caddy validate --config /etc/caddy/Caddyfile >/dev/null
  else
    docker run --rm \
      -v "$PLATFORM_DIR/deploy/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
      -e "QTAIL_DOMAIN=$QTAIL_DOMAIN" \
      caddy:2.10.2-alpine caddy validate --config /etc/caddy/Caddyfile >/dev/null
  fi
  pass "Caddy edge configuration"
else
  pass "Cloudflare named-tunnel configuration"
fi

echo "Q-Tail server preflight passed ($PREFLIGHT_MODE mode)"
