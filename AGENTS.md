# AGENTS.md

Context for coding agents (and humans) working in this repository. Read this fully before making changes.

## Project in one sentence

Tracking the person behind AI coding agents: recognizing which agent and model visits a site, and linking requests from different agents back to the same user across cooperating websites.

This is the offensive track of the Information Security course team project on advanced tracking (UM6P College of Computing). The final deliverables are an ACM AsiaCCS style paper and an end of semester presentation.

## The idea

Tool-using AI agents such as Claude Code and Codex fetch web pages from the user's own machine while doing tasks. We ask whether a network of cooperating websites (our "partner sites") can use those visits to recognize the person behind them and follow that person across every request their agents make. The target is the user, not the tool. One user may run several agents, and we want one person to stay one identity no matter which agent sends the request or which partner site receives it.

We study three questions in increasing difficulty:

1. Harness. Can a site tell which agent made the request (Claude Code, Codex, Cline, Aider, ...), and tell agent traffic apart from ordinary scripts that use the same HTTP library?
2. Model. Can a site tell which model drives the agent? We classify the model from text the agent itself writes on our page, and report a probability across providers rather than a single label.
3. User. Can a site link requests to the same human across different agents and different partner sites, and to that human's own browser visits?

Research question: given requests that a network of cooperating websites collects passively from tool-using agent sessions, can they identify the harness and the model behind each request, and link those requests to a single human across different agents and different sites?

## Scope

In scope: agents that execute locally and fetch pages from the user's machine (coding agents and CLI agents). Optionally local browser agents.

Out of scope: chat assistants such as claude.ai and chatgpt.com. Their URL fetches run on the provider's servers and carry nothing about the user (Borysenko 2026 observed server side fetches, with Claude's backend even using separate IPs for parallel requests).

Locality, first checked on 2026-11-18 on one Linux machine (`harness/hypotheses.md`, H1 step 2): Claude Code's WebFetch runs locally (it reached our local `.test` site; version 2.1.327 sends `Claude-User (claude-code/<version>; ...)`, not Borysenko's `axios/1.8.4`). Codex CLI's web tool, in its default sandbox, never reached the local site, consistent with fetching from OpenAI's servers; shell commands such as curl run locally for both agents. Still to confirm on the shared VM by checking whether the logged client IP matches the user's machine.

## Ethics and safety rules (hard rules)

- All tracking happens only on our own instrumented test sites. Never track, scrape or probe any third party site.
- No hidden text, no injected instructions, no prompt injection of any kind. Pages ask for input in plain visible text (for example "summarize this page in two sentences and submit it in this field").
- This visible request deliberately models what a malicious site could achieve with hidden prompt injection, in a safe and lawful way. Do not "improve" it into a hidden or coercive version.
- Participants are team members or volunteers who consent. They use fictitious personas and no real personal data.
- Never commit raw logs or IP addresses to this repo; it is public, so everything in it, including `runs/*.csv` and the docs, is world-readable. Raw data lives in the gitignored `data/` folder, which is a clone of the private data repo [`malekawlaqi/whose-human-runs`](https://github.com/malekawlaqi/whose-human-runs).

## Key findings from the literature

**Borysenko 2026, "Developer Experience with AI Coding Agents: HTTP Behavioral Signatures in Documentation Portals"** (arXiv:2604.02544)
Measured nine coding agents. Signatures (User-Agent, headers, pre-fetch behavior) were stable across trials. Most agents use generic HTTP runtimes: Claude Code (Node/axios), Cursor (Node/got), Cline and Junie (curl), Windsurf (Go/Colly), Antigravity (Go net/http). Only Aider and GitHub Copilot name themselves. 1 to 4 requests per prompt. Logged client IPs but never analyzed them. Did not include Codex CLI. The anonymised headers (no TLS, 3 trials) are published under Apache 2.0: https://github.com/oborys/AI-Agents-HTTP-level-behaviour

**Kang et al. 2026, "Whose Agent Are You? Multi-Layer Fingerprinting and Attribution of Autonomous Web Agents"** (arXiv:2606.20910)
Framework MARK: https://github.com/SPIN-UMass/AI-agent-fingerprint (we built our own logger in `infra/server/` while only the analysis scripts and a server binary were published; the repo now also has the server source and the raw request logs of 6 agents, humans and 3 crawlers, 30 trials each, with real IPs and no licence file). Go service on fingerproxy that logs raw TLS ClientHello (JA3, JA4), HTTP/2 Akamai fingerprint, headers and browser events to JSONL. Six web agents (not coding agents, which they explicitly exclude). Extra Trees classifier, 97% accuracy combined; no single layer suffices. Claude and Gemini near identical at TLS and HTTP. Combined features exceed 60% macro F1 after 3 requests; timing features are useless with few requests. Traditional crawlers (no JavaScript) had stable, distinct TLS fingerprints, which is what we expect coding agents to look like. Goal was content protection; they deliberately avoided logging participant IPs, so user linking is untouched. Their prompt told agents to use synthetic inputs, and they did not classify agent text.

**Lugoloobi et al. 2026, "Known By Their Actions: Fingerprinting LLM Browser Agents via UI Traces"** (arXiv:2605.14786)
Identifies which of 14 LLMs drives a browser agent from click, scroll, key and timing traces (up to 96% F1). Needs rich interaction traces, which coding agents do not produce, so this approach does not transfer to our setting. Fingerprints are site conditioned (poor transfer across sites). Retraining on delayed traces recovers accuracy, so simple timing defenses fail.

**Wang, Shafiq, Vekaria 2026, "FP-Agent: Fingerprinting AI Browsing Agents"** (arXiv:2605.01247)
Seven browsing agents vs humans. Local agents expose the host machine's attributes (screen resolution, cores); cloud agents expose a fixed remote environment. Agents produce mouse events only at click time and paste text rather than typing, so human behavioral biometrics (keystroke, mouse dynamics) do not apply to agents.

**Ukani et al. 2025, "Privacy Practices of Browser Agents"** (arXiv:2512.07725)
Several agents keep profile state across sessions and some leak personal details from earlier chats to websites. Did not study fingerprinting or behavioral linking of users.

**Pasquini et al. 2025, "LLMmap: Fingerprinting for Large Language Models"** (USENIX Security 2025)
Identifies the model from its text responses with high accuracy across 42 model versions. This is the method behind our model track, applied to the text agents post on our page.

**Zimmeck et al. 2017, "A Privacy Analysis of Cross-device Tracking"** (USENIX Security 2017)
Linked a user's devices with F1 0.91 from IP address and browsing history similarity. Baseline for user linking.

**Bird et al. 2020, "Replication: Why We Still Can't Browse in Peace"** (SOUPS 2020)
About 50% of users with 50+ distinct domains re-identifiable from browsing history, over 80% at 150+. Baseline for linking from what a user visits.

**Crichton, Cranor, Christin 2025, "Rethinking Fingerprinting"** (PoPETs 2025)
Behavioral fingerprinting over 150,000 users and two years: highly unique and stable; combining behavioral and browser fingerprints works best. Stronger recent baseline for user re-identification. To add to the proposal.

**Zhang et al. 2025, "Exposing LLM User Privacy via Traffic Fingerprint Analysis"** (arXiv:2510.07176)
Infers agent behaviors and some user attributes from encrypted network traffic. Works for an on-path network observer, not the visited website. Closest prior work at the user level; we position against it.

Why the obvious alternatives were dropped:
- WebGPU and GPU fingerprinting is crowded (several 2024 to 2026 papers, browser defenses already shipped).
- Canvas fingerprinting defenses were already attacked (WWW 2025).
- Cloud browser agents run on provider VMs, so hardware fingerprints say nothing about the user, and agent motor behavior belongs to the model, not the user.
- Model identification from timing barely works with the few requests coding agents send, hence text-based classification.

## Expected difficulty per question

- Harness: largely solvable. Open part is separating an agent from a plain script using the same library (Claude Code's axios vs any axios script). Expect some collisions, as Kang saw for Claude and Gemini.
- Model: hard from requests alone; feasible from the agent's posted text. Agents that never post are their own class, not a failure.
- User: feasible if fetches are local (IP, runtime and TLS environment, timing, requested URLs). Reviewers may call the IP signal obvious, so the interesting results are linking across agents, across sites, and to the user's own browsing, and whether linking survives an IP change.

## Repository layout

```
infra/          shared infrastructure; setup steps in infra/README.md
  server/       logging HTTPS server (TLS ClientHello, JA3/JA4, ordered headers, HTTP/2 fingerprint)
  sites/        partner site content (site1, site2)
  certs.py      local CA and certificates for site1.test / site2.test
  loader.py     reads server JSONL into one table and joins the run manifests
  schema.md     the log schema; changes only by pull request reviewed by the team
runs/           run manifests, one CSV per member (labels per run_id, no IPs)
Dockerfile, docker-compose.yml   the server, cert generation and checks run in Docker (see infra/README.md)
harness/        track 1: harness identification
model/          track 2: model identification from agent text
linking/        track 3: user linking across agents and sites
data/           gitignored; a clone of the private whose-human-runs repo (raw logs, corpora)
paper/          LaTeX for the final paper
```

Each track folder contains its own code, tests, and a `hypotheses.md`.

## Rules for coding agents in this repo

- Tracks 1 and 2 are owned per piece (see `TEAM.md`): only edit files belonging to the piece you were assigned, plus its tests, and do not touch other pieces' files without being asked. Track 3 (`linking/`) is joint work owned by all members.
- Never change `infra/` or the schema without being explicitly told to; schema changes go through a reviewed pull request.
- Never push to `main`. Work on the member's own branch and open a pull request; it merges only after CI passes and a teammate approves (see `CONTRIBUTING.md`). Run the CI checks locally before pushing.
- Never add hidden text, injected instructions or any probing of agents to test pages. See the ethics rules.
- Never write real personal data, credentials or real IP addresses into committed files.
- Every experiment run gets a `run_id`. Development traffic from your own fetches to our test servers must be tagged and kept out of experiment data.
- Prefer small, readable scripts over frameworks. Python for analysis (pandas, scikit-learn). Classifiers should output probabilities (`predict_proba`), not only labels.
- When an experiment finishes, record it in the track's `hypotheses.md` (template below) before starting the next one.

## Log schema

The log schema lives in `infra/schema.md` and is the single source of truth. Ground truth labels (`label_agent`, `label_model`, `label_user`) come from the run manifests in `runs/`, joined on `run_id` by `infra/loader.py`.

## Tracks and starting hypotheses

Track 1, harness identification. Run agents and plain library scripts against your own server.
- H1: agents sharing an HTTP library are indistinguishable from plain scripts using that library at the TLS layer alone.
- H2: header order, header set and request timing separate them anyway.

Track 2, model identification. Collect text agents post on the visible input page, or directly from APIs.
- H1: two short sentences suffice to identify the provider with useful accuracy.
- H2: the harness's system prompt shifts the text enough to hurt a classifier trained on raw API output.

Track 3, user linking. Run several agents from several machines against two or more partner sites.
- H1: requests from different agents on the same machine share the IP and an environment signature (runtime and TLS stack versions).
- H2: linking still works when the IP changes, using environment and timing alone.

## hypotheses.md template

```
## H<n>: <one sentence hypothesis>
Date:
Run ids:
Setup: <agents, models, machines, sites, number of runs>
Result: <numbers>
Conclusion: supported / rejected / inconclusive
Next: <what this changes, and for which track>
```
