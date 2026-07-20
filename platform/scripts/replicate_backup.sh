#!/usr/bin/env bash
set -Eeuo pipefail

backup_file="${1:-}"
destination="${OFFSITE_BACKUP_URI:-}"
verify_download="${OFFSITE_VERIFY_DOWNLOAD:-1}"

[[ -n "$backup_file" && -f "$backup_file" ]] || {
  echo "Usage: OFFSITE_BACKUP_URI=<file:///path|s3://bucket/prefix|oss://bucket/prefix> $0 <backup-file>" >&2
  exit 2
}
[[ -n "$destination" ]] || { echo "OFFSITE_BACKUP_URI is required" >&2; exit 2; }
[[ "$verify_download" == "0" || "$verify_download" == "1" ]] || {
  echo "OFFSITE_VERIFY_DOWNLOAD must be 0 or 1" >&2
  exit 2
}
if [[ "${OFFSITE_ALLOW_PLAINTEXT:-0}" != "1" && "$backup_file" != *.enc ]]; then
  echo "Refusing to replicate an unencrypted backup" >&2
  exit 2
fi

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-offsite-backup.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
base_name="$(basename "$backup_file")"
downloaded="$work_dir/$base_name.downloaded"
checksum_file="$work_dir/$base_name.sha256"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

source_sha256="$(hash_file "$backup_file")"
printf '%s  %s\n' "$source_sha256" "$base_name" > "$checksum_file"
chmod 600 "$checksum_file"

case "$destination" in
  file:///*)
    destination_dir="${destination#file://}"
    [[ "$destination_dir" == /* ]] || { echo "file:// destination must be absolute" >&2; exit 2; }
    install -d -m 0700 "$destination_dir"
    install -m 0600 "$backup_file" "$destination_dir/$base_name"
    install -m 0600 "$checksum_file" "$destination_dir/$base_name.sha256"
    downloaded="$destination_dir/$base_name"
    remote_object="file://$destination_dir/$base_name"
    ;;
  s3://*)
    command -v aws >/dev/null 2>&1 || { echo "aws CLI is required for s3:// replication" >&2; exit 2; }
    remote_object="${destination%/}/$base_name"
    aws s3 cp "$backup_file" "$remote_object" --only-show-errors
    aws s3 cp "$checksum_file" "$remote_object.sha256" --only-show-errors
    if [[ "$verify_download" == "1" ]]; then
      aws s3 cp "$remote_object" "$downloaded" --only-show-errors
    fi
    ;;
  oss://*)
    command -v ossutil >/dev/null 2>&1 || { echo "ossutil is required for oss:// replication" >&2; exit 2; }
    remote_object="${destination%/}/$base_name"
    ossutil cp -f "$backup_file" "$remote_object"
    ossutil cp -f "$checksum_file" "$remote_object.sha256"
    if [[ "$verify_download" == "1" ]]; then
      ossutil cp -f "$remote_object" "$downloaded"
    fi
    ;;
  *)
    echo "Unsupported OFFSITE_BACKUP_URI scheme; use file://, s3://, or oss://" >&2
    exit 2
    ;;
esac

if [[ "$verify_download" == "1" ]]; then
  restored_sha256="$(hash_file "$downloaded")"
  [[ "$restored_sha256" == "$source_sha256" ]] || {
    echo "Offsite backup SHA-256 mismatch" >&2
    exit 1
  }
  verification="downloaded_sha256_match"
else
  verification="checksum_sidecar_uploaded"
fi

receipt_file="${OFFSITE_BACKUP_RECEIPT_FILE:-$(dirname "$backup_file")/.offsite-latest.json}"
python3 - "$receipt_file" "$base_name" "$source_sha256" "$remote_object" "$verification" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

receipt_file, source_file, source_sha256, remote_object, verification = sys.argv[1:]
receipt = {
    "status": "passed",
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "source_file": source_file,
    "source_sha256": source_sha256,
    "remote_object": remote_object,
    "verification": verification,
}
path = Path(receipt_file)
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name(f".{path.name}.tmp")
temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY

echo "PASS offsite encrypted backup replication"
echo "Object: $remote_object"
echo "SHA-256: $source_sha256"
echo "Verification: $verification"
echo "Receipt: $receipt_file"
