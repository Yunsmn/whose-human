# Division of work

- **Tracks 1 and 2** are split into six pieces. Each member owns one Track 1 piece and one Track 2 piece. Each member's pair is a heavy piece plus a light one, or two medium ones, so the load is roughly even.
- **Track 3** is the joint final task. It needs everyone's machines, operating systems and agents, plus the feature code from Track 1 and, optionally, the classifier from Track 2. All three members collect the data together; each member leads one part of the analysis.

| Member | Track 1: Harness | Track 2: Model | Infra | Track 3 lead (joint) |
|---|---|---|---|---|
| **A** | 1a. Agent runs (medium) | 2a. Input page and agent text (medium) | Partner sites and served pages | 3c. Linking across agents, sites and browser |
| **B** | 1b. Plain script baselines (light) | 2c. Text classifier (heavy) | Logging server (MARK / fingerproxy) | 3d. IP change and collisions |
| **C** | 1c. Harness classifier (heavy) | 2b. API reference corpus (light) | `infra/loader.py` and `infra/schema.md` | 3b. Environment signatures |

Owning a piece means you write its code, record its results in the track's `hypotheses.md`, and draft its methods and results in the paper. Everyone reviews and helps on everything.

## Track 1: Harness identification (`harness/`)

- **1a. Agent runs (A, medium).** Run Claude Code, Codex CLI, Cline, Aider and any other agents we can get against our server with fixed task prompts. First, check whether each agent fetches from the user's machine or from the provider's servers, by comparing the logged client IP with the machine's IP. Track 3 depends on this check.
- **1b. Plain script baselines (B, light).** Write minimal scripts using the same HTTP stacks the agents use (axios, got, curl, Python requests/httpx, Go net/http, Colly) and run them on the same pages. Without these, H1 can't be tested.
- **1c. Harness classifier (C, heavy).** Write the shared feature extractor `harness/features.py` covering the TLS layer (JA3/JA4), the HTTP layer (header order, header set, HTTP/2 fingerprint) and timing. Then train a classifier that outputs probabilities, and test H1 and H2. Track 3 reuses this feature extractor.

## Track 2: Model identification (`model/`)

- **2a. Input page and agent text collection (A, medium).** Build the visible input page and collect the text agents post on it, during the same sessions as 1a. Pilot in week 1: most built-in fetch tools only send GET requests, so test whether agents submit at all, and offer a GET submit link (`/submit?text=...`) next to the form. Strictly no hidden text; see the ethics rules.
- **2b. API reference corpus (C, light).** Send the same page content and instruction directly to each provider's API, with no harness in between, to get reference text. H2 needs this corpus.
- **2c. Text classifier (B, heavy).** Train a provider/model classifier in the LLMmap style that reports a probability per provider. Evaluate it on API text and on agent text, and treat agents that never post as their own class.

## Track 3: User linking (`linking/`, joint)

`linking/` is owned by all three members. It starts once the infra is up and 1a has checked which agents fetch from the user's machine. Agents whose fetches come from the provider's servers are dropped from Track 3.

**Together:**

- **Protocol.** Agree on the session plan in `linking/protocol.md`: personas, agents, tasks, sites, and which runs change the IP.
- **Inventory.** Each member fills in their machines in `linking/machines.md`: OS, runtime versions, agents, and network type. Never real IP addresses.
- **Campaign.** Each member runs the sessions on their own machines and browser, against at least two partner sites. These runs include VPN or hotspot runs for the IP change setting. All runs are logged with `run_id` and `label_user`.
- **Results.** Write the Track 3 results section of the paper together.

**Analysis leads:**

- **3b. Environment signatures (C).** Build a per-request environment signature with the feature extractor from 1c. Measure how stable it is within a user and how distinct it is between users.
- **3c. Linking across agents, sites and browser (A).** Build a pairwise same-user model and clustering. Report linking across agents, across sites and to the user's own browser visits, and compare against the Zimmeck 2017 and Bird 2020 baselines.
- **3d. IP change and collisions (B).** Cover the hard cases: linking after the IP changes (H2), different users behind one shared IP (campus NAT), and different users with identical software setups. Optionally add the 2c classifier's model prediction as a linking feature.

## Shared work

| Piece | Owner |
|---|---|
| Paper: introduction, threat model, ethics | A |
| Paper: related work | B |
| Paper: discussion, limitations, defenses | C |
| Paper: Track 3 results | Everyone |
| Presentation | Everyone, one section each |

## Order of work

```
week 1      infra (A sites, B server, C loader)  +  1a local-or-server check  +  2a GET/POST pilot
               |
tracks 1-2  1a+2a (same sessions), 1b, 2b collect  ->  1c features + classifier, 2c classifier
               |                                        |
track 3     protocol + inventory  ->  joint campaign  ->  3b signatures (needs 1c features)
                                                      ->  3c linking, 3d IP change (need 3b)
               |
writing     each owner drafts their pieces; Track 3 results written together
```

1. **Week 1, everyone:** finish the infra and freeze the schema. A runs the local-or-server check and the GET/POST pilot first.
2. **Tracks 1 and 2:** each member runs their two pieces. Draft the Track 3 protocol and machine inventory in parallel.
3. **Track 3 campaign:** once the infra is stable, run it together. The campaign's logs are also extra data for Tracks 1 and 2.
4. **Track 3 analysis:** starts when the 1c feature extractor exists. It doesn't need 1c's classifier results.
5. **Writing:** record each experiment in `hypotheses.md` first, then draft the paper.

## Branches and merging

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: work on your own branch, open a pull request into `main`, and merge only after CI passes and a teammate approves.
