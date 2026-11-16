# Track 2: Model identification

Owner of 2b (API reference corpus): C. 2a (agent text): A. 2c (classifier): B. See `TEAM.md`.

## 2b: API reference corpus (`api_corpus.py`)

Sends the same page text and visible instruction that agents see on our input page (`infra/sites/<site>/input.html`) **directly to model APIs**, with no agent in between. The replies are the reference for H2: does an agent harness's system prompt shift the text enough to hurt a classifier trained on raw API output?

Design choices, so the corpus stays a clean reference:

- **The prompt is read from the live page.** If A edits a page, the prompt (and its `prompt_id`, a hash of the text) changes with it.
- **No system prompt.** That is the "raw API" condition.
- **No sampling parameters, no thinking settings.** Every provider runs with its defaults. Current Claude models reject `temperature` anyway.
- **No refusal fallbacks.** A fallback would silently answer with a different model and mislabel the text. Refusals are kept and counted (`stop_reason` `refusal` / `content_filter` / `SAFETY`).

### Running (Docker)

```sh
docker compose run --rm corpus --dry-run            # show the prompts and the request plan; no network
docker compose run --rm corpus --max-requests 10    # real run, capped
```

- **Keys:** put them in your `.env`, which is never committed: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`. Only the ones for enabled models are needed.
- **Models:** they're listed in `corpus_models.toml`: three tiers per provider, matching the classes 2c outputs. Claude Opus, Sonnet and Haiku 5.5 and OpenAI GPT-6 Astra, GPT-6.1 Sol and GPT-6 Luna are enabled. The Gemini (3.1 Pro, 3.8 Flash, 3.5 Flash-Lite) and open-weight entries are disabled `FILL_ME` placeholders: copy the exact model id from the provider's model list, then set `enabled = true`. The run refuses to start while an enabled entry still says `FILL_ME`.
- **Cost:** the default plan is 2 pages × 5 samples per model, so 10 short requests per model. That is cents, not dollars. `--max-requests` (default 200) is a hard cap per run.
- **Re-running is safe:** requests that already succeeded are skipped, so an interrupted run just continues.

### Output

Rows are appended to `data/corpus/api/corpus-<YYYYMMDD>.jsonl` (gitignored), one per request. Each row has the model label (`name`), provider, requested and returned model id, `prompt_id`, `sample_idx`, the text, `stop_reason`, token counts, latency, the response id, the SDK version, and `error` if the call failed.

For 2c, `load_corpus()` returns the successful rows as a DataFrame with `label_model` and `label_provider` columns:

```python
from model.api_corpus import load_corpus

corpus = load_corpus("data/corpus/api")
```
