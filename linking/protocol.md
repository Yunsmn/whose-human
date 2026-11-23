# Track 3 session protocol

Status: draft for the team to agree on in the pull request that adds it. Personas, agents and machines go in comments there and then in `machines.md`.

## Where the sessions run

All Track 3 sessions go to **the shared VM**, never to our local Docker servers. Locally, Docker's port forwarding replaces every client address with its gateway (`172.18.0.1` in all our local logs), so the IP, the main linking signal, is lost there. The VM runs `infra/server` with host networking (see "Shared VM" in `infra/README.md`):

- Two hostnames, one per partner site, with publicly trusted certificates (Let's Encrypt). Agents then need no `NODE_EXTRA_CA_CERTS`, no `--cacert` and no CA in the trust store.
- Port 443, no CDN or proxy in front: TLS has to end at our server.
- Its logs hold real IP addresses. They go to the private data repo (`logs/vm-YYYYMMDD.jsonl`), never to this repo.

## Personas

Fictitious only, one per member unless a member adds a second: `persona-a1`, `persona-b1`, `persona-c1` (the ones Tracks 1 and 2 already use). The persona is the ground truth `label_user`: everything a member does on their own machines and browser is the same user.

## Sites

The two partner sites on the VM, with the same pages as `infra/sites/`. Every visit goes to `https://<site>/r/<run_id>/`, agents and browser alike.

## Session plan

The basic unit is one run: one agent, one site, one fresh session, the fixed task. "Agents" means every agent the member listed in the PR comments, plus Claude Code in both tool settings (WebFetch only; WebFetch and Bash).

| Setting | What changes | Runs per member |
|---|---|---|
| 1. Same machine, different agents | the agent | each agent × 2 sites × 3 runs, home network |
| 2. Same agent, different sites | the site | covered by 1 (both sites) |
| 3. Agent and own browser | agent vs browser | in the same sitting as 1: open both sites in your normal browser, 3 visits per site, and click the submit form once per site |
| 4. IP change | the network | repeat 1 and 3 with 2 runs per agent and site, on a second network (mobile hotspot, or a VPN); note which |
| 5. Shared IP, different users | the user, same network | one sitting with all three of us on campus Wi-Fi at the same time: Claude Code (WebFetch and Bash) × 2 sites × 2 runs, plus 2 browser visits per site |

Settings 1, 3 and 4 can be done alone, at any time once the VM is up. Setting 5 needs one meeting.

The cookie: the server sets `wh_session` on every response. Browsers send it back; WebFetch and curl don't, because each fetch or curl call starts with an empty cookie jar (0 of 56 Claude Code requests on Linux and Windows returned it; Codex's curl did once, inside one run, because its command used a cookie jar). So the cookie only links a person's browser visits to the same site (our two sites are different hostnames, so it doesn't link across them), and it never links the browser to an agent. That is what Track 3 has to do with IP, environment and timing instead, and setting 3 measures it.

## Task prompt

Agents: the fixed task from `python -m harness.agent_runs prepare ... --base-url https://<site>` (it prints the task and records the manifest row). Paste it unchanged, from an empty folder outside the repo, in a fresh session, with no extra instructions. The same visible-text rules as the rest of the project apply.

Browser: open the page, read it, write two sentences in the form yourself, submit.

## Run ids and labels

- Run ids: `<letter>-t3-<agent>-<site>-<setting>-<nnn>`, for example `c-t3-claude-sh-site1-s1-001`, `c-t3-browser-site2-s4-002`.
- One row per run in `runs/<letter>.csv`, with `label_agent` (`browser` for browser visits), `label_model`, `label_user` (your persona), `machine`, `network` (`home`, `campus`, `mobile`, `vpn`) and notes.
- The browser visits use the same `/r/<run_id>/` path, so they get a manifest row too.

## Checklist per run

- [ ] `run_id` assigned and noted, through `harness.agent_runs prepare`
- [ ] persona (`label_user`), agent (`label_agent`) and model (`label_model`) noted
- [ ] network type noted (no real IPs in committed files)
- [ ] own development traffic tagged and kept out (`dev-` ids)
