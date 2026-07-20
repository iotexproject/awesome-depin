#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
COMPOSE_OVERLAYS="${COMPOSE_OVERLAYS:-}"
MIN_FREE_DISK_PERCENT="${MIN_FREE_DISK_PERCENT:-15}"
MAX_BACKUP_AGE_HOURS="${MAX_BACKUP_AGE_HOURS:-30}"
BACKUP_DIR="${BACKUP_DIR:-}"
REQUIRED_SERVICES="${REQUIRED_SERVICES:-db,api,worker,web}"

[[ -f "$ENV_FILE" ]] || { echo "Environment file not found: $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

compose=(docker compose --env-file "$ENV_FILE")
if [[ -n "$COMPOSE_PROJECT_NAME" ]]; then
  compose+=(-p "$COMPOSE_PROJECT_NAME")
fi
compose+=(-f "$ROOT_DIR/docker-compose.yml")
if [[ -n "$COMPOSE_OVERLAYS" ]]; then
  IFS=':' read -r -a overlay_files <<< "$COMPOSE_OVERLAYS"
  for overlay in "${overlay_files[@]}"; do
    compose+=(-f "$overlay")
  done
fi

running_services="$("${compose[@]}" ps --status running --services)"
IFS=',' read -r -a required_services <<< "$REQUIRED_SERVICES"
for service in "${required_services[@]}"; do
  service="${service//[[:space:]]/}"
  [[ -n "$service" ]] || continue
  grep -qx "$service" <<< "$running_services" || { echo "FAIL service not running: $service" >&2; exit 1; }
  container_id="$("${compose[@]}" ps -q "$service")"
  health_status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
  [[ "$health_status" == "healthy" ]] || { echo "FAIL service is not healthy: $service ($health_status)" >&2; exit 1; }
done
echo "PASS Docker services healthy"

"${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -h 127.0.0.1 -uroot --silent' >/dev/null
echo "PASS MySQL ping"

local_url="${LOCAL_BASE_URL:-http://${WEB_BIND_HOST:-127.0.0.1}:${WEB_PORT:-8080}}"
local_url="${local_url%/}"
health="$(curl --fail --silent --show-error --max-time 15 "$local_url/api/health")"
grep -q '"ok":true' <<< "$health" || { echo "FAIL local API health" >&2; exit 1; }
echo "PASS local API health"

if [[ "${QTAIL_TLS_MODE:-domain_acme}" == "ip_certificate" ]]; then
  [[ -n "${QTAIL_PUBLIC_IP:-}" ]] || { echo "FAIL QTAIL_PUBLIC_IP is missing" >&2; exit 1; }
  certbot_config_dir="${QTAIL_CERTBOT_CONFIG_DIR:-/opt/qtail/certbot/config}"
  ip_certificate="$certbot_config_dir/live/$QTAIL_PUBLIC_IP/fullchain.pem"
  [[ -s "$ip_certificate" ]] || { echo "FAIL IP certificate is missing" >&2; exit 1; }
  openssl x509 -in "$ip_certificate" -noout -checkend "${QTAIL_CERT_MIN_VALIDITY_SECONDS:-172800}" >/dev/null || {
    echo "FAIL IP certificate expires inside the safety window" >&2
    exit 1
  }
  public_health="$(curl --fail --silent --show-error --max-time 20 \
    --resolve "$QTAIL_PUBLIC_IP:443:127.0.0.1" \
    "https://$QTAIL_PUBLIC_IP/api/health")"
  grep -q '"ok":true' <<< "$public_health" || { echo "FAIL trusted IP HTTPS health" >&2; exit 1; }
  echo "PASS trusted IP HTTPS and certificate validity"
fi

available_percent="$(df -Pk "$ROOT_DIR" | awk 'NR==2 {gsub(/%/,"",$5); print 100-$5}')"
(( available_percent >= MIN_FREE_DISK_PERCENT )) || { echo "FAIL free disk ${available_percent}% is below ${MIN_FREE_DISK_PERCENT}%" >&2; exit 1; }
echo "PASS disk capacity (${available_percent}% free)"

if [[ -n "$BACKUP_DIR" ]]; then
  latest_backup="$(find "$BACKUP_DIR" -type f -name 'qtail-*.tar.gz*' -print 2>/dev/null | sort | tail -n 1)"
  [[ -n "$latest_backup" ]] || { echo "FAIL no backup found in $BACKUP_DIR" >&2; exit 1; }
  now_epoch="$(date +%s)"
  if stat -f %m "$latest_backup" >/dev/null 2>&1; then
    backup_epoch="$(stat -f %m "$latest_backup")"
  else
    backup_epoch="$(stat -c %Y "$latest_backup")"
  fi
  backup_age_hours="$(( (now_epoch - backup_epoch) / 3600 ))"
  (( backup_age_hours <= MAX_BACKUP_AGE_HOURS )) || { echo "FAIL latest backup is ${backup_age_hours}h old" >&2; exit 1; }
  echo "PASS backup freshness (${backup_age_hours}h)"

  if [[ "${REQUIRE_OFFSITE_BACKUP:-0}" == "1" ]]; then
    offsite_receipt="${OFFSITE_BACKUP_RECEIPT_FILE:-$BACKUP_DIR/.offsite-latest.json}"
    [[ -f "$offsite_receipt" ]] || { echo "FAIL offsite backup receipt is missing: $offsite_receipt" >&2; exit 1; }
    receipt_source="$(python3 - "$offsite_receipt" <<'PY'
import json
from pathlib import Path
import sys

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if receipt.get("status") != "passed" or not receipt.get("source_file") or not receipt.get("source_sha256"):
    raise SystemExit("invalid offsite receipt")
print(receipt["source_file"])
PY
    )" || { echo "FAIL invalid offsite backup receipt" >&2; exit 1; }
    [[ "$receipt_source" == "$(basename "$latest_backup")" ]] || {
      echo "FAIL latest local backup has no matching offsite receipt" >&2
      exit 1
    }
    if stat -f %m "$offsite_receipt" >/dev/null 2>&1; then
      receipt_epoch="$(stat -f %m "$offsite_receipt")"
    else
      receipt_epoch="$(stat -c %Y "$offsite_receipt")"
    fi
    receipt_age_hours="$(( (now_epoch - receipt_epoch) / 3600 ))"
    (( receipt_age_hours <= MAX_BACKUP_AGE_HOURS )) || {
      echo "FAIL offsite backup receipt is ${receipt_age_hours}h old" >&2
      exit 1
    }
    echo "PASS offsite backup receipt (${receipt_age_hours}h)"
  fi
fi

if [[ -n "${PUBLIC_URL:-}" ]]; then
  public_curl=(curl --fail --silent --show-error --max-time 20)
  if [[ "${QTAIL_TLS_MODE:-domain_acme}" == "ip_certificate" && \
        "${PUBLIC_URL%/}" == "https://${QTAIL_PUBLIC_IP:-}" ]]; then
    # Alibaba ECS does not guarantee public-IP hairpin NAT. Keep the exact
    # public hostname and trust verification while reaching the local edge.
    public_curl+=(--resolve "$QTAIL_PUBLIC_IP:443:127.0.0.1")
  fi
  public_health="$("${public_curl[@]}" "${PUBLIC_URL%/}/api/health")"
  grep -q '"ok":true' <<< "$public_health" || { echo "FAIL public API health" >&2; exit 1; }
  echo "PASS public API health"
fi

echo "Q-Tail stack checks passed"
