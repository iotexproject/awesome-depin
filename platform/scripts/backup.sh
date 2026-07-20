#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
BACKUP_QUIESCE_TIMEOUT_SECONDS="${BACKUP_QUIESCE_TIMEOUT_SECONDS:-600}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
COMPOSE_OVERLAYS="${COMPOSE_OVERLAYS:-}"

if command -v flock >/dev/null 2>&1; then
  lock_project="${COMPOSE_PROJECT_NAME:-default}"
  lock_project="${lock_project//[^A-Za-z0-9_.-]/_}"
  backup_lock="${BACKUP_LOCK_FILE:-${TMPDIR:-/tmp}/qtail-backup-$lock_project.lock}"
  exec 8>"$backup_lock"
  if ! flock -n 8; then
    echo "Q-Tail backup already running; overlapping invocation skipped"
    exit 0
  fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ "${APP_ENV:-development}" == "production" && -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
  echo "BACKUP_ENCRYPTION_PASSWORD is required when APP_ENV=production" >&2
  exit 1
fi

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

umask 077
mkdir -p "$BACKUP_DIR"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-backup.XXXXXX")"
worker_paused=0
unpause_worker() {
  if [[ "$worker_paused" == "1" ]]; then
    "${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "INSERT INTO system_settings (setting_key,setting_value) VALUES ('"'"'worker_paused'"'"','"'"'0'"'"') ON DUPLICATE KEY UPDATE setting_value='"'"'0'"'"';"' >/dev/null 2>&1 || true
    worker_paused=0
  fi
}
cleanup() {
  unpause_worker
  rm -rf "$work_dir"
}
trap cleanup EXIT

echo "Quiescing generation worker..."
"${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "INSERT INTO system_settings (setting_key,setting_value) VALUES ('"'"'worker_paused'"'"','"'"'1'"'"') ON DUPLICATE KEY UPDATE setting_value='"'"'1'"'"';"' >/dev/null
worker_paused=1
deadline="$(( $(date +%s) + BACKUP_QUIESCE_TIMEOUT_SECONDS ))"
while true; do
  running_jobs="$("${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM generation_jobs WHERE status='"'"'running'"'"';"')"
  [[ "$running_jobs" == "0" ]] && break
  (( $(date +%s) < deadline )) || { echo "Timed out waiting for $running_jobs running generation job(s)" >&2; exit 1; }
  sleep 2
done
echo "Generation worker quiesced"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain_archive="$work_dir/qtail-$timestamp.tar.gz"

echo "Dumping MySQL..."
"${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --ignore-table="$MYSQL_DATABASE.system_settings" "$MYSQL_DATABASE"' > "$work_dir/database.sql"

echo "Archiving generated delivery packages..."
"${compose[@]}" exec -T api sh -lc 'tar -C "$QTAIL_JOBS_DIR" -czf - .' > "$work_dir/jobs.tar.gz"

cat > "$work_dir/metadata.txt" <<EOF
created_at_utc=$timestamp
database=${MYSQL_DATABASE:-qtail}
app_env=${APP_ENV:-development}
compose_project=${COMPOSE_PROJECT_NAME:-default}
generation_worker_quiesced=true
EOF

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$work_dir" && sha256sum database.sql jobs.tar.gz metadata.txt > checksums.sha256)
else
  (cd "$work_dir" && shasum -a 256 database.sql jobs.tar.gz metadata.txt > checksums.sha256)
fi

tar -C "$work_dir" -czf "$plain_archive" database.sql jobs.tar.gz metadata.txt checksums.sha256

if [[ -n "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
  final_archive="$BACKUP_DIR/qtail-$timestamp.tar.gz.enc"
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "$plain_archive" -out "$final_archive" -pass env:BACKUP_ENCRYPTION_PASSWORD
else
  final_archive="$BACKUP_DIR/qtail-$timestamp.tar.gz"
  cp "$plain_archive" "$final_archive"
fi

if [[ -n "${BACKUP_READ_GROUP:-}" ]]; then
  getent group "$BACKUP_READ_GROUP" >/dev/null 2>&1 || {
    echo "Backup read group does not exist: $BACKUP_READ_GROUP" >&2
    exit 1
  }
  chgrp "$BACKUP_READ_GROUP" "$final_archive"
  chmod 0640 "$final_archive"
fi

if [[ -n "${OFFSITE_BACKUP_URI:-}" ]]; then
  "$ROOT_DIR/scripts/replicate_backup.sh" "$final_archive"
fi

find "$BACKUP_DIR" -type f -name 'qtail-*.tar.gz*' -mtime "+$RETENTION_DAYS" -delete
echo "Backup complete: $final_archive"
