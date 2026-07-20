#!/usr/bin/env bash
set -Eeuo pipefail

host="${QTAIL_BACKUP_HOST:-}"
user="${QTAIL_BACKUP_USER:-qtailbackup}"
ssh_key="${QTAIL_BACKUP_SSH_KEY:-$HOME/.ssh/id_ed25519}"
expected_fingerprint="${QTAIL_BACKUP_HOST_FINGERPRINT:-}"
protocol="${QTAIL_BACKUP_PROTOCOL:-restricted_stream}"
remote_dir="${QTAIL_REMOTE_BACKUP_DIR:-/opt/qtail/backups}"
offsite_dir="${QTAIL_OFFSITE_DIR:-$HOME/qtail-offsite-backups}"
retention_days="${QTAIL_OFFSITE_RETENTION_DAYS:-90}"
receipt_file="${QTAIL_OFFSITE_RECEIPT_FILE:-$offsite_dir/.pull-latest.json}"

[[ -n "$host" ]] || { echo "QTAIL_BACKUP_HOST is required" >&2; exit 2; }
[[ -f "$ssh_key" ]] || { echo "SSH key not found: $ssh_key" >&2; exit 2; }
[[ -n "$expected_fingerprint" ]] || { echo "QTAIL_BACKUP_HOST_FINGERPRINT is required" >&2; exit 2; }
[[ "$protocol" == "restricted_stream" || "$protocol" == "scp" ]] || {
  echo "QTAIL_BACKUP_PROTOCOL must be restricted_stream or scp" >&2
  exit 2
}
if [[ "$protocol" == "scp" ]]; then
  [[ "$remote_dir" == /* && "$remote_dir" != *[^A-Za-z0-9_./-]* ]] || {
    echo "QTAIL_REMOTE_BACKUP_DIR must be a safe absolute path" >&2
    exit 2
  }
fi
[[ "$retention_days" =~ ^[0-9]+$ ]] || { echo "QTAIL_OFFSITE_RETENTION_DAYS must be numeric" >&2; exit 2; }

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-offsite-pull.XXXXXX")"
cleanup() { rm -rf "$work_dir"; }
trap cleanup EXIT
known_hosts="$work_dir/known_hosts"

ssh-keyscan -T 10 -t ed25519 "$host" > "$known_hosts" 2>/dev/null
[[ -s "$known_hosts" ]] || { echo "Unable to obtain the backup host ED25519 key" >&2; exit 1; }
actual_fingerprint="$(ssh-keygen -lf "$known_hosts" | awk 'NR==1 {print $2}')"
[[ "$actual_fingerprint" == "$expected_fingerprint" ]] || {
  echo "Backup host fingerprint mismatch" >&2
  exit 1
}

ssh_options=(
  -i "$ssh_key"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$known_hosts"
)

if [[ "$protocol" == "restricted_stream" ]]; then
  remote_metadata="$(ssh "${ssh_options[@]}" "$user@$host" qtail-backup-metadata)"
  read -r remote_sha256 remote_name <<< "$remote_metadata"
  [[ "$remote_sha256" =~ ^[0-9a-f]{64}$ && "$remote_name" == qtail-*.tar.gz.enc && "$remote_name" != */* ]] || {
    echo "Invalid restricted backup metadata" >&2
    exit 1
  }
  remote_file="$remote_dir/$remote_name"
else
  remote_metadata="$(ssh "${ssh_options[@]}" "$user@$host" \
    "set -Eeuo pipefail; latest=\$(find '$remote_dir' -maxdepth 1 -type f -name 'qtail-*.tar.gz.enc' -print | sort | tail -n1); test -n \"\$latest\"; sha256sum \"\$latest\"")"
  read -r remote_sha256 remote_file <<< "$remote_metadata"
  [[ "$remote_sha256" =~ ^[0-9a-f]{64}$ && "$remote_file" == "$remote_dir"/qtail-*.tar.gz.enc ]] || {
    echo "Invalid remote backup metadata" >&2
    exit 1
  }
  remote_name="$(basename "$remote_file")"
fi

install -d -m 0700 "$offsite_dir"
local_file="$offsite_dir/$remote_name"
temporary_file="$offsite_dir/.$remote_name.part.$$"

if [[ -f "$local_file" ]]; then
  local_sha256="$(shasum -a 256 "$local_file" | awk '{print $1}')"
else
  local_sha256=""
fi
if [[ "$local_sha256" != "$remote_sha256" ]]; then
  if [[ "$protocol" == "restricted_stream" ]]; then
    ssh "${ssh_options[@]}" "$user@$host" "qtail-backup-stream $remote_name" > "$temporary_file"
  else
    scp "${ssh_options[@]}" "$user@$host:$remote_file" "$temporary_file"
  fi
  chmod 600 "$temporary_file"
  local_sha256="$(shasum -a 256 "$temporary_file" | awk '{print $1}')"
  [[ "$local_sha256" == "$remote_sha256" ]] || {
    echo "Downloaded backup SHA-256 mismatch" >&2
    exit 1
  }
  mv -f "$temporary_file" "$local_file"
fi

python3 - "$receipt_file" "$host" "$remote_file" "$local_file" "$remote_sha256" "$actual_fingerprint" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

receipt_file, host, remote_file, local_file, sha256, fingerprint = sys.argv[1:]
receipt = {
    "status": "passed",
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "source_host": host,
    "source_file": remote_file,
    "local_file": local_file,
    "sha256": sha256,
    "host_fingerprint": fingerprint,
    "encrypted_archive_only": True,
}
path = Path(receipt_file)
temporary = path.with_name(f".{path.name}.tmp")
temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY

find "$offsite_dir" -maxdepth 1 -type f -name 'qtail-*.tar.gz.enc' \
  -mtime "+$retention_days" -delete

echo "PASS encrypted backup pulled off-host"
echo "Backup: $local_file"
echo "SHA-256: $remote_sha256"
echo "Receipt: $receipt_file"
