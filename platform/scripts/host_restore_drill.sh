#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${QTAIL_ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SOURCE_ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
SOURCE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
SOURCE_OVERLAYS="${COMPOSE_OVERLAYS:-}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
REPORT_DIR="${RESTORE_DRILL_REPORT_DIR:-$ROOT_DIR/var/acceptance}"
API_IMAGE="${RESTORE_DRILL_API_IMAGE:-${SOURCE_PROJECT_NAME:-qtail-production}-api}"
MYSQL_IMAGE="${RESTORE_DRILL_MYSQL_IMAGE:-mysql:8.4}"

[[ -f "$SOURCE_ENV_FILE" ]] || { echo "Environment file not found: $SOURCE_ENV_FILE" >&2; exit 1; }
[[ -n "$SOURCE_PROJECT_NAME" ]] || { echo "COMPOSE_PROJECT_NAME is required" >&2; exit 1; }
docker image inspect "$API_IMAGE" >/dev/null 2>&1 || { echo "API image not found: $API_IMAGE" >&2; exit 1; }
docker image inspect "$MYSQL_IMAGE" >/dev/null 2>&1 || { echo "MySQL image not found: $MYSQL_IMAGE" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "$SOURCE_ENV_FILE"
set +a
[[ -n "${BACKUP_ENCRYPTION_PASSWORD:-}" ]] || {
  echo "BACKUP_ENCRYPTION_PASSWORD is required for the host restore drill" >&2
  exit 1
}

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-host-restore-drill.XXXXXX")"
drill_project="qtail-host-restore-drill-$$"
drill_env="$work_dir/.env.drill"
override_file="$work_dir/compose.drill.yml"
payment_secrets="$work_dir/payment-secrets"
backup_file="${RESTORE_DRILL_BACKUP_FILE:-}"

cleanup() {
  docker compose -p "$drill_project" --env-file "$drill_env" \
    -f "$ROOT_DIR/docker-compose.yml" -f "$override_file" \
    down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work_dir"
}
trap cleanup EXIT

free_port() {
  python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

mysql_port="$(free_port)"
mkdir -p "$payment_secrets" "$REPORT_DIR" "$BACKUP_DIR"
chmod 755 "$payment_secrets"

python3 - "$SOURCE_ENV_FILE" "$drill_env" "$mysql_port" "$payment_secrets" <<'PY'
from pathlib import Path
import sys

source, destination, mysql_port, payment_secrets = sys.argv[1:]
overrides = {
    "APP_ENV": "restore-drill",
    "SESSION_COOKIE_SECURE": "0",
    "MYSQL_BIND_HOST": "127.0.0.1",
    "MYSQL_EXPOSED_PORT": mysql_port,
    "QTAIL_WORKER_ENABLED": "0",
    "PAYMENT_MODE": "manual_qr_verification",
    "PAYMENT_PUBLIC_URL": "",
    "QTAIL_PAYMENT_SECRETS_DIR": payment_secrets,
}
output = []
seen = set()
for line in Path(source).read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in overrides:
        output.append(f"{key}={overrides[key]}")
        seen.add(key)
    else:
        output.append(line)
for key, value in overrides.items():
    if key not in seen:
        output.append(f"{key}={value}")
Path(destination).write_text("\n".join(output) + "\n", encoding="utf-8")
PY
chmod 600 "$drill_env"

# Docker Compose gives exported shell variables precedence over --env-file.
# The production environment was sourced above for credentials, so explicitly
# pin every drill-only value before creating the isolated project.
export APP_ENV=restore-drill
export SESSION_COOKIE_SECURE=0
export MYSQL_BIND_HOST=127.0.0.1
export MYSQL_EXPOSED_PORT="$mysql_port"
export QTAIL_WORKER_ENABLED=0
export PAYMENT_MODE=manual_qr_verification
export PAYMENT_PUBLIC_URL=
export QTAIL_PAYMENT_SECRETS_DIR="$payment_secrets"

cat > "$override_file" <<EOF
services:
  db:
    image: $MYSQL_IMAGE
    mem_limit: 384m
    command:
      - mysqld
      - --innodb-buffer-pool-size=128M
      - --performance-schema=OFF
      - --skip-log-bin
  api:
    image: $API_IMAGE
    mem_limit: 256m
EOF

if [[ -z "$backup_file" ]]; then
  echo "Creating a fresh encrypted production backup..."
  backup_output="$(ENV_FILE="$SOURCE_ENV_FILE" \
    COMPOSE_PROJECT_NAME="$SOURCE_PROJECT_NAME" \
    COMPOSE_OVERLAYS="$SOURCE_OVERLAYS" \
    BACKUP_DIR="$BACKUP_DIR" \
    "$ROOT_DIR/scripts/backup.sh")"
  echo "$backup_output"
  backup_file="$(printf '%s\n' "$backup_output" | sed -n 's/^Backup complete: //p' | tail -n 1)"
fi
[[ -f "$backup_file" ]] || { echo "Backup file not found: $backup_file" >&2; exit 1; }

BACKUP_ENCRYPTION_PASSWORD="$BACKUP_ENCRYPTION_PASSWORD" \
  ENV_FILE="$drill_env" "$ROOT_DIR/scripts/restore.sh" "$backup_file"

compose=(docker compose -p "$drill_project" --env-file "$drill_env"
  -f "$ROOT_DIR/docker-compose.yml" -f "$override_file")
"${compose[@]}" up -d --no-build --wait db api

RESTORE_MODE=restore \
RESTORE_CONFIRM=restore-qtail \
BACKUP_ENCRYPTION_PASSWORD="$BACKUP_ENCRYPTION_PASSWORD" \
ENV_FILE="$drill_env" \
COMPOSE_PROJECT_NAME="$drill_project" \
COMPOSE_OVERLAYS="$override_file" \
  "$ROOT_DIR/scripts/restore.sh" "$backup_file"

"${compose[@]}" exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=5).read()"

count_sql="SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM api_access_applications),(SELECT COUNT(*) FROM api_keys),(SELECT COUNT(*) FROM payment_orders),(SELECT COUNT(*) FROM invoice_requests),(SELECT COUNT(*) FROM refund_requests),(SELECT COUNT(*) FROM payment_provider_events),(SELECT COUNT(*) FROM generation_jobs),(SELECT COUNT(*) FROM generation_data_rights),(SELECT COUNT(*) FROM data_deletion_requests),(SELECT COUNT(*) FROM buyer_compliance_profiles),(SELECT COUNT(*) FROM legal_acceptances),(SELECT COUNT(*) FROM procurement_cases),(SELECT COUNT(*) FROM procurement_gate_evidence),(SELECT COUNT(*) FROM procurement_contracts),(SELECT COUNT(*) FROM audit_events);"
source_compose=(docker compose -p "$SOURCE_PROJECT_NAME" --env-file "$SOURCE_ENV_FILE" -f "$ROOT_DIR/docker-compose.yml")
source_counts="$("${source_compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "$1"' sh "$count_sql")"
drill_counts="$("${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "$1"' sh "$count_sql")"
[[ "$source_counts" == "$drill_counts" ]] || {
  echo "Restore row-count mismatch: source=$source_counts drill=$drill_counts" >&2
  exit 1
}

source_jobs="$("${source_compose[@]}" exec -T api sh -lc 'find "$QTAIL_JOBS_DIR" -type f | wc -l')"
drill_jobs="$("${compose[@]}" exec -T api sh -lc 'find "$QTAIL_JOBS_DIR" -type f | wc -l')"
[[ "$source_jobs" == "$drill_jobs" ]] || {
  echo "Restore delivery-file mismatch: source=$source_jobs drill=$drill_jobs" >&2
  exit 1
}

if command -v sha256sum >/dev/null 2>&1; then
  backup_sha256="$(sha256sum "$backup_file" | awk '{print $1}')"
else
  backup_sha256="$(shasum -a 256 "$backup_file" | awk '{print $1}')"
fi
run_id="$(date -u +%Y%m%dT%H%M%SZ)-host-restore"
report_file="$REPORT_DIR/$run_id.json"
python3 - "$report_file" "$run_id" "$backup_file" "$backup_sha256" "$source_counts" "$drill_counts" "$source_jobs" "$drill_jobs" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

report_file, run_id, backup_file, backup_sha256, source_counts, drill_counts, source_jobs, drill_jobs = sys.argv[1:]
labels = [
    "users", "api_access_applications", "api_keys", "payment_orders",
    "invoice_requests", "refund_requests", "payment_provider_events",
    "generation_jobs", "generation_data_rights", "data_deletion_requests",
    "buyer_compliance_profiles", "legal_acceptances", "procurement_cases",
    "procurement_gate_evidence", "procurement_contracts", "audit_events",
]

def counts(value):
    values = [int(item) for item in value.split()]
    if len(values) != len(labels):
        raise SystemExit(f"expected {len(labels)} counts, got {len(values)}")
    return dict(zip(labels, values))

report = {
    "status": "passed",
    "run_id": run_id,
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "mode": "isolated_host_restore",
    "production_volumes_modified": False,
    "backup_file": str(Path(backup_file).resolve()),
    "backup_sha256": backup_sha256,
    "source_counts": counts(source_counts),
    "restored_counts": counts(drill_counts),
    "source_delivery_files": int(source_jobs),
    "restored_delivery_files": int(drill_jobs),
}
Path(report_file).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
chmod 600 "$report_file"

echo "PASS isolated host restore drill"
echo "Database counts: $drill_counts"
echo "Delivery files: $drill_jobs"
echo "Report: $report_file"
