#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
SOURCE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
DRILL_PASSWORD="${BACKUP_ENCRYPTION_PASSWORD:-qtail-local-restore-drill-only}"

[[ -f "$SOURCE_ENV_FILE" ]] || { echo "Environment file not found: $SOURCE_ENV_FILE" >&2; exit 1; }
[[ -n "$SOURCE_PROJECT_NAME" ]] || { echo "COMPOSE_PROJECT_NAME is required to identify the source stack" >&2; exit 1; }

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-restore-drill.XXXXXX")"
drill_project="qtail-restore-drill-$$"
drill_env="$work_dir/.env.drill"
backup_dir="$work_dir/backups"

free_port() {
  python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

web_port="$(free_port)"
mysql_port="$(free_port)"

cleanup() {
  docker compose -p "$drill_project" --env-file "$drill_env" -f "$ROOT_DIR/docker-compose.yml" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work_dir"
}
trap cleanup EXIT

python3 - "$SOURCE_ENV_FILE" "$drill_env" "$web_port" "$mysql_port" <<'PY'
from pathlib import Path
import sys

source, destination, web_port, mysql_port = sys.argv[1:]
lines = Path(source).read_text(encoding="utf-8").splitlines()
overrides = {
    "APP_ENV": "restore-drill",
    "SESSION_COOKIE_SECURE": "0",
    "WEB_BIND_HOST": "127.0.0.1",
    "WEB_PORT": web_port,
    "MYSQL_BIND_HOST": "127.0.0.1",
    "MYSQL_EXPOSED_PORT": mysql_port,
    "QTAIL_WORKER_ENABLED": "0",
    "PAYMENT_MODE": "manual_qr_verification",
    "PAYMENT_PUBLIC_URL": "",
    "QTAIL_PAYMENT_SECRETS_DIR": str(Path(destination).parent / "payment-secrets"),
}
seen = set()
output = []
for line in lines:
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

echo "Creating encrypted source backup..."
backup_output="$(ENV_FILE="$SOURCE_ENV_FILE" COMPOSE_PROJECT_NAME="$SOURCE_PROJECT_NAME" BACKUP_DIR="$backup_dir" BACKUP_ENCRYPTION_PASSWORD="$DRILL_PASSWORD" "$ROOT_DIR/scripts/backup.sh")"
echo "$backup_output"
backup_file="$(find "$backup_dir" -type f -name 'qtail-*.tar.gz.enc' | sort | tail -n 1)"
[[ -n "$backup_file" ]] || { echo "Encrypted backup was not created" >&2; exit 1; }

BACKUP_ENCRYPTION_PASSWORD="$DRILL_PASSWORD" ENV_FILE="$drill_env" "$ROOT_DIR/scripts/restore.sh" "$backup_file"

docker compose -p "$drill_project" --env-file "$drill_env" -f "$ROOT_DIR/docker-compose.yml" up -d --build

for _attempt in $(seq 1 60); do
  if curl --fail --silent --max-time 3 "http://127.0.0.1:$web_port/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:$web_port/api/health" >/dev/null

RESTORE_MODE=restore RESTORE_CONFIRM=restore-qtail BACKUP_ENCRYPTION_PASSWORD="$DRILL_PASSWORD" ENV_FILE="$drill_env" COMPOSE_PROJECT_NAME="$drill_project" "$ROOT_DIR/scripts/restore.sh" "$backup_file"
"$ROOT_DIR/scripts/smoke.sh" "http://127.0.0.1:$web_port"

count_sql="SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM api_access_applications),(SELECT COUNT(*) FROM api_keys),(SELECT COUNT(*) FROM payment_orders),(SELECT COUNT(*) FROM invoice_requests),(SELECT COUNT(*) FROM refund_requests),(SELECT COUNT(*) FROM payment_provider_events),(SELECT COUNT(*) FROM generation_jobs),(SELECT COUNT(*) FROM generation_data_rights),(SELECT COUNT(*) FROM data_deletion_requests),(SELECT COUNT(*) FROM buyer_compliance_profiles),(SELECT COUNT(*) FROM legal_acceptances),(SELECT COUNT(*) FROM procurement_cases),(SELECT COUNT(*) FROM procurement_gate_evidence),(SELECT COUNT(*) FROM procurement_contracts),(SELECT COUNT(*) FROM audit_events);"
source_counts="$(docker compose -p "$SOURCE_PROJECT_NAME" --env-file "$SOURCE_ENV_FILE" -f "$ROOT_DIR/docker-compose.yml" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "$1"' sh "$count_sql")"
drill_counts="$(docker compose -p "$drill_project" --env-file "$drill_env" -f "$ROOT_DIR/docker-compose.yml" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "$1"' sh "$count_sql")"
[[ "$source_counts" == "$drill_counts" ]] || { echo "Restore row-count mismatch: source=$source_counts drill=$drill_counts" >&2; exit 1; }

source_jobs="$(docker compose -p "$SOURCE_PROJECT_NAME" --env-file "$SOURCE_ENV_FILE" -f "$ROOT_DIR/docker-compose.yml" exec -T api sh -lc 'find "$QTAIL_JOBS_DIR" -type f | wc -l')"
drill_jobs="$(docker compose -p "$drill_project" --env-file "$drill_env" -f "$ROOT_DIR/docker-compose.yml" exec -T api sh -lc 'find "$QTAIL_JOBS_DIR" -type f | wc -l')"
[[ "$source_jobs" == "$drill_jobs" ]] || { echo "Restore delivery-file mismatch: source=$source_jobs drill=$drill_jobs" >&2; exit 1; }

echo "PASS isolated destructive restore drill"
echo "Database counts (users,applications,keys,orders,invoices,refunds,provider_events,jobs,data_rights,deletions,compliance_profiles,legal_acceptances,cases,evidence,contracts,audits): $drill_counts"
echo "Delivery files: $drill_jobs"
