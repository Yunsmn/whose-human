"""Collect Track 2b reference text through locally installed coding-agent CLIs."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from model.api_corpus import (
    ROOT,
    ModelSpec,
    Prompt,
    Reply,
    build_prompts,
    is_refusal,
    load_config,
    make_plan,
    prompt_id,
)

DIRECT_INSTRUCTION = "Summarize this page in two sentences. Reply with only your summary."
MINIMAL_SYSTEM_PROMPT = "You are a helpful assistant."
Runner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]


class CliError(ValueError):
    """An agent CLI failed to produce a usable reply."""


class PreflightError(ValueError):
    """A required local CLI is unavailable or unsupported."""


def cli_prompt(prompt: Prompt) -> Prompt:
    article = prompt.user_message.rsplit("\n\n", 1)[0]
    message = f"{article}\n\n{DIRECT_INSTRUCTION}"
    return Prompt(prompt.site, prompt_id(prompt.site, message), message)


def claude_command(executable: str, model: str, prompt: str, condition: str) -> list[str]:
    argv = [
        executable,
        "-p",
        "--model",
        model,
        "--tools",
        "",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--output-format",
        "json",
    ]
    if condition == "minimal":
        argv.extend(["--system-prompt", MINIMAL_SYSTEM_PROMPT])
    return [*argv, prompt]


def codex_command(executable: str, model: str, prompt: str, workdir: Path, condition: str) -> list[str]:
    argv = [
        executable,
        "exec",
        "-m",
        model,
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-rules",
        "--ignore-user-config",
        "-C",
        str(workdir),
        "--json",
    ]
    if condition == "minimal":
        path = workdir / "minimal-system-prompt.txt"
        path.write_text(MINIMAL_SYSTEM_PROMPT, encoding="utf-8")
        argv.extend(["-c", f'model_instructions_file="{path}"'])
    return [*argv, prompt]


def parse_claude(stdout: str) -> Reply:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CliError(f"unparsable Claude stdout: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError("unparsable Claude stdout: expected one JSON object")
    if data.get("is_error"):
        raise CliError(str(data.get("result") or data.get("subtype") or "Claude returned an error"))
    usage = data.get("modelUsage") or {}
    keys = sorted(usage) if isinstance(usage, dict) else []
    response_model = keys[0] if len(keys) == 1 else ",".join(keys) or None
    input_fields = ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
    input_tokens = sum(v.get(f, 0) or 0 for v in usage.values() for f in input_fields) if keys else None
    output_tokens = sum(v.get("outputTokens", 0) or 0 for v in usage.values()) if keys else None
    return Reply(
        data.get("result"),
        data.get("stop_reason"),
        response_model,
        input_tokens,
        output_tokens,
        data.get("session_id"),
    )


def parse_codex(stdout: str) -> Reply:
    thread_id = stop_reason = None
    text = None
    input_tokens = output_tokens = None
    extra_items = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        elif event_type in {"error", "turn.failed"}:
            raise CliError(str(event.get("message") or event.get("error") or event))
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                text = item.get("text")
            else:
                extra_items += 1
        elif event_type == "turn.completed":
            usage = event.get("usage") or {}
            input_tokens = (input_tokens or 0) + (usage.get("input_tokens") or 0)
            output_tokens = (output_tokens or 0) + (usage.get("output_tokens") or 0)
    if text is None:
        raise CliError("Codex returned no agent_message")
    # Non-message items (commands, reasoning, file reads) mean the reply was not a single plain answer.
    stop_reason = "end_turn" if not extra_items else f"end_turn+{extra_items}_items"
    return Reply(text, stop_reason, None, input_tokens, output_tokens, thread_id)


def _stderr_tail(stderr: str) -> str:
    tail = " ".join(stderr.split())[-500:]
    return f"; stderr: {tail}" if tail else ""


def _invoke(runner: Runner, argv: list[str], workdir: Path, timeout: int) -> Reply:
    try:
        result = runner(argv, workdir, timeout)
    except subprocess.TimeoutExpired as exc:
        raise CliError(f"timed out after {timeout}s") from exc
    if result.returncode:
        raise CliError(f"CLI exited with status {result.returncode}{_stderr_tail(result.stderr or '')}")
    try:
        return parse_claude(result.stdout) if Path(argv[0]).name == "claude" else parse_codex(result.stdout)
    except CliError as exc:
        raise CliError(f"{exc}{_stderr_tail(result.stderr or '')}") from exc


def _default_runner(argv: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def resolve_preflight(
    models: list[ModelSpec] | tuple[ModelSpec, ...], which: Callable[[str], str | None] = shutil.which
) -> dict[str, str]:
    enabled = [model for model in models if model.enabled]
    if any(model.provider == "google" for model in enabled):
        raise PreflightError("Gemini CLI collector not implemented")
    providers = {model.provider for model in enabled}
    unknown = providers - {"anthropic", "openai"}
    if unknown:
        raise PreflightError(f"unsupported CLI provider: {', '.join(sorted(unknown))}")
    executables = {"anthropic": "claude", "openai": "codex"}
    result = {}
    for provider in sorted(providers):
        executable = executables[provider]
        resolved = which(executable)
        if not resolved:
            raise PreflightError(f"required CLI {executable!r} for {provider} was not found on PATH")
        result[provider] = resolved
    return result


def cli_version(executable: str, runner: Runner) -> str:
    result = runner([executable, "--version"], Path.cwd(), 30)
    if result.returncode:
        raise PreflightError(f"cannot read {executable} version{_stderr_tail(result.stderr or '')}")
    return result.stdout.splitlines()[0] if result.stdout.splitlines() else "unknown"


def _completed(out_dir: Path) -> set[tuple[str, str, str, int]]:
    done: set[tuple[str, str, str, int]] = set()
    if not out_dir.exists():
        return done
    for path in sorted(out_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as source:
            for line_no, line in enumerate(source, 1):
                try:
                    row = json.loads(line)
                    if row.get("error") is None:
                        done.add((row["name"], row["prompt_id"], row["condition"], row["sample_idx"]))
                except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
                    print(f"{path}:{line_no}: malformed line; continuing", file=sys.stderr)
    return done


def _collect_one(
    model: ModelSpec,
    prompt: Prompt,
    sample_idx: int,
    condition: str,
    runner: Runner,
    executable_map: dict[str, str],
    version_map: dict[str, str],
    timeout: int,
) -> dict[str, object]:
    start = time.monotonic()
    text = stop = response_model = raw_id = error = None
    input_tokens = output_tokens = None
    try:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            message = cli_prompt(prompt).user_message
            if model.provider == "anthropic":
                argv = claude_command(executable_map[model.provider], model.model, message, condition)
            else:
                argv = codex_command(executable_map[model.provider], model.model, message, workdir, condition)
            reply = _invoke(runner, argv, workdir, timeout)
        text, stop, response_model = reply.text, reply.stop_reason, reply.response_model
        input_tokens, output_tokens, raw_id = reply.input_tokens, reply.output_tokens, reply.raw_id
    except (CliError, OSError, KeyError) as exc:
        error = str(exc)
    return {
        "id": f"{model.name}:{prompt.prompt_id}:{condition}:{sample_idx}",
        "ts": datetime.now(UTC).isoformat(),
        "name": model.name,
        "provider": model.provider,
        "harness": "claude-code" if model.provider == "anthropic" else "codex",
        "cli_version": version_map[model.provider],
        "condition": condition,
        "requested_model": model.model,
        "response_model": response_model,
        "site": prompt.site,
        "prompt_id": prompt.prompt_id,
        "sample_idx": sample_idx,
        "text": text,
        "stop_reason": stop,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_s": round(time.monotonic() - start, 3),
        "raw_id": raw_id,
        "error": error,
    }


def run_collection(
    models: list[ModelSpec] | tuple[ModelSpec, ...],
    prompts: list[Prompt],
    samples: int,
    conditions: list[str],
    out_dir: Path,
    runner: Runner = _default_runner,
    *,
    executable_map: dict[str, str] | None = None,
    version_map: dict[str, str] | None = None,
    timeout: int = 300,
    max_requests: int = 200,
) -> dict[str, dict[str, int]]:
    executable_map = executable_map or resolve_preflight(models)
    version_map = version_map or {p: cli_version(executable_map[p], runner) for p in executable_map}
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"corpus-{datetime.now(UTC):%Y%m%d}.jsonl"
    completed = _completed(out_dir)
    stats: dict[str, dict[str, int]] = defaultdict(lambda: dict(done=0, skipped=0, errors=0, refusals=0))
    attempted = 0
    for model, prompt, sample_idx in make_plan(models, prompts, samples):
        for condition in conditions:
            counts = stats[model.name]
            key = (model.name, prompt.prompt_id, condition, sample_idx)
            if key in completed:
                counts["skipped"] += 1
                continue
            if attempted >= max_requests:
                break
            attempted += 1
            row = _collect_one(
                model, prompt, sample_idx, condition, runner, executable_map, version_map, timeout
            )
            if row["error"] is None:
                counts["done"] += 1
                if is_refusal(row["stop_reason"]):
                    counts["refusals"] += 1
            else:
                counts["errors"] += 1
            with target.open("a", encoding="utf-8") as output:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
        if attempted >= max_requests:
            break
    for model in models:
        if model.enabled:
            print(
                f"{model.name}: done={stats[model.name]['done']} skipped={stats[model.name]['skipped']} "
                f"errors={stats[model.name]['errors']} refusals={stats[model.name]['refusals']}"
            )
    stats["_run"] = {
        "attempted": attempted,
        "errors": sum(s["errors"] for n, s in stats.items() if n != "_run"),
    }
    return dict(stats)


def _dry_run(
    models: list[ModelSpec],
    prompts: list[Prompt],
    samples: int,
    conditions: list[str],
    executables: dict[str, str],
) -> None:
    for prompt in prompts:
        converted = cli_prompt(prompt)
        print(f"{prompt.site} prompt_id={converted.prompt_id} message={converted.user_message}")
    for provider, executable in executables.items():
        model = next(m for m in models if m.enabled and m.provider == provider)
        for condition in conditions:
            with tempfile.TemporaryDirectory() as temporary:
                workdir = Path(temporary)
                if provider == "anthropic":
                    argv = claude_command(executable, model.model, "<PROMPT>", condition)
                else:
                    argv = codex_command(executable, model.model, "<PROMPT>", workdir, condition)
                print(f"{provider}/{condition} argv: {argv}")
    for model in models:
        if model.enabled:
            print(f"{model.name} x condition: {len(prompts) * samples} requests each")


def main(argv: list[str] | None = None, runner: Runner = _default_runner) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "model" / "corpus_models.toml")
    parser.add_argument("--sites", default="site1,site2")
    parser.add_argument("--samples", type=int)
    parser.add_argument("--conditions", default="default,minimal")
    parser.add_argument("--models")
    parser.add_argument("--max-requests", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "corpus" / "cli")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        models = [
            m for m in config.models if m.enabled and (not args.models or m.name in args.models.split(","))
        ]
        conditions = args.conditions.split(",")
        if not models:
            raise PreflightError("no enabled models selected")
        if not conditions or any(c not in {"default", "minimal"} for c in conditions):
            raise PreflightError("conditions must be default,minimal")
        prompts = [cli_prompt(prompt) for prompt in build_prompts(args.sites.split(","))]
        executables = resolve_preflight(models)
        if args.dry_run:
            _dry_run(models, prompts, args.samples or config.samples_per_prompt, conditions, executables)
            return 0
        versions = {provider: cli_version(executable, runner) for provider, executable in executables.items()}
        stats = run_collection(
            models,
            prompts,
            args.samples or config.samples_per_prompt,
            conditions,
            args.out,
            runner,
            executable_map=executables,
            version_map=versions,
            timeout=args.timeout,
            max_requests=args.max_requests,
        )
        return int(stats["_run"]["errors"] > 0)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
