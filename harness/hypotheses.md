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
Run ids: c-claude-h-001, c-claude-h-002, c-claude-i-001, c-codex-h-001, c-codex-i-001, c-claude-{wf,sh}-site{1,2}-00{1,2,3} (runs/c.csv)
Setup:
- Same machine as the 1b baselines (C, Linux). Claude Code 2.1.327 (claude-opus-5-5), Codex CLI 0.167.1 (gpt-6-luna). Fixed visible task from `harness.agent_runs`, fresh session each run, run from an empty folder outside the repo.
- Interactive (user's own settings) vs headless. Headless Claude Code ran in two tool conditions: WebFetch only (`--allowedTools WebFetch --disallowedTools Bash`) and WebFetch plus Bash (`--allowedTools WebFetch Bash`), 3 runs per condition per site, shuffled. Codex headless used `--sandbox danger-full-access`.
- c-claude-i-001 holds two interactive sessions (WebFetch, then told to use curl); see its notes.
Result:
- The tool decides the fingerprint, not the mode. WebFetch headless and WebFetch interactive gave identical requests in every logged field.
- WebFetch (8 runs, 16 requests): one variant. HTTP/1.1, User-Agent `Claude-User (claude-code/2.1.327; +https://support.anthropic.com/)`, Accept `text/markdown, text/html, */*`, JA4 `t13d181000_...`. Header order and Accept-Encoding equal axios's defaults, but the JA4 matches none of the Node baselines (`t13d521100_...`), so even without the User-Agent TLS separates it from a plain axios script. It always submits through the visible GET fallback. Claude Code also runs Haiku on the fetched page (both models in its usage).
- Shell allowed: 5 of 6 runs used curl only, 1 fetched with WebFetch and submitted with curl. Agent curl is identical to the `script_curl` baseline in JA4, JA3, HTTP/2 fingerprint, ALPN, header order and User-Agent. Only the request body format varied (form-urlencoded or multipart, the command Claude wrote); Codex's curl added a Cookie header.
- Interactive Claude Code in the user's auto permission mode blocked `curl -sk` and fell back to WebFetch. Interactive Codex in its default sandbox used its web tool, which never reached the local `.test` site: no request was logged, consistent with Codex web browsing running on OpenAI's side.
- Timing: agents took 3 to 13 s between page fetch and submit (WebFetch 8 to 13 s, curl about 3 s); the 4-request curl script took 0.16 s in total.
Conclusion: supported when the agent shells out (agent curl is indistinguishable from curl at the TLS and header layers); rejected for Claude Code's WebFetch (it names itself and has its own TLS fingerprint). Which case a site sees depends on the user's permission settings.
Next:
- Headless runs with an explicit tool allowlist are a faithful, cheaper substitute for interactive runs; use them for the larger collection.
- A (Codex is A's main agent): Codex interactive and headless runs on A's machine; the web tool needs the shared VM with a real domain to be observed at all.
- Repeat on Windows, where curl uses Schannel.

## H2: Header order, header set and request timing separate them anyway.
Status: open
