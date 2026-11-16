# Track 1: Harness identification

Owner of 1c (features and classifier): C. Baselines (1b): B. Agent runs (1a): A. See `TEAM.md`.

## Files

| File | What it does |
|---|---|
| `agent_runs.py` | Prepares Member A's combined 1a/2a runs, prints the fixed visible task, and audits local-versus-provider origin without printing IPs |
| `member_a_1a_2a_protocol.md` | Exact combined collection matrix, privacy rules, locality and submission interpretation, and completion criteria |
| `features.py` | Turns loaded server logs (`infra.loader.load_logs`) into one row of features per request |
| `classify.py` | Extra Trees classifier with grouped cross-validation (a `run_id` is never split across train and test) and `predict_proba` output |

## 1a: Member A agent runs

Prepare one labelled combined 1a/2a run and print the task to paste into the agent:

```sh
docker compose run --rm --entrypoint python checks -m harness.agent_runs prepare \
  --run-id a-codex-001 --agent codex-cli --model model-alias \
  --persona persona-a1 --machine machine-a1 --network home \
  --base-url https://site1.example.test
```

After running agents against the shared VM, privately compare the logged peers with the participant network's
expected egress address. The report prints only `local`, `remote`, `mixed`, or `inconclusive` and aggregate counts:

```sh
docker compose run --rm --entrypoint python checks -m harness.agent_runs audit data/logs \
  --expected-ip-file data/member-a-egress-ips.txt
```

The task visits the visible input page and requests a two-sentence submission for Track 2a. See
[`member_a_1a_2a_protocol.md`](member_a_1a_2a_protocol.md) before collecting experimental traffic. Do not replace a
failed built-in fetch with curl, a browser, or another tool, because that would measure a different client.

## Feature contract (used by Track 3b)

`extract_features(logs)` returns the `ID_COLUMNS` followed by these feature groups (`FEATURE_GROUPS`):

| Group | Examples | Source |
|---|---|---|
| `tls` | `tls_ja4` and its three parts, `tls_ja3_md5`, ALPN, groups (incl. post-quantum `tls_has_pq`), signature algorithms, extension order, GREASE | Re-parsed from the raw ClientHello, so it can be extended later without re-collecting data |
| `http` | version, method, header order and set hashes, header case (HTTP/1.1), User-Agent family and version, Accept, Accept-Encoding, Sec-Fetch, Connection | Ordered request headers |
| `h2` | Akamai fingerprint, SETTINGS, WINDOW_UPDATE, pseudo-header order | HTTP/2 frames before the first request |
| `timing` | requests per connection and per run, connections per run, gap to the previous request of the run, connection setup time | Timestamps and ids |
| `body` | body length, whether text was submitted | Request body |

`CATEGORICAL_COLUMNS` lists the string features; all others (`NUMERIC_COLUMNS`) are floats, with booleans as 0/1 and NaN when missing. Changing a column name or meaning is a contract change, so tell A (3b) and C (3c) in the PR.

## Hypotheses → feature sets

`evaluate()` compares these feature sets by macro F1 under grouped cross-validation:

| Set | Groups |
|---|---|
| `tls_only` | `tls` |
| `http_only` | `http`, `h2` |
| `tls+http` | `tls`, `http`, `h2` |
| `all` | every group |

- **H1** (agents sharing an HTTP library are indistinguishable from plain scripts using that library, at the TLS layer alone): label agent runs and the matching 1b script runs (for example `claude_code` vs `script_axios`) and check that `tls_only` cannot separate them.
- **H2** (header order, header set and timing separate them anyway): on the same data, `tls+http` and `all` should clearly beat `tls_only`.

## Running

Labels come from `runs/*.csv`, joined on `run_id`. With labelled runs in `data/logs`:

```sh
docker compose run --rm --entrypoint python checks -m harness.classify
```

Add `--include-dev` to include `dev-` runs, and `--label label_model` or `--label label_user` to predict something else. Each class needs at least two runs, because whole runs are held out.
