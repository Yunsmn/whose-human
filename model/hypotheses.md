# Hypotheses

Record each finished experiment here before starting the next one (template in AGENTS.md).

## H1: Two short sentences suffice to identify the provider with useful accuracy.
Status: supported for the provider, through its agent harness, on our two site pages (120 summaries, 24 model/page/condition groups; second test below); needs more pages. Open for the exact model

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
- Training: 1,200 two-sentence summaries of 100 practice pages, collected the way 2b collects them (same CLI commands and instruction, `default` and `minimal` conditions), 200 per model. The practice pages are model-written paragraphs from Sun et al.'s data; our site pages are written by us.
- Test: 2b's 120 summaries of our two site pages (6 models, 20 each), in 24 model/page/condition groups of 5 near-paraphrase samples. No site page is in training.
Result:
- Provider: 89.2% (provider head; chance 50%). 95% interval 82–94% if texts were independent, 81–96% resampling the 24 groups. 72.5% from summing the six-way head. Weakest: gpt-6.1-sol, 14/20 (4 groups).
- Exact model: 35.8% (chance 16.7%). Haiku (17/20), Luna (15/20) and Sol (9/20) are recognized; Opus and Sonnet are mostly called Haiku.
- The head trained on generic questions got 43% provider on the first 100 of these summaries, so matching the task mattered more than more data.
Conclusion: supported for the provider, through its agent harness (every text comes through Anthropic's coding agent CLI or the Codex CLI), on two site pages; needs more pages before it is general. Not supported for the exact model, except the small tiers.
Next:
- Rerun when 2b has more pages (only two site pages so far).
- Test on 2a's agent text.

## H2: The harness's system prompt shifts the text enough to hurt a classifier trained on raw API output.
Status: weakly supported for the full agent session (first test below, small n); not tested against raw API output, which we don't have
Observation (2026-11-21, not a test of H2 yet): with the H1 heads above, which are trained on both conditions, 2b's `minimal` summaries are easier than `default` ones: provider 93.3% against 85.0%, exact model 38.3% against 33.3% (n = 60 each). That is 5 texts on the provider, from only 12 groups per condition, so suggestive only. It fits a harness reading: changing the harness's system prompt shifts the text.

Date: 2026-11-24
Run ids: every agent run with a submitted summary: B's b-claude-{wf,sh}-*, b-claude-sh-{haiku,sonnet,opus}-* and b-codex-h-luna-site{1,2}-00{1,2,3} (Windows); C's c-claude-* and c-codex-h-001 (Linux). Text from `model.agent_text` (private, data/corpus/agent/), placeholders excluded.
Setup:
- Classifier: the H1 heads unchanged (`--head short`), trained on CLI summaries of practice pages in `default` and `minimal` conditions, not on raw API output.
- Test: 53 summaries that agents submitted on our two site pages during their own sessions (52 runs): Claude Code 46 (Haiku 6, Sonnet 6, Opus 34), Codex CLI 7 (all gpt-6-luna; the ChatGPT login used here doesn't offer gpt-6-astra or gpt-6.1-sol, so 8 attempts with them failed before running and are not recorded).
- Reference: 2b's 120 CLI summaries of the same two pages (H1, second test). Both come through the same CLIs; the difference is the agent session (task framing, tool calls, the agent's own answer) against one direct CLI call.
Result:
- Provider: 79.2% (42/53; 95% interval 67–88%) on agent text, against 89.2% (107/120; 82–94%) on 2b. Claude Code 82.6% (38/46) against 91.7% (55/60) for the Claude models on 2b. Codex 4/7.
- Exact model: 13.2% (7/53) against 35.8%. Opus is mostly called Haiku (1/34 exact), as on 2b; Sonnet 0/6; Haiku 5/6.
- gpt-6-luna drops most: 15/20 exact on 2b, 1/7 on agent text, and only 4/7 on the provider (the provider head's p_anthropic ranges from 0.04 to 0.91 on these 7).
- Agent summaries are longer: median 44 words, against 35 on 2b.
Conclusion: weakly supported. Text written inside an agent session is harder for a head trained on direct CLI output: about 10 points on the provider and 23 on the exact model, with the largest drop for the GPT model. The intervals overlap, and the GPT side is 7 texts from one model, so this is a direction, not a result.
Next:
- More Codex runs, with a login that offers gpt-6-astra and gpt-6.1-sol, for all three GPT tiers.
- Train or adapt the head on agent-session text (a held-out split of these runs) and check whether the gap closes.
- Raw API output, if we get API access, to test H2 as written.
