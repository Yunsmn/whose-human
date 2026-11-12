"""Collect direct API reference text for Track 2b."""

from __future__ import annotations

import argparse
import hashlib
import html.parser
import importlib.metadata
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Reply:
    text: str | None
    stop_reason: str | None
    response_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    raw_id: str | None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    model: str
    enabled: bool


@dataclass(frozen=True)
class Config:
    models: tuple[ModelSpec, ...]
    samples_per_prompt: int
    max_output_tokens: int


@dataclass(frozen=True)
class Prompt:
    site: str
    prompt_id: str
    user_message: str


@dataclass(frozen=True)
class RunStats:
    done: int = 0
    skipped: int = 0
    errors: int = 0
    refusals: int = 0
    attempted: int = 0
    per_model: dict[str, dict[str, int]] | None = None


class Adapter(Protocol):
    def generate(self, model: str, user_message: str, max_output_tokens: int) -> Reply: ...


class PreflightError(ValueError):
    pass


class _VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []
        self.label_depth = 0
        self.article_depth = 0
        self.article_parts: list[str] = []
        self.labels: list[str] = []
        self._label_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"title", "script", "style"}:
            self.hidden += 1
        if tag == "article":
            self.article_depth += 1
        if tag == "label":
            self.label_depth += 1
            self._label_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
        if tag == "label" and self.label_depth:
            self.labels.append(" ".join(" ".join(self._label_parts).split()))
            self.label_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)
            if self.article_depth:
                self.article_parts.append(data)
        if self.label_depth:
            self._label_parts.append(data)


def extract_prompt(html: str, site: str) -> Prompt:
    parser = _VisibleTextParser()
    parser.feed(html)
    instruction = parser.labels[0] if parser.labels else ""
    if not parser.article_parts or not instruction:
        raise ValueError(f"{site}: page must contain article text and a visible instruction label")
    article = " ".join(" ".join(parser.article_parts).split())
    marker = "Summarize this page"
    if not article or not instruction.startswith(marker):
        raise ValueError(f"{site}: could not extract article text and instruction")
    message = f"{article}\n\n{instruction}"
    return Prompt(site, prompt_id(site, message), message)


def prompt_id(site: str, user_message: str) -> str:
    return f"{site}:{hashlib.sha256(user_message.encode('utf-8')).hexdigest()[:12]}"


def build_prompt(site: str, root: Path = ROOT) -> Prompt:
    path = root / "infra" / "sites" / site / "input.html"
    try:
        return extract_prompt(path.read_text(encoding="utf-8"), site)
    except OSError as exc:
        raise ValueError(f"cannot read input page for {site} at {path}: {exc}") from exc


def build_prompts(sites: list[str], root: Path = ROOT) -> list[Prompt]:
    return [build_prompt(site, root) for site in sites]


def load_config(path: Path = ROOT / "model" / "corpus_models.toml") -> Config:
    import tomllib

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        models = tuple(ModelSpec(**entry) for entry in data["models"])
        defaults = data["defaults"]
        return Config(models, int(defaults["samples_per_prompt"]), int(defaults["max_output_tokens"]))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid model config {path}: {exc}") from exc


def make_plan(
    models: tuple[ModelSpec, ...] | list[ModelSpec], prompts: list[Prompt], samples: int
) -> list[tuple[ModelSpec, Prompt, int]]:
    return [
        (model, prompt, idx)
        for model in models
        if model.enabled
        for prompt in prompts
        for idx in range(samples)
    ]


def validate_preflight(models: list[ModelSpec] | tuple[ModelSpec, ...], environ: dict[str, str]) -> list[str]:
    required = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "google": "GEMINI_API_KEY"}
    warnings: list[str] = []
    for model in models:
        if not model.enabled:
            continue
        if model.model == "FILL_ME":
            raise PreflightError(f"enabled model {model.name} still has model id FILL_ME")
        if model.provider == "anthropic" and not environ.get("ANTHROPIC_API_KEY"):
            warnings.append("WARN: ANTHROPIC_API_KEY is unset; an `ant auth login` profile may be used.")
        elif model.provider in required and not environ.get(required[model.provider]):
            raise PreflightError(
                f"enabled {model.provider} model {model.name} requires {required[model.provider]}"
            )
    return warnings


class AnthropicAdapter:
    def __init__(self) -> None:
        import anthropic

        # No temperature/thinking/fallbacks on purpose: defaults only, and a fallback would
        # silently change which model wrote the text (see model/README.md).
        self.client = anthropic.Anthropic()

    def generate(self, model: str, user_message: str, max_output_tokens: int) -> Reply:
        response = self.client.messages.create(
            model=model, max_tokens=max_output_tokens, messages=[{"role": "user", "content": user_message}]
        )
        return Reply(
            "".join(block.text for block in response.content if block.type == "text"),
            response.stop_reason,
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.id,
        )


class OpenAIAdapter:
    def __init__(self, openrouter: bool = False) -> None:
        import openai

        self.client = (
            openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
            if openrouter
            else openai.OpenAI()
        )

    def generate(self, model: str, user_message: str, max_output_tokens: int) -> Reply:
        response = self.client.chat.completions.create(
            model=model,
            max_completion_tokens=max_output_tokens,
            messages=[{"role": "user", "content": user_message}],
        )
        choice = response.choices[0]
        usage = response.usage
        return Reply(
            choice.message.content,
            choice.finish_reason,
            response.model,
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
            response.id,
        )


class OpenRouterAdapter(OpenAIAdapter):
    def __init__(self) -> None:
        super().__init__(openrouter=True)


class GoogleAdapter:
    def __init__(self) -> None:
        from google import genai

        self.client = genai.Client()

    def generate(self, model: str, user_message: str, max_output_tokens: int) -> Reply:
        response = self.client.models.generate_content(
            model=model, contents=user_message, config={"max_output_tokens": max_output_tokens}
        )
        candidate = response.candidates[0] if response.candidates else None
        usage = response.usage_metadata
        return Reply(
            response.text,
            str(candidate.finish_reason) if candidate else None,
            model,
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
            None,
        )


def _sdk_version(provider: str) -> str | None:
    package = {
        "anthropic": "anthropic",
        "openai": "openai",
        "openrouter": "openai",
        "google": "google-genai",
    }.get(provider)
    try:
        return importlib.metadata.version(package) if package else None
    except importlib.metadata.PackageNotFoundError:
        return None


def _completed(out_dir: Path) -> set[tuple[str, str, int]]:
    """Requests already answered without error. Malformed lines (e.g. from a killed run) are skipped."""
    done: set[tuple[str, str, int]] = set()
    for path in sorted(out_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"cannot read resume data from {path}: {exc}") from exc
        for number, line in enumerate(lines, start=1):
            try:
                row = json.loads(line)
                if row.get("error") is None:
                    done.add((row["name"], row["prompt_id"], int(row["sample_idx"])))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
                print(f"WARN: skipping malformed line {number} in {path}: {exc}", file=sys.stderr)
    return done


# Stop/finish reasons meaning the provider declined: Anthropic "refusal", OpenAI "content_filter",
# Google "SAFETY" / "PROHIBITED_CONTENT" / "BLOCKLIST" (enum names may carry a "FinishReason." prefix).
REFUSAL_MARKERS = ("refusal", "content_filter", "safety", "prohibited_content", "blocklist")


def is_refusal(stop_reason: str | None) -> bool:
    return bool(stop_reason) and any(marker in stop_reason.lower() for marker in REFUSAL_MARKERS)


def _adapter(provider: str) -> Adapter:
    factories = {
        "anthropic": AnthropicAdapter,
        "openai": OpenAIAdapter,
        "openrouter": OpenRouterAdapter,
        "google": GoogleAdapter,
    }
    try:
        return factories[provider]()
    except KeyError as exc:
        raise ValueError(f"unsupported provider {provider}") from exc


def _empty_row(spec: ModelSpec, prompt: Prompt, sample_idx: int) -> dict[str, object]:
    return {
        "corpus_id": uuid.uuid4().hex,
        "ts": time.time(),
        "name": spec.name,
        "provider": spec.provider,
        "model": spec.model,
        "response_model": None,
        "prompt_id": prompt.prompt_id,
        "site": prompt.site,
        "sample_idx": sample_idx,
        "text": None,
        "stop_reason": None,
        "input_tokens": None,
        "output_tokens": None,
        "latency_s": None,
        "raw_id": None,
        "error": None,
        "sdk_version": _sdk_version(spec.provider),
    }


def _request_row(adapter_for, spec: ModelSpec, prompt: Prompt, sample_idx: int, max_tokens: int) -> dict:
    """Run one request; errors are recorded in the row instead of stopping the run."""
    row = _empty_row(spec, prompt, sample_idx)
    start = time.perf_counter()
    try:
        reply = adapter_for(spec.provider).generate(spec.model, prompt.user_message, max_tokens)
        row.update(
            text=reply.text,
            stop_reason=reply.stop_reason,
            response_model=reply.response_model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            raw_id=reply.raw_id,
        )
    except Exception as exc:  # any SDK/network error: record it and continue with the next request
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["latency_s"] = time.perf_counter() - start
    return row


def _adapter_cache(adapter_factories: dict[str, object] | None):
    adapters: dict[str, Adapter] = {}
    factories = adapter_factories or {}

    def adapter_for(provider: str) -> Adapter:
        if provider not in adapters:
            factory = factories.get(provider)
            adapters[provider] = factory() if factory else _adapter(provider)
        return adapters[provider]

    return adapter_for


def _outcome(row: dict) -> str:
    if row["error"] is not None:
        return "errors"
    return "refusals" if is_refusal(row["stop_reason"]) else "done"


def run_requests(
    models: list[ModelSpec] | tuple[ModelSpec, ...],
    prompts: list[Prompt],
    samples: int,
    out_dir: Path,
    adapter_factories: dict[str, object] | None = None,
    max_requests: int = 200,
    max_output_tokens: int = 2048,
) -> RunStats:
    """Run the plan, appending one JSONL row per request; skips requests already answered."""
    out_dir.mkdir(parents=True, exist_ok=True)
    completed = _completed(out_dir)
    output = out_dir / f"corpus-{datetime.now(UTC).strftime('%Y%m%d')}.jsonl"
    adapter_for = _adapter_cache(adapter_factories)
    counts = {
        m.name: dict.fromkeys(("done", "skipped", "errors", "refusals"), 0) for m in models if m.enabled
    }
    attempted = 0
    try:
        with output.open("a", encoding="utf-8") as stream:
            for spec, prompt, sample_idx in make_plan(models, prompts, samples):
                if (spec.name, prompt.prompt_id, sample_idx) in completed:
                    counts[spec.name]["skipped"] += 1
                    continue
                if attempted >= max_requests:
                    break
                attempted += 1
                row = _request_row(adapter_for, spec, prompt, sample_idx, max_output_tokens)
                outcome = _outcome(row)
                counts[spec.name][outcome] += 1
                if outcome == "refusals":
                    counts[spec.name]["done"] += 1  # a refusal is a completed request
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
    except OSError as exc:
        raise ValueError(f"cannot append corpus output at {output}: {exc}") from exc
    total = {key: sum(c[key] for c in counts.values()) for key in ("done", "skipped", "errors", "refusals")}
    return RunStats(total["done"], total["skipped"], total["errors"], total["refusals"], attempted, counts)


def load_corpus(path: str | Path = "data/corpus/api"):
    import pandas as pd

    source = Path(path)
    files = [source] if source.is_file() else sorted(source.glob("*.jsonl"))
    rows: list[dict[str, object]] = []
    try:
        for file in files:
            rows.extend(
                json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()
            )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load corpus from {source}: {exc}") from exc
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame["label_model"] = []
        frame["label_provider"] = []
        return frame
    frame = frame.loc[frame["error"].isna()].copy()
    frame["label_model"] = frame["name"]
    frame["label_provider"] = frame["provider"]
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "model" / "corpus_models.toml")
    parser.add_argument("--sites", default="site1,site2")
    parser.add_argument("--samples", type=int)
    parser.add_argument("--max-requests", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("data/corpus/api"))
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        prompts = build_prompts([site.strip() for site in args.sites.split(",") if site.strip()])
        samples = args.samples if args.samples is not None else config.samples_per_prompt
        if samples < 1 or args.max_requests < 0:
            raise ValueError("samples must be positive and max-requests cannot be negative")
        plan = make_plan(config.models, prompts, samples)
        if args.dry_run:
            print(f"Plan: {len(plan)} requests")
            for prompt in prompts:
                print(f"\n{prompt.prompt_id}\n{prompt.user_message}")
            for model in config.models:
                if model.enabled:
                    print(f"{model.name}: {len(prompts) * samples} requests")
            return 0
        warnings = validate_preflight(config.models, dict(os.environ))
        for warning in warnings:
            print(warning, file=sys.stderr)
        stats = run_requests(
            config.models,
            prompts,
            samples,
            args.out,
            max_requests=args.max_requests,
            max_output_tokens=config.max_output_tokens,
        )
        print(
            f"done={stats.done} skipped={stats.skipped} errors={stats.errors} "
            f"refusals={stats.refusals} attempted={stats.attempted}"
        )
        for model, values in (stats.per_model or {}).items():
            print(f"{model}: {values}")
        return 0
    except PreflightError as exc:
        print(f"Pre-flight refused: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
