# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Agents sharing an HTTP library are indistinguishable from plain scripts using that library at the TLS layer alone.
Status: open (scripts-only step below; the agent comparison waits for agent runs on the same machine)

Date: 2026-11-18
Run ids: c-0001..c-0722 (runs/c.csv)
Setup:
- 12 plain script stacks (1b) on one Linux machine (C): Node 26 (axios 1.8.4, axios 1.21.1, got, node https, node fetch), Python 3.14 (requests, httpx, aiohttp, urllib), curl 8.23 / OpenSSL 4.1, Go (net/http, Colly).
- 2 sites, 30 trials each (httpx and requests 31), 4 requests per run: 2,888 requests, all status 200.
- 1c Extra Trees, 5-fold cross-validation grouped by run_id, one label per stack.
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

## H2: Header order, header set and request timing separate them anyway.
Status: open
