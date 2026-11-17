# Track 2: Model identification

Owner of 2b (API reference corpus): C. 2a (agent text): A. 2c (classifier): B. See `TEAM.md`.

## 2a: Visible input page and agent text (`agent_text.py`)

Member A runs 2a during the same controlled sessions as 1a. The fixed task sends the agent directly to a visible
`input.html` page, asks for exactly two summary sentences, and requests submission through the form POST or the
page's visible `submit?text=YOUR_SUMMARY` GET fallback. There is no hidden text or injected instruction.

Audit every planned run and optionally export the private labelled text corpus:

```sh
docker compose run --rm --entrypoint python checks -m model.agent_text data/logs \
  --manifest runs/a.csv \
  --output data/corpus/agent/member-a-agent-text.csv
```

The terminal output contains only aggregate counts for POST submitted, GET submitted, placeholder submitted,
fetched but not submitted, other observed traffic, and no observed request. A literal `YOUR_SUMMARY` submission is
reported as `placeholder_submitted` and excluded from the CSV. The CSV contains only usable submitted text and
ground-truth labels for 2c; keep it in the gitignored `data/` directory or approved private storage. See
[`harness/member_a_1a_2a_protocol.md`](../harness/member_a_1a_2a_protocol.md) for the complete collection protocol.

## 2b: API reference corpus (`api_corpus.py`)

Sends the same page text and visible instruction that agents see on our input page (`infra/sites/<site>/input.html`) **directly to model APIs**, with no agent in between. The replies are the reference for H2: does an agent harness's system prompt shift the text enough to hurt a classifier trained on raw API output?

### Collecting through the CLIs (no API keys)

`cli_corpus.py` collects reference text using the locally installed Claude Code and Codex CLIs. This avoids provider API keys and uses the same models through team members' existing subscriptions. It runs each model and prompt under two conditions: `default` keeps the CLI's own system prompt; `minimal` replaces it with `You are a helpful assistant.` This directly measures H2, the effect of the harness system prompt on generated text.

The collector sends this exact visible instruction after each page article: `Summarize this page in two sentences. Reply with only your summary.` It must run natively on the host where the CLIs and their logins are installed, not in Docker. Start with a plan preview, then a small capped collection:

```sh
python3 -m model.cli_corpus --dry-run
python3 -m model.cli_corpus --max-requests 4
```

Rows append to `data/corpus/cli/corpus-<YYYYMMDD>.jsonl` (gitignored). Claude Code's `--system-prompt` still prepends `You are a Claude agent, built on Anthropic's Claude Agent SDK.`, so its `minimal` condition is not raw API. Codex's `model_instructions_file` replaces its base instructions, while tool definitions and environment context remain; measured input usage was about 11.8k tokens in minimal versus 15.2k by default. Codex does not report the response model, and it sometimes takes an extra step (a command or other item) before answering; such rows have `stop_reason` `end_turn+<n>_items` and can be filtered out. Gemini is not wired yet.

2c can read these rows with `load_corpus("data/corpus/cli")` (`label_model` is the row's `name`), or use `predict.py` with `--id-column id`.

The API collector below remains available, but needs provider API keys and is not currently used for collection.

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
