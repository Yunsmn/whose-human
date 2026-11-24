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

## Observation: the agent passes the visit's identifier on to the user
Status: observation, not a test yet (2026-11-24)
Run ids: the 27 headless Claude Code runs with saved outputs: c-claude-h-00{1,2}, c-claude-{wf,sh}-site{1,2}-00{1,2,3} (Linux) and b-claude-{wf,sh}-site{1,2}-00{1,2,3} (Windows).
Result: 5 of the 27 final answers shown to the user contain the visit's path with its run id, 4 of them as a full link. All 5 are runs that used WebFetch: 4 of B's 6 and 1 of C's 8. No run that used curl did. The task never asks for sources.
Meaning: a per-visit identifier in the URL reaches the user's screen through the agent's answer. If the user clicks the link, their own browser visit carries the identifier. That links the agent's visit to the person's browsing with no cookie, no IP and no fingerprint. It is UID smuggling (Randall et al., IMC 2022) through the agent.
Next: in the Track 3 campaign, count how often answers cite our links, and how often we follow them ourselves in setting 3, with tasks that ask research-style questions (agents cite sources there). Report it per agent and per tool.
