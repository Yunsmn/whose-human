# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Agents sharing an HTTP library are indistinguishable from plain scripts using that library at the TLS layer alone.
Status: supported for agents that shell out to curl, on Linux (step 2) and Windows (step 3); rejected for Claude Code's WebFetch, a client of its own

Date: 2026-11-18
Run ids: c-0001..c-0722 (runs/c.csv)
Setup:
- 12 plain script stacks (1b) on one Linux machine (C): Node 26 (axios 1.8.4, axios 1.21.1, got, node https, node fetch), Python 3.14 (requests, httpx, aiohttp, urllib), curl 8.23 / OpenSSL 4.1, Go (net/http, Colly).
- 2 sites, 30 trials per stack per site (31 for httpx on site2 and for requests on site1, from a restarted run), 4 requests per run: 2,888 requests, all status 200.
- 1c Extra Trees, 5-fold cross-validation grouped by run_id, one label per stack. TLS only, and HTTP and HTTP/2 only, are the standard sets of `python -m harness.classify`. "HTTP without the User-Agent" and "User-Agent alone" use the same model and splits on custom column sets that `harness.classify` does not have: the `http` and `h2` columns minus `http_ua`, `http_ua_family` and `http_ua_version`, and those three columns alone.
Result:
- Every stack kept one JA4 across all its runs. The 12 stacks share 7 JA4s:
  - axios 1.8.4, axios 1.21.1, got and node https: one JA4;
  - Go net/http and Colly: one JA4 and the same HTTP/2 fingerprint;
  - httpx and aiohttp: one JA4;
  - requests, urllib, node fetch and curl: one each.
- TLS only: accuracy 0.583, macro F1 0.477. All errors are within those shared-JA4 groups.
- HTTP and HTTP/2 only: 1.000. The User-Agent alone also gives 1.000, because these scripts send library defaults.
- HTTP without the User-Agent columns: accuracy 0.917, macro F1 0.889. The only remaining confusion is axios 1.8.4 vs axios 1.21.1 (same library, two versions); header order and set separate everything else, including Go net/http vs Colly.
Conclusion: inconclusive for H1 (no agent traffic yet), but the premise holds: on one machine the TLS layer mostly identifies the runtime (the Node stacks built on node https share one JA4, Go and Colly share one), not the tool; Python stacks split into three JA4s. Supports the H2 direction: headers separate stacks even without the User-Agent.
Next:
- Run Claude Code and Codex on the same Linux machine (c- run ids) and compare them with these baselines, with and without the User-Agent.
- Repeat on Windows with A's agent runs and B's baselines.

### H1, step 2: Claude Code and Codex on the same Linux machine
Date: 2026-11-18
Run ids: 17 agent ids in runs/c.csv: c-claude-h-001, c-claude-h-002, c-claude-i-001, c-codex-h-001, c-codex-i-001, c-claude-{wf,sh}-site{1,2}-00{1,2,3}
Setup:
- Same machine as the 1b baselines (C, Linux). Claude Code 2.1.327 (claude-opus-5-5), Codex CLI 0.167.1 (gpt-6-luna). Fixed visible task from `harness.agent_runs`, fresh session each run, run from an empty folder outside the repo.
- 18 agent sessions under 17 ids: `c-claude-i-001` holds two interactive sessions, a natural one (WebFetch) and a second one explicitly told to use curl. The directed session is excluded from every tool-choice count and timing figure below; analyses grouped by run id must drop `c-claude-i-001` or split it by User-Agent (WebFetch vs curl).
- Interactive sessions used the user's own settings (Claude Code in auto permission mode, Codex in its default sandbox). Headless Claude Code ran in two tool conditions, 3 runs per condition per site in shuffled order: WebFetch only (`--allowedTools WebFetch --disallowedTools Bash`) and WebFetch plus Bash (`--allowedTools WebFetch Bash`); plus c-claude-h-001 (WebFetch and Bash) and c-claude-h-002 (WebFetch only). Codex headless used `--sandbox danger-full-access`.
Result:
- Tool choice (natural sessions only):
  - WebFetch only: 7 of 7 headless runs used WebFetch.
  - WebFetch and Bash allowed: 6 of 7 headless runs fetched with curl (c-claude-h-001 and 5 of the 6 `sh` runs); c-claude-sh-site1-001 fetched with WebFetch and submitted with curl.
  - Interactive Claude Code (auto mode): its `curl -sk` attempt was blocked, and it used WebFetch.
  - Interactive Codex (default sandbox): used its web tool; no request reached the local `.test` site.
  - Codex headless: curl.
- WebFetch (9 sessions with WebFetch requests): one variant of every logged field. HTTP/1.1, User-Agent `Claude-User (claude-code/2.1.327; +https://support.anthropic.com/)`, Accept `text/markdown, text/html, */*`, JA4 `t13d181000_...`. Header order and Accept-Encoding equal axios's defaults, but the JA4 matches none of the Node baselines (`t13d521100_...`). It always submitted through the visible GET fallback. The headless and interactive WebFetch requests were identical in every logged field. Claude Code also runs Haiku on the fetched page (both models in its usage).
- Agent curl vs `script_curl`, per field:
  - GET (page fetch): JA4, JA3, HTTP/2 fingerprint, ALPN, HTTP version, header order, User-Agent `curl/8.23.0` and Accept all matched in every agent curl request.
  - POST (submit): TLS and HTTP/2 fields, User-Agent and Accept matched. Two differences: in 5 Claude Code runs (c-claude-h-001, c-claude-sh-site1-002, -003, c-claude-sh-site2-001, -003) the body was `multipart/form-data` instead of `application/x-www-form-urlencoded` (the curl command Claude wrote); Codex's POST (c-codex-h-001) added a `Cookie` header, giving the order `user-agent, accept, content-type, content-length, cookie`.
- Timing, same endpoints on both sides (first `input.html` request to the first `submit` request of the run):
  - all 1b scripts: median 0.005 s, max 0.056 s (722 runs); `script_curl`: median 0.037 s, max 0.056 s (60 runs);
  - Claude Code with curl: median 3.21 s, range 3.12 to 3.63 s (6 runs);
  - Claude Code with WebFetch: median 8.83 s, range 7.92 to 12.94 s (8 headless runs);
  - Codex headless: 5.21 s (1 run).
Conclusion: for agents that shell out, supported at the TLS and HTTP/2 layers; at the header layer the page fetch matched exactly, and the submit differed only by command choices (multipart body, an added Cookie header). Rejected for Claude Code's WebFetch, which names itself and has its own JA4. On this Linux setup, headless and interactive sessions that use the same tool produce the same fingerprint; whether they choose the same tool under other permission settings is open.
Next:
- Headless runs with an explicit tool allowlist reproduce a tool's fingerprint, so use them for the larger collection, and report the allowlist with each condition.
- A (Codex is A's main agent): Codex interactive and headless runs on A's machine; the web tool needs the shared VM with a real domain to be observed at all.
- Repeat on Windows, where curl uses Schannel.

### H1, step 3: Claude Code and scripts on the same Windows machine
Date: 2026-11-24
Run ids: B's b-0001..b-0720 (1b, 12 stacks × 2 sites × 30 trials, #31) and b-claude-{wf,sh}-site{1,2}-00{1,2,3} (#29), all on B's Windows 11 machine on 2026-11-23.
Setup: as in step 2. Claude Code 2.1.319 headless, 3 runs per tool condition per site. Its Bash runs Git Bash's curl 8.21.0 (Schannel) with `-sk`. The script counterpart is `script_curl-norevoke` (the same curl with `--ssl-no-revoke`; both flags drop the same ClientHello extension, see `harness/baselines/README.md`). Plain Schannel curl fails against our local CA and is not a baseline.
Result:
- Agent curl vs `script_curl-norevoke`, on the raw requests: the same JA4 (`t13d2012h1_2b729b4bf6f3_36bf25f296df`), HTTP/1.1, User-Agent `curl/8.21.0` and header order, on the GET (Host, User-Agent, Accept) and on the POST (plus Content-Length, Content-Type). Unlike on Linux, all 6 submits used the urlencoded form.
- 1c on B's machine only (13 classes, grouped CV, TLS + HTTP without the User-Agent): 10 of Claude Code's 12 curl requests are labelled `script_curl-norevoke`; agent curl vs `script_curl-norevoke` alone gets macro F1 0.499 (chance).
- WebFetch's JA4 (`t13d181000_...`, identical to Linux) matches none of B's scripts, the Node stacks included.
Conclusion: supported on Windows for agents that shell out. Claude Code's curl is the same as a script running the same curl, at the TLS and header layers, as on Linux. Rejected for WebFetch, which is its own client on both OSes.
Next: H2 step 2 (timing) covers B's machine.

## H2: Header order, header set and request timing separate them anyway.
Status: supported against scripts that do not pause, on three machines (Linux and Windows); rejected against a script that pauses like an agent (step 2)

Date: 2026-11-18
Run ids: c-0001..c-0722 (1b scripts) and the 15 Claude Code ids from H1 step 2. The directed curl session in c-claude-i-001 is dropped (its 2 curl requests); its natural WebFetch session is kept. Codex is left out (1 run with traffic).
Setup:
- 1c Extra Trees, grouped 5-fold cross-validation by run_id; 13 classes (claude-code + 12 script stacks), 2,888 script requests and 30 Claude Code requests (17 WebFetch, 13 curl).
- New run-level timing features in `harness/features.py`: `run_max_gap_s` (slowest gap between consecutive requests of the run) and `run_submit_wait_s` (gap before the run's first `/submit`). They use the whole run, so they score a finished run, not a request as it arrives.
- Run-count features (`run_n_requests`, `run_n_conns`) and body length are not used: the scripts make 4 requests with a fixed text by design.
Result:
- Per request, share of Claude Code requests labelled claude-code (WebFetch / curl), and macro F1 over 13 classes:
  - TLS only: 1.00 / 0.00, macro F1 0.519. Every curl request was labelled `script_curl`.
  - TLS + HTTP + HTTP/2: 1.00 / 0.00, macro F1 0.963.
  - TLS + HTTP without User-Agent: 1.00 / 0.00, macro F1 0.861.
  - plus the per-request gap: 1.00 / 0.46, macro F1 0.909. The first request of a run has no gap.
  - plus the run-level timing features: 1.00 / 1.00, macro F1 0.934, and no script request labelled claude-code. The rest of the error is axios 1.8.4 vs 1.21.1 without the User-Agent.
- Claude Code's curl vs `script_curl` only (7 vs 60 runs): TLS only macro F1 0.211; TLS + HTTP 0.497; run-level timing alone 1.000.
- Per run, slowest gap: scripts 0.008 to 0.105 s (722 runs); Claude Code with curl 3.1 to 3.6 s (6), with WebFetch 7.9 to 16.2 s (8), both tools 10.7 s (1). A 1 s threshold flags 15 of 15 Claude Code runs and 0 of 722 script runs.
Conclusion: supported on this machine, through timing rather than headers. Header order and set do not separate Claude Code's curl from plain curl (they only separate script stacks from each other); the model's pause before submitting does, once the whole run is scored. The threshold was chosen after seeing the data, with 15 agent runs. The scripts are fast by construction, and a person typing curl took 136 s, so this separates an LLM in the loop from an automated script, not an agent from a human.
Next:
- Repeat on A's and B's machines and on the VM, with more agent runs.
- Add human-typed runs as a class, to test agent vs human timing.

### H2 step 2: across machines, and against scripts that pause
Date: 2026-11-23, updated 2026-11-24 with B's script baselines
Run ids:
- Scripts:
  - C, Linux: c-0001..c-0722, plus c-0723..c-0770. The second set is 48 runs made with `--think-time 2-6` (#26; 12 stacks × 2 sites × 2 trials, seed 11), so each script sleeps 2 to 6 s before each request after the first.
  - A, Windows: 660 runs (`runs/a.csv`, 11 stacks, no curl).
  - B, Windows: b-0001..b-0720 (12 stacks, with `curl-norevoke`, #31).
- Agents: the 15 Claude Code runs above, and B's 12 Windows Claude Code runs (b-claude-{wf,sh}-site{1,2}-00{1,2,3}, #29).
Setup: the same features and Extra Trees as step 1; agent vs script (binary) and the 13 classes. Four tests:
- same machine (B's Windows machine alone, grouped CV by run_id);
- train on one machine with agents and scripts (C or B) and test on the other;
- leave one machine out;
- pooled grouped 5-fold cross-validation by run_id.
Result:
- Without the think-time scripts:
  - Per run, slowest gap. Scripts: 0.008 to 0.105 s on C's Linux machine (722), 0.019 to 0.245 s on A's Windows machine (660), 0.029 to 0.399 s on B's (720). Claude Code with curl: 3.1 to 3.6 s on Linux, 2.9 to 3.4 s on Windows. With WebFetch: 7.9 s and up on Linux, 12.1 to 16.7 s on Windows.
  - A 1 s threshold flags 27 of 27 Claude Code runs and 0 of 2,102 script runs. Any threshold from 0.5 to 2 s gives the same.
  - Same machine (B): agent vs script macro F1 1.000 with run-level timing, alone or added to TLS + HTTP without the User-Agent. Without timing, all 240 `script_curl-norevoke` requests are labelled agent (macro F1 0.562). Agent curl vs `script_curl-norevoke` alone: 0.499 without timing, 1.000 with it.
  - Across machines, in both directions (train on C, test on B, and the reverse): run-level timing alone labels every agent request as agent and none of the 2,880 / 2,888 script requests. TLS + HTTP, with or without timing, catches WebFetch (the same client on both OSes) but none of the other OS's agent curl requests. Linux curl (OpenSSL, HTTP/2) and Git Bash's Schannel curl are different fingerprints, and the trees split on TLS before timing.
- With the think-time scripts:
  - Their slowest gap is 3.7 to 6.0 s (median 5.4 s). Their wait before the submit is 2.1 to 6.0 s. Both overlap Claude Code's.
  - A 1 s or 2 s threshold flags 48 of 48 of them as agents. A model trained without them labels all 192 of their requests as agent with run-level timing alone. TLS + HTTP mislabels 16, the curl stack, whose TLS is the agent's.
  - Pooled cross-validation over all three machines with them in training:
    - agent vs script macro F1 0.968 (TLS + HTTP + run-level timing) and 0.973 (run-level timing alone);
    - 4 of 192 think-time requests labelled agent;
    - agent recall 0.94 and 0.96.

    Run counts are not features, so this boundary is timing. It fits our 2 to 6 s draw (most of their slowest gaps are above Claude's curl range), and an adversary doesn't have to keep that.
Conclusion:
- Timing separates an LLM in the loop from a script that doesn't pause, on the same machine (Linux and Windows) and across machines and operating systems, where TLS doesn't transfer.
- Rejected against a script that pauses: a script that sleeps like an agent defeats the threshold, and the learned boundary only works because our pauses are drawn differently from the agent's. A script copying the agent's pause distribution would not be caught by these features.
- What still separates them is the client, not the behavior. WebFetch has its own JA4 and `Claude-User` User-Agent on both OSes (a self-identifying client). Agents that shell out to curl remain indistinguishable from the same curl run by a script that pauses.
Next:
- 3b/3c: timing transfers across machines, but it measures the model's latency, not the user. Treat it as an agent feature, not a linking feature. TLS is the machine's (Linux curl ≠ Git Bash curl), which is what 3b needs.
- Think-time baselines on Windows, and a script that replays Claude Code's measured pauses, to bound the timing feature properly.
- Base rates. The timing threshold's error rates bound what a site gets from it, depending on how many of its curl-like visitors are agents. Against scripts that don't pause, a 1 s threshold gave 27/27 and 0/2,102. By the rule of three, the 95% bounds are a recall of at least 0.89 and a false-positive rate of at most 0.14%. The resulting precision depends on the share of agents among such visitors:

  | Share of agents | Precision at least |
  |---|---|
  | 0.1% | 0.38 |
  | 1% | 0.86 |
  | 10% | 0.99 |

  Against scripts that pause like an agent, the false-positive rate is 1, so the precision falls to the share of agents itself. The number a site gets depends on whether its ordinary scripts pause, which we can't measure from our own baselines.

## H3: The network trace alone reveals which model tier drives Claude Code.
Status: supported for the tool sequence on two machines (Linux, Windows); the submit pause drifts between days, so it works only against runs from the same sitting (step 2). This is not one of the starting hypotheses: it came out of the timing results. It is a Track 2 signal that needs no text.
Date: 2026-11-24
Run ids: c-claude-sh-{haiku,sonnet}-site{1,2}-00{1,2,3} (new), compared with the Opus runs that had Bash allowed: c-claude-h-001 and c-claude-sh-site{1,2}-00{1,2,3} (Linux, 2026-11-18), and b-claude-sh-site{1,2}-00{1,2,3} (B's Windows machine, #29).
Setup: Claude Code 2.1.331, headless, `--model haiku` or `--model sonnet`, `--allowedTools WebFetch Bash`, the fixed task, 3 runs per site, shuffled. These are the same condition and task as the Opus runs. The two server-side measures are the tool, read from the fingerprint (WebFetch's JA4 and User-Agent, or curl's), and the time from the page fetch to the submit.
Result:
- Tool choice depends on the model:

  | Model | WebFetch | curl |
  |---|---|---|
  | Haiku | 6 of 6 | 0 |
  | Sonnet | 1 of 6 | 5 |
  | Opus (Linux) | 1 of 7 | 6 |
  | Opus (Windows) | 0 of 6 | 6 |

  In this condition, a curl fingerprint rules out Haiku. A WebFetch fingerprint makes Haiku likely, but not certain.
- Among the curl runs, the time from the page to the submit separates Sonnet from Opus:
  - Sonnet: 2.02 to 2.79 s (median 2.19 s, 5 runs, Linux).
  - Opus: 3.12 to 3.63 s (median 3.21 s, 6 runs, Linux) and 2.86 to 3.44 s (median 3.19 s, 6 runs, Windows).
  - There is no overlap: a 2.8 s threshold splits all 17 runs. The submitted summaries have similar lengths (Sonnet median 320 characters, Opus 306 to 459), so the difference is the model's speed, not the length of its output.
- With WebFetch, the wait includes Claude Code's own Haiku pass over the page. Haiku took 9.0 to 10.0 s (one 19.1 s outlier, a 7-turn run), against 8.7 s for the one Sonnet run and 7.9 to 12.9 s for Opus earlier. This doesn't separate the models.
Conclusion: supported for these three tiers on one machine, with a few runs each. The tool reveals Haiku, and the pause before submitting separates Sonnet from Opus when the agent uses curl. This is the case where TLS and headers say nothing. Caveats:
- The Opus and Sonnet runs were made on different days, and API latency changes with load and network. The pause measures provider-side speed, so it can drift over time.
- One version of Claude Code, one task.
Next:
- Interleave the models in one session of runs, to remove the day and load confound, with more runs per model.
- Repeat on the shared VM, where the network path is real.
- Report it to 2c as a model feature that needs no text.

### H3, step 2: the three models interleaved, on Windows (B)
Date: 2026-11-24
Run ids: b-claude-sh-{haiku,sonnet,opus}-site{1,2}-00{1,2,3} (runs/b.csv, #33), compared with B's Opus runs from the day before (b-claude-sh-site{1,2}-00{1,2,3}, #29).
Setup: B's Windows machine, Claude Code 2.1.319, headless, `--allowedTools WebFetch Bash`, the fixed task, 6 runs per model (2 sites × 3), all 18 interleaved in one sitting in a fixed shuffled order. Recomputed from the raw log (data repo #3): 2 requests per run, all 18 submitted.
Result:
- The sequence of tools separates all three models, with no overlap:

  | Model | Reads the page with | Submits with | Pause before submitting |
  |---|---|---|---|
  | Haiku | WebFetch (6/6) | WebFetch, GET fallback (6/6) | 13.0 to 20.5 s |
  | Sonnet | WebFetch (5/6), curl (1/6) | curl (6/6): GET 5, POST 1 | 10.0 to 14.4 s; 2.49 s in the curl-only run |
  | Opus | curl (6/6) | curl, POST (6/6) | 4.1 to 5.7 s |

  So the server sees three different patterns: WebFetch twice (Haiku), WebFetch then curl (Sonnet), curl twice (Opus). On Linux (step 1) Sonnet used curl for both steps in 5 of 6 runs, so the mixed pattern is new here; together, a WebFetch read followed by a curl submit has only been seen with Sonnet (6 runs), and curl for both steps with Sonnet or Opus.
- The pause drifts between days. B's interleaved Opus runs paused 4.1 to 5.7 s; the same machine, CLI and task gave 2.9 to 3.4 s the day before (#29), and C's Linux Opus runs 3.1 to 3.6 s. The 2.8 s threshold from step 1 still splits the one curl-only Sonnet run (2.49 s) from every Opus run, but one run doesn't test it.
Conclusion: supported for the tool sequence, which reads from the fingerprint alone and held on both machines. For timing, a fixed threshold is rejected: the pause measures provider-side latency, which moved by over 1 s between two days. Timing can still rank models within one sitting (relative, not absolute), which is what a site sees when several agents visit at about the same time.
Next:
- Compare runs only within one sitting, or normalise each pause against a reference run made at the same time.
- More curl-only Sonnet runs, to test Sonnet vs Opus on timing within one sitting.
- 2c: use the tool sequence as a text-free model feature.
