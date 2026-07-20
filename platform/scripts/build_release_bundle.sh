#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$PLATFORM_DIR/.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$PLATFORM_DIR/var/releases}"
RELEASE_ID="${RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
BUNDLE_NAME="qtail-forge-${RELEASE_ID}"

[[ "$RELEASE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
  echo "RELEASE_ID may contain only letters, numbers, dot, underscore, and hyphen" >&2
  exit 1
}

command -v tar >/dev/null || { echo "tar is required" >&2; exit 1; }
command -v shasum >/dev/null || { echo "shasum is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

python3 "$PLATFORM_DIR/scripts/build_buyer_pilot_kit.py" >/dev/null
python3 "$PLATFORM_DIR/scripts/verify_buyer_pilot_kit.py" >/dev/null

mkdir -p "$OUTPUT_DIR"
stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-release.XXXXXX")"
trap 'rm -rf "$stage_dir"' EXIT
bundle_root="$stage_dir/$BUNDLE_NAME"

mkdir -p \
  "$bundle_root/platform" \
  "$bundle_root/tools" \
  "$bundle_root/data" \
  "$bundle_root/results/openx_strong_training"

copy_required() {
  local source="$1"
  local target="$2"
  [[ -e "$source" ]] || { echo "Required release input is missing: $source" >&2; exit 1; }
  cp -R "$source" "$target"
}

copy_required "$REPO_DIR/.dockerignore" "$bundle_root/.dockerignore"

for file in \
  .env.example .gitignore .npmrc CHANGELOG.md README.md completion-audit.md \
  Dockerfile.edge Dockerfile.web Dockerfile.tunnel-dns \
  docker-compose.yml docker-compose.production.yml docker-compose.edge.yml \
  docker-compose.ecs-small.yml docker-compose.ip-tls.yml docker-compose.alt-https.yml \
  docker-compose.cloudflare.yml docker-compose.cloudflare-preview.yml \
  index.html nginx.conf package.json package-lock.json vite.config.mjs; do
  copy_required "$PLATFORM_DIR/$file" "$bundle_root/platform/$file"
done

for directory in backend deploy docs public scripts src; do
  copy_required "$PLATFORM_DIR/$directory" "$bundle_root/platform/$directory"
done

# Local compile/test runs may have left bytecode caches inside otherwise
# allow-listed source directories.  They are non-reproducible host artifacts.
find "$bundle_root" -type f \( -name '*.pyc' -o -name '.DS_Store' \) -delete
find "$bundle_root" -type d -name '__pycache__' -prune -exec rm -rf {} +

for file in \
  qtail_data_engine.py qtail_openx_service_model.py \
  qtail_build_package.py qtail_validate_package.py; do
  copy_required "$REPO_DIR/tools/$file" "$bundle_root/tools/$file"
done

copy_required "$REPO_DIR/data/uploaded_data.csv" "$bundle_root/data/uploaded_data.csv"
for file in openx_demo_training_report.json openx_shard_training_rows.csv; do
  copy_required \
    "$REPO_DIR/results/openx_strong_training/$file" \
    "$bundle_root/results/openx_strong_training/$file"
done

# Release artifacts carry provenance but never the working tree's secrets,
# generated customer packages, database state, or downloaded training corpus.
git_revision="unversioned-working-tree"
source_tree_state="not-a-git-worktree"
if command -v git >/dev/null && git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git_revision="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || printf '%s' 'uncommitted')"
  source_tree_state="clean"
  if [[ -n "$(git -C "$REPO_DIR" status --porcelain -- platform tools data/uploaded_data.csv results/openx_strong_training 2>/dev/null)" ]]; then
    source_tree_state="dirty-or-untracked; SHA256SUMS is the release source of truth"
  fi
fi
acceptance_run="not-recorded"
acceptance_report="$(find "$PLATFORM_DIR/var/acceptance" -maxdepth 1 -type f -name '*full-e2e*.json' -print 2>/dev/null | while IFS= read -r candidate; do printf '%s\t%s\n' "$(stat -f '%m' "$candidate" 2>/dev/null || stat -c '%Y' "$candidate")" "$candidate"; done | sort -rn | head -n 1 | cut -f2-)"
if [[ -z "$acceptance_report" || ! -f "$acceptance_report" ]]; then
  acceptance_report="$PLATFORM_DIR/var/acceptance/authenticity-latest.json"
fi
if [[ ! -f "$acceptance_report" ]]; then
  acceptance_report="$PLATFORM_DIR/var/acceptance/cloudflare-retention-latest.json"
fi
if [[ ! -f "$acceptance_report" ]]; then
  acceptance_report="$PLATFORM_DIR/var/acceptance/cloudflare-compliance-latest.json"
fi
if [[ ! -f "$acceptance_report" ]]; then
  acceptance_report="$PLATFORM_DIR/var/acceptance/latest.json"
fi
if [[ -f "$acceptance_report" ]]; then
  acceptance_run="$(sed -n 's/.*"run_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$acceptance_report" | head -n 1)"
  [[ -n "$acceptance_run" ]] || acceptance_run="unreadable"
fi
{
  echo "release_id=$RELEASE_ID"
  echo "built_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "source_git_revision=$git_revision"
  echo "source_tree_state=$source_tree_state"
  echo "acceptance_run_id=$acceptance_run"
  echo "claim_boundary=Deployable software bundle; not real-robot, buyer-acceptance, payment-settlement, or executed-contract evidence."
} > "$bundle_root/RELEASE-METADATA.txt"

forbidden_paths="$(find "$bundle_root" \
  \( -name '.env' -o -name '.env.preview' -o -name '.env.acceptance' \
     -o -name '*.pem' -o -name '*.key' -o -name '*.p12' \
     -o -name 'node_modules' -o -name 'var' -o -name 'dist' \
     -o -name '__pycache__' -o -name '*.pyc' \
     -o -name '*.sql.gz' -o -name '*.tar.gz.enc' \) -print)"
if [[ -n "$forbidden_paths" ]]; then
  echo "Refusing to package forbidden runtime/secret paths:" >&2
  echo "$forbidden_paths" >&2
  exit 1
fi

(
  cd "$bundle_root"
  find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done > SHA256SUMS
  shasum -a 256 -c SHA256SUMS >/dev/null
)

archive_path="$OUTPUT_DIR/$BUNDLE_NAME.tar.gz"
checksum_path="$archive_path.sha256"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$stage_dir" -czf "$archive_path" "$BUNDLE_NAME"
(
  cd "$OUTPUT_DIR"
  shasum -a 256 "$(basename "$archive_path")" > "$(basename "$checksum_path")"
  shasum -a 256 -c "$(basename "$checksum_path")" >/dev/null
)

archive_listing="$(tar -tzf "$archive_path")"
grep -q "^$BUNDLE_NAME/platform/docker-compose.edge.yml$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/docker-compose.ecs-small.yml$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/docker-compose.ip-tls.yml$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/docker-compose.alt-https.yml$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/docker-compose.cloudflare.yml$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/scripts/server_preflight.sh$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/scripts/host_restore_drill.sh$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/scripts/replicate_backup.sh$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/scripts/test_alert_delivery.sh$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/scripts/pull_remote_backup.sh$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/deploy/launchd/com.qtail.offsite-backup.plist.example$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/deploy/server/qtail-backup-export.sh$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/deploy/caddy/Caddyfile.ip$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/deploy/systemd/qtail-cert-renew.timer$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/public/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/public/buyer-kit/tools/validate_gate1_delivery.py$" <<< "$archive_listing"
grep -q "^$BUNDLE_NAME/platform/scripts/verify_buyer_pilot_kit.py$" <<< "$archive_listing"
if grep -Eq '/(\.env|\.env\.preview|\.env\.acceptance|node_modules|var/jobs|dist|__pycache__)(/|$)|\.pyc$' <<< "$archive_listing"; then
  echo "Release archive contains a forbidden path" >&2
  exit 1
fi

echo "PASS release bundle integrity and forbidden-path checks"
echo "Archive: $archive_path"
echo "Archive checksum: $checksum_path"
echo "Release root: $BUNDLE_NAME"
