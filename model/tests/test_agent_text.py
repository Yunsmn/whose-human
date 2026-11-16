import json

import pandas as pd
import pytest

from model.agent_text import load_manifest, main, run_outcomes, submission_corpus


def manifest():
    return pd.DataFrame(
        [
            ["a-post", "codex", "model-a", "user-a", "host-a", "home", ""],
            ["a-get", "claude", "model-b", "user-a", "host-a", "home", ""],
            ["a-fetch", "cline", "model-c", "user-a", "host-a", "home", ""],
            ["a-other", "omen", "model-d", "user-a", "host-a", "home", ""],
            ["a-absent", "aider", "model-e", "user-a", "host-a", "home", ""],
        ],
        columns=["run_id", "label_agent", "label_model", "label_user", "machine", "network", "notes"],
    )


def logs():
    return pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "a-post",
                "path": "/r/a-post/input.html",
                "method": "GET",
                "submitted_text": None,
                "ts": 1,
                "site": "site1",
                "status": 200,
            },
            {
                "kind": "request",
                "run_id": "a-post",
                "path": "/r/a-post/submit",
                "method": "POST",
                "submitted_text": "Sentence one. Sentence two.",
                "ts": 2,
                "site": "site1",
                "status": 200,
            },
            {
                "kind": "request",
                "run_id": "a-get",
                "path": "/r/a-get/submit?text=x",
                "method": "GET",
                "submitted_text": "First. Second.",
                "ts": 3,
                "site": "site2",
                "status": 200,
            },
            {
                "kind": "request",
                "run_id": "a-fetch",
                "path": "/r/a-fetch/input.html",
                "method": "GET",
                "submitted_text": "   ",
                "ts": 4,
                "site": "site1",
                "status": 200,
            },
            {
                "kind": "request",
                "run_id": "a-other",
                "path": "/r/a-other/",
                "method": "GET",
                "submitted_text": None,
                "ts": 5,
                "site": "site1",
                "status": 200,
            },
            {
                "kind": "request",
                "run_id": "unplanned",
                "path": "/r/unplanned/submit",
                "method": "POST",
                "submitted_text": "Do not include me. In the corpus.",
                "ts": 6,
                "site": "site1",
                "status": 200,
            },
        ]
    )


def test_run_outcomes_covers_every_planned_run():
    outcomes = run_outcomes(logs(), manifest()).set_index("run_id")

    assert outcomes.loc["a-post", "outcome"] == "post_submitted"
    assert outcomes.loc["a-get", "outcome"] == "get_submitted"
    assert outcomes.loc["a-fetch", "outcome"] == "fetched_but_not_submitted"
    assert outcomes.loc["a-other", "outcome"] == "request_observed_without_input_fetch"
    assert outcomes.loc["a-absent", "outcome"] == "no_request_observed"
    assert outcomes.loc["a-fetch", "submission_count"] == 0


def test_submission_corpus_keeps_only_planned_non_empty_text_and_labels():
    corpus = submission_corpus(logs(), manifest())

    assert list(corpus["run_id"]) == ["a-get", "a-post"]
    assert corpus.loc[corpus["run_id"] == "a-post", "label_agent"].item() == "codex"
    assert corpus["submitted_text"].str.strip().str.len().gt(0).all()
    assert "unplanned" not in set(corpus["run_id"])


def test_empty_inputs_preserve_output_contract():
    outcomes = run_outcomes(logs().iloc[0:0], manifest().iloc[0:0])
    corpus = submission_corpus(logs().iloc[0:0], manifest())

    assert outcomes.empty
    assert "outcome" in outcomes
    assert corpus.empty
    assert "submitted_text" in corpus


def test_manifest_rejects_missing_fields_and_duplicate_run_ids(tmp_path):
    missing = tmp_path / "missing.csv"
    pd.DataFrame({"run_id": ["a-one"]}).to_csv(missing, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_manifest(missing)

    duplicate = tmp_path / "duplicate.csv"
    pd.concat([manifest().iloc[:1], manifest().iloc[:1]]).to_csv(duplicate, index=False)
    with pytest.raises(ValueError, match="duplicate"):
        load_manifest(duplicate)


def test_cli_prints_counts_without_submitted_text(tmp_path, capsys):
    manifest_path = tmp_path / "a.csv"
    log_path = tmp_path / "logs.jsonl"
    output_path = tmp_path / "private" / "corpus.csv"
    manifest().iloc[:2].to_csv(manifest_path, index=False)
    records = logs().iloc[:3].to_dict("records")
    log_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    arguments = [
        str(log_path),
        "--manifest",
        str(manifest_path),
        "--runs-dir",
        str(tmp_path / "none"),
        "--output",
        str(output_path),
    ]
    assert main(arguments) == 0

    stdout = capsys.readouterr().out
    assert "Sentence one" not in stdout
    assert "post_submitted" in stdout
    assert output_path.exists()
