# 2c baseline: Sun et al.'s classifier in 4-bit

Owner: B. An off-the-shelf model attribution baseline for Track 2: the published chat API classifier of Sun et al., "Idiosyncrasies in Large Language Models" (ICML 2025; code [locuslab/llm-idiosyncrasies](https://github.com/locuslab/llm-idiosyncrasies), MIT license; weights [Yida/classifier_chat](https://huggingface.co/Yida/classifier_chat)), converted to 4-bit so it runs on a 6 GB GPU. No training on our side.

## What it can and cannot answer

It outputs a probability for five labels, each trained on one 2024 model:

| Label | Provider | Trained on |
|---|---|---|
| ChatGPT | openai | gpt-4o-2024-08-06 |
| Claude | anthropic | claude-3-5-sonnet-20241022 |
| Grok | xai | grok-beta |
| Gemini | google | gemini-1.5-pro-002 |
| DeepSeek | deepseek | deepseek-chat |

- Text from a newer model of one of these providers can only be mapped to the provider's 2024 label. Whether that works is an open question, and our measurement of it is a result.
- Models from other providers are forced into one of the five labels.
- It was trained on long chat answers (UltraChat prompts, up to 1,024 tokens), not two-sentence summaries written through an agent.

## Architecture

LLM2Vec (Llama-3-8B-Instruct with bidirectional attention), with Sun et al.'s LoRA adapters merged in, then mean pooling over all tokens into one 4,096-number vector, then a linear head with five outputs and a softmax. The head (42 KB) is their trained part; everything else is the Llama 3 backbone.

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

## Running

From the repository root, with the separate environment:

```sh
python -m model.sun_classifier.convert merge        # LoRA merged into bf16 shards (CPU, about 15 GB disk)
python -m model.sun_classifier.convert quantize     # 4-bit model in data/models/sun_chat/nf4
python -m model.sun_classifier.evaluate --download  # Sun et al.'s published answers, for checking
python -m model.sun_classifier.evaluate --per-class 200
```

```python
from model.sun_classifier.classify import SunChatClassifier

clf = SunChatClassifier()
clf.predict_proba(["Two sentences written by an agent."])  # p_chatgpt, p_claude, p_grok, p_gemini, p_deepseek
```

## Faithfulness to the original

- **Bidirectional attention** as in LLM2Vec: every layer's `is_causal` is off, and an all-zero attention mask is passed. `SunChatClassifier.is_bidirectional()` checks it on every evaluation run.
- **LoRA merge** uses peft's formula with scale `lora_alpha / r = 32 / 16`.
- **Tokenizer.** transformers 4.57 warns about an "incorrect regex pattern" (a Mistral bug). The stored pattern is Llama 3's own, and the suggested fix would change how most texts are split, so it is explicitly not applied.
- **One text at a time.** LLM2Vec's mean pooling for plain text averages every position, padding included; with no padding this is exact.
- **Chat wrapper.** LLM2Vec wraps text in a Llama 3 user turn only when the config names `meta-llama/Meta-Llama-3-8B-Instruct`; whether that held in their training run can't be read from the code, so `evaluate.py --both-wrappers` measured both. The wrapper reproduces their accuracy (see Results) and is the default; `SunChatClassifier(chat_wrapper=False)` turns it off.
- **Test split** reproduced from their `classification.py` (`train_test_split(train_size=10_000, test_size=1_000, seed=42)` per model).

## Results

Checked on 1,000 of Sun et al.'s held-out test answers (200 per model, `evaluate.py --per-class 200 --both-wrappers`), on an RTX 3050 Laptop GPU (6 GB):

| Setting | Accuracy | ChatGPT | Claude | Grok | Gemini | DeepSeek |
|---|---|---|---|---|---|---|
| Published, full precision | 97.1% | | | | | |
| 4-bit, chat wrapper (default) | 96.1% | 193/200 | 194/200 | 192/200 | 198/200 | 184/200 |
| 4-bit, plain text | 94.5% | 184/200 | 192/200 | 186/200 | 198/200 | 185/200 |

- 4-bit costs about one point of accuracy, so the conversion is faithful.
- The chat wrapper is closer to their number, which suggests their training wrapped texts as a Llama 3 user turn.
- 0.68 seconds per text, 4.56 GiB peak GPU memory, 4.3 GiB on disk.
- These are long chat answers from 2024 models. Accuracy on short agent text and on newer models is still to be measured.
