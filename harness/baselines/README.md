# 1b: plain script baselines

Owner: B. Consumer: C (1c, `harness/features.py` and `harness/classify.py`). See `TEAM.md`.

Track 1's first hypothesis says an agent is indistinguishable, at the TLS layer alone, from a plain script using the same HTTP library. Testing it needs traffic from plain scripts. These scripts produce it: one per HTTP stack that coding agents use, each with **library defaults**, making the **same visit**, labelled `script_<stack>`.

## Stacks

| Stack | Label | Library (pinned) | Agent using this stack (Borysenko 2026) |
|---|---|---|---|
| `axios-1.8.4` | `script_axios-1.8.4` | axios 1.8.4, Node | the Node/axios coding agent (observed `axios/1.8.4`) |
| `axios` | `script_axios` | axios 1.21.1, Node | current axios, to separate "same library" from "same version" |
| `got` | `script_got` | got 16.2.0, Node | Cursor |
| `node-fetch` | `script_node-fetch` | Node built-in fetch (undici) | Node-based tools |
| `node-https` | `script_node-https` | Node built-in `https` | Node-based tools |
| `curl` | `script_curl` | the system curl | Cline, Junie (observed `curl/8.4.0`) |
| `requests` | `script_requests` | requests 2.34.2 | Python tools |
| `httpx` | `script_httpx` | httpx 0.28.1 | Python tools |
| `urllib` | `script_urllib` | Python built-in `urllib` | Python tools |
| `aiohttp` | `script_aiohttp` | aiohttp 3.14.5 | Python tools |
| `go-nethttp` | `script_go-nethttp` | Go `net/http` | Antigravity (observed `Go-http-client/2.0`) |
| `colly` | `script_colly` | Colly v2.3.0 | Windsurf |

Aider is not in this list on purpose: Borysenko observed it fetching with headless Chromium (Playwright), not a plain HTTP library.

## What every script does

The same four requests, in this order, against `https://<site>.test:8443/r/<run_id>/`:

1. `GET index.html`
2. `GET input.html`
3. `GET submit?text=baseline script submission`
4. `POST submit` with the same text as a form field

Rules, so differences in the logs come from the stack and not from the script:

- **Library defaults.** No custom headers, no User-Agent, no forced HTTP version. Only what a form post must carry is set (`Content-Type` and `Content-Length` in the bare `https` script).
- **Certificate checks stay on.** The runner points each stack at our local CA through environment variables (`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE`). These change which certificates are trusted, not the ClientHello.
- **Natively on the host, never in Docker.** The host's runtime and TLS library are the measurement.
- **Same machine as the agent runs.** A comparison with A's 1a agent runs only means something on the same OS and TLS stack.

These choices follow Kang et al. 2026 (crawler baselines with defaults, same pages as the agents, 30 sessions each, one at a time) and Borysenko 2026 (agent stacks and versions).

## Setup

1. The local server and its CA, from `infra/README.md`, **including step 3 (trust the CA) and step 4 (hosts file)**. Go on Windows and macOS only trusts the system store.
2. Node 22 or later: `cd harness/baselines/node && npm ci`
3. Python 3.12: `pip install -r harness/baselines/python/requirements.txt`
4. curl: the system curl and `bash` (`curl/fetch_curl.sh`). `--list` shows curl's version and TLS library. On Windows, Schannel curl is left out of `--stacks all` (see below); name it explicitly with `--stacks curl` to run it anyway, for example against the shared VM. Its `curl-norevoke` variant runs instead (see below).
5. Go 1.24 or later (Colly v2.3.0 requires it). `go.sum` is committed; `go run` fetches the modules on first use.

## Running

From the repository root:

```sh
python -m harness.baselines.run_baselines --list              # stacks and versions; unavailable ones are marked
python -m harness.baselines.run_baselines --dev --trials 1    # smoke test: dev- ids, no manifest rows
python -m harness.baselines.run_baselines --dry-run           # show the plan, run nothing
python -m harness.baselines.run_baselines                     # real run: 30 trials per stack per site
```

- **Run ids:** `b-0001`, `b-0002`, ..., continuing from `runs/b.csv`. Each trial appends one row: `label_agent` = `script_<stack>`, empty `label_model`, `label_user` = `baseline`, and the library, runtime, OS, site, trial number, seed and exit code in `notes`. Versions are cut to three parts, because the CI private-data guard reads four-part numbers as IP addresses.
- **Order:** every (stack, site, trial) is shuffled with a recorded seed, and runs one at a time with a 2 second gap (`--gap`).
- **Only our servers:** the runner refuses any host outside `site1.test`, `site2.test`, `localhost` and `127.0.0.1`. Add the shared VM's hostnames with `WH_ALLOWED_HOSTS=host1,host2` and `--url-template`.
- **Failures:** a failed trial still gets its manifest row, with its exit code in `notes`, so any records it left stay labelled. Check the output before handing data to C.
- **Another member running them:** `--member c` (or `a`) numbers runs `c-0001`, ... and writes them to `runs/c.csv`, with machine label `c-<os>`, so ids never clash with B's.
- **Pauses inside a visit:** by default the four requests go back to back, which makes plain timing separate any agent from these scripts by construction. `--think-time 3` (or a random range, `--think-time 2-6`, at most 30 s) makes every stack wait that long before each request after the first. The runner passes it as `WH_THINK_TIME` and writes `think <value>s` into the run's `notes`. Runs without it record nothing and are unchanged. The pause does not change how a client builds a handshake, but it can change how connections are reused. Checked on Windows (one dev run per stack, with and without `--think-time 1-2`): every stack kept the same JA4, header order and connection count, except node fetch (undici). Without pauses, undici opens a second connection for the back-to-back requests, and that handshake resumes the first session (adds `pre_shared_key`, extension 41: JA4 `t13d5213h1` instead of `t13d5212h1`). With pauses, it reuses one connection.
- Options: `--stacks`, `--sites`, `--trials`, `--machine` (a short label, never a hostname), `--network`, `--seed`, `--think-time`.

## Known issue: curl on Windows

The system curl on Windows uses Schannel, which checks certificate revocation and fails with our local CA ("revocation status unknown"). Revocation flags are not neutral: in one test on 2026-11-12, curl without `--ssl-no-revoke` sent a ClientHello with 13 extensions and curl with it sent 12, so the JA4 differed. The runner therefore adds no revocation flag. Trusting the CA in the Windows store does not help: on 2026-11-16 curl still failed with `CRYPT_E_NO_REVOCATION_CHECK`. The Windows curl baseline therefore needs the shared VM, which has a publicly trusted certificate. Its failed handshakes are logged as `tls_failure` records, but without a run id, because the request line never arrives.

So the runner leaves Schannel curl out of `--stacks all`, and runs it only when named with `--stacks curl`.

**`curl-norevoke` (Schannel only).** The agent's own curl on Windows skips the check too: in all 6 Bash-allowed headless runs (`b-claude-sh-*`, 2026-11-23) it ran `curl -sk`. Checked against `infra/server` the same day, with Git for Windows' curl 8.21.0 (Schannel):
- Plain curl (the failed handshakes, logged as `tls_failure`): JA4 `t13d2013h1_2b729b4bf6f3_e24568c0d440`.
- `-k`, `--ssl-no-revoke`, and `--ssl-no-revoke` with `CURL_CA_BUNDLE`: all `t13d2012h1_2b729b4bf6f3_36bf25f296df`, the agent's JA4.
- The only difference is extension 5 (`status_request`, OCSP stapling), which Schannel sends only when it checks revocation. Ciphers and signature algorithms are identical.

**Which curl runs.** On Windows, three curls can differ. A bare `curl` started from Python finds `System32\curl.exe` first (8.22.0 here), and a bare `bash` finds `System32\bash.exe` first, which is WSL: a Linux bash running Linux's curl (8.18.0, OpenSSL), which receives none of our environment variables. `PATH` names Git's bash and Git's `mingw64` curl (8.21.0, Schannel), the one the agent's Git Bash used. Before 2026-11-23 the runner reported the first curl and ran the script in WSL with the second. Now it starts the `bash` on `PATH`, passes the `curl` on `PATH` to `fetch_curl.sh` as `WH_CURL`, and records that binary's version. If that `bash` is WSL's (under `System32`) or a `WindowsApps` alias, the runner now refuses to run any curl stack and says to put Git's `usr\bin` before `System32` in `PATH`.

So `curl-norevoke` runs `fetch_curl.sh` with `--ssl-no-revoke`. Against our local CA it is the script counterpart of the agent's curl. It is not a plain curl script: on a site with a publicly trusted certificate, plain Schannel curl would add `status_request`. The runner runs it only where curl uses Schannel; elsewhere `--stacks all` skips it.

On Linux the script works: on 2026-11-16, `fetch_curl.sh` with curl 8.18.0 (OpenSSL 3.5) in WSL made all four requests (200 each) against a test HTTPS server using our local certificate, trusting the CA only through `CURL_CA_BUNDLE`. That check used a small stand-in server, not `infra/server`, so no TLS fingerprint was recorded; the first real Linux curl run will do that.

The infra test `test_curl_tls_request_when_available` fails on Windows for the same reason; it passes in CI on Linux.

## Tests

`harness/tests/test_run_baselines.py` covers the runner without network, Node or Go: run id allocation, manifest rows, the allowlist, command building, the CA environment and the trial plan.
