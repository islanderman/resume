#!/usr/bin/env bash
# Serves public/ with `wrangler pages dev`, which applies _redirects and _headers the way Pages
# does, then checks the status codes that the unit tests cannot see. Run `npm ci` first.
set -euo pipefail

cd "$(dirname "$0")/.."
base='http://127.0.0.1:8788'
log="$(mktemp)"

WRANGLER_SEND_METRICS=false ./node_modules/.bin/wrangler pages dev public \
  --ip 127.0.0.1 --port 8788 --show-interactive-dev-session=false >"${log}" 2>&1 &
pid=$!
trap 'kill "${pid}" 2>/dev/null || true; wait "${pid}" 2>/dev/null || true; rm -f "${log}"' EXIT

# code <path> [curl options]: the status of the last response, 000 when nothing answered.
code() {
  local path=$1
  shift
  curl --silent --max-time 10 --output /dev/null --write-out '%{http_code}' "$@" "${base}${path}" ||
    true
}

# csp <path>: the Content-Security-Policy value, empty when the header is absent.
csp() {
  { curl --silent --max-time 10 --output /dev/null --dump-header - "${base}$1" || true; } |
    tr -d '\r' | awk 'tolower($0) ~ /^content-security-policy:/ { sub(/^[^:]*:[ \t]*/, ""); print }'
}

failures=0
pass() { echo "ok    $1"; }
fail() {
  echo "FAIL  $1" >&2
  failures=$((failures + 1))
}
expect() { # expect <status> <path> [curl options]
  local want=$1 path=$2 got label
  shift 2
  got="$(code "${path}" "$@")"
  label="${path}${*:+ $*} -> ${got}"
  if [ "${got}" = "${want}" ]; then pass "${label}"; else fail "${label}, want ${want}"; fi
}

# Wait for a 200 on /, not just any answer: a proxy in front of localhost answers 502 early.
for _ in $(seq 120); do
  kill -0 "${pid}" 2>/dev/null || break
  [ "$(code /)" = 200 ] && break
  sleep 0.5
done
kill -0 "${pid}" 2>/dev/null || fail 'wrangler pages dev exited early'

expect 200 /
expect 404 /404
expect 404 /404.html --location
expect 404 /nope

nope_csp="$(csp /nope)"
if [ -z "${nope_csp}" ]; then
  fail '/nope sends no Content-Security-Policy'
elif [ "$(csp /404)" != "${nope_csp}" ]; then
  fail "/404 sends a different Content-Security-Policy than /nope: '$(csp /404)'"
else
  pass '/404 sends the same Content-Security-Policy as /nope'
fi

if [ "${failures}" -gt 0 ]; then
  echo "--- wrangler pages dev output ---" >&2
  cat "${log}" >&2
  exit 1
fi
