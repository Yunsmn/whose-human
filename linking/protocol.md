# Track 3 session protocol

Status: draft, to agree on together before the campaign.

Member A's local-model same-PC sub-study has a concrete, privacy-minimised procedure in
[`machine_linking_protocol.md`](machine_linking_protocol.md). It tracks a machine-level experimental label, not a
human identity, and uses a whole-machine train/test split.

## Personas

Fictitious only. One or more per member, recorded as `label_user`.

## Sites

Which partner sites the sessions visit (at least two).

## Session plan

| Setting | What changes | Runs per persona |
|---|---|---|
| Same machine, different agents | agent | |
| Same agent, different sites | site | |
| Agent and own browser | agent vs browser | |
| IP change | network (VPN, hotspot) | |
| Shared IP, different users | user, same campus network | |

## Task prompts

The fixed prompts given to agents (same visible-text rules as the rest of the project).

## Checklist per run

- [ ] `run_id` assigned and noted
- [ ] persona (`label_user`), agent (`label_agent`) and model (`label_model`) noted
- [ ] network type noted (no real IPs in committed files)
- [ ] own development traffic tagged and kept out
- [ ] machine-level study uses a pseudonymous `machine` label and never a hostname or serial number
