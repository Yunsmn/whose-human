import pandas as pd

from model.agent_text import run_outcomes, submission_corpus


def manifest():
    return pd.DataFrame(
        [
            ["a-post", "codex", "model-a", "user-a", "host-a", "home", ""],
            ["a-get", "claude", "model-b", "user-a", "host-a", "home", ""],
            ["a-fetch", "cline", "model-c", "user-a", "host-a", "home", ""],
            ["a-absent", "aider", "model-d", "user-a", "host-a", "home", ""],
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
                "submitted_text": None,
                "ts": 4,
                "site": "site1",
                "status": 200,
            },
        ]
    )


def test_run_outcomes_includes_planned_runs_with_no_traffic():
    outcomes = run_outcomes(logs(), manifest()).set_index("run_id")

    assert outcomes.loc["a-post", "outcome"] == "post_submitted"
    assert outcomes.loc["a-get", "outcome"] == "get_submitted"
    assert outcomes.loc["a-fetch", "outcome"] == "fetched_but_not_submitted"
    assert outcomes.loc["a-absent", "outcome"] == "no_request_observed"


def test_submission_corpus_keeps_text_and_ground_truth_labels():
    corpus = submission_corpus(logs(), manifest())

    assert list(corpus["run_id"]) == ["a-get", "a-post"]
    assert corpus.loc[corpus["run_id"] == "a-post", "label_agent"].item() == "codex"
    assert corpus["submitted_text"].str.len().gt(0).all()


def test_empty_manifest_produces_empty_outcome_table():
    empty = manifest().iloc[0:0]

    outcomes = run_outcomes(logs(), empty)

    assert outcomes.empty
    assert "outcome" in outcomes
