# Track 3c: user linking

Three steps, each a small module:

- `sessions.py`: request logs → sessions. A session is one run id, split into the agent's requests and the browser's.
  On the Track 3 VM every visit goes to `/r/<run_id>/`, so a browser request under an agent's run id is the user
  opening a link the agent relayed: it becomes its own session that shares the run id. Each session keeps the IP and
  its /24 or /64 prefix, the set of values it showed for each signature column (an agent that reads with WebFetch
  and submits with curl shows two JA4s), its tool sequence (`webfetch>curl`) and its timing.
- `pairs.py`: every pair of sessions, labelled same user or not, with comparison features in four groups: IP,
  relay token, schedule (time between the sessions), and the network trace (signature matches, tool sequence,
  timing). Slices for reporting: cross-agent, cross-site, agent–browser, IP changed, shared IP.
- `link.py`: two rules (same IP; every signature column matches), a logistic regression that outputs a same-user
  probability, cross-validated so no session is in both train and test, and connected-component clusters scored
  with ARI and B-cubed F1.

```sh
python -m linking.link <logs_dir> [--runs runs] [--include-baselines] [--threshold 0.5]
```

The model is scored on three feature sets: `all`, `no_ip` (H2: does linking survive an IP change?) and
`network_only` (no IP, no relay token, no schedule).

Evaluation details:
- Cross-validation splits sessions into folds; the pairs between folds k and m are scored by a model trained only
  on pairs touching neither fold, so every pair gets a score from a model that saw neither of its sessions
  (needs at least 3 folds).
- Clusters use average linkage on 1 − score (`--threshold` is the mean score needed to merge two groups). The
  connected-components result is printed next to it: single linkage merges two users on one false link.
- `log_dt_start` measures our campaign schedule as much as the user; `network_only` leaves it out.
- `SIGNATURE_COLUMNS` is a placeholder; 3b (A) owns the environment signature and will replace it.

## Campaign report (`campaign.py`)

Run first, as soon as a VM log lands in the data repo: `python -m linking.campaign <logs_dir> [--runs runs]`.
It checks every Track 3 run in the manifests against the log (missing, fetched only, submitted; agent runs that
didn't submit are listed), counts distinct addresses and /24 or /64 prefixes per user, setting and network,
the IPv6 share and whether browser visits shared the agents' address (counts only, never an address), lists
each agent's tool sequences, and checks decision A: whether a submitted summary names the keyword of the
per-visit sentence its page carried (`visit_variant`).

## Track 3d: hard cases (`hard_cases.py`, B)

```sh
python -m linking.hard_cases <logs_dir> [--runs runs] [--threshold 0.5]
```

It reuses 3c's sessions, pairs and cross-validated scores, and reports four tables. Each one compares the IP rule
with 3c's model without the IP (`no_ip`) and on the network trace alone (`network_only`):

- **IP change** (H2, setting 4): pairs of one user's sessions whose IPs differ, by the two networks' labels
  (`home / vpn`, `home / mobile`, ...). For each: recall, and how often the /24 or /64 prefix still matched.
- **Shared IP** (setting 5): pairs of different users behind one IP, by tool pair, with the false-link rate. The IP
  rule links all of them by construction.
- **Identical setups:** pairs of different users whose sessions have the same values on every signature column.
  Two empty columns count as equal here (WebFetch sends no HTTP/2 and no UA version), unlike 3c's `same_<column>`
  features, which need a shared value.
- **Anonymity:** for each session, how many other users have a session with its exact signature. The table gives
  the share of sessions with a signature unique to their user.

Every pair is scored out of sample (3c's cross-validation, at least 3 folds); `n_scored_*` gives the counts.
