import json

import pandas as pd
import pytest

from model.sun_classifier.agent_answers import build_prompt, parse_reply
from model.sun_classifier.predict import predict_file, read_texts
from model.sun_classifier.train_head import split_by_question

PROVIDERS = {"opus": "anthropic", "haiku": "anthropic", "astra": "openai"}


def fake_score(texts):
    # Put all the weight on one model chosen by text length, to keep it deterministic.
    models = list(PROVIDERS)
    rows = []
    for text in texts:
        rows.append({f"p_{m}": float(i == len(text) % 3) for i, m in enumerate(models)})
    return pd.DataFrame(rows)


SCORER = (fake_score, PROVIDERS)


def write_agent_csv(path):
    pd.DataFrame(
        {
            "run_id": ["a-1", "a-1", "a-2", "a-3"],
            "site": ["site1", "site2", "site1", "site1"],
            "submitted_text": ["abc", "abcd", "abcde", "   "],
            "label_model": ["secret-1", "secret-1", "secret-2", "secret-3"],
            "label_agent": ["x", "x", "y", "z"],
        }
    ).to_csv(path, index=False)


def test_read_texts_keeps_only_id_and_text(tmp_path):
    path = tmp_path / "agent.csv"
    write_agent_csv(path)
    texts = read_texts(path)
    assert list(texts.columns) == ["id", "text"]
    assert list(texts["id"]) == ["a-1", "a-1", "a-2"]  # blank submission dropped
    assert texts.attrs["has_key"]


def test_labels_never_reach_the_output(tmp_path):
    path = tmp_path / "agent.csv"
    write_agent_csv(path)
    for written in predict_file(path, tmp_path / "out", SCORER):
        content = written.read_text()
        assert "secret" not in content and "label_" not in content


def test_per_text_and_per_run_outputs(tmp_path):
    path = tmp_path / "agent.csv"
    write_agent_csv(path)
    texts_path, ids_path = predict_file(path, tmp_path / "out", SCORER)
    texts = pd.read_csv(texts_path, dtype={"id": str})
    models = ["p_opus", "p_haiku", "p_astra"]
    providers = ["provider_anthropic", "provider_openai"]
    assert list(texts.columns) == ["id", *models, *providers, "top_model", "top_provider"]
    assert texts["top_model"].tolist() == ["opus", "haiku", "astra"]  # lengths 3, 4, 5
    assert texts["top_provider"].tolist() == ["anthropic", "anthropic", "openai"]
    runs = pd.read_csv(ids_path).set_index("id")
    assert runs.loc["a-1", "n_texts"] == 2
    assert runs.loc["a-1", ["p_opus", "p_haiku", "p_astra"]].tolist() == [0.5, 0.5, 0.0]
    assert runs.loc["a-1", "provider_anthropic"] == 1.0


def test_text_without_any_run(tmp_path):
    # A real visitor: only the text, no run_id, no labels.
    path = tmp_path / "visitor.csv"
    pd.DataFrame({"submitted_text": ["hello there", "general kenobi"]}).to_csv(path, index=False)
    written = predict_file(path, tmp_path / "out", SCORER)
    assert len(written) == 1  # no per-run file without a key
    assert pd.read_csv(written[0])["id"].tolist() == [0, 1]


def test_reads_the_api_corpus_text_column(tmp_path):
    path = tmp_path / "corpus.jsonl"
    rows = [{"prompt_id": "site1", "text": "abc", "label_model": "m"}]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    texts = read_texts(path, id_column="prompt_id")
    assert texts.to_dict("records") == [{"id": "site1", "text": "abc"}]


def test_missing_text_column_is_an_error(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"body": ["x"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="no text column"):
        read_texts(path)


def test_build_prompt_numbers_questions():
    prompt = build_prompt(["Why?", "How?"])
    assert prompt.endswith("1. Why?\n2. How?")
    assert "two sentences" in prompt


def test_parse_reply_takes_the_json_and_cleans_it():
    reply = 'Sure.\n{"1": "One.  Two.", "2": "", "3": "Out of range.", "x": "bad"}\n'
    assert parse_reply(reply, 2) == {1: "One. Two."}
    assert parse_reply("no json here", 2) == {}


def test_split_by_question_holds_out_whole_questions():
    rows = [{"model": m, "prompt_idx": i} for m in ("a", "b") for i in range(8)]
    train, test = split_by_question(rows, 0.25)
    train_q = {rows[i]["prompt_idx"] for i in train}
    test_q = {rows[i]["prompt_idx"] for i in test}
    assert test_q == {6, 7} and not train_q & test_q
    assert len(test) == 4  # both models answer the held-out questions
