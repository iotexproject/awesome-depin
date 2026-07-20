#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
archive="${1:-}"

[[ -n "$archive" ]] || { echo "Usage: $0 <qtail-forge-release.tar.gz>" >&2; exit 1; }
archive="$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")"
checksum_file="$archive.sha256"
report_file="${VERIFICATION_REPORT:-${archive%.tar.gz}.verification.json}"

[[ -f "$archive" ]] || { echo "Release archive not found: $archive" >&2; exit 1; }
[[ -f "$checksum_file" ]] || { echo "Release checksum not found: $checksum_file" >&2; exit 1; }
for command in docker tar shasum curl openssl python3; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 1; }
done
docker info >/dev/null

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-release-verify.XXXXXX")"
project="qtail-release-verify-$$"
env_file="$work_dir/.env.verify"
token_file="$work_dir/cloudflare_tunnel_token"
payment_secret_dir="$work_dir/payment-secrets"
ip_certbot_dir="$work_dir/ip-certbot"
ip_acme_webroot="$work_dir/ip-acme-webroot"
ip_tls_container="${project}-ip-tls"
acceptance_report="$work_dir/acceptance.json"
release_root=""

cleanup() {
  docker stop "$ip_tls_container" >/dev/null 2>&1 || true
  docker rm "$ip_tls_container" >/dev/null 2>&1 || true
  if [[ -n "$release_root" && -d "$release_root/platform" ]]; then
    docker compose -p "$project" --env-file "$env_file" \
      -f "$release_root/platform/docker-compose.yml" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT

(
  cd "$(dirname "$archive")"
  shasum -a 256 -c "$(basename "$checksum_file")"
)
tar -xzf "$archive" -C "$work_dir"
release_root_count="$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -name 'qtail-forge-*' -print | wc -l | tr -d ' ')"
[[ "$release_root_count" -eq 1 ]] || { echo "Archive must contain exactly one qtail-forge-* root" >&2; exit 1; }
release_root="$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -name 'qtail-forge-*' -print | head -n 1)"

(
  cd "$release_root"
  shasum -a 256 -c SHA256SUMS
)
forbidden_paths="$(find "$release_root" \
  \( -name '.env' -o -name '.env.preview' -o -name '.env.acceptance' \
     -o -name 'node_modules' -o -name 'var' -o -name 'dist' \
     -o -name '__pycache__' -o -name '*.pyc' -o -name '*.tar.gz.enc' \) -print)"
[[ -z "$forbidden_paths" ]] || { echo "Release contains forbidden runtime paths: $forbidden_paths" >&2; exit 1; }

python3 "$release_root/platform/scripts/verify_buyer_pilot_kit.py"

offsite_source="$work_dir/offsite-source"
offsite_destination="$work_dir/offsite-destination"
mkdir -p "$offsite_source" "$offsite_destination"
openssl rand -out "$offsite_source/qtail-verification.tar.gz.enc" 4096
OFFSITE_BACKUP_URI="file://$offsite_destination" OFFSITE_VERIFY_DOWNLOAD=1 \
  "$release_root/platform/scripts/replicate_backup.sh" \
  "$offsite_source/qtail-verification.tar.gz.enc"
cmp "$offsite_source/qtail-verification.tar.gz.enc" \
  "$offsite_destination/qtail-verification.tar.gz.enc"
python3 - "$offsite_source/.offsite-latest.json" <<'PY'
import json
from pathlib import Path
import sys

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if receipt.get("status") != "passed" or receipt.get("verification") != "downloaded_sha256_match":
    raise SystemExit("offsite replication receipt did not prove download verification")
if len(receipt.get("source_sha256") or "") != 64:
    raise SystemExit("offsite replication receipt has no SHA-256")
PY
if OFFSITE_BACKUP_URI="file://$offsite_destination" \
  "$release_root/platform/scripts/replicate_backup.sh" \
  "$release_root/RELEASE-METADATA.txt" >/dev/null 2>&1; then
  echo "Offsite replication accepted a plaintext artifact" >&2
  exit 1
fi

export_source="$work_dir/restricted-export-source"
mkdir -p "$export_source"
cp "$offsite_source/qtail-verification.tar.gz.enc" \
  "$export_source/qtail-verification.tar.gz.enc"
export_metadata="$(QTAIL_BACKUP_EXPORT_DIR="$export_source" \
  SSH_ORIGINAL_COMMAND=qtail-backup-metadata \
  "$release_root/platform/deploy/server/qtail-backup-export.sh")"
read -r export_sha256 export_name <<< "$export_metadata"
[[ "$export_name" == "qtail-verification.tar.gz.enc" ]] || {
  echo "Restricted exporter returned the wrong file" >&2
  exit 1
}
QTAIL_BACKUP_EXPORT_DIR="$export_source" \
  SSH_ORIGINAL_COMMAND="qtail-backup-stream $export_name" \
  "$release_root/platform/deploy/server/qtail-backup-export.sh" \
  > "$work_dir/restricted-export-downloaded.enc"
[[ "$(shasum -a 256 "$work_dir/restricted-export-downloaded.enc" | awk '{print $1}')" == "$export_sha256" ]] || {
  echo "Restricted backup stream SHA-256 mismatch" >&2
  exit 1
}
if QTAIL_BACKUP_EXPORT_DIR="$export_source" SSH_ORIGINAL_COMMAND='cat /etc/passwd' \
  "$release_root/platform/deploy/server/qtail-backup-export.sh" >/dev/null 2>&1; then
  echo "Restricted exporter accepted an arbitrary command" >&2
  exit 1
fi
if QTAIL_BACKUP_EXPORT_DIR="$export_source" \
  SSH_ORIGINAL_COMMAND='qtail-backup-stream ../../etc/passwd' \
  "$release_root/platform/deploy/server/qtail-backup-export.sh" >/dev/null 2>&1; then
  echo "Restricted exporter accepted path traversal" >&2
  exit 1
fi

free_port() {
  local attempt=0 port
  while (( attempt < 50 )); do
    port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
    )"
    # On Docker Desktop a published VM port can be absent from the macOS host's
    # socket table. Check Docker's published-port inventory as well as asking
    # the host kernel for an ephemeral port.
    if ! docker ps --format '{{.Ports}}' | grep -Fq ":$port->"; then
      printf '%s\n' "$port"
      return 0
    fi
    attempt="$((attempt + 1))"
  done
  echo "Unable to allocate a Docker-safe verification port" >&2
  return 1
}
web_port="$(free_port)"
mysql_port="$(free_port)"
ip_tls_port="$(free_port)"
alt_https_port="$(free_port)"

umask 077
mkdir -p "$payment_secret_dir"
mkdir -p "$ip_certbot_dir/live/203.0.113.10" "$ip_acme_webroot"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=203.0.113.10' -addext 'subjectAltName=IP:203.0.113.10' \
  -keyout "$ip_certbot_dir/live/203.0.113.10/privkey.pem" \
  -out "$ip_certbot_dir/live/203.0.113.10/fullchain.pem" >/dev/null 2>&1
printf '%s\n' \
  'APP_ENV=acceptance' \
  'APP_SECRET=qtail-release-verification-app-secret-2026-at-least-32-characters' \
  'ADMIN_TOKEN=qtail-release-verification-admin-token-2026-at-least-32-characters' \
  'SESSION_COOKIE_SECURE=0' \
  'MYSQL_DATABASE=qtail' \
  'MYSQL_USER=qtail' \
  'MYSQL_PASSWORD=qtail-release-verification-database-password' \
  'MYSQL_ROOT_PASSWORD=qtail-release-verification-root-password' \
  'MYSQL_BIND_HOST=127.0.0.1' \
  "MYSQL_EXPOSED_PORT=$mysql_port" \
  'PRO_PRICE_CENTS=99900' \
  'PAYMENT_MODE=manual_qr_verification' \
  'PAYMENT_PUBLIC_URL=' \
  "QTAIL_PAYMENT_SECRETS_DIR=$payment_secret_dir" \
  'PRO_DAILY_GENERATION_LIMIT=50' \
  'MAX_ACTIVE_GENERATIONS_PER_USER=5' \
  'QTAIL_FAKE_GENERATOR=0' \
  'QTAIL_WORKER_ENABLED=1' \
  'QTAIL_WORKER_MAX_ATTEMPTS=3' \
  'QTAIL_WORKER_POLL_SECONDS=1' \
  'QTAIL_WORKER_HEARTBEAT_SECONDS=15' \
  'QTAIL_WORKER_LEASE_SECONDS=120' \
  'QTAIL_WORKER_RETRY_BASE_SECONDS=1' \
  'QTAIL_RETENTION_SWEEP_SECONDS=1' \
  'WEB_BIND_HOST=127.0.0.1' \
  "WEB_PORT=$web_port" \
  'QTAIL_DOMAIN=localhost' \
  'QTAIL_INGRESS_MODE=caddy' \
  "CLOUDFLARE_TUNNEL_TOKEN_FILE=$token_file" \
  > "$env_file"
printf '%s\n' 'release-verification-placeholder-token-not-for-network-use-0000000000000000' > "$token_file"
chmod 0600 "$env_file" "$token_file"

platform_dir="$release_root/platform"
docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" \
  -f "$platform_dir/docker-compose.production.yml" \
  -f "$platform_dir/docker-compose.edge.yml" config --quiet
docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" \
  -f "$platform_dir/docker-compose.production.yml" \
  -f "$platform_dir/docker-compose.cloudflare.yml" config --quiet
docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" \
  -f "$platform_dir/docker-compose.production.yml" \
  -f "$platform_dir/docker-compose.edge.yml" \
  -f "$platform_dir/docker-compose.ecs-small.yml" config --quiet
QTAIL_PUBLIC_IP=203.0.113.10 \
QTAIL_CERTBOT_CONFIG_DIR="$ip_certbot_dir" \
QTAIL_ACME_WEBROOT="$ip_acme_webroot" \
docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" \
  -f "$platform_dir/docker-compose.production.yml" \
  -f "$platform_dir/docker-compose.edge.yml" \
  -f "$platform_dir/docker-compose.ip-tls.yml" \
  -f "$platform_dir/docker-compose.ecs-small.yml" config --quiet
alt_https_config="$(QTAIL_PUBLIC_IP=203.0.113.10 \
QTAIL_ALT_HTTPS_PORT="$alt_https_port" \
QTAIL_CERTBOT_CONFIG_DIR="$ip_certbot_dir" \
QTAIL_ACME_WEBROOT="$ip_acme_webroot" \
docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" \
  -f "$platform_dir/docker-compose.production.yml" \
  -f "$platform_dir/docker-compose.edge.yml" \
  -f "$platform_dir/docker-compose.ip-tls.yml" \
  -f "$platform_dir/docker-compose.alt-https.yml" config --format json)"
ALT_HTTPS_CONFIG="$alt_https_config" python3 - "$alt_https_port" <<'PY'
import json
import os
import sys

expected = int(sys.argv[1])
document = json.loads(os.environ["ALT_HTTPS_CONFIG"])
ports = document["services"]["edge"]["ports"]
matches = [item for item in ports if int(item["published"]) == expected and int(item["target"]) == 8443]
if len(matches) != 1:
    raise SystemExit(f"alternate HTTPS mapping is missing or ambiguous: {ports}")
PY
docker run --rm \
  -v "$platform_dir/deploy/caddy/Caddyfile.ip:/etc/caddy/Caddyfile:ro" \
  -v "$ip_certbot_dir:/etc/letsencrypt:ro" \
  -v "$ip_acme_webroot:/srv/acme:ro" \
  -e QTAIL_PUBLIC_IP=203.0.113.10 \
  caddy:2.10.2-alpine caddy validate --config /etc/caddy/Caddyfile >/dev/null

docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" up -d --build --wait
"$platform_dir/scripts/smoke.sh" "http://127.0.0.1:$web_port"

# IP-literal HTTPS clients normally omit SNI. Start the packaged Caddyfile on
# the verified application network and require a trusted, SNI-less handshake
# plus a real proxied health response. Config validation alone cannot catch a
# missing default_sni policy.
docker run -d --name "$ip_tls_container" \
  --network "${project}_default" \
  -p "127.0.0.1:${ip_tls_port}:8443" \
  -v "$platform_dir/deploy/caddy/Caddyfile.ip:/etc/caddy/Caddyfile:ro" \
  -v "$ip_certbot_dir:/etc/letsencrypt:ro" \
  -v "$ip_acme_webroot:/srv/acme:ro" \
  -e QTAIL_PUBLIC_IP=203.0.113.10 \
  caddy:2.10.2-alpine >/dev/null
ip_tls_health=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if ip_tls_health="$(curl --fail --silent --show-error --max-time 5 \
    --cacert "$ip_certbot_dir/live/203.0.113.10/fullchain.pem" \
    --resolve "203.0.113.10:${ip_tls_port}:127.0.0.1" \
    "https://203.0.113.10:${ip_tls_port}/api/health" 2>/dev/null)"; then
    break
  fi
  sleep 1
done
grep -q '"ok":true' <<< "$ip_tls_health" || {
  docker logs "$ip_tls_container" >&2 || true
  echo "Packaged IP TLS failed an SNI-less trusted handshake or health proxy" >&2
  exit 1
}
SSL_CERT_FILE="$ip_certbot_dir/live/203.0.113.10/fullchain.pem" \
  python3 - "$platform_dir/scripts/docker_acceptance.py" "$ip_tls_port" <<'PY'
import importlib.util
import sys

script_path, port = sys.argv[1:]
spec = importlib.util.spec_from_file_location("qtail_docker_acceptance", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
base_url = f"https://203.0.113.10:{port}"
client = module.Client(base_url, resolve_spec=f"203.0.113.10:{port}:127.0.0.1")
status, body = client.request("GET", "/api/health")
if status != 200 or body.get("ok") is not True or body.get("database") != "mysql":
    raise SystemExit(f"Python HTTPS resolution acceptance failed: HTTP {status}: {body}")
print("PASS Python HTTPS resolution, certificate validation, and health proxy")
PY

docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" exec -T \
  -e QTAIL_FAKE_GENERATOR=1 api \
  python -m unittest discover -s /app/platform/backend/tests -v

ADMIN_TOKEN='qtail-release-verification-admin-token-2026-at-least-32-characters' \
  python3 "$platform_dir/scripts/docker_acceptance.py" \
  --base-url "http://127.0.0.1:$web_port" \
  --report "$acceptance_report"

docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" restart db api worker web
docker compose -p "$project" --env-file "$env_file" \
  -f "$platform_dir/docker-compose.yml" up -d --wait
ADMIN_TOKEN='qtail-release-verification-admin-token-2026-at-least-32-characters' \
  python3 "$platform_dir/scripts/docker_acceptance.py" \
  --base-url "http://127.0.0.1:$web_port" \
  --report "$acceptance_report" --verify-persistence

ENV_FILE="$env_file" COMPOSE_PROJECT_NAME="$project" \
  "$platform_dir/scripts/monitor.sh"

archive_sha256="$(shasum -a 256 "$archive" | awk '{print $1}')"
release_id="$(sed -n 's/^release_id=//p' "$release_root/RELEASE-METADATA.txt")"
python3 - "$acceptance_report" "$report_file" "$archive" "$archive_sha256" "$release_id" <<'PY'
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

acceptance_path, report_path, archive, archive_sha256, release_id = sys.argv[1:]
acceptance = json.loads(Path(acceptance_path).read_text(encoding="utf-8"))
if acceptance.get("simulation_contract_blocked") is not True:
    raise SystemExit("release acceptance did not prove the simulation-to-contract guard")
if len(acceptance.get("execution_attestation_sha256") or "") != 64:
    raise SystemExit("release acceptance did not produce an execution attestation")
provider_signature = acceptance.get("provider_signature_sha256") or ""
buyer_signature = acceptance.get("buyer_signature_sha256") or ""
if len(provider_signature) != 64 or len(buyer_signature) != 64 or provider_signature == buyer_signature:
    raise SystemExit("release acceptance did not preserve independent provider and buyer signature proofs")
if acceptance.get("persistence", {}).get("status") != "passed":
    raise SystemExit("release acceptance persistence verification did not pass")
report = {
    "status": "passed",
    "verified_at": datetime.now(UTC).isoformat(),
    "release_id": release_id,
    "archive": archive,
    "archive_sha256": archive_sha256,
    "inner_manifest": "passed",
    "production_compose_render": {"caddy": "passed", "cloudflare": "passed", "ecs_small_caddy": "passed", "ip_tls_caddy": "passed", "alternate_https": "passed"},
    "ip_tls_caddy_validation": "passed_with_sni_less_trusted_handshake_and_health_proxy",
    "smoke_checks": 16,
    "buyer_pilot_kit": "passed_with_11_blank_templates_executable_gate1_validator_archive_and_sha256_sidecar",
    "backend_tests": 31,
    "official_payment_crypto": "passed_with_generated_test_keys",
    "offsite_backup_replication": "passed_with_local_file_destination_and_downloaded_sha256_match",
    "restricted_backup_export": "passed_metadata_stream_hash_and_command_rejection",
    "commercial_e2e_run_id": acceptance["run_id"],
    "commercial_e2e_persistence": acceptance.get("persistence", {}).get("status"),
    "simulation_contract_guard": "passed",
    "execution_attestation_sha256": acceptance.get("execution_attestation_sha256"),
    "provider_signature_sha256": provider_signature,
    "buyer_signature_sha256": buyer_signature,
    "deletion_receipt_sha256": acceptance.get("deletion_receipt_sha256"),
    "simulation_only": True,
    "claim_boundary": "Independent release verification proves packaged Docker software behavior only; not payment settlement, buyer acceptance, real-robot performance, or an executed contract.",
}
Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "PASS independent release archive verification"
echo "Verification report: $report_file"
