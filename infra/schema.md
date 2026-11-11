# Log schema (proposed)

Status: proposed, to confirm when infra is set up. Changes only by pull request reviewed by the team.

One record per HTTP request, after loading:

| field | meaning |
|---|---|
| `ts` | server timestamp (UTC, float seconds) |
| `run_id` | experiment run identifier |
| `site` | which partner site received the request |
| `session_id` | session id embedded in the served page, when available |
| `ip` | client IP (never committed) |
| `method`, `path` | request line |
| `http_version` | HTTP/1.1 or HTTP/2 |
| `headers` | full header dict, original order preserved |
| `ja3`, `ja4` | TLS fingerprints (from MARK) |
| `h2_fp` | Akamai HTTP/2 fingerprint, if HTTP/2 |
| `body` | request body (posted text), truncated |
| `label_agent` | ground truth: claude_code, codex, cline, aider, script_axios, browser, ... |
| `label_model` | ground truth model, if known |
| `label_user` | ground truth persona or volunteer id |
