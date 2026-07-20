#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-qtail-production}"
action="${1:-up}"

[[ -f "$ENV_FILE" ]] || { echo "Environment file not found: $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

ingress_mode="${QTAIL_INGRESS_MODE:-caddy}"
tls_mode="${QTAIL_TLS_MODE:-domain_acme}"
alt_https_port="${QTAIL_ALT_HTTPS_PORT:-}"
compose=(docker compose -p "$COMPOSE_PROJECT_NAME" --env-file "$ENV_FILE"
  -f "$ROOT_DIR/docker-compose.yml"
  -f "$ROOT_DIR/docker-compose.production.yml")
overlays="$ROOT_DIR/docker-compose.production.yml"
required_services="db,api,worker,web"

host_profile="${QTAIL_HOST_PROFILE:-standard}"
case "$host_profile" in
  standard)
    ;;
  ecs-small)
    compose+=(-f "$ROOT_DIR/docker-compose.ecs-small.yml")
    overlays+=":$ROOT_DIR/docker-compose.ecs-small.yml"
    ;;
  *)
    echo "QTAIL_HOST_PROFILE must be standard or ecs-small" >&2
    exit 2
    ;;
esac

prepare_cloudflare_secret() {
  local secret_file="${CLOUDFLARE_TUNNEL_TOKEN_FILE:-$ROOT_DIR/var/secrets/cloudflare_tunnel_token}"
  local token="${CLOUDFLARE_TUNNEL_TOKEN:-}"
  local secret_dir temp_file secret_mode

  if [[ "$secret_file" != /* ]]; then
    secret_file="$ROOT_DIR/${secret_file#./}"
  fi
  export CLOUDFLARE_TUNNEL_TOKEN_FILE="$secret_file"

  # A host secret manager may expose the connector token only for this command.
  # Materialize it atomically because file-backed Compose secrets work across
  # Compose implementations and never put the value in container metadata.
  if [[ -n "$token" ]]; then
    secret_dir="$(dirname "$secret_file")"
    install -d -m 0700 "$secret_dir"
    temp_file="$(mktemp "$secret_dir/.cloudflare_tunnel_token.XXXXXX")"
    chmod 0600 "$temp_file"
    printf '%s\n' "$token" > "$temp_file"
    mv -f "$temp_file" "$secret_file"
  fi

  [[ -s "$secret_file" ]] || {
    echo "Cloudflare token secret is missing: $secret_file" >&2
    echo "Set CLOUDFLARE_TUNNEL_TOKEN for this command or provision CLOUDFLARE_TUNNEL_TOKEN_FILE." >&2
    exit 1
  }
  if [[ "$(uname -s)" == "Linux" ]]; then
    secret_mode="$(stat -c '%a' "$secret_file")"
  else
    secret_mode="$(stat -f '%Lp' "$secret_file")"
  fi
  (( (8#$secret_mode & 077) == 0 )) || {
    echo "Cloudflare token secret must not be accessible by group/others (mode is $secret_mode)" >&2
    exit 1
  }
}

case "$ingress_mode" in
  caddy)
    compose+=(-f "$ROOT_DIR/docker-compose.edge.yml")
    overlays+=":$ROOT_DIR/docker-compose.edge.yml"
    case "$tls_mode" in
      domain_acme)
        ;;
      ip_certificate)
        compose+=(-f "$ROOT_DIR/docker-compose.ip-tls.yml")
        overlays+=":$ROOT_DIR/docker-compose.ip-tls.yml"
        ;;
      *)
        echo "QTAIL_TLS_MODE must be domain_acme or ip_certificate for Caddy ingress" >&2
        exit 2
        ;;
    esac
    if [[ -n "$alt_https_port" ]]; then
      [[ "$alt_https_port" =~ ^[0-9]+$ ]] && (( alt_https_port >= 1024 && alt_https_port <= 65535 )) || {
        echo "QTAIL_ALT_HTTPS_PORT must be an integer from 1024 through 65535" >&2
        exit 2
      }
      [[ "$alt_https_port" != "${HTTP_PORT:-80}" && "$alt_https_port" != "${HTTPS_PORT:-443}" ]] || {
        echo "QTAIL_ALT_HTTPS_PORT must differ from HTTP_PORT and HTTPS_PORT" >&2
        exit 2
      }
      compose+=(-f "$ROOT_DIR/docker-compose.alt-https.yml")
      overlays+=":$ROOT_DIR/docker-compose.alt-https.yml"
    fi
    required_services+=",edge"
    ;;
  cloudflare)
    prepare_cloudflare_secret
    compose+=(-f "$ROOT_DIR/docker-compose.cloudflare.yml")
    overlays+=":$ROOT_DIR/docker-compose.cloudflare.yml"
    required_services+=",tunnel-dns,cloudflared"
    ;;
  *)
    echo "QTAIL_INGRESS_MODE must be caddy or cloudflare" >&2
    exit 2
    ;;
esac

case "$action" in
  config)
    "${compose[@]}" config --quiet
    ;;
  up|reload)
    "${compose[@]}" up -d --build --wait
    ;;
  start)
    "${compose[@]}" up -d --no-build --wait
    ;;
  down)
    "${compose[@]}" down
    ;;
  ps)
    "${compose[@]}" ps
    ;;
  check)
    ENV_FILE="$ENV_FILE" \
      COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
      COMPOSE_OVERLAYS="$overlays" \
      REQUIRED_SERVICES="$required_services" \
      exec "$ROOT_DIR/scripts/check_stack.sh"
    ;;
  monitor)
    ENV_FILE="$ENV_FILE" \
      COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
      COMPOSE_OVERLAYS="$overlays" \
      REQUIRED_SERVICES="$required_services" \
      exec "$ROOT_DIR/scripts/monitor.sh"
    ;;
  backup)
    ENV_FILE="$ENV_FILE" \
      COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
      COMPOSE_OVERLAYS="$overlays" \
      exec "$ROOT_DIR/scripts/backup.sh"
    ;;
  restart-edge)
    [[ "$ingress_mode" == "caddy" ]] || {
      echo "restart-edge is only valid for Caddy ingress" >&2
      exit 2
    }
    # Release directories are switched behind /opt/qtail/current. A plain
    # restart may retain a bind mount resolved from the previous symlink
    # target, so recreate only the edge and leave Web/API/MySQL untouched.
    "${compose[@]}" up -d --no-build --no-deps --force-recreate --wait edge
    ;;
  *)
    echo "Usage: $0 {config|up|start|reload|down|ps|check|monitor|backup|restart-edge}" >&2
    exit 2
    ;;
esac
