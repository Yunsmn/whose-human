"""Collect privacy-minimised timing features from a local Ollama model.

The collector talks only to a loopback Ollama endpoint.  It stores counts and
timings, never prompts or generated text.  These measurements are an optional
machine-linking feature set; they are not proof of physical-device identity.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

BENCHMARK_VERSION = "local-llm-v1"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    context_words: int
    output_tokens: int


CASES = (
    BenchmarkCase("short-32", 128, 32),
    BenchmarkCase("short-128", 128, 128),
    BenchmarkCase("medium-128", 512, 128),
    BenchmarkCase("long-128", 2048, 128),
    BenchmarkCase("long-256", 2048, 256),
)


def validate_loopback_url(base_url: str) -> str:
    """Return a normalised local endpoint and refuse accidental remote collection."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("the local-model endpoint must use localhost or a loopback IP address")
    if parsed.query or parsed.fragment:
        raise ValueError("the local-model endpoint must not contain a query or fragment")
    return base_url.rstrip("/")


def benchmark_prompt(case: BenchmarkCase) -> str:
    """Build deterministic synthetic input without participant or repository data."""
    filler = " ".join(["neutral"] * case.context_words)
    return (
        f"Synthetic performance benchmark. Context: {filler}. "
        f"Return a numbered list of brief factual items, using at most {case.output_tokens} tokens."
    )


def _seconds(value) -> float | None:
    try:
        return float(value) / 1_000_000_000
    except (TypeError, ValueError):
        return None


def _rate(count, duration_s: float | None) -> float | None:
    try:
        return float(count) / duration_s if duration_s and duration_s > 0 else None
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def summarise_stream(
    messages: list[dict],
    arrival_times: list[float],
    started_at: float,
    finished_at: float,
    metadata: dict,
) -> dict:
    """Convert an Ollama JSONL stream into non-content timing features."""
    if len(messages) != len(arrival_times):
        raise ValueError("every stream message must have one arrival timestamp")
    content_times = [
        timestamp
        for message, timestamp in zip(messages, arrival_times, strict=True)
        if str(message.get("response", ""))
    ]
    intervals = [right - left for left, right in zip(content_times, content_times[1:], strict=False)]
    final = next((message for message in reversed(messages) if message.get("done")), {})
    prompt_duration = _seconds(final.get("prompt_eval_duration"))
    eval_duration = _seconds(final.get("eval_duration"))
    record = {
        **metadata,
        "benchmark_version": BENCHMARK_VERSION,
        "success": bool(final.get("done")),
        "wall_total_s": finished_at - started_at,
        "first_chunk_s": content_times[0] - started_at if content_times else None,
        "chunk_count": len(content_times),
        "chunk_interval_median_s": statistics.median(intervals) if intervals else None,
        "chunk_interval_p95_s": _percentile(intervals, 0.95),
        "chunk_interval_stdev_s": statistics.pstdev(intervals) if len(intervals) > 1 else None,
        "load_s": _seconds(final.get("load_duration")),
        "model_total_s": _seconds(final.get("total_duration")),
        "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_s": prompt_duration,
        "prompt_tokens_per_s": _rate(final.get("prompt_eval_count"), prompt_duration),
        "eval_count": final.get("eval_count"),
        "eval_s": eval_duration,
        "eval_tokens_per_s": _rate(final.get("eval_count"), eval_duration),
    }
    # Generated text and the synthetic prompt are intentionally never included.
    return record


def collect_case(
    base_url: str,
    model: str,
    case: BenchmarkCase,
    metadata: dict,
    timeout_s: float = 600,
) -> dict:
    """Run one streaming Ollama benchmark and return timing-only features."""
    endpoint = validate_loopback_url(base_url) + "/api/generate"
    payload = {
        "model": model,
        "prompt": benchmark_prompt(case),
        "stream": True,
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_predict": case.output_tokens,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    messages: list[dict] = []
    arrivals: list[float] = []
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - loopback enforced
        for raw_line in response:
            if not raw_line.strip():
                continue
            messages.append(json.loads(raw_line))
            arrivals.append(time.perf_counter())
    finished = time.perf_counter()
    return summarise_stream(messages, arrivals, started, finished, metadata)


def benchmark_plan(repetitions: int) -> list[tuple[BenchmarkCase, int]]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    return [(case, repeat) for case in CASES for repeat in range(repetitions)]


def append_jsonl(path: str | Path, record: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="print the fixed benchmark matrix without calling a model")
    plan.add_argument("--repetitions", type=int, default=5)

    collect = commands.add_parser("collect", help="collect timing-only metrics from local Ollama")
    collect.add_argument("--base-url", default="http://127.0.0.1:11434")
    collect.add_argument("--model", required=True)
    collect.add_argument("--agent", required=True)
    collect.add_argument("--machine", required=True, help="ground-truth machine alias, never a real hostname")
    collect.add_argument("--session-id", required=True)
    collect.add_argument("--repetitions", type=int, default=5)
    collect.add_argument("--quantization", default="unknown")
    collect.add_argument("--output", default="data/benchmarks/local-model.jsonl")
    collect.add_argument("--timeout", type=float, default=600)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        plan = benchmark_plan(args.repetitions)
        if args.command == "plan":
            print(json.dumps([asdict(case) | {"repeat": repeat} for case, repeat in plan], indent=2))
            return 0
        validate_loopback_url(args.base_url)
        for position, (case, repeat) in enumerate(plan, 1):
            metadata = {
                "session_id": args.session_id,
                "machine": args.machine,
                "agent": args.agent,
                "model": args.model,
                "engine": "ollama",
                "quantization": args.quantization,
                "case": case.name,
                "context_words_target": case.context_words,
                "output_tokens_target": case.output_tokens,
                "repeat": repeat,
                "phase": "first" if position == 1 else "warm",
            }
            record = collect_case(args.base_url, args.model, case, metadata, args.timeout)
            append_jsonl(args.output, record)
            print(
                f"{position}/{len(plan)} {case.name} repeat={repeat} "
                f"eval_tps={record.get('eval_tokens_per_s')}"
            )
        return 0
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        parser().error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
