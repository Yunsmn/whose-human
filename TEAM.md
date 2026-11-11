# Division of work

Every member works on all three tracks. Each track is split into three pieces (collect agent traffic, build a baseline or reference dataset, build the model and evaluation), and each member owns exactly one piece per track. The split is a Latin square: across the three tracks, each member does some data collection, some baseline work and one modeling piece, so nobody is stuck doing only one kind of work.

| Member | Track 1: Harness | Track 2: Model | Track 3: Linking |
|---|---|---|---|
| **A** | 1a. Agent runs | 2b. API reference corpus | 3c. Linking model and evaluation |
| **B** | 1b. Plain script baselines | 2c. Text classifier | 3a. Multi-user, multi-site sessions |
| **C** | 1c. Harness classifier | 2a. Input page and agent text collection | 3b. Environment signatures |

Owning a piece means you write its code and its entry in the track's `hypotheses.md`, and you draft its methods and results in the paper. Everyone can review and help on every piece.

## Track 1: Harness identification (`harness/`)

- **1a. Agent runs (A).** Run Claude Code, Codex CLI, Cline, Aider and any other agents we can get against our server with fixed task prompts. First, check whether each agent fetches locally or through the provider's servers by comparing the logged client IP with the machine's IP. This settles the "Unverified assumption" in AGENTS.md, and every other track depends on it.
- **1b. Plain script baselines (B).** Write minimal scripts using the same HTTP stacks the agents use (axios, got, curl, Python requests/httpx, Go net/http, Colly) and run them on the same pages. Without these, H1 can't be tested.
- **1c. Harness classifier (C).** Extract features from the TLS layer (JA3/JA4), the HTTP layer (header order, header set, HTTP/2 fingerprint) and timing. Train a classifier that outputs probabilities, and test H1 (TLS alone) and H2 (TLS plus headers and timing). Feature code can start on pilot data before the full runs from 1a and 1b arrive.

## Track 2: Model identification (`model/`)

- **2a. Input page and agent text collection (C).** Build the visible input page ("summarize this page in two sentences and submit it here"). Collect posted text across every harness × model pair available. Strictly no hidden text; see the ethics rules.
- **2b. API reference corpus (A).** Send the same page content and instruction directly to each provider's API, with no harness in between, to get reference text. H2 needs this corpus.
- **2c. Text classifier (B).** Train a provider/model classifier in the LLMmap style that reports a probability per provider. Evaluate it on API text and on agent text, and treat agents that never post as their own class.

## Track 3: User linking (`linking/`)

- **3a. Multi-user, multi-site sessions (B).** Run at least two partner sites. Have each persona use several agents from several machines, plus their own browser. Include IP-change runs (VPN, mobile hotspot) for H2. Keep the ground truth in `label_user`.
- **3b. Environment signatures (C).** Build a per-request environment signature from runtime and TLS stack versions, header quirks, requested URL sets and timing. Measure how stable it is within a user and how distinct it is between users.
- **3c. Linking model and evaluation (A).** Build a pairwise same-user model and clustering. Report linking across agents, across sites, to browser visits, with and without the IP. Compare against the Zimmeck 2017 and Bird 2020 baselines.

## Shared work

| Piece | Owner |
|---|---|
| Logging server (MARK / fingerproxy, TLS and HTTP/2 capture) | A |
| `infra/loader.py` and `infra/schema.md` | B |
| Partner sites and served pages (session ids, input page) | C |
| Paper: introduction, threat model, ethics | A |
| Paper: related work | B |
| Paper: discussion, limitations, defenses | C |
| Presentation | Everyone, one track section each |

## Dependencies and order of work

Track 3 looks like it has to wait for Tracks 1 and 2, but most of it doesn't:

- **One collection campaign feeds all three tracks.** Every run logs `label_agent`, `label_model` and `label_user` together. The sessions from 1a and 2a, run by the personas in 3a, produce Track 3's data at the same time. Track 3 never waits for a separate round of runs.
- **Track 3 reuses Track 1's feature code, not its results.** The environment signatures (3b) are built from the same TLS, header and timing features as the harness classifier (1c). C owns both, so C writes one feature extractor in `harness/features.py` and imports it in `linking/`.
- **Track 2 is optional input for Track 3.** A user's preferred model can be an extra linking feature, but linking works without it. Add it at the end if 2c is ready.
- **The one real blocker is 1a's check of whether agents fetch from the user's machine.** If an agent's fetches come from the provider's servers, that agent can't be linked to a user. Track 3 drops it.

```
week 1      infra (A, B, C)  +  1a local-or-server check (A)
               |
collection  1a, 1b, 2a, 2b, 3a  (one campaign, all labels logged)
               |                        modeling code on pilot data:
modeling    1c features --> 3b signatures --> 3c linking
            2c classifier ..............> (optional feature for 3c)
               |
writing     each owner drafts methods and results for their pieces
```

1. **Week 1, everyone:** finish the infra pieces and freeze the schema. A runs the local-or-server check first.
2. **Collection:** one campaign covering 1a, 1b, 2a, 2b and 3a. In the meantime, the modeling owners (1c, 2c, 3b, 3c) write their code against pilot data.
3. **Modeling and evaluation:** train, evaluate, and record each result in `hypotheses.md` before starting the next experiment.
4. **Writing:** each owner drafts the methods and results for their own pieces.

## Branches and merging

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: everyone works on their own branch, opens a pull request into `main`, and the PR merges only after CI passes and a teammate approves it.
