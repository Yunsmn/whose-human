# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Requests from different agents on the same machine share the IP and an environment signature (runtime and TLS stack versions).
Status: open (first observation below)

Date: 2026-11-18
Run ids: c-user-curl-001 (site2), compared with c-claude-i-001 and c-codex-h-001 (site1)
Setup: C typed curl by hand on site2 (the user's own traffic); Claude Code and Codex used curl on site1, all on the same Linux machine.
Result: the user's own curl on site2 and both agents' curl on site1 have the same JA4, JA3, HTTP/2 fingerprint and User-Agent (`curl/8.23.0`, OpenSSL 4.1); the header order matches Claude Code's curl, and Codex's adds only a Cookie header. The site does not change the signature. Only timing separated the human: 136 s from page to submit, against 3 to 7 s for the agents.
Conclusion: supported for agents that shell out: when an agent uses the system curl it carries the same environment signature as the user's own curl, across agents and sites. How identifying that is depends on how rare the build is; a rolling-release curl/OpenSSL pair is narrower than stock Windows curl. Inconclusive for agents with their own client (WebFetch).
Next: 3c combines this signature with IP and timing; test whether it survives an IP change (H2).

## H2: Linking still works when the IP changes, using environment and timing alone.
Status: open
