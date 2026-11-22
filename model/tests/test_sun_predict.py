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


def test_prose_paragraphs_keep_only_plain_paragraphs_of_the_right_length():
    from model.sun_classifier.summary_answers import prose_paragraphs

    words = " ".join(["word"] * 40)
    text = "\n\n".join(
        [
            f"{words}.",  # kept
            f"- {words}.",  # list item
            f"## {words}.",  # heading
            f"Some **bold** {words}.",  # markdown
            "Too short.",
            f"{words} without an end",  # no final punctuation
        ]
    )
    assert prose_paragraphs(text) == [f"{words}."]


def test_page_prompt_matches_the_2b_instruction():
    from model.cli_corpus import DIRECT_INSTRUCTION
    from model.sun_classifier.summary_answers import page_prompt

    assert page_prompt("A page.") == f"A page.\n\n{DIRECT_INSTRUCTION}"


def test_done_keys_skip_failed_and_half_written_rows(tmp_path):
    from model.sun_classifier.summary_answers import done_keys

    path = tmp_path / "m.jsonl"
    rows = [
        {"prompt_idx": 0, "condition": "default", "text": "ok"},
        {"prompt_idx": 0, "condition": "minimal", "text": None, "error": "boom"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"prompt_idx": 1', encoding="utf-8")
    assert done_keys(path) == {(0, "default")}


def test_cache_keys_separate_conditions_and_corpora():
    from model.sun_classifier.train_head import cache_key

    row = {"model": "m", "prompt_idx": 3, "condition": "default"}
    assert cache_key("summaries", row) != cache_key("summaries", row | {"condition": "minimal"})
    assert cache_key("summaries", row) != cache_key("short", row)
    assert cache_key("2b", {"id": "m:site1:default:0", "model": "m"}) == "2b|m:site1:default:0"


def test_provider_head_columns_are_kept_not_summed(tmp_path):
    def score_with_provider_head(texts):
        frame = fake_score(texts)
        frame["provider_anthropic"] = 0.2  # the provider head disagrees with the model head
        frame["provider_openai"] = 0.8
        return frame

    path = tmp_path / "agent.csv"
    write_agent_csv(path)
    texts_path, ids_path = predict_file(path, tmp_path / "out", (score_with_provider_head, PROVIDERS))
    texts = pd.read_csv(texts_path)
    assert texts["provider_openai"].tolist() == [0.8, 0.8, 0.8]
    assert texts["top_provider"].tolist() == ["openai"] * 3
    assert texts["top_model"].tolist() == ["opus", "haiku", "astra"]  # unchanged
    runs = pd.read_csv(ids_path).set_index("id")
    assert runs.loc["a-1", "provider_openai"] == pytest.approx(0.8)


def test_two_class_head_weights_give_sklearns_probabilities():
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    from model.sun_classifier.train_head import softmax_weights

    rng = np.random.default_rng(0)
    x = rng.normal(size=(40, 5))
    y = np.where(x[:, 0] > 0, "openai", "anthropic")
    model = LogisticRegression().fit(x, y)
    weight, bias = softmax_weights(model)
    assert weight.shape == (2, 5)
    logits = x @ weight.T + bias
    probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    assert np.allclose(probs, model.predict_proba(x), atol=1e-5)
