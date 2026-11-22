# 2c: text classifier on Sun et al.'s backbone, in 4-bit

Owner: B. Identifies the model behind a short text an agent wrote, as a probability vector over the models we study.

It reuses the published chat API classifier of Sun et al., "Idiosyncrasies in Large Language Models" (ICML 2025; code [locuslab/llm-idiosyncrasies](https://github.com/locuslab/llm-idiosyncrasies), MIT license; weights [Yida/classifier_chat](https://huggingface.co/Yida/classifier_chat)), converted to 4-bit so it runs on a 6 GB GPU. Its backbone is kept frozen. Only the last layer (the head) is replaced by one trained on our own models.

## Two heads

| Head | Labels | Trained on | Use |
|---|---|---|---|
| `short` (default) | our 6 current models (below), plus a two-way provider head | two-sentence page summaries we collected through the agents' CLIs, the way 2b collects them | 2c output |
| `sun` | ChatGPT, Claude, Grok, Gemini, DeepSeek (2024 models) | Sun et al.'s long chat answers | baseline only |

Models of the `short` head, three tiers per provider:

| Provider | Flagship | Mid | Small |
|---|---|---|---|
| anthropic | claude-opus-5-5 | claude-sonnet-5-5 | claude-haiku-5-5 |
| openai | gpt-6-astra | gpt-6.1-sol | gpt-6-luna |

This list is proposed to 2b so that its API corpus covers the same models. Gemini is not included yet: there is no Gemini agent on the collection machine.

What it cannot answer:

- A model outside the list is forced into one of its labels.
- The training summaries come from agents: Anthropic models through Anthropic's coding agent CLI, OpenAI models through the Codex CLI. Harness and provider are therefore confounded, and the head may partly learn the harness. Separating tiers within one provider is not affected.
- The `sun` head predicts Gemini for almost any short text. It was trained on long answers, and Gemini's training answers include the most short ones (10.5% under 60 words, against 3–6% for the others).

## Architecture

LLM2Vec (Llama-3-8B-Instruct with bidirectional attention), with Sun et al.'s LoRA adapters merged in, then mean pooling over all tokens into one 4,096-number vector, then a linear head and a softmax.

- `sun` head: their trained 4096→5 layer (42 KB).
- `short` head: two logistic regressions on the same standardized vectors, both in `heads/head-short.npz` (committed, about 170 KB):
  - a six-way one over the models (C = 0.01), which gives `p_<model>`;
  - a two-way one over the providers (C = 0.001), which gives `provider_<name>`. It names the provider more often than summing the model probabilities, because it doesn't have to tell the tiers apart first.

## Hardware

| | Original (bf16) | This version (4-bit NF4) |
|---|---|---|
| Model on disk | 15.2 GB | 4.3 GiB |
| GPU memory | 16 GB or more | 4.6 GiB peak (measured) |

Needs an NVIDIA GPU with CUDA and about 30 GB of free disk during conversion (download, merged copy, 4-bit copy). After conversion, the download and merged copy can be deleted.

## Setup

Use a separate environment; the repository's requirements don't include the GPU stack.

```sh
python -m venv ../sun-cls-env                       # anywhere outside the repo
../sun-cls-env/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
../sun-cls-env/Scripts/python -m pip install -r model/sun_classifier/requirements.txt
```

Files, all into the gitignored `data/models/sun_chat/download/`:

- `model.safetensors` and `head.pt` from `huggingface.co/Yida/classifier_chat`
- `config.json`, `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json` from the ungated `huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp`, saved with the prefix `mcgill-`

Meta's gated Llama 3 repository is not needed: the checkpoint already holds every weight. The model is still a Llama 3 derivative, under Meta's Llama 3 license.

## Building the backbone

From the repository root, with the separate environment:

```sh
python -m model.sun_classifier.convert merge        # LoRA merged into bf16 shards (CPU, about 15 GB disk)
python -m model.sun_classifier.convert quantize     # 4-bit model in data/models/sun_chat/nf4
python -m model.sun_classifier.evaluate --download  # Sun et al.'s published answers, for checking
python -m model.sun_classifier.evaluate --per-class 200   # check the conversion with the sun head
```

## Training the short head

The committed head is enough to predict. Retrain it only to change the models or add data.

```sh
python -m model.sun_classifier.summary_answers pages --n 100              # practice pages, once
python -m model.sun_classifier.summary_answers collect claude-haiku-5-5   # once per model
python -m model.sun_classifier.train_head
```

- **Pages:** `summary_answers.py pages` writes `data/corpus/summaries/pages.json`: 100 prose paragraphs of 30–80 words from the non-test part of Sun et al.'s data, drawn evenly across their five models (seed 7). They are never our site pages, which stay the test.
- **Collection:** the task is 2b's: the page followed by 2b's instruction ("Summarize this page in two sentences. Reply with only your summary."). Each page is one CLI call, built with 2b's own command builders and parsers in `model/cli_corpus.py`, in both conditions (`default` and `minimal` system prompt). Summaries go to the gitignored `data/corpus/summaries/<model>.jsonl`. Re-running retries failed calls and skips the rest.
- **Training:** `train_head.py` turns every summary into a vector with the frozen backbone (cached in `data/models/sun_chat/short-embeddings.npz`), and holds out whole pages (the last 25%) for testing. It records the held-out score, refits both heads on every summary, scores them on 2b's corpus of our site pages (`data/corpus/cli`), and writes `heads/head-short.npz` and `data/results/short_head_eval.json`.
- The earlier generic-question collector (`agent_answers.py`, 20 UltraChat questions per call as JSON) is kept for comparison; `train_head.py --corpus-dir data/corpus/short` trains on its answers.

## Predicting (2c output)

```sh
python -m model.sun_classifier.predict data/corpus/agent/member-a-agent-text.csv   # 2a's agent text
python -m model.sun_classifier.predict data/corpus/api/corpus-YYYYMMDD.jsonl --id-column prompt_id   # 2b's API text
python -m model.sun_classifier.predict some.csv --head sun                         # the 2024 baseline
```

- **Input:** any CSV or JSONL with one text per row. Only the text column (`submitted_text`, else `text`) and an optional key (`run_id` if present, or `--id-column`) are read. Labels are never read, so it works the same on a real visitor's text with no run behind it.
- **Output**, in the gitignored `data/predictions/2c/`, named `<input>-<head>-texts.csv` and `<input>-<head>-ids.csv`:
  - texts: one row per text, with:
    - `id`
    - `p_<model>` for each model of the head, summing to 1
    - `provider_<name>` from the provider head, summing to 1 (with `--head sun`, the sum over that provider's models)
    - `top_model` and `top_provider`. The two heads are separate, so `top_provider` can differ from the provider of `top_model`; for the provider, trust `top_provider`.
  - ids, only when there is a key: one row per key (a run, in our tests). It holds the mean of its texts' vectors, `n_texts`, `top_model` and `top_provider`.
- Scoring against `label_model` is a separate step that joins on `id`.

```python
from model.sun_classifier.classify import SHORT_HEAD, SunChatClassifier

clf = SunChatClassifier(head=SHORT_HEAD)  # head=None for the sun head
clf.predict_proba(["Two sentences written by an agent."])  # one p_<model> column per model
```

## Faithfulness to the original

- **Bidirectional attention** as in LLM2Vec: every layer's `is_causal` is off, and an all-zero attention mask is passed. `SunChatClassifier.is_bidirectional()` checks it on every evaluation run.
- **LoRA merge** uses peft's formula with scale `lora_alpha / r = 32 / 16`.
- **Tokenizer.** transformers 4.57 warns about an "incorrect regex pattern" (a Mistral bug). The stored pattern is Llama 3's own, and the suggested fix would change how most texts are split, so it is explicitly not applied.
- **One text at a time.** LLM2Vec's mean pooling for plain text averages every position, padding included; with no padding this is exact.
- **Chat wrapper.** LLM2Vec wraps text in a Llama 3 user turn only when the config names `meta-llama/Meta-Llama-3-8B-Instruct`. Whether that held in their training run can't be read from the code, so `evaluate.py --both-wrappers` measured both. The wrapper reproduces their accuracy (see Results) and is the default; `SunChatClassifier(chat_wrapper=False)` turns it off.
- **Test split** reproduced from their `classification.py` (`train_test_split(train_size=10_000, test_size=1_000, seed=42)` per model).

## Results

### Backbone conversion (sun head)

Checked on 1,000 of Sun et al.'s held-out test answers (200 per model, `evaluate.py --per-class 200 --both-wrappers`), on an RTX 3050 Laptop GPU (6 GB):

| Setting | Accuracy | ChatGPT | Claude | Grok | Gemini | DeepSeek |
|---|---|---|---|---|---|---|
| Published, full precision | 97.1% | | | | | |
| 4-bit, chat wrapper (default) | 96.1% | 193/200 | 194/200 | 192/200 | 198/200 | 184/200 |
| 4-bit, plain text | 94.5% | 184/200 | 192/200 | 186/200 | 198/200 | 185/200 |

- 4-bit costs about one point of accuracy, so the conversion is faithful.
- The chat wrapper is closer to their number, which suggests their training wrapped texts as a Llama 3 user turn.
- 0.68 seconds per text, 4.56 GiB peak GPU memory, 4.3 GiB on disk.

### Short head

Training: 1,200 two-sentence summaries, 200 per model (100 practice pages, two conditions). Chance is 16.7% for the model and 50% for the provider.

| Test | n | Provider (provider head) | Provider (sum of model head) | Exact model |
|---|---|---|---|---|
| Held-out practice pages (last 25 pages) | 300 | 80.0% | 78.3% | 34.7% |
| **2b, our site pages** | 100 | **93.0%** | 77.0% | 34.0% |
| 2b, `default` system prompt | 50 | 88.0% | 70.0% | 30.0% |
| 2b, `minimal` system prompt | 50 | 98.0% | 84.0% | 38.0% |

On 2b's corpus, per model (true model in rows; 2b has no gpt-6.1-sol yet):

| True model | Provider right (provider head) | Exact model right | Most often called |
|---|---|---|---|
| claude-opus-5-5 | 19/20 | 1/20 | claude-haiku-5-5 (10) |
| claude-sonnet-5-5 | 19/20 | 1/20 | claude-haiku-5-5 (16) |
| claude-haiku-5-5 | 17/20 | 17/20 | |
| gpt-6-astra | 18/20 | 0/20 | gpt-6.1-sol (10), claude-haiku-5-5 (10) |
| gpt-6-luna | 20/20 | 15/20 | |

- The provider is named 93% of the time on our real site pages, from two sentences. The six-way head alone gets 77%: its errors are mostly Astra called Haiku.
- Tiers are weak. Only the small models stand out (Haiku 17/20, Luna 15/20). Opus and Sonnet are mostly called Haiku, and on held-out pages Astra and Sol are mostly confused with each other.
- The regularization strength hardly matters for the six-way head (held-out provider 76–79% for C from 0.001 to 1). The provider head's C = 0.001 was chosen on the held-out pages, not on 2b.
- Earlier heads, for comparison on the same 2b corpus:
  - Sun et al.'s head can't name our models; the head trained on generic UltraChat questions (92.8% provider on its own held-out questions) got only 43% provider and 27% exact model on 2b. The task, not the models, made the difference.
- Caveats:
  - 2b's corpus is small (100 summaries, 5 models), so one model's 20 texts move a row by 5 points each.
  - Harness and provider are confounded (see above).
  - Held-out practice pages score lower than our site pages. The practice pages are paragraphs from chat answers on any topic, and the held-out set includes gpt-6.1-sol, the hardest model, which 2b lacks.
