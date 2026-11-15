# Member A: probabilistic same-PC linking for local agents

## Claim and boundary

This sub-study asks whether two **locally hosted model sessions**—for example, Omen and Queen—probably ran on
the same enrolled PC. It does not identify a person, recover a hardware serial number, or prove physical-device
identity. The output is one of:

- `probably_same_pc` when the learned score meets a validation-selected high threshold;
- `unknown` otherwise.

The conservative `unknown` outcome is important. Similar hardware, background load, thermal throttling, model
updates, and different power settings can make two PCs look alike or one PC look different.

## What is measured

An ordinary website request exposes TLS, HTTP, HTTP/2, header, sequence, and coarse request-timing features. It
does not expose CPU, GPU, RAM, or local-model token usage directly. For consenting experiments, the optional
local collector in `linking.local_model_benchmark` calls a loopback Ollama server and stores only:

- first streamed-chunk time (an approximation of time to first token);
- total duration and model-reported load, prompt-evaluation, and evaluation duration;
- prompt and output token counts and derived tokens per second;
- median, p95, and standard deviation of streamed-chunk intervals;
- fixed benchmark case, model, engine, quantization, agent, and pseudonymous session/machine labels.

Ollama chunks are not guaranteed to correspond one-to-one with tokens. These are performance features, not
direct utilization readings and not immutable hardware identifiers. Prompts and generated text are deliberately
discarded. The endpoint must be localhost or a loopback IP, so the collector cannot accidentally benchmark a
remote provider.

## Fixed Omen/Queen experiment

Use the exact same model file, quantization, Ollama version, benchmark cases, and power mode on every calibration
machine. Enrol at least six labelled PCs; more machines are strongly preferable. On each PC, collect one Omen
session and one Queen session under both idle and documented background-load conditions. Repeat on a second day
or after a reboot to measure drift. Use pseudonyms such as `pc-03`, never a hostname or serial number.

Preview the five fixed synthetic cases without running a model:

```powershell
python -m linking.local_model_benchmark plan --repetitions 5
```

Collect 25 measurements for each agent session:

```powershell
python -m linking.local_model_benchmark collect --model llama3.2:3b `
  --agent omen --machine pc-03 --session-id pc-03-omen-day1 --quantization q4_K_M

python -m linking.local_model_benchmark collect --model llama3.2:3b `
  --agent queen --machine pc-03 --session-id pc-03-queen-day1 --quantization q4_K_M
```

The default private output is `data/benchmarks/local-model.jsonl`. It is gitignored. Copy that private file from
each consenting calibration PC into the analysis environment; never commit it.

## Build, train, and score

Aggregate repeated measurements into one performance profile per session:

```powershell
python -m linking.machine_linker profiles data/benchmarks/*.jsonl `
  --output data/benchmarks/profiles.csv
```

Train and evaluate with **entire PCs held out**, never with a random request split:

```powershell
python -m linking.machine_linker train data/benchmarks/profiles.csv --threshold 0.95
```

This writes a private model and a JSON report containing precision, recall, F1, ROC-AUC, and Brier score. The
0.95 threshold is only a provisional default. Before making a research claim, choose it on separate validation
machines to meet the study's desired false-match rate, freeze it, and then report performance once on untouched
test machines.

Score cross-agent pairs:

```powershell
python -m linking.machine_linker score data/benchmarks/profiles.csv --threshold 0.95
```

The CSV contains `same_pc_probability` and `decision`. A high Omen/Queen score supports “these sessions probably
came from the same enrolled PC under this benchmark configuration.” It does not support “these sessions belong
to the same human” or “this is globally the same physical PC.”

## Required baselines and hard cases

Compare the learned performance linker with: (1) chance, (2) IP-only, (3) the existing transport/runtime
`env-v1` exact signature, and (4) performance-only without IP. Report false matches and false non-matches for:

- same PC after reboot, network change, and background load;
- different PCs behind the same NAT;
- different PCs with identical CPU/GPU and software;
- the same PC after model, quantization, driver, engine, or power-mode changes.

If the untouched-machine precision is not high enough, the result is that the feature set is insufficient. Do
not add hidden prompts, query third-party sites, expose raw IPs, or relabel an uncertain pair as a match.
