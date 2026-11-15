# Member A local Omen/Queen same-PC test summary

**Date:** 15 November 2026  
**Status:** Local exploratory validation; not the final multi-machine experiment

## Objective

This test checked whether the Member A pipeline can collect and compare two local-model sessions labelled Omen
and Queen on the same controlled PC. The known ground truth was `same_machine = 1`. The test measured the local
inference configuration; it did not attempt to identify a human or recover a hardware serial number.

## Local setup and method

- Machine alias: `local-pc-test` (the real hostname was not recorded)
- Runtime: Ollama on `127.0.0.1`
- Model: `qwen2.5:0.5b`, 494.03M parameters, Q4_K_M quantization
- Sessions: `local-omen-v2-20261115` and `local-queen-v2-20261115`
- Plan: five fixed synthetic cases, five repetitions per case, 25 measurements per session
- Privacy: prompt/output content was discarded; only timings, counts, case labels, and pseudonymous metadata were
  stored in the gitignored `data/benchmarks` directory
- Cold-start control: the model was unloaded before each session

The cases varied target context and output sizes: `short-32`, `short-128`, `medium-128`, `long-128`, and
`long-256`. Repetitions were aggregated into one profile per session. Pairwise numeric features used the symmetric
relative difference

\[
d_k(a,b)=\frac{|x_{a,k}-x_{b,k}|}{|x_{a,k}|+|x_{b,k}|+\epsilon}.
\]

## Failure found and correction

The first `local-llm-v1` run repeated the word `neutral` throughout the synthetic context. Ollama aborted most
longer generations with HTTP 500 and `prediction aborted, token repeat limit reached`. Only 12 of 50 measurements
completed. This was a benchmark-input defect, not a same-PC result.

The benchmark was corrected and versioned as `local-llm-v2`:

- repeated filler was replaced with deterministic unique labels (`datum0000`, `datum0001`, ...);
- output was changed to a deterministic consecutive-integer task;
- a privacy-safe `failure_reason` field was added for incomplete streams;
- unit tests were updated to lock the new prompt structure.

A one-repetition validation then completed all five cases successfully, after which the full test was rerun.

## Measured result

Both complete v2 sessions succeeded in all cases: **50/50 measurements (100%)**.

| Case | Omen median evaluation tokens/s | Queen median evaluation tokens/s | Symmetric difference |
|---|---:|---:|---:|
| `short-32` | 427.693 | 428.644 | 0.11% |
| `short-128` | 405.741 | 422.936 | 2.08% |
| `medium-128` | 398.812 | 414.866 | 1.97% |
| `long-128` | 418.453 | 411.104 | 0.89% |
| `long-256` | 418.763 | 418.588 | 0.02% |

Across **53 comparable profile features**, the median relative difference was **0.032097 (3.21%)**. The largest
single relative difference was **0.754491**, mainly from IQR and chunk-jitter features. This shows why one unstable
dispersion feature must not control the decision; the central throughput measurements were much closer.

The repository verification after the v2 correction also passed:

- Ruff lint: passed
- Ruff format check: passed
- Pytest: **28 passed, 1 platform-dependent test skipped**

## Interpretation and limitation

The measurements are compatible with Omen and Queen running on the same PC, which is the known controlled setup.
However, this test cannot produce a defensible learned `same_pc_probability`: it contains one physical machine
and therefore no different-machine negative pairs. The correct classifier output remains **`unknown`**, not a
claimed positive identification.

This test proves that the local collector, privacy controls, profile aggregation, and pair-feature calculation
work end to end. It does **not** prove that the features uniquely identify a PC or distinguish this PC from other
machines. Identical hardware may collide, while background load, thermal state, drivers, power mode, model,
quantization, or engine changes may move the same machine's profile.

## Required next experiment

Collect Omen and Queen profiles from at least six labelled PCs (preferably substantially more), including idle
and background-load conditions, reboot/day-two repetitions, identical-hardware machines, same-NAT machines, and
network changes. Split the dataset by whole machine, choose the decision threshold on validation machines, freeze
it, and report precision, recall, false-match rate, false-nonmatch rate, ROC-AUC, and Brier score once on untouched
test machines. Until that experiment is complete, the scientific same-PC hypothesis remains open.
