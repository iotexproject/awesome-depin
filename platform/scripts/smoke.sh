#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${1:-${BASE_URL:-http://127.0.0.1:8080}}"
BASE_URL="${BASE_URL%/}"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/qtail-smoke.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
curl_opts=(--silent --show-error --max-time 20)
if [[ "${CURL_INSECURE:-0}" == "1" ]]; then
  curl_opts+=(--insecure)
fi

check_page() {
  local path="$1"
  local output="$tmp_dir/page"
  local code
  code="$(curl "${curl_opts[@]}" --location --output "$output" --write-out '%{http_code}' "$BASE_URL$path")"
  [[ "$code" == "200" ]] || { echo "FAIL $path returned $code" >&2; exit 1; }
  grep -q 'Q-Tail' "$output" || { echo "FAIL $path did not contain the application shell" >&2; exit 1; }
  echo "PASS $path"
}

check_asset() {
  local path="$1"
  local output="$tmp_dir/asset"
  local result
  result="$(curl "${curl_opts[@]}" --location --output "$output" --write-out '%{http_code} %{content_type}' "$BASE_URL$path")"
  [[ "$result" == 200\ image/* ]] || { echo "FAIL $path returned $result" >&2; exit 1; }
  [[ -s "$output" ]] || { echo "FAIL $path was empty" >&2; exit 1; }
  echo "PASS $path"
}

check_download() {
  local path="$1"
  local expected_sha256="$2"
  local output="$tmp_dir/download"
  local code actual_sha256
  code="$(curl "${curl_opts[@]}" --location --output "$output" --write-out '%{http_code}' "$BASE_URL$path")"
  [[ "$code" == "200" && -s "$output" ]] || { echo "FAIL $path returned $code or an empty file" >&2; exit 1; }
  if command -v sha256sum >/dev/null; then
    actual_sha256="$(sha256sum "$output" | awk '{print $1}')"
  else
    actual_sha256="$(shasum -a 256 "$output" | awk '{print $1}')"
  fi
  [[ "$actual_sha256" == "$expected_sha256" ]] || { echo "FAIL $path SHA-256 mismatch" >&2; exit 1; }
  echo "PASS $path ($actual_sha256)"
}

health="$(curl "${curl_opts[@]}" --fail "$BASE_URL/api/health")"
grep -q '"ok":true' <<< "$health" || { echo "FAIL /api/health" >&2; exit 1; }
grep -q '"database":"mysql"' <<< "$health" || { echo "FAIL MySQL health" >&2; exit 1; }
echo "PASS /api/health"

for route in / /evidence /register /login /docs /terms /privacy /dpa /payment-policy /app/compliance; do
  check_page "$route"
done
check_asset /pay/alipay.jpg
check_asset /pay/wechat.jpg
check_download /buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip db4b6432ee91dbb8cb7851dc8f4094e9b2d1329023c4fa935426c7647afd78ff

kit_manifest="$(curl "${curl_opts[@]}" --fail "$BASE_URL/buyer-kit/manifest.json")"
grep -q '"package": "qtail_buyer_procurement_pilot_kit"' <<< "$kit_manifest" || { echo "FAIL /buyer-kit/manifest.json" >&2; exit 1; }
grep -q '"contract_eligibility": false' <<< "$kit_manifest" || { echo "FAIL buyer kit claim boundary" >&2; exit 1; }
echo "PASS /buyer-kit/manifest.json"

kit_sidecar="$(curl "${curl_opts[@]}" --fail "$BASE_URL/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip.sha256")"
[[ "$kit_sidecar" == "db4b6432ee91dbb8cb7851dc8f4094e9b2d1329023c4fa935426c7647afd78ff  qtail-buyer-pilot-kit-v1.2.0.zip" ]] || { echo "FAIL buyer kit checksum sidecar" >&2; exit 1; }
echo "PASS /buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip.sha256"

if [[ -n "${SMOKE_AUTH_EMAIL:-}" && -n "${SMOKE_AUTH_PASSWORD:-}" ]]; then
  cookie_jar="$tmp_dir/cookies"
  login_code="$(curl "${curl_opts[@]}" --cookie-jar "$cookie_jar" --output "$tmp_dir/login.json" --write-out '%{http_code}' -H 'Content-Type: application/json' --data "{\"email\":\"$SMOKE_AUTH_EMAIL\",\"password\":\"$SMOKE_AUTH_PASSWORD\"}" "$BASE_URL/api/auth/login")"
  [[ "$login_code" == "200" ]] || { echo "FAIL authenticated login returned $login_code" >&2; exit 1; }
  me="$(curl "${curl_opts[@]}" --cookie "$cookie_jar" "$BASE_URL/api/auth/me")"
  grep -q '"ok":true' <<< "$me" || { echo "FAIL authenticated session" >&2; exit 1; }
  curl "${curl_opts[@]}" --cookie "$cookie_jar" --request POST --output /dev/null "$BASE_URL/api/auth/logout"
  echo "PASS authenticated session"
fi

echo "Q-Tail smoke checks passed for $BASE_URL"
