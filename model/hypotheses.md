# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Two short sentences suffice to identify the provider with useful accuracy.
Status: open (first test below; the test on our site pages waits for 2b's corpus)

Date: 2026-11-16
Run ids: none (agent answers to generic questions, collected without our server; see model/sun_classifier/README.md)
Setup:
- Classifier: Sun et al.'s 4-bit backbone, frozen, with a new linear head (2c).
- Models: claude-opus-5-5, claude-sonnet-5-5 and claude-haiku-5-5 through Claude Code; gpt-6-astra, gpt-6.1-sol and gpt-6-luna through the Codex CLI.
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

## H2: The harness's system prompt shifts the text enough to hurt a classifier trained on raw API output.
Status: open
