# Local research server

Everyone runs the same server on their own laptop for Tracks 1 and 2, so logs from all three of us can be pooled. Later, the same code runs on a shared VM for Track 3.

The server records peer IP addresses and raw TLS ClientHellos. Point it only at our own pages, use fictitious personas, and keep `data/` private (it is gitignored; never commit logs).

## One-time setup

Run everything from the repository root.

1. **Python environment** (3.12 or newer):

   ```sh
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```

2. **Certificates.** Create a local CA and a certificate for `site1.test`, `site2.test`, `localhost` and `127.0.0.1`:

   ```sh
   python -m infra.certs              # writes data/certs/ca.pem, server.pem, server-key.pem
   ```

3. **Trust the CA** on your own machine, so agents accept the certificate:

   | OS | Command |
   |---|---|
   | Arch Linux | `sudo trust anchor --store data/certs/ca.pem` |
   | Debian/Ubuntu | `sudo cp data/certs/ca.pem /usr/local/share/ca-certificates/whose-human-local.crt && sudo update-ca-certificates` |
   | macOS | `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain data/certs/ca.pem` |
   | Windows (admin) | `certutil -addstore Root data\certs\ca.pem` |

   Some runtimes ignore the system store. Point them at the CA explicitly:
   - Node-based agents (Claude Code, Cline, ...): `export NODE_EXTRA_CA_CERTS=$PWD/data/certs/ca.pem`
   - Python `requests`: `REQUESTS_CA_BUNDLE`; other OpenSSL clients: `SSL_CERT_FILE`
   - curl: `--cacert data/certs/ca.pem`

   These settings only tell a client which certificates to trust; they don't change the TLS fingerprint it sends. Remove the CA when the project is over.

4. **Hosts file.** Add this line to `/etc/hosts` (Linux/macOS) or `C:\Windows\System32\drivers\etc\hosts` (Windows, as admin):

   ```
   127.0.0.1 site1.test site2.test
   ```

## Running

```sh
python -m infra.server --source local-c     # use your own letter: local-a, local-b, local-c
```

The server listens on `https://site1.test:8443/` and `https://site2.test:8443/`. Check that it works:

```sh
curl https://site1.test:8443/r/dev-check/          # add --cacert data/certs/ca.pem if the CA isn't trusted
tail -n 1 data/logs/local-c-*.jsonl                # one JSON record with ja4, header_order, ...
```

## Run ids

Put the run id in the URL you give the agent: `https://site1.test:8443/r/<run_id>/input.html`. The server strips the `/r/<run_id>/` prefix to find the page and records the id. `?run=<id>` also works.

- Start ids with your member letter (`a-`, `b-`, `c-`), for example `c-012`.
- Use `dev-` for your own testing. The loader drops `dev-` rows by default.
- Add one row per run to your file in `runs/` (`runs/c.csv`): agent, model, persona, machine, network. No IP addresses.

## Logs

Records append to `data/logs/<source>-<YYYYMMDD>.jsonl`; `infra/schema.md` describes every field. An agent that rejects our certificate still leaves a `no_request` or `tls_failure` record with its TLS fingerprint, which is useful for the 1a local-or-server check.

Share logs only through the team's private Drive/OneDrive folder. Load them in analysis code with:

```python
from infra.loader import load_logs

df = load_logs("data/logs", runs_dir="runs")
requests = df[df["kind"] == "request"]
```

## Options

| Flag | Default | Use |
|---|---|---|
| `--source` | `local-x` | Label in every record and in the log file name |
| `--host`, `--port` | `127.0.0.1`, `8443` | Listen address |
| `--cert`, `--key` | `data/certs/server.pem`, `data/certs/server-key.pem` | Certificate and key |
| `--log-dir` | `data/logs` | Where JSONL files go |
| `--sites-dir` | `infra/sites` | Site content (`site1/`, `site2/`) |
| `--alpn` | `h2,http/1.1` | Protocols offered, in preference order |
| `--plain-port` | off | Extra unencrypted port for debugging (no TLS fields) |

On the shared VM: `--host 0.0.0.0 --port 443 --source vm` with publicly trusted certificates for the real domains (for example from Let's Encrypt), and no CDN or proxy in front, since TLS has to end at this server.
