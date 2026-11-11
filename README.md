# Whose Human Are You? Re-identifying Users Behind AI Coding Agents

Tool-using AI agents such as Claude Code and Codex fetch web pages from the user's own machine while they work. This project asks whether a network of cooperating websites can use those visits to recognize the **person** behind the agent, and follow that person across every agent they run and every site those agents visit.

Team project for the Information Security course (advanced tracking, offensive track), UM6P College of Computing. Deliverables: an ACM AsiaCCS style paper and an end of semester presentation.

## Research questions

Given requests that cooperating websites collect passively from agent sessions, can they:

1. **Harness**: identify which agent sent the request (Claude Code, Codex, Cline, Aider, ...), and tell it apart from a plain script using the same HTTP library?
2. **Model**: identify which model drives the agent, from text the agent writes on our page (probability across providers, not a single label)?
3. **User**: link requests to the same human across different agents, different partner sites, and the user's own browser visits, even when the IP changes?

## Scope

- **In scope**: agents that run locally and fetch pages from the user's machine (coding and CLI agents; optionally local browser agents).
- **Out of scope**: chat assistants (claude.ai, chatgpt.com) whose fetches run on provider servers.

## Ethics

- Tracking happens **only on our own instrumented test sites**. No third party sites are probed or scraped.
- **No hidden text or prompt injection.** Pages ask for input in plain visible text.
- Participants are consenting team members or volunteers using fictitious personas.
- Raw logs (which contain IP addresses) are **never committed**; they live in the gitignored `data/` folder or private storage.

## Repository layout

```
infra/      shared logging server and log loader (schema in infra/schema.md)
harness/    track 1: harness identification
model/      track 2: model identification from agent text
linking/    track 3: user linking across agents and sites
data/       gitignored; raw logs and datasets
paper/      LaTeX for the final paper
```

Each track folder has its own code, tests, and a `hypotheses.md` where every finished experiment is recorded.

## Getting started

1. Read [`AGENTS.md`](AGENTS.md) in full. It holds the project context, literature summary, ethics rules, log schema, and working rules for both humans and coding agents.
2. Work only inside your assigned track folder. Changes to `infra/` or the schema go through a reviewed pull request.
3. Tag every experiment with a `run_id`, and keep your own development traffic out of experiment data.
