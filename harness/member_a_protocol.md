# Member A run protocol (Tracks 1a and 2a)

This protocol collects the harness request fingerprint and the agent-written text in the same session. It
does not automate or wrap an agent: each agent must use its own built-in URL-fetch feature so the measured
traffic is genuinely that harness's traffic.

## Preconditions

1. Run only against the team's instrumented sites. For the local pilot, complete `infra/README.md` and start
   the server. For the local-versus-provider decision, use the shared VM because local Docker hides the
   client address.
2. Use a fictitious persona and a machine alias. Never put an IP address or real personal information in a
   manifest, note, screenshot, or commit.
3. Record the exact harness version and model version in the run notes when available. Keep agent settings at
   their defaults and start a fresh agent session for each run.

## Prepare and execute one run

Prepare the manifest row and print the fixed prompt:

```powershell
python -m harness.agent_runs prepare `
  --run-id a-codex-001 --agent codex-cli --model gpt-model `
  --persona persona-a1 --machine machine-a1 --network home `
  --site site1 --notes "harness version; clean session"
```

Paste the printed prompt into the named agent without editing it. Do not fall back to curl, wget, PowerShell,
or a custom script if the built-in fetch fails: the failure is a result. Preserve the private server log and
record the outcome in private experiment notes.

For the week-one pilot, run at least three clean sessions for each available harness on both sites. Include
Claude Code, Codex CLI, Cline, and Aider when installed. Repeat failed submissions once without changing the
prompt. Classify each session as `POST submitted`, `GET submitted`, `fetched but did not submit`, `fetch
failed`, or `no request observed`.

## Local-versus-provider check

On the shared VM, independently determine the public address of Member A's test network and keep it in a
private, gitignored file containing only that address. Then run:

```powershell
python -m harness.agent_runs audit data/logs --expected-ip-file data/member-a-ip.txt
```

The report deliberately prints no addresses:

- `local`: every observed request used the expected network address;
- `remote`: none did, evidence that fetching happened elsewhere;
- `mixed`: both appeared and the run needs manual inspection;
- `inconclusive`: no usable peer address, including all local-Docker runs.

Do not infer locality from a User-Agent. Require at least three independent runs per harness, and treat a
split result as mixed rather than selecting the majority.

## Completion criteria

- Every experimental URL has an `a-` run id and exactly one row in `runs/a.csv`.
- Raw JSONL remains in `data/` or the team's private storage.
- Submission behavior and locality are reported by harness with counts, not anecdotes.
- Results are added to `harness/hypotheses.md` and `model/hypotheses.md` only after the runs exist.
