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
Conclusion: inconclusive for H1 (no agent traffic yet), but the premise holds: on one machine the TLS layer identifies the runtime, not the library or tool. Supports the H2 direction: headers separate stacks even without the User-Agent.
Next:
- Run Claude Code and Codex on the same Linux machine (c- run ids) and compare them with these baselines, with and without the User-Agent.
- Repeat on Windows with A's agent runs and B's baselines.

## H2: Header order, header set and request timing separate them anyway.
Status: open
