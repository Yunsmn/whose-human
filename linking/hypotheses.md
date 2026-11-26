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

## 3c dry run: linking the local agent runs without the IP
Date: 2026-11-24
Run ids: every non-baseline run of persona-b1 (B, Windows: 30 Claude Code runs) and persona-c1 (C, Linux: 27 Claude Code runs, 1 Codex, 1 user curl), from the local logs. Not a Track 3 campaign: a test of the `linking/` pipeline on the data we have.
Setup: `python -m linking.link`, one session per run (no browser sessions yet), 59 sessions, 1,711 pairs (841 same user). Local runs all show the Docker gateway as the client IP, so the IP carries nothing here and every result is effectively "without IP".
Result:
- Whether two sessions' JA4s match, by the tool each session used:

  | Sessions compared | Same user | Different users |
  |---|---|---|
  | curl and curl | match in 156 of 156 pairs | match in 0 of 169 |
  | WebFetch and WebFetch | 87 of 87 | 84 of 84 |
  | curl and WebFetch | 0 of 247 | 0 of 247 |

- Logistic regression on the network-trace features (no IP, no run token, no schedule), 5-fold by session: AUC 0.84, precision 0.75, recall 0.72 at 0.5 (319 scored pairs).
Conclusion: when the agent shells out, the system curl carries the machine's TLS stack and links its sessions; WebFetch carries the same fingerprint on every machine, so it links nothing without the IP; and nothing in the trace links a user's curl sessions to their WebFetch sessions. With two users on different operating systems this is the easy case: two users with the same OS and curl build would collide (3d).
Next: the Track 3 campaign on the VM, with real IPs, browser visits and three users; more than one user per OS.

## 3d dry run: hard cases on the local runs
Date: 2026-11-25
Run ids: the same sessions as the 3c dry run (59 sessions, persona-b1 and persona-c1, local logs). Not a Track 3 campaign: a test of `linking.hard_cases` on the data we have.
Setup: `python -m linking.hard_cases data/logs`. Every local request shows the Docker gateway as its client IP, so every pair "shares an IP", and no pair shows an IP change.
Result:
- IP change: no pairs (no second network in local runs).
- Identical setups: 84 of 870 pairs of different users (9.7%) match on every signature column. All 84 are WebFetch against WebFetch: 84 of 84 of those pairs, and 0 for every other tool pair (curl against curl, 0 of 169).
- Anonymity: 40 of 59 sessions (68%) have a signature that no other user shares: every curl and every WebFetch-then-curl session. None of the 19 WebFetch-only sessions does.
- Shared IP (here: every pair of different users): the `network_only` model falsely links 20.1% of the 174 scored pairs, and the `no_ip` model 13.8%. The false links come from mixed tool pairs (curl / WebFetch 42.6%, WebFetch / WebFetch-then-curl 34.6%), not from curl against curl (0 of 32) or WebFetch against WebFetch (0 of 15).
Conclusion: the pipeline runs. With two users on two OSes, the identical-setup case is exactly WebFetch, as 3c found: its sessions collide between users, while a user's system curl keeps them apart. The false links under a shared IP are the model's mistakes on mixed tool pairs, not collisions of environment.
Next: the campaign's settings 4 (IP change) and 5 (three users on one campus IP). Then the identical-setup question needs two users with the same OS and curl build.
