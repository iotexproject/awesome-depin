#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
RESTORE_MODE="${RESTORE_MODE:-verify}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
COMPOSE_OVERLAYS="${COMPOSE_OVERLAYS:-}"
backup_file="${1:-}"

if [[ -z "$backup_file" || ! -f "$backup_file" ]]; then
  echo "Usage: $0 /path/to/qtail-backup.tar.gz[.enc]" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

compose=()
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-restore.XXXXXX")"
worker_paused=0
cleanup() {
  if [[ "$worker_paused" == "1" ]] && (( ${#compose[@]} > 0 )); then
    "${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "INSERT INTO system_settings (setting_key,setting_value) VALUES ('"'"'worker_paused'"'"','"'"'0'"'"') ON DUPLICATE KEY UPDATE setting_value='"'"'0'"'"';"' >/dev/null 2>&1 || true
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT
archive="$backup_file"

if [[ "$backup_file" == *.enc ]]; then
  if [[ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
    echo "BACKUP_ENCRYPTION_PASSWORD is required for encrypted backups" >&2
    exit 1
  fi
  archive="$work_dir/archive.tar.gz"
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$backup_file" -out "$archive" -pass env:BACKUP_ENCRYPTION_PASSWORD
fi

tar -C "$work_dir" -xzf "$archive"
for required in database.sql jobs.tar.gz metadata.txt checksums.sha256; do
  [[ -f "$work_dir/$required" ]] || { echo "Backup is missing $required" >&2; exit 1; }
done

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$work_dir" && sha256sum -c checksums.sha256)
else
  (cd "$work_dir" && shasum -a 256 -c checksums.sha256)
fi

if [[ "$RESTORE_MODE" == "verify" ]]; then
  echo "Backup verification passed: $backup_file"
  exit 0
fi
if [[ "$RESTORE_MODE" != "restore" || "${RESTORE_CONFIRM:-}" != "restore-qtail" ]]; then
  echo "Set RESTORE_MODE=restore and RESTORE_CONFIRM=restore-qtail to perform a destructive restore" >&2
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

echo "Quiescing generation worker for restore..."
"${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "INSERT INTO system_settings (setting_key,setting_value) VALUES ('"'"'worker_paused'"'"','"'"'1'"'"') ON DUPLICATE KEY UPDATE setting_value='"'"'1'"'"';"' >/dev/null
worker_paused=1
for _attempt in $(seq 1 300); do
  running_jobs="$("${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM generation_jobs WHERE status='"'"'running'"'"';"')"
  [[ "$running_jobs" == "0" ]] && break
  sleep 2
done
[[ "$running_jobs" == "0" ]] || { echo "Timed out waiting for running generation jobs" >&2; exit 1; }

echo "Restoring MySQL..."
"${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot "$MYSQL_DATABASE"' < "$work_dir/database.sql"

echo "Replacing generated delivery packages..."
"${compose[@]}" exec -T api sh -lc 'find "$QTAIL_JOBS_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
"${compose[@]}" exec -T api sh -lc 'tar -C "$QTAIL_JOBS_DIR" -xzf -' < "$work_dir/jobs.tar.gz"
"${compose[@]}" exec -T db sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "INSERT INTO system_settings (setting_key,setting_value) VALUES ('"'"'worker_paused'"'"','"'"'0'"'"') ON DUPLICATE KEY UPDATE setting_value='"'"'0'"'"';"' >/dev/null
worker_paused=0
echo "Restore complete"
