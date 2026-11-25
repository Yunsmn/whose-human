# Track 3 session protocol

Status: draft for the team to agree on in the pull request that adds it. Personas, agents and machines go in comments there and then in `machines.md`.

## Where the sessions run

All Track 3 sessions go to **the shared VM**, never to our local Docker servers. Locally, Docker's port forwarding replaces every client address with its gateway (`172.18.0.1` in all our local logs), so the IP, the main linking signal, is lost there. The VM runs `infra/server` with host networking (see "Shared VM" in `infra/README.md`):

- A free VM (Azure for Students) run by A, with a public IPv4 and IPv6 address.
- Two free DuckDNS subdomains, one per partner site (each is its own site: `duckdns.org` is on the public suffix list), with A and AAAA records and publicly trusted certificates from Let's Encrypt (the DNS-01 challenge through DuckDNS's TXT API, e.g. acme.sh's `dns_duckdns`, needs no port 80). Agents then need no `NODE_EXTRA_CA_CERTS`, no `--cacert` and no CA in the trust store.
- Port 443, no CDN or proxy in front: TLS has to end at our server.
- Its logs hold real IP addresses. They go to the private data repo (`logs/vm-YYYYMMDD.jsonl`), never to this repo.

### Extra signals the VM should capture

Track 3 links a person through signals that come from their machine and network, not from the agent's HTTP client. Browser, curl and WebFetch share those, while their TLS fingerprints differ. One is worth building into the VM from the start:

- **IPv6 (dual stack).** Give both hostnames an AAAA record and let the server listen on IPv6 too (needs a small `infra/server` change: today it listens on IPv4 only). The /64 prefix is **network evidence, not a machine identifier**: a home network keeps one /64 for all its devices while each device rotates its address, so on a home network it can link a person's agents and browser when the full address differs; on campus Wi-Fi one /64 can hold many people. Report it like the IP: how often it links the same person, and how often it collides between different people (setting 5). It also shows whether each client prefers IPv6 (Happy Eyeballs), which differs between runtimes.
- **Dropped: our own DNS zone.** The sites use free DuckDNS subdomains, so we don't control a zone. It would also only have shown the visitor's recursive resolver, not the machine (resolver evidence, shared by everyone on the same resolver).

Tested on C's machine and dropped, so the VM doesn't need them:
- **TCP timestamps** (Kohno et al. 2005, clock skew). On Linux 7.2 each connection gets its own random timestamp offset: six connections from curl, Python, Node and a second port gave six unrelated values. Clock skew needs long connections, and agent connections last well under a second. Windows sends no timestamps by default.
- **TLS session tickets** (Sy et al. 2018). No agent connection in our logs resumed a session: WebFetch opens one fresh connection per run, and every curl call is a new process. Only some Node scripts resumed, on their own second connection.

## Personas

Fictitious only, one per member unless a member adds a second: `persona-a1`, `persona-b1`, `persona-c1` (the ones Tracks 1 and 2 already use). The persona is the ground truth `label_user`: everything a member does on their own machines and browser is the same user.

## Sites

The two partner sites on the VM, with the same pages as `infra/sites/`. Every visit goes to `https://<site>/r/<run_id>/`, agents and browser alike.

### Site changes on the VM (team decisions, 2026-11-24)

Both apply **only on the VM**; the local servers keep serving `infra/sites/` unchanged, so Track 1 and 2 data stay comparable.

- **A. One per-visit sentence (decided: yes, VM only).** Each page view gets one ordinary visible sentence on the page's topic, drawn at random from a fixed pool, as a normal paragraph in the text. No hidden text, no instruction: it reads like any other sentence of the page. The server logs which sentence it served (`visit_variant`, a new schema field). If a submitted summary reflects that visit's sentence, an LLM read that exact visit, even when its curl is byte for byte a script's and it pauses like an agent, the case timing can't catch. A random code would rarely make it into a two-sentence summary, which is why it is a sentence on the topic.
  - Pool: about 20 short, neutral, clearly different sentences per site, each with one distinctive keyword, so a summary can be matched to its variant by keyword. A (site content) writes them.
  - Serving: the server inserts the drawn sentence into HTML pages only when started with a flag (e.g. `--visit-variants <pool file>`), and logs `visit_variant`; without the flag pages are unchanged. B (`infra/server`, schema) adds it.
  - 2c: summaries from the VM may mention the variant sentence; drop or mask it before using them as model-classifier text.
- **B. `llms.txt` and Markdown versions (decided: yes).** Each site gets `/llms.txt` and a `.md` copy of each page, linked from the HTML with `<link rel="alternate" type="text/markdown">`. Requests for them are logged like any other, so we see which clients look for them. A writes the files; B makes the server send `.md` as `text/markdown` and `.txt` as `text/plain` (today every non-HTML file goes out as `application/octet-stream`).

## Session plan

The basic unit is one run: one agent, one site, one fresh session, the fixed task. "Agents" means every agent the member listed in the PR comments. Not everyone has the same agents: Claude Code runs on B's Windows machine and C's Linux machine, in both tool settings (WebFetch only; WebFetch and Bash), and A runs Codex. Agents shared by two members are what make the "different users, same agent" comparison possible.

| Setting | What changes | Runs per member |
|---|---|---|
| 1. Same machine, different agents | the agent | each agent × 2 sites × 3 runs, home network |
| 2. Same agent, different sites | the site | covered by 1 (both sites) |
| 3. Agent and own browser | agent vs browser | in the same sitting as 1: open both sites in your normal browser, 3 visits per site, and click the submit form once per site |
| 4. IP change | the network | repeat 1 and 3 with 2 runs per agent and site, on a second network (mobile hotspot, or a VPN); note which |
| 5. Shared IP, different users | the user, same network | one sitting with all three of us on campus Wi-Fi at the same time: your main agent × 2 sites × 2 runs, plus 2 browser visits per site |

Settings 1, 3 and 4 can be done alone, at any time once the VM is up. Setting 5 needs one meeting.

The cookie: the server sets `wh_session` on every response. Browsers send it back; WebFetch and curl don't, because each fetch or curl call starts with an empty cookie jar (0 of 56 Claude Code requests on Linux and Windows returned it; Codex's curl did once, inside one run, because its command used a cookie jar). So the cookie only links a person's browser visits to the same site (our two sites are different hostnames, so it doesn't link across them), and it never links the browser to an agent. That is what Track 3 has to do with IP, environment and timing instead, and setting 3 measures it.

## Task prompt

Agents: the fixed task from `python -m harness.agent_runs prepare ... --base-url https://<site>` (it prints the task and records the manifest row). Paste it unchanged, from an empty folder outside the repo, in a fresh session, with no extra instructions. The same visible-text rules as the rest of the project apply.

Browser: open the page, read it, write two sentences in the form yourself, submit.

## Run ids and labels

- Run ids: `<letter>-t3-<agent>-<site>-<setting>-<nnn>`, for example `c-t3-claude-sh-site1-s1-001`, `c-t3-browser-site2-s4-002`.
- One row per run in `runs/<letter>.csv`, with `label_agent` (`browser` for browser visits), `label_model`, `label_user` (your persona), `machine`, `network` (`home`, `campus`, `mobile`, `vpn`) and notes.
- The browser visits use the same `/r/<run_id>/` path, so they get a manifest row too. Prepare them with `--agent browser --model none`.

## Checklist per run

- [ ] `run_id` assigned and noted, through `harness.agent_runs prepare`
- [ ] persona (`label_user`), agent (`label_agent`) and model (`label_model`) noted
- [ ] network type noted (no real IPs in committed files)
- [ ] own development traffic tagged and kept out (`dev-` ids)
