# Log schema

Status: **v1**. Changes only by a pull request the whole team reviews.

The server (`infra/server`) appends one JSON object per line to `data/logs/<source>-<YYYYMMDD>.jsonl`. Raw logs contain participant IP addresses: they stay in the gitignored `data/` folder (a clone of the private `whose-human-runs` repo) and are never committed here.

## Record kinds

| `kind` | Written when | Fields present |
|---|---|---|
| `request` | Every HTTP request (HTTP/1.1 or HTTP/2) | Connection, TLS, HTTP and body fields below |
| `tls_failure` | The server-side TLS handshake failed after a ClientHello arrived | Connection and TLS fields, `tls_error` |
| `no_request` | TLS completed but the client sent no request, typically because the client rejected our certificate | Connection and TLS fields, `tls_error` |

`tls_failure` and `no_request` records keep the client's TLS fingerprint even when an agent refuses our local CA.

## Fields

**Connection**

| Field | Meaning |
|---|---|
| `ts` | UTC Unix time the record was written (float seconds) |
| `source` | Server label passed with `--source`, e.g. `local-c` or `vm` |
| `conn_id` | Random id of the TCP connection; shared by all requests on it |
| `conn_ts` | TCP accept time (float seconds) |
| `client_ip`, `client_port` | Peer address (private data). `ip` is an alias of `client_ip`. IPv4 or IPv6; an IPv4 client on a dual-stack socket is logged as plain IPv4, never as `::ffff:a.b.c.d` |

**TLS** (absent on the plain-HTTP debug port)

| Field | Meaning |
|---|---|
| `sni` | Server name from the ClientHello, or null |
| `alpn_offered` | ALPN list in the client's order |
| `alpn_negotiated` | Selected protocol (`h2`, `http/1.1`) |
| `tls_version`, `tls_cipher` | Negotiated version and cipher (null on `tls_failure`) |
| `client_hello_hex` | Raw TLS record bytes holding the ClientHello, so fingerprints can be recomputed |
| `ja3`, `ja3_md5` | JA3 string and MD5 (Salesforce spec, GREASE removed) |
| `ja4`, `ja4_r` | JA4 and its raw form (FoxIO spec) |
| `tls_error` | Error text for `tls_failure` and `no_request` records |

**HTTP** (`request` records only)

| Field | Meaning |
|---|---|
| `req_index_on_conn` | 1-based index of the request on its connection |
| `http_version` | `HTTP/1.1` or `HTTP/2` |
| `method`, `path` | Method and request target exactly as sent, including the `/r/<run_id>/` prefix and query |
| `query` | Raw query string |
| `site` | `site1` or `site2`, from Host / `:authority` (`localhost` and `127.0.0.1` map to `site1`) |
| `run_id` | From the `/r/<run_id>/` path prefix, else the `?run=` query parameter |
| `session_id` | `wh_session` cookie value, existing or newly set on HTML responses |
| `headers` | Ordered `[name, value]` pairs as received (original case for HTTP/1.1; HTTP/2 names are lowercase and pseudo-headers are excluded) |
| `header_order` | Header names from `headers`, in order |
| `body` | Raw request body, UTF-8 decoded with replacement, capped at 64 KiB |
| `body_len`, `body_truncated` | Full body length in bytes; whether `body` was cut |
| `submitted_text` | For `/submit` only: the text field from a form POST, the raw POST body otherwise, or `?text=` on GET |
| `status` | Response status code |

**HTTP/2** (`request` records with `http_version` `HTTP/2`)

All values come from the client's frames sent before its first HEADERS frame, so they are identical for every request on a connection.

| Field | Meaning |
|---|---|
| `h2_settings` | First SETTINGS frame as `id:value` strings, in order |
| `h2_window_update` | First connection-level WINDOW_UPDATE increment, or null |
| `h2_priority` | PRIORITY frames as `stream:exclusive:parent:weight` |
| `h2_pseudo_order` | Pseudo-header order of this request, e.g. `[":method", ":authority", ":scheme", ":path"]` |
| `h2_fp` | Akamai fingerprint `SETTINGS|WINDOW_UPDATE|PRIORITY|PSEUDO`, e.g. `2:0;4:262144|458753|0|a,m,p,s` (`00` if no WINDOW_UPDATE, `0` if no PRIORITY) |

## Loaded table

`infra.loader.load_logs(paths_or_dir, runs_dir="runs", include_dev=False)` returns a pandas DataFrame:

- one row per JSONL record, with every field above as a column (missing ones are null);
- `label_agent`, `label_model`, `label_user`, `machine`, `network`, `notes` joined from `runs/*.csv` on `run_id`;
- rows whose `run_id` starts with `dev-` dropped unless `include_dev=True`;
- malformed lines skipped with a warning naming each line, plus a total count; a `run_id` listed twice in `runs/` triggers a warning and the last entry wins.

Filter on `kind == "request"` for per-request analysis.
