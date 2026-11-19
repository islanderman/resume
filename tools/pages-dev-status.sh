#!/usr/bin/env bash
# Serves public/ with `wrangler pages dev`, which applies _redirects and _headers the way Pages
# does, then checks the status codes that the unit tests cannot see. Run `npm ci` first.
# PAGES_DEV_PORT pins the port; by default the kernel picks a free one.
set -euo pipefail

cd "$(dirname "$0")/.."
# curl honors http_proxy; requests to this machine must never leave it through a proxy.
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="127.0.0.1,localhost${no_proxy:+,${no_proxy}}"
readonly ready_seconds=90

# free_port: a loopback port the kernel reports unused. wrangler's own defaults (8788, inspector
# 9229) may be taken, or held by a stale server that would answer these checks in its place.
free_port() {
  node -e 'const s = require("net").createServer();
    s.listen(0, "127.0.0.1", () => { console.log(s.address().port); s.close(); });'
}

port="${PAGES_DEV_PORT:-$(free_port)}"
inspector_port="$(free_port)"
while [ "${inspector_port}" = "${port}" ]; do inspector_port="$(free_port)"; done
base="http://127.0.0.1:${port}"
log="$(mktemp)"
pid=''
cleanup() {
  if [ -n "${pid}" ]; then
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  fi
  rm -f "${log}"
}
trap cleanup EXIT

# code <path> [curl options]: the status of the last response, 000 when nothing answered.
code() {
  local path=$1
  shift
  curl --silent --max-time 10 --output /dev/null --write-out '%{http_code}' "$@" "${base}${path}" ||
    true
}

# header <path> <name>: the value of response header <name>, empty when it is absent.
header() {
  { curl --silent --max-time 10 --output /dev/null --dump-header - "${base}$1" || true; } |
    tr -d '\r' | awk -v name="$2" 'index(tolower($0), name ":") == 1 {
      sub(/^[^:]*:[ \t]*/, ""); print }'
}

# Something that already answers here would be checked instead of wrangler.
if [ "$(code / --max-time 2)" != 000 ]; then
  echo "FAIL  ${base} answers before wrangler starts; stop that server or set PAGES_DEV_PORT" >&2
  exit 1
fi

WRANGLER_SEND_METRICS=false ./node_modules/.bin/wrangler pages dev public \
  --ip 127.0.0.1 --port "${port}" --inspector-port "${inspector_port}" \
  --show-interactive-dev-session=false >"${log}" 2>&1 &
pid=$!

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
dump_log() {
  echo "--- wrangler pages dev output ---" >&2
  cat "${log}" >&2
}

# Wait for a 200 on /, not just any answer: a proxy in front of localhost answers 502 early. The
# deadline bounds the whole wait, short probes included.
deadline=$((SECONDS + ready_seconds))
ready=false
while [ "${SECONDS}" -lt "${deadline}" ] && kill -0 "${pid}" 2>/dev/null; do
  if [ "$(code / --max-time 2)" = 200 ]; then
    ready=true
    break
  fi
  sleep 0.5
done
if [ "${ready}" != true ]; then
  if kill -0 "${pid}" 2>/dev/null; then
    fail "wrangler pages dev gave / no 200 within ${ready_seconds} s"
  else
    fail 'wrangler pages dev exited early'
  fi
  dump_log
  exit 1
fi

expect 200 /
expect 404 /404
# /404/ has no index.html, so Pages redirects it to /404, which the rewrite answers with 404.
expect 308 /404/
expect 404 /404/ --location
expect 404 /404.html --location
expect 404 /nope

location="$(header /404/ location)"
if [ "${location}" = /404 ]; then
  pass '/404/ redirects to /404'
else
  fail "/404/ redirects to '${location}', want /404"
fi

nope_csp="$(header /nope content-security-policy)"
not_found_csp="$(header /404 content-security-policy)"
if [ -z "${nope_csp}" ]; then
  fail '/nope sends no Content-Security-Policy'
elif [ "${not_found_csp}" != "${nope_csp}" ]; then
  fail "/404 sends a different Content-Security-Policy than /nope: '${not_found_csp}'"
else
  pass '/404 sends the same Content-Security-Policy as /nope'
fi

if [ "${failures}" -gt 0 ]; then
  dump_log
  exit 1
fi
