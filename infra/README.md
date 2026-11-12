# Local research server

The logging server runs in Docker, identically for all three of us: same Python, same OpenSSL, same code. Logs can be pooled without "it worked differently on my machine" problems. Later, the same image runs on a shared VM for Track 3.

**Only the server runs in Docker. The agents and scripts we study always run natively on your own machine**, exactly as a real user would run them: their OS, runtime and TLS stack are the signal we measure.

The server records peer IP addresses and raw TLS ClientHellos. Point it only at our own pages, use fictitious personas, and keep `data/` private. It is gitignored apart from an empty `.gitkeep`; never commit logs.

## One-time setup

You need Docker (Docker Desktop on Windows/macOS; `docker` + `docker-compose` on Linux). Run everything from the repository root.

1. **Your source label.** Copy `.env.example` to `.env` and set your letter:

   ```
   WH_SOURCE=local-c          # local-a, local-b or local-c
   ```

2. **Build the image and create the certificates** for `site1.test`, `site2.test`, `localhost` and `127.0.0.1`:

   ```sh
   docker compose build
   docker compose run --rm certs      # writes data/certs/ca.pem, server.pem, server-key.pem
   ```

3. **Trust the CA on your own machine**, so agents accept the certificate:

   | OS | Command |
   |---|---|
   | Windows (PowerShell as admin) | `certutil -addstore Root data\certs\ca.pem` |
   | macOS | `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain data/certs/ca.pem` |
   | Arch Linux | `sudo trust anchor --store data/certs/ca.pem` |
   | Debian/Ubuntu | `sudo cp data/certs/ca.pem /usr/local/share/ca-certificates/whose-human-local.crt && sudo update-ca-certificates` |

   Node-based agents (Claude Code, Cline, ...) ignore the system store, so also point Node at the CA:

   | Shell | Command |
   |---|---|
   | Windows, permanent | `setx NODE_EXTRA_CA_CERTS "%CD%\data\certs\ca.pem"` (then open a new terminal) |
   | Linux/macOS | add `export NODE_EXTRA_CA_CERTS=/path/to/repo/data/certs/ca.pem` to your shell profile |

   For Python `requests` use `REQUESTS_CA_BUNDLE`; for curl, `--cacert data/certs/ca.pem` (or rely on the system store). These settings only tell a client which certificates to trust; they don't change the TLS fingerprint it sends. Remove the CA when the project is over.

4. **Hosts file.** Add this line to `C:\Windows\System32\drivers\etc\hosts` (Windows, editor run as admin) or `/etc/hosts` (Linux/macOS):

   ```
   127.0.0.1 site1.test site2.test
   ```

## Daily use

```sh
docker compose up -d        # start (it also restarts automatically with Docker)
docker compose logs -f      # server output
docker compose down         # stop
```

The sites are at `https://site1.test:8443/` and `https://site2.test:8443/`. Check that everything works:

```sh
curl https://site1.test:8443/r/dev-check/
```

A new line should appear in `data/logs/local-c-<date>.jsonl`, with `ja4`, `header_order` and so on.

After pulling changes to the server code, rebuild with `docker compose up -d --build`. Changes to the site content (`infra/sites/`) apply immediately, without a rebuild.

## Run ids

Put the run id in the URL you give the agent: `https://site1.test:8443/r/<run_id>/input.html`. The server strips the `/r/<run_id>/` prefix to find the page and records the id. `?run=<id>` also works.

- Start ids with your member letter (`a-`, `b-`, `c-`), for example `c-012`.
- Use `dev-` for your own testing. The loader drops `dev-` rows by default.
- Add one row per run to your file in `runs/` (`runs/c.csv`): agent, model, persona, machine, network. No IP addresses.

## Logs

Records append to `data/logs/<source>-<YYYYMMDD>.jsonl`; `infra/schema.md` describes every field.

- **A certificate rejection still leaves a record.** An agent that rejects our certificate leaves a `no_request` or `tls_failure` record with its TLS fingerprint, which is useful for the 1a local-or-server check.
- **The client IP is Docker's gateway locally.** It shows up as an address like `172.18.0.1` rather than `127.0.0.1`, because of Docker's port forwarding. Local IPs carry no signal anyway; TLS and HTTP fingerprints are unaffected, which was checked against a run without Docker.

Share logs only through the team's private Drive/OneDrive folder. Load them in analysis code with:

```python
from infra.loader import load_logs

df = load_logs("data/logs", runs_dir="runs")
requests = df[df["kind"] == "request"]
```

## Checks

Lint, formatting and tests against your working copy, the same as CI:

```sh
docker compose run --rm checks
```

## Shared VM (Track 3)

Use the same image, but run it with host networking. Docker's port forwarding replaces the client's real IP, which Track 3 needs. Give it publicly trusted certificates for the real domains (for example from Let's Encrypt), and put no CDN or proxy in front, since TLS has to end at this server:

```sh
docker run -d --name whose-human --network host --restart unless-stopped \
  -v "$PWD/data:/app/data" -v "$PWD/infra/sites:/app/infra/sites:ro" \
  whose-human-server --host 0.0.0.0 --port 443 --source vm \
  --cert data/certs/fullchain.pem --key data/certs/privkey.pem
```

This VM setup is a sketch and hasn't been tested yet. The container runs as a non-root user, so binding port 443 still needs solving (for example by lowering `net.ipv4.ip_unprivileged_port_start` on the VM). We'll finalise it once the VM exists.
