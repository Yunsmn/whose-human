"""Collect short two-sentence answers from current models, through the coding agents on this machine.

    python -m model.sun_classifier.agent_answers claude-haiku-5-5 --n 400

Training data for the new 2c head. Questions are generic UltraChat prompts taken from the non-test
part of Sun et al.'s data (data/corpus/short/prompts.json), never our site pages, which stay the
test. Each agent call answers a batch of questions in exactly two sentences each, and returns JSON.

Anthropic models run through Anthropic's coding agent CLI (print mode), OpenAI models through the Codex CLI
(`codex exec`, read-only sandbox). Both run in an empty temporary folder, so they see no files.
The text therefore carries each harness's system prompt; that is the agent text 2c is meant to
read, but harness and provider are confounded (every Anthropic answer comes from Anthropic's CLI).

Answers are appended to data/corpus/short/<model>.jsonl (gitignored); re-running skips questions
that already have an answer.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PROMPTS = Path("data/corpus/short/prompts.json")
OUT_DIR = Path("data/corpus/short")
BATCH = 20

# model id -> (provider, harness). Tiers line up: Opus/Astra, Sonnet/Sol, Haiku/Luna.
MODELS = {
    "claude-opus-5-5": ("anthropic", "anthropic-cli"),
    "claude-sonnet-5-5": ("anthropic", "anthropic-cli"),
    "claude-haiku-5-5": ("anthropic", "anthropic-cli"),
    "gpt-6-astra": ("openai", "codex"),
    "gpt-6.1-sol": ("openai", "codex"),
    "gpt-6-luna": ("openai", "codex"),
}

ANTHROPIC_CLI = "claude"  # executable name of Anthropic's coding agent CLI

INSTRUCTION = (
    "Answer each question below independently, in exactly two sentences of plain prose "
    "(no lists, no markdown). Reply with only a JSON object mapping each question number to its answer."
)


def build_prompt(questions: list[str]) -> str:
    lines = [f"{number}. {question}" for number, question in enumerate(questions, start=1)]
    return INSTRUCTION + "\n" + "\n".join(lines)


def parse_reply(reply: str, n_questions: int) -> dict[int, str]:
    """Answers by question number (1-based) from the last JSON object in the reply."""
    for match in reversed(list(re.finditer(r"\{.*\}", reply, flags=re.DOTALL))):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        answers = {}
        for key, value in data.items():
            if str(key).strip().isdigit() and isinstance(value, str) and value.strip():
                number = int(str(key).strip())
                if 1 <= number <= n_questions:
                    answers[number] = " ".join(value.split())
        return answers
    return {}


def command(model: str, prompt: str) -> list[str]:
    harness = MODELS[model][1]
    if harness == "anthropic-cli":
        return [
            shutil.which(ANTHROPIC_CLI) or ANTHROPIC_CLI,
            "-p",
            "--model",
            model,
            "--max-turns",
            "1",
            prompt,
        ]
    return [
        shutil.which("codex") or "codex", "exec", "-m", model,
        "--sandbox", "read-only", "--skip-git-repo-check", prompt,
    ]  # fmt: skip


def done_indices(path: Path) -> set[int]:
    if not path.exists():
        return set()
    return {json.loads(line)["prompt_idx"] for line in path.read_text(encoding="utf-8").splitlines() if line}


def collect(model: str, n: int, out_dir: Path = OUT_DIR, timeout: int = 600) -> int:
    provider, harness = MODELS[model]
    prompts = json.loads(PROMPTS.read_text(encoding="utf-8"))[:n]
    out = out_dir / f"{model}.jsonl"
    todo = [i for i in range(len(prompts)) if i not in done_indices(out)]
    written = 0
    with tempfile.TemporaryDirectory() as workdir:
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            try:
                result = subprocess.run(
                    command(model, build_prompt([prompts[i] for i in batch])),
                    cwd=workdir, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                print(f"{model}: batch at {batch[0]} timed out", flush=True)
                continue
            answers = parse_reply(result.stdout, len(batch))
            with out.open("a", encoding="utf-8") as stream:
                for number, idx in enumerate(batch, start=1):
                    if number in answers:
                        row = {"prompt_idx": idx, "model": model, "provider": provider, "harness": harness}
                        row |= {"prompt": prompts[idx], "text": answers[number]}
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                        written += 1
            print(f"{model}: {len(answers)}/{len(batch)} answers, batch at {batch[0]}", flush=True)
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--n", type=int, default=400, help="number of questions (from the start of the list)")
    args = parser.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{args.model}: wrote {collect(args.model, args.n)} answers")


if __name__ == "__main__":
    main()
