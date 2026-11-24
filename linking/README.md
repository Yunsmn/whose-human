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

Known limits of the scaffold:
- `SIGNATURE_COLUMNS` is a placeholder; 3b (A) owns the environment signature and will replace it.
- The cross-validation scores only pairs whose two sessions fall in the same fold, so the cluster metrics see a
  fraction of the pairs and are not meaningful yet.
