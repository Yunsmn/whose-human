import json

import pytest

from linking.local_model_benchmark import (
    CASES,
    benchmark_plan,
    benchmark_prompt,
    summarise_stream,
    validate_loopback_url,
)


def test_loopback_validation_rejects_remote_endpoint():
    assert validate_loopback_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    with pytest.raises(ValueError, match="loopback"):
        validate_loopback_url("https://models.example/api")


def test_plan_and_prompt_are_fixed_and_synthetic():
    plan = benchmark_plan(3)
    assert len(plan) == len(CASES) * 3
    prompt = benchmark_prompt(CASES[0])
    assert "Synthetic performance benchmark" in prompt
    assert prompt.count("datum") == CASES[0].context_words
    assert "datum0000" in prompt
    assert "datum0127" in prompt


def test_stream_summary_keeps_metrics_but_not_generated_content():
    messages = [
        {"response": "alpha", "done": False},
        {"response": " beta", "done": False},
        {
            "response": "",
            "done": True,
            "load_duration": 100_000_000,
            "total_duration": 2_000_000_000,
            "prompt_eval_count": 20,
            "prompt_eval_duration": 500_000_000,
            "eval_count": 10,
            "eval_duration": 1_000_000_000,
        },
    ]
    record = summarise_stream(
        messages,
        [1.2, 1.3, 2.0],
        1.0,
        2.1,
        {"session_id": "a-omen-001", "machine": "pc-a"},
    )

    assert record["first_chunk_s"] == pytest.approx(0.2)
    assert record["eval_tokens_per_s"] == 10.0
    assert record["prompt_tokens_per_s"] == 40.0
    assert record["chunk_interval_median_s"] == pytest.approx(0.1)
    assert "response" not in json.dumps(record)
    assert "alpha" not in json.dumps(record)


def test_stream_summary_records_privacy_safe_failure_reason():
    record = summarise_stream(
        [{"error": "prediction aborted, token repeat limit reached"}],
        [1.0],
        started_at=0.0,
        finished_at=1.1,
        metadata={"session_id": "a-omen-failed", "machine": "pc-a"},
    )

    assert record["success"] is False
    assert record["failure_reason"] == "prediction aborted, token repeat limit reached"
    assert "response" not in record
