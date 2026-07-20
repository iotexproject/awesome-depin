#!/usr/bin/env bash
set -Eeuo pipefail

PATH=/usr/bin:/bin:/usr/sbin:/sbin
BACKUP_DIR="${QTAIL_BACKUP_EXPORT_DIR:-/opt/qtail/backups}"
original_command="${SSH_ORIGINAL_COMMAND:-}"

latest_backup() {
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'qtail-*.tar.gz.enc' -print \
    | LC_ALL=C sort | tail -n 1
}

case "$original_command" in
  qtail-backup-metadata)
    latest="$(latest_backup)"
    [[ -n "$latest" && -f "$latest" && ! -L "$latest" ]] || exit 1
    sha256="$(sha256sum "$latest" | awk '{print $1}')"
    printf '%s %s\n' "$sha256" "$(basename "$latest")"
    ;;
  qtail-backup-stream\ qtail-*.tar.gz.enc)
    file_name="${original_command#qtail-backup-stream }"
    [[ "$file_name" != */* && "$file_name" != *[^A-Za-z0-9_.-]* ]] || exit 1
    backup_file="$BACKUP_DIR/$file_name"
    [[ -f "$backup_file" && ! -L "$backup_file" ]] || exit 1
    exec cat -- "$backup_file"
    ;;
  *)
    echo "Only Q-Tail encrypted-backup export commands are allowed" >&2
    exit 2
    ;;
esac
