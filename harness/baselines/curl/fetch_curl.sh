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
set -u

if [ "$#" -ne 2 ]; then
  echo "usage: bash fetch_curl.sh <base_url> <text>" >&2
  exit 2
fi
base="$1"
text="$2"
case "$base" in */) ;; *) base="$base/" ;; esac

failed=0
step() {
  local name="$1"
  shift
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
