# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Requests from different agents on the same machine share the IP and an environment signature (runtime and TLS stack versions).
Status: open (first observation below)

Date: 2026-11-18
Run ids: c-user-curl-001 (site2), compared with the 7 natural headless Claude Code runs that used curl (c-claude-h-001, c-claude-sh-site{1,2}-00{1,2,3}; site1 and site2) and c-codex-h-001 (site1). The directed curl session in c-claude-i-001 is not used, as in the harness entry.
Setup: C typed curl by hand on site2 (the user's own traffic); the agents used curl on their own, all on the same Linux machine.
Result: the user's own curl and every agent curl request have the same JA4, JA3, HTTP/2 fingerprint, ALPN, HTTP version, User-Agent (`curl/8.23.0`, OpenSSL 4.1) and Accept. All 7 Claude Code GET requests also matched the user's header order exactly. Of the 6 Claude Code POST submits, 1 matched exactly and 5 differed only in the body format (`multipart/form-data`, the curl command Claude wrote); Codex's POST added a `Cookie` header. The site does not change the signature. Timing from the page to the first submit: user 136.3 s; the 6 Claude Code runs that used only curl 3.1 to 3.6 s; Codex 5.2 s.
Conclusion: supported for agents that shell out: when an agent uses the system curl it carries the same environment signature as the user's own curl, across agents and sites. How identifying that is depends on how rare the build is; a rolling-release curl/OpenSSL pair is narrower than stock Windows curl. Inconclusive for agents with their own client (WebFetch). Based on one user run.
Next: 3c combines this signature with IP and timing; test whether it survives an IP change (H2).

## H2: Linking still works when the IP changes, using environment and timing alone.
Status: open
