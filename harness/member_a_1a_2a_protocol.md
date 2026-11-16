# Member A Track 1a and 2a protocol

Member A collects harness traffic (1a) and agent-written text (2a) in the same controlled sessions. Each agent
visits one visible input page, summarizes its two visible paragraphs in exactly two sentences, and submits the
summary using either the form POST or the page's visible GET fallback. Nothing is hidden or injected.

## Preconditions

1. Use only the team's instrumented sites. Complete `infra/README.md` first.
2. Use a fictitious persona, machine alias, and network-category label. Never commit an address, hostname,
   personal identity, API key, raw log, or submitted corpus.
3. Record the exact agent and model version in `notes` when known. Start a fresh agent session for every run and
   keep default settings.
4. Use a shared VM with real TLS certificates for the locality decision. Local Docker replaces the peer address
   with its bridge/gateway address, so local results are marked `inconclusive`.

## Prepare and execute one combined run

Create the manifest row and print the fixed visible task:

```powershell
python -m harness.agent_runs prepare `
  --run-id a-codex-001 --agent codex-cli --model model-alias `
  --persona persona-a1 --machine machine-a1 --network home `
  --base-url https://site1.example.test `
  --notes "agent version; model version; clean session"
```

Paste the printed task into the named agent exactly as shown. The agent must use its built-in web/URL-fetch
capability. It should submit with POST when supported; otherwise it may use the visible
`submit?text=YOUR_SUMMARY` GET fallback on the page. Do not replace a failed built-in fetch or submission with
curl, wget, PowerShell, a browser, or a custom script: that would measure a different client.

Run at least three independent sessions per available harness. Cover Claude Code, Codex CLI, Cline, Aider, and
other locally available agents, distribute runs across both partner sites, and use a new `a-...` run ID each time.

## Audit Track 1a locality

Independently determine the participant network's public egress address. Store it only in a private, gitignored
file; one IPv4 or IPv6 address per line is accepted. Then run:

```powershell
python -m harness.agent_runs audit data/logs `
  --expected-ip-file data/member-a-egress-ips.txt
```

The command never prints addresses. It reports `local`, `remote`, `mixed`, or `inconclusive`, plus run counts per
harness. Require at least three independent runs before assigning a harness-level conclusion. Do not infer
locality from User-Agent or TLS alone.

## Audit Track 2a submissions

Classify every planned run and optionally write the private text corpus:

```powershell
python -m model.agent_text data/logs `
  --manifest runs/a.csv `
  --output data/corpus/agent/member-a-agent-text.csv
```

The terminal output contains only aggregate outcome counts. The private CSV contains submitted text and labels
for Track 2c, so it must remain in `data/` or approved private storage. Outcomes distinguish POST submission, GET
fallback submission, fetched-but-not-submitted, other observed traffic, and no observed request.

## Completion criteria

- Every experimental session has one unique `a-...` run ID and one row in `runs/a.csv`.
- Every agent receives the same visible task and uses only its built-in fetch capability.
- Raw JSONL, expected addresses, and submitted text remain private.
- 1a reports locality counts per harness; 2a reports submission outcomes and exports labelled text privately.
- Only completed experimental results are added to the relevant `hypotheses.md` file.
