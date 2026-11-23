"""Collect two-sentence page summaries from current models, exactly the way 2b collects them.

    python -m model.sun_classifier.summary_answers pages --n 100     # build the practice pages once
    python -m model.sun_classifier.summary_answers collect claude-haiku-5-5

Training data for the 2c head. The task matches 2b's: a short page followed by 2b's instruction
("Summarize this page in two sentences. Reply with only your summary."). Each call answers one
page, through the same CLI commands as model/cli_corpus.py (its own command builders and parsers),
in both conditions (`default` and `minimal` system prompt).

The practice pages are never our site pages, which stay the test. Each one is a single prose
paragraph of 30 to 80 words, taken from the non-test part of Sun et al.'s data
(data/corpus/sun_et_al), so topics vary widely.

Pages go to data/corpus/summaries/pages.json and answers to
data/corpus/summaries/<model>.jsonl (both gitignored; not part of the shared data repo).
Re-running skips (page, condition) pairs that already have an answer.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import tempfile
from pathlib import Path

from model.cli_corpus import (
    DIRECT_INSTRUCTION,
    CliError,
    claude_command,
    codex_command,
    parse_claude,
    parse_codex,
    resolve_preflight,
)
from model.sun_classifier import LABELS
from model.sun_classifier.prepare import their_test_indices

SUN_DIR = Path("data/corpus/sun_et_al")
OUT_DIR = Path("data/corpus/summaries")
PAGES = OUT_DIR / "pages.json"
CONDITIONS = ("default", "minimal")
MIN_WORDS, MAX_WORDS = 30, 80

# model id -> provider, the same six models as the head (model/corpus_models.toml).
MODELS = {
    "claude-opus-5-5": "anthropic",
    "claude-sonnet-5-5": "anthropic",
    "claude-haiku-5-5": "anthropic",
    "gpt-6-astra": "openai",
    "gpt-6.1-sol": "openai",
    "gpt-6-luna": "openai",
}


def prose_paragraphs(text: str) -> list[str]:
    """Plain prose paragraphs of MIN_WORDS to MAX_WORDS words (no lists, headings or code)."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(block.split())
        if not block or re.match(r"^([-*#>|`]|\d+[.)])", block) or "**" in block or "`" in block:
            continue
        if MIN_WORDS <= len(block.split()) <= MAX_WORDS and block[-1] in ".!?":
            paragraphs.append(block)
    return paragraphs


def build_pages(n: int, seed: int = 7, sun_dir: Path = SUN_DIR) -> list[str]:
    """`n` distinct paragraphs, drawn evenly from Sun et al.'s five models, outside their test split."""
    rng = random.Random(seed)
    per_model = -(-n // len(LABELS))
    pages: list[str] = []
    for label in LABELS:
        data = json.loads((sun_dir / f"{label}.json").read_text(encoding="utf-8"))
        test = set(their_test_indices(len(data)).tolist())
        candidates = [
            p for i in range(len(data)) if i not in test for p in prose_paragraphs(data[i][-1]["content"])
        ]
        rng.shuffle(candidates)
        pages += candidates[:per_model]
    rng.shuffle(pages)
    return list(dict.fromkeys(pages))[:n]


def page_prompt(page: str) -> str:
    return f"{page}\n\n{DIRECT_INSTRUCTION}"


def command(model: str, executable: str, prompt: str, workdir: Path, condition: str) -> list[str]:
    if MODELS[model] == "anthropic":
        return claude_command(executable, model, prompt, condition)
    return codex_command(executable, model, prompt, workdir, condition)


def answer(model: str, executable: str, prompt: str, condition: str, timeout: int = 300) -> str:
    """One CLI call, run like 2b's: empty temporary folder, stdin closed."""
    parse = parse_claude if MODELS[model] == "anthropic" else parse_codex
    with tempfile.TemporaryDirectory() as temporary:
        workdir = Path(temporary)
        argv = command(model, executable, prompt, workdir, condition)
        result = subprocess.run(
            argv, cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", timeout=timeout, check=False,
        )  # fmt: skip
    reply = parse(result.stdout)
    if result.returncode:
        raise CliError(f"CLI exited with status {result.returncode}")
    if not reply.text or not reply.text.strip():
        raise CliError("empty reply")
    return " ".join(reply.text.split())


def done_keys(path: Path) -> set[tuple[int, str]]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("text"):
            keys.add((row["prompt_idx"], row["condition"]))
    return keys


def collect(model: str, out_dir: Path = OUT_DIR, limit: int | None = None) -> tuple[int, int]:
    pages = json.loads(PAGES.read_text(encoding="utf-8"))[:limit]
    provider = MODELS[model]
    executable = resolve_preflight_for(provider)
    out = out_dir / f"{model}.jsonl"
    done = done_keys(out)
    ok = failed = 0
    for idx, page in enumerate(pages):
        for condition in CONDITIONS:
            if (idx, condition) in done:
                continue
            row = {
                "prompt_idx": idx,
                "model": model,
                "provider": provider,
                "condition": condition,
                "prompt": page,
            }
            try:
                row |= {"text": answer(model, executable, page_prompt(page), condition), "error": None}
                ok += 1
            except (CliError, OSError, subprocess.TimeoutExpired) as exc:
                row |= {"text": None, "error": str(exc)[:300]}
                failed += 1
            with out.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{model}: page {idx + 1}/{len(pages)}, {ok} answers, {failed} errors", flush=True)
    return ok, failed


def resolve_preflight_for(provider: str) -> str:
    from model.api_corpus import ModelSpec

    spec = ModelSpec(name="x", provider=provider, model="x", enabled=True)
    return resolve_preflight([spec])[provider]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    pages = commands.add_parser("pages", help="build the practice pages from Sun et al.'s data")
    pages.add_argument("--n", type=int, default=100)
    run = commands.add_parser("collect", help="collect one model's summaries of every page")
    run.add_argument("model", choices=sorted(MODELS))
    run.add_argument("--limit", type=int, help="only the first N pages (for a pilot)")
    args = parser.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.command == "pages":
        built = build_pages(args.n)
        PAGES.write_text(json.dumps(built, indent=0, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {len(built)} pages to {PAGES}")
    else:
        ok, failed = collect(args.model, limit=args.limit)
        print(f"{args.model}: {ok} answers, {failed} errors")


if __name__ == "__main__":
    main()
