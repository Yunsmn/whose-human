#!/usr/bin/env bash
# curl with its defaults: one curl process per request, as agents that shell out to curl do
# (Borysenko 2026 saw curl/8.4.0 from Cline and Junie). Same four requests as every other stack.
#
# Usage: bash fetch_curl.sh <base_url> <text>
#   base_url  e.g. https://site1.test:8443/r/b-0001/
#
# -sS, -o and -w only change what curl prints, not what it sends. Trust for our local CA comes
# from the CURL_CA_BUNDLE environment variable, which the runner sets; it doesn't change the
# ClientHello. Works with OpenSSL-based curl (Linux, macOS). The Schannel curl on Windows fails
# its revocation check against our local CA; see README.md.
#
# WH_THINK_TIME (set by the runner's --think-time) adds a pause before every request after the
# first: "3" waits 3 seconds, "2-6" a random time between 2 and 6 seconds. Unset: no pause.
set -u

if [ "$#" -ne 2 ]; then
  echo "usage: bash fetch_curl.sh <base_url> <text>" >&2
  exit 2
fi
base="$1"
text="$2"
case "$base" in */) ;; *) base="$base/" ;; esac

think="${WH_THINK_TIME:-}"
think="${think// /}"
if [ -n "$think" ] && ! [[ "$think" =~ ^[0-9]+(\.[0-9]+)?(-[0-9]+(\.[0-9]+)?)?$ ]]; then
  echo "invalid WH_THINK_TIME='$think': use seconds (3) or a range (2-6)" >&2
  exit 2
fi
pause() {
  [ -n "$think" ] || return 0
  local seconds
  seconds="$(awk -v spec="$think" -v seed="$RANDOM$$" 'BEGIN {
    n = split(spec, part, "-"); lo = part[1] + 0; hi = (n > 1 ? part[2] : part[1]) + 0
    if (hi < lo) exit 1
    srand(seed); printf "%.3f", lo + rand() * (hi - lo) }')" || {
    echo "invalid WH_THINK_TIME='$think': the range must not decrease" >&2
    exit 2
  }
  sleep "$seconds"
}

failed=0
requests=0
step() {
  local name="$1"
  shift
  [ "$requests" -eq 0 ] || pause
  requests=$((requests + 1))
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$@")" || code="${code:-000}"
  echo "$name $code"
  [ "$code" = "200" ] || failed=1
}

step "GET index.html" "${base}index.html"
step "GET input.html" "${base}input.html"
step "GET submit" -G --data-urlencode "text=${text}" "${base}submit"
step "POST submit" --data-urlencode "text=${text}" "${base}submit"

exit "$failed"
