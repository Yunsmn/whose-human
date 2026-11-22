# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Two short sentences suffice to identify the provider with useful accuracy.
Status: supported for the provider on our site pages (second test below); open for the exact model

Date: 2026-11-16
Run ids: none (agent answers to generic questions, collected without our server; see model/sun_classifier/README.md)
Setup:
- Classifier: Sun et al.'s 4-bit backbone, frozen, with a new linear head (2c).
- Models: claude-opus-5-5, claude-sonnet-5-5 and claude-haiku-5-5 through Anthropic's coding agent CLI; gpt-6-astra, gpt-6.1-sol and gpt-6-luna through the Codex CLI.
- Data: 2,359 two-sentence answers to UltraChat questions. 100 questions (580 answers) are held out.
Result:
- Provider: 92.8% (chance 50%).
- Exact model: 48.3% (chance 16.7%).
- Tiers within a provider are mostly confused with each other.
Conclusion: supported for the provider on generic questions; inconclusive for the exact model.
Next:
- Test on 2b's API answers to the site pages once 2b collects the same six models.
- Test on 2a's agent text.
- Harness and provider are confounded here, which H2 has to untangle.

Date: 2026-11-21
Run ids: none (2b's CLI corpus of our site pages, data/corpus/cli; training summaries collected without our server)
Setup:
- Classifier: the same frozen backbone, with two new heads (six-way over the models, two-way over the providers).
- Training: 1,200 two-sentence summaries of 100 practice pages, collected the way 2b collects them (same CLI commands and instruction, `default` and `minimal` conditions), 200 per model.
- Test: 2b's 120 summaries of our site pages (6 models, 20 each). No site page is in training.
Result:
- Provider: 89.2% (provider head; chance 50%). 72.5% from summing the six-way head. Weakest: gpt-6.1-sol, 14/20.
- Exact model: 35.8% (chance 16.7%). Haiku (17/20), Luna (15/20) and Sol (9/20) are recognized; Opus and Sonnet are mostly called Haiku.
- The head trained on generic questions got 43% provider on the first 100 of these summaries, so matching the task mattered more than more data.
Conclusion: supported for the provider; not supported for the exact model, except the small tiers.
Next:
- Rerun when 2b has more pages (only two site pages so far).
- Test on 2a's agent text.

## H2: The harness's system prompt shifts the text enough to hurt a classifier trained on raw API output.
Status: open
Observation (2026-11-21, not a test of H2 yet): with the H1 heads above, which are trained on both conditions, 2b's `minimal` summaries are easier than `default` ones: provider 93.3% against 85.0%, exact model 38.3% against 33.3% (n = 60 each). That is 5 texts on the provider, so suggestive only.
