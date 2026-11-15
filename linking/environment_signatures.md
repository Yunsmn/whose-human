# Track 3b: environment signatures

Member A leads this analysis after Member C's `harness.features` extractor is merged and the joint Track 3
campaign has produced labelled logs.

`linking.environment_signatures` builds a deterministic `env-v1` signature from TLS, HTTP runtime, and HTTP/2
features. It intentionally excludes the peer IP, cookies, site, URL/path, request timing, body, and submitted
text. This separation prevents the environment result from being an IP-linking result in disguise and avoids
using task content as an identifier.

The analysis first computes one signature per request, then uses the modal signature for each run. It reports:

- coverage: fraction of runs with a usable signature;
- within-machine exact-match rate across run pairs;
- within-machine exact-match rate restricted to different agents;
- between-machine collision rate across run pairs.

Run it only on private data:

```powershell
python -m linking.environment_signatures data/logs
```

An optional `--output data/environment-signatures.csv` writes per-run signatures for diagnosis. Keep that
file private even though the signature excludes IPs: it is a derived persistent identifier.

Exact matching is the deliberately simple first baseline. If it performs poorly across agents, report that
result before trying weighted similarity. This baseline fingerprints the observable network software stack; it
is not a direct physical-hardware fingerprint. The local-model performance extension and its Omen/Queen protocol
are documented in [`machine_linking_protocol.md`](machine_linking_protocol.md). Do not tune feature selection on
test machines; define any similarity threshold using separate training/validation machines and freeze it before
the final held-out-machine evaluation.
