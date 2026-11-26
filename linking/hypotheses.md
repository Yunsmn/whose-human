# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Requests from different agents on the same machine share the IP and an environment signature (runtime and TLS stack versions).
Status: supported for the IP on the VM (every member's agents shared one address per setting); for the environment signature only between agents that use the same system tool (see "Campaign, first results").

Date: 2026-11-18
Run ids: c-user-curl-001 (site2), compared with the 7 natural headless Claude Code runs that used curl (c-claude-h-001, c-claude-sh-site{1,2}-00{1,2,3}; site1 and site2) and c-codex-h-001 (site1). The directed curl session in c-claude-i-001 is not used, as in the harness entry.
Setup: C typed curl by hand on site2 (the user's own traffic); the agents used curl on their own, all on the same Linux machine.
Result: the user's own curl and every agent curl request have the same JA4, JA3, HTTP/2 fingerprint, ALPN, HTTP version, User-Agent (`curl/8.23.0`, OpenSSL 4.1) and Accept. All 7 Claude Code GET requests also matched the user's header order exactly. Of the 6 Claude Code POST submits, 1 matched exactly and 5 differed only in the body format (`multipart/form-data`, the curl command Claude wrote); Codex's POST added a `Cookie` header. The site does not change the signature. Timing from the page to the first submit: user 136.3 s; the 6 Claude Code runs that used only curl 3.1 to 3.6 s; Codex 5.2 s.
Conclusion: supported for agents that shell out: when an agent uses the system curl it carries the same environment signature as the user's own curl, across agents and sites. How identifying that is depends on how rare the build is; a rolling-release curl/OpenSSL pair is narrower than stock Windows curl. Inconclusive for agents with their own client (WebFetch). Based on one user run.
Next: 3c combines this signature with IP and timing; test whether it survives an IP change (H2).

## H2: Linking still works when the IP changes, using environment and timing alone.
Status: partly supported, first campaign data (see "Campaign, first results" below); one user changed network, so the IP-change case rests on one person.

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

- Logistic regression, 5-fold by session, every pair scored by a model trained on neither of its sessions (1,711 pairs), threshold 0.5:

  | Features | Pair AUC | Precision | Recall | Clusters: ARI | B-cubed F1 |
  |---|---|---|---|---|---|
  | without IP (`no_ip`: network trace, schedule, run token) | 0.89 | 0.82 | 0.75 | 0.80 | 0.89 |
  | network trace only (`network_only`) | 0.84 | 0.71 | 0.69 | 0.38 | 0.67 |

  Clusters use average linkage. Connected components (single linkage) merge everyone into one cluster with either feature set (ARI 0.00), because WebFetch sessions of different users look the same and one false link is enough.
- What the clusters hold: without IP, one cluster per user's curl and mixed sessions; B's WebFetch sessions join B's cluster and C's form a cluster of their own. They are kept apart by the time between sessions, not by the network: B and C ran their agents on different days. With the network trace alone, WebFetch sessions of both users end up in one cluster with B's curl sessions.
Conclusion: the gain from `network_only` to `no_ip` is our schedule, not a property of the user, so `network_only` is the honest number for linking without IP. When the agent shells out, the system curl carries the machine's TLS stack and links its sessions; WebFetch carries the same fingerprint on every machine, so it links nothing without the IP; and nothing in the trace links a user's curl sessions to their WebFetch sessions. With two users on different operating systems this is the easy case: two users with the same OS and curl build would collide (3d).
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

## Campaign, first results (settings 1, 3, 4)
Date: 2026-11-26
Run ids: every `<letter>-t3-...` run in runs/a.csv, b.csv, c.csv up to setting 4: A's Codex and browser runs (settings 1 and 3), B's Claude Code, Codex and browser runs (1 and 3), C's Claude Code, Codex and browser runs (1, 3 and 4). Setting 5 not run yet.
Setup: the shared VM log of 2026-11-25 and a snapshot of 2026-11-26 (data repo, `logs/vm-*.jsonl`); `python -m linking.campaign` and `python -m linking.paper_tables` (#51, #56) with the rarity features and browser-detection fix of #55. 72 sessions of 3 users, 2,556 pairs, every pair scored out of sample (5 folds), clusters by average linkage. Only counts and rates leave the private data; no address is printed.
Result:
- Coverage: every planned run is in the log. Not submitted: 3 of B's 6 Codex runs (its web tool, PowerShell and curl failed in the sandbox) and C's `c-t3-claude-wf-site1-s4-002` (WebFetch reported the page as not loading; no request logged). Browser visits: every visit logged, one human submit per site.
- Addresses: within each member and setting, all agents and the browser came from one address. C's setting 4 used a different address from setting 1 (the IP change). B's setting 1 and C's setting 4 came from the same address: two different people behind one campus IP, a first shared-IP case before setting 5. No client used IPv6.
- Environment signature: each member's agents showed 5 different JA4 sets (WebFetch, curl, Python requests and urllib); of 7 agent JA4 values, 2 were seen for more than one user (WebFetch's, and Windows Schannel curl). 79% of sessions have a signature no other user shares.
- Linking (pair AUC / ARI / B-cubed F1): same-IP rule 0.58 / 0.15 / 0.64; model with every feature 0.90 / 0.69 / 0.85; without the IP 0.87 / 0.69 / 0.85; network trace only 0.70 / 0.38 / 0.65. Recall of same-person pairs, model with every feature: across agents 0.80, across sites 0.82, agent and browser 0.79.
- IP change (C's settings 1 vs 4, 360 same-person pairs): same-IP rule 0%, model without the IP 34%, network trace only 89%. The model without the IP also uses the time between sessions; C's setting 4 ran hours after setting 1 while different people ran at different times, so that feature reads the change as a different person. It measures our schedule, not the user.
- Shared IP (747 pairs of different people behind one address): the same-IP rule links all of them; false links: model without the IP 23%, network trace only 41%.
- Per-visit sentence (decision A): the submitted summary names the keyword of a sentence its page served in 81% of 31 Claude Code runs and 95% of 19 Codex runs, against 8% of 12 human browser submits; summaries named a keyword of a pool sentence the run was not served 0% of the time.
- No agent requested `robots.txt`, `llms.txt`, a favicon or the Markdown copies, although every VM page links `llms.txt` and its `.md` copy.
- Two agent requests carried a `Mozilla/5.0` User-Agent: Codex through PowerShell 7 on A's machine, and a Claude Code run on B's machine that wrote its own (`Mozilla/5.0 (compatible; ClaudeCode)`). Counting them as browser visits made them look like relayed links; #55 fixes the detection. No real relayed-link visit occurred in these runs.
Conclusion: preliminary, three users. The IP alone links poorly here, because one user changed network and two shared an address; the model without the IP keeps AUC 0.87, and the network trace alone links one person across an IP change (89% of pairs) at the cost of false links behind a shared IP (41%). The time between sessions should be left out of headline numbers. The per-visit sentence is a strong sign of an LLM in the loop: agents repeat it, people don't.
Next: setting 5 (all three behind one campus IP at once); A's runs are labelled `home` but share B's campus address, to be confirmed with A; rerun the tables when the 2026-11-26 log is final.
