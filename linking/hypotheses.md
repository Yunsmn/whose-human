# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Requests from different agents on the same machine share the IP and an environment signature (runtime and TLS stack versions).
Status: open (first observation below)

Date: 2026-11-18
Run ids: c-user-curl-001 (site2), compared with the 7 natural headless Claude Code runs that used curl (c-claude-h-001, c-claude-sh-site{1,2}-00{1,2,3}; site1 and site2) and c-codex-h-001 (site1). The directed curl session in c-claude-i-001 is not used, as in the harness entry.
Setup: C typed curl by hand on site2 (the user's own traffic); the agents used curl on their own, all on the same Linux machine.
Result: the user's own curl and every agent curl request have the same JA4, JA3, HTTP/2 fingerprint, ALPN, HTTP version, User-Agent (`curl/8.23.0`, OpenSSL 4.1) and Accept. All 7 Claude Code GET requests also matched the user's header order exactly. Of the 6 Claude Code POST submits, 1 matched exactly and 5 differed only in the body format (`multipart/form-data`, the curl command Claude wrote); Codex's POST added a `Cookie` header. The site does not change the signature. Timing from the page to the first submit: user 136.3 s; the 6 Claude Code runs that used only curl 3.1 to 3.6 s; Codex 5.2 s.
Conclusion: supported for agents that shell out: when an agent uses the system curl it carries the same environment signature as the user's own curl, across agents and sites. How identifying that is depends on how rare the build is; a rolling-release curl/OpenSSL pair is narrower than stock Windows curl. Inconclusive for agents with their own client (WebFetch). Based on one user run.
Next: 3c combines this signature with IP and timing; test whether it survives an IP change (H2).

## 3b campaign snapshot: exact environment-signature stability and collisions
Status: preliminary (only runs whose manifests are merged on public `main`; setting 5 is not collected)

Date: 2026-11-26
Run ids: the 57 controlled Track 3 sessions whose `a-t3-`, `b-t3-` or `c-t3-` manifests are on public `main`, found in the private `vm-20261125.jsonl` and 2,590-row `vm-20261126.jsonl` snapshot: 12 A, 21 B and 24 C sessions. The earlier 122-session calculation mixed Track 1/local runs into the campaign and is superseded by this entry.
Setup: `python -m linking.signatures data/logs --runs runs`. The declared environment signature is the 11 IP-free and timing-free fields in `sessions.SIGNATURE_COLUMNS`; a session keeps every value it showed for each field. The default report now filters to controlled Track 3 run ids. We compared all 1,596 unordered session pairs: 552 same-person/same-machine pairs and 1,044 different-person/different-machine pairs. An exact match means the two sessions have equal value sets in all 11 fields. Address changes are computed privately from observed addresses, not from the public network-kind label; the report prints no address or raw signature value.
Result:
- Seven fields were present in all 57 sessions. HTTP/2 covered 24/57 (42.1%), User-Agent version 25/57 (43.9%), Accept-Encoding 44/57 (77.2%) and Accept 48/57 (84.2%). Individual columns had 2 to 23 population values; largest shares ranged from 28.1% to 77.2%.
- Exact signatures matched 58/552 same-person pairs (10.5%) and 36/1,044 different-person pairs (3.4%). Every different-person collision was WebFetch against WebFetch: 36/36 (100%); all other different-person tool pairs had zero exact collisions.
- Curl against curl matched 13/19 same-person pairs (68.4%), including 9/12 cross-site pairs (75.0%), versus 0/47 different-person curl pairs. WebFetch against WebFetch matched 30/30 same-person and 36/36 different-person pairs (both 100%): it identifies the provider client, not the machine.
- Python urllib matched 11/13 same-person pairs (84.6%) and 0/15 different-person pairs. The browser signature matched only 2/45 same-person pairs, no cross-site pair, and 0/108 different-person pairs.
- No currently merged same-person pair crosses an observed address, so this snapshot does not yet measure same-person signature stability after an IP change. Of the 1,044 different-person pairs, 792 cross an observed address; their 36 exact collisions are all WebFetch/WebFetch. The public network labels are all `campus`, so the secondary label-based split has zero pairs.
- No cross-tool pair had an exact signature. In particular, exact environment equality did not link an agent's curl, WebFetch or Python session to the same person's browser.
Conclusion: H1 is supported for agents that reuse a machine-specific runtime: curl and Python urllib signatures are stable enough to link many sessions and did not collide exactly between the measured machines. It is rejected for WebFetch alone, whose perfectly stable signature is shared by every user, and exact matching cannot bridge different tools or link agents to the browser. The rarity-weighted 3c model is therefore necessary: it discounts common provider-fixed values and combines partial signature matches, while IP and the relay token remain separate evidence.
Next: rerun after A's setting 4 manifest merges, then add setting 5 to measure same-network collisions in one sitting.

## H2: Linking still works when the IP changes, using environment and timing alone.
Status: open

## Observation: the agent passes the visit's identifier on to the user
Status: observation, not a test yet (2026-11-24)
Run ids: the 27 headless Claude Code runs with saved outputs: c-claude-h-00{1,2}, c-claude-{wf,sh}-site{1,2}-00{1,2,3} (Linux) and b-claude-{wf,sh}-site{1,2}-00{1,2,3} (Windows).
Result: 5 of the 27 final answers shown to the user contain the visit's path with its run id, 4 of them as a full link. All 5 are runs that used WebFetch: 4 of B's 6 and 1 of C's 8. No run that used curl did. The task never asks for sources.
Meaning: a per-visit identifier in the URL reaches the user's screen through the agent's answer. If the user clicks the link, their own browser visit carries the identifier. That links the agent's visit to the person's browsing with no cookie, no IP and no fingerprint. It is UID smuggling (Randall et al., IMC 2022) through the agent.
Next: in the Track 3 campaign, count how often answers cite our links, and how often we follow them ourselves in setting 3, with tasks that ask research-style questions (agents cite sources there). Report it per agent and per tool.

## 3c dry run: linking the local agent runs without the IP
Date: 2026-11-24
Run ids: every non-baseline run of persona-b1 (B, Windows: 30 Claude Code runs) and persona-c1 (C, Linux: 27 Claude Code runs, 1 Codex, 1 user curl), from the local logs. Not a Track 3 campaign: a test of the `linking/` pipeline on the data we have.
Setup: `python -m linking.link`, one session per run (no browser sessions yet), 59 sessions, 1,711 pairs (841 same user). Local runs all show the Docker gateway as the client IP, so the IP carries nothing here and every result is effectively "without IP".
Result:
- Whether two sessions' JA4s match, by the tool each session used:

  | Sessions compared | Same user | Different users |
  |---|---|---|
  | curl and curl | match in 156 of 156 pairs | match in 0 of 169 |
  | WebFetch and WebFetch | 87 of 87 | 84 of 84 |
  | curl and WebFetch | 0 of 247 | 0 of 247 |

- Logistic regression, 5-fold by session, every pair scored by a model trained on neither of its sessions (1,711 pairs), threshold 0.5:

  | Features | Pair AUC | Precision | Recall | Clusters: ARI | B-cubed F1 |
  |---|---|---|---|---|---|
  | without IP (`no_ip`: network trace, schedule, run token) | 0.89 | 0.82 | 0.75 | 0.80 | 0.89 |
  | network trace only (`network_only`) | 0.84 | 0.71 | 0.69 | 0.38 | 0.67 |

  Clusters use average linkage. Connected components (single linkage) merge everyone into one cluster with either feature set (ARI 0.00), because WebFetch sessions of different users look the same and one false link is enough.
- What the clusters hold: without IP, one cluster per user's curl and mixed sessions; B's WebFetch sessions join B's cluster and C's form a cluster of their own. They are kept apart by the time between sessions, not by the network: B and C ran their agents on different days. With the network trace alone, WebFetch sessions of both users end up in one cluster with B's curl sessions.
Conclusion: the gain from `network_only` to `no_ip` is our schedule, not a property of the user, so `network_only` is the honest number for linking without IP. When the agent shells out, the system curl carries the machine's TLS stack and links its sessions; WebFetch carries the same fingerprint on every machine, so it links nothing without the IP; and nothing in the trace links a user's curl sessions to their WebFetch sessions. With two users on different operating systems this is the easy case: two users with the same OS and curl build would collide (3d).
Next: the Track 3 campaign on the VM, with real IPs, browser visits and three users; more than one user per OS.

## 3d dry run: hard cases on the local runs
Date: 2026-11-25
Run ids: the same sessions as the 3c dry run (59 sessions, persona-b1 and persona-c1, local logs). Not a Track 3 campaign: a test of `linking.hard_cases` on the data we have.
Setup: `python -m linking.hard_cases data/logs`. Every local request shows the Docker gateway as its client IP, so every pair "shares an IP", and no pair shows an IP change.
Result:
- IP change: no pairs (no second network in local runs).
- Identical setups: 84 of 870 pairs of different users (9.7%) match on every signature column. All 84 are WebFetch against WebFetch: 84 of 84 of those pairs, and 0 for every other tool pair (curl against curl, 0 of 169).
- Anonymity: 40 of 59 sessions (68%) have a signature that no other user shares: every curl and every WebFetch-then-curl session. None of the 19 WebFetch-only sessions does.
- Shared IP (here: every pair of different users): the `network_only` model falsely links 20.1% of the 174 scored pairs, and the `no_ip` model 13.8%. The false links come from mixed tool pairs (curl / WebFetch 42.6%, WebFetch / WebFetch-then-curl 34.6%), not from curl against curl (0 of 32) or WebFetch against WebFetch (0 of 15).
Conclusion: the pipeline runs. With two users on two OSes, the identical-setup case is exactly WebFetch, as 3c found: its sessions collide between users, while a user's system curl keeps them apart. The false links under a shared IP are the model's mistakes on mixed tool pairs, not collisions of environment.
Next: the campaign's settings 4 (IP change) and 5 (three users on one campus IP). Then the identical-setup question needs two users with the same OS and curl build.

## Experiment: choosing the linking model on train / validation / test splits
Date: 2026-11-26
Run ids: the Track 3 runs of the first campaign results (settings 1, 3, 4; 72 sessions, 3 users, 2,556 pairs), VM log in the data repo.
Setup: `python -m linking.experiments <vm logs> --runs runs --extra-train <local logs> --seeds 5`. Sessions are split 60/20/20 into train, validation and test, stratified by user and setting; training pairs have both sessions in train, validation and test pairs always involve a session the model never saw; clusters are scored on the validation or test sessions alone. Five random splits. Round 1: six feature sets × logistic regression, gradient boosting and extra trees, a supervised Fellegi-Sunter scorer with value-specific agreement weights (with and without the IP), and training extended with the local Track 1 sessions; round 2: extra-trees settings (leaf size 1/3/10, features per split sqrt/0.5/all) on the two best feature sets. The clustering threshold (0.3 to 0.8) is part of each configuration. Selection by mean validation B-cubed F1; the feature set with the time between sessions is reported but never selectable. Rarity value shares come from each split's training sessions only (and from each fold's training sessions in `cross_val_scores`), so evaluation sessions never shape their own features; A's runs relabelled `campus` (#61).
Result:
- The time between sessions alone makes linking perfect (validation and test B-cubed F1 1.000, AUC 0.996): each user ran in their own time blocks. It measures our schedule, confirming that it must stay out of every headline number.
- Validation B-cubed F1 (mean of 5 splits): IP rule 0.652; network trace 0.744; trace + rarity 0.754; with the /16 or the IP added 0.752; extra trees beat gradient boosting (0.69–0.73) and logistic regression (0.70–0.71); the local sessions as extra training data did not help (0.73); Fellegi-Sunter 0.60–0.63. Round 2 best: trace + rarity + IP, extra trees with leaf size 3 (all or half the features per split tie), threshold 0.4: 0.781.
- Test, that configuration: B-cubed F1 0.724 ± 0.112, pair AUC 0.848 ± 0.029, ARI 0.44 ± 0.27; IP rule 0.652, AUC 0.584, ARI 0.10. (Round 1's pick, trace + rarity with default extra trees, scored 0.709 ± 0.093 on the same test sets, which were looked at after round 1; selection in both rounds used validation only.)
- Round 3 (more model families, every model with feature scaling, the full 2026-11-26 log): on trace + rarity + IP, random forest ties extra trees (validation 0.781); k-NN 0.774; an average of extra trees, random forest and k-NN 0.769 (the best pair AUC, 0.855, but not better clusters); RBF SVM and a small MLP were weaker. Among the tied top configurations, test B-cubed F1 ranges from 0.68 to 0.72 depending on the pick (0.684 ± 0.075 for the first in the tie), which is the size of the uncertainty here.
- Why the IP rule is weak in this data: all three of us ran from the same university network (two Wi-Fi networks of the same campus), so the address could only separate people when they happened to leave through different addresses. With users on different networks the IP would do far better; our numbers measure the hard case of colleagues on one campus, not the general one.
Conclusion: on three users, the network trace with rarity weights links better than the IP (test B-cubed F1 0.72 vs 0.65, AUC 0.85 vs 0.58), and nonlinear models help; the gains between the top configurations (about 0.03) are within the split-to-split spread (± 0.07 to 0.09), so they are not distinguishable yet. More users (setting 5) and the TCP-level fingerprint are the larger levers.
Next: rerun after setting 5 with the selected configuration fixed in advance, so that the next test is untouched.
