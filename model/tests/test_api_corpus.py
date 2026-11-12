import json
import sys

import pytest

from model import api_corpus as corpus


def test_real_page_prompt_contains_article_and_instruction_only():
    prompt = corpus.build_prompt("site1")
    assert "Local websites can record ordinary connection" in prompt.user_message
    assert "Summarize this page in two sentences and submit it here" in prompt.user_message
    assert "YOUR_SUMMARY" not in prompt.user_message
    assert "Research Library response" not in prompt.user_message
    assert prompt.prompt_id == corpus.prompt_id("site1", prompt.user_message)


def test_prompt_id_is_stable():
    message = "article\n\ninstruction"
    assert corpus.prompt_id("site1", message) == corpus.prompt_id("site1", message)


def test_plan_size_is_enabled_models_times_prompts_times_samples(tmp_path):
    config = corpus.load_config()
    prompts = corpus.build_prompts(["site1", "site2"])
    plan = corpus.make_plan(config.models, prompts, 3)
    assert len(plan) == sum(m.enabled for m in config.models) * 2 * 3


def test_preflight_rejects_fill_me_and_missing_keys():
    model = corpus.ModelSpec("x", "openai", "FILL_ME", True)
    with pytest.raises(corpus.PreflightError, match="FILL_ME"):
        corpus.validate_preflight([model], {})
    model = corpus.ModelSpec("x", "openai", "configured", True)
    with pytest.raises(corpus.PreflightError, match="OPENAI_API_KEY"):
        corpus.validate_preflight([model], {})


def test_dry_run_does_not_import_provider_sdks(monkeypatch, capsys):
    for module in ("anthropic", "openai", "google.genai"):
        if module in sys.modules:
            pytest.skip(f"{module} was already imported")
    monkeypatch.setattr(sys, "argv", ["api_corpus", "--dry-run", "--sites", "site1"])
    assert corpus.main() == 0
    assert "anthropic" not in sys.modules
    assert "openai" not in sys.modules
    assert "google.genai" not in sys.modules
    assert "Summarize this page" in capsys.readouterr().out


class FakeAdapter:
    def generate(self, model, user_message, max_output_tokens):
        return corpus.Reply("A two sentence answer.", "end_turn", model, 3, 5, "id-1")


class ErrorAdapter:
    def generate(self, model, user_message, max_output_tokens):
        if "site1" in user_message:
            raise RuntimeError("fake failure")
        return corpus.Reply("ok", "end_turn", model, 1, 2, None)


def test_runner_writes_jsonl_and_resumes_completed_triples(tmp_path):
    model = corpus.ModelSpec("m", "anthropic", "claude", True)
    prompt = corpus.Prompt("site1", "p1", "user message")
    first = corpus.run_requests(
        [model], [prompt], 2, tmp_path, {"anthropic": lambda: FakeAdapter()}, max_requests=2
    )
    rows = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert first.done == 2 and first.skipped == 0
    assert {
        "corpus_id",
        "ts",
        "name",
        "provider",
        "model",
        "response_model",
        "prompt_id",
        "site",
        "sample_idx",
        "text",
        "stop_reason",
        "input_tokens",
        "output_tokens",
        "latency_s",
        "raw_id",
        "error",
        "sdk_version",
    } <= rows[0].keys()
    second = corpus.run_requests([model], [prompt], 2, tmp_path, {"anthropic": lambda: FakeAdapter()})
    assert second.skipped == 2 and second.done == 0


def test_errors_are_recorded_and_run_continues(tmp_path):
    model = corpus.ModelSpec("m", "anthropic", "claude", True)
    prompts = [corpus.Prompt("site1", "p1", "site1"), corpus.Prompt("site2", "p2", "site2")]
    stats = corpus.run_requests([model], prompts, 1, tmp_path, {"anthropic": lambda: ErrorAdapter()})
    rows = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert stats.errors == 1 and stats.done == 1
    assert rows[0]["error"] == "RuntimeError: fake failure"


def test_max_requests_is_honoured(tmp_path):
    model = corpus.ModelSpec("m", "anthropic", "claude", True)
    prompts = [corpus.Prompt(f"site{i}", f"p{i}", "msg") for i in range(4)]
    stats = corpus.run_requests(
        [model], prompts, 2, tmp_path, {"anthropic": lambda: FakeAdapter()}, max_requests=3
    )
    assert stats.attempted == 3


def test_load_corpus_filters_errors_and_adds_labels(tmp_path):
    target = tmp_path / "rows.jsonl"
    target.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"error": None, "name": "model-a", "provider": "anthropic", "text": "ok"},
                {"error": "bad", "name": "model-b", "provider": "openai", "text": "no"},
            ]
        )
    )
    frame = corpus.load_corpus(tmp_path)
    assert len(frame) == 1
    assert frame.iloc[0]["label_model"] == "model-a"
    assert frame.iloc[0]["label_provider"] == "anthropic"


@pytest.mark.parametrize(
    "reason, refused",
    [
        ("refusal", True),
        ("content_filter", True),
        ("FinishReason.SAFETY", True),
        ("PROHIBITED_CONTENT", True),
        ("end_turn", False),
        ("stop", False),
        ("STOP", False),
        (None, False),
    ],
)
def test_refusals_are_detected_for_every_provider(reason, refused):
    assert corpus.is_refusal(reason) is refused


def test_resume_skips_malformed_lines(tmp_path, capsys):
    (tmp_path / "corpus-old.jsonl").write_text(
        '{"name": "m", "prompt_id": "p1", "sample_idx": 0, "error": null}\n{"name": "m", "prompt_'
    )
    assert corpus._completed(tmp_path) == {("m", "p1", 0)}
    assert "malformed line 2" in capsys.readouterr().err
