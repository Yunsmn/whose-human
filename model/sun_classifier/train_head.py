"""Train a new output head over our current models, on top of the frozen 4-bit Sun et al. backbone.

    python -m model.sun_classifier.train_head                          # page summaries (default)
    python -m model.sun_classifier.train_head --corpus-dir data/corpus/short

Sun et al.'s head knows five 2024 chatbots. This replaces it with one over the models in
`--corpus-dir`. The default is two-sentence summaries of practice pages, collected by
summary_answers.py the way 2b collects them. Each text goes through the frozen backbone once
(mean-pooled 4,096 numbers, cached), then two logistic regressions are fitted on those
vectors: a six-way one over the models and a two-way one over the providers. The provider head
names the provider more often than the sum of the model head's probabilities (it doesn't have
to tell tiers apart first), so 2c takes the provider from it.
Only the heads are trained; the backbone is unchanged.

Pages (or questions) are split, not texts: every model's answers to the last `--test-share` of
them are held out, so held-out pages were never seen in training. The shipped head is then
refitted on everything and scored on 2b's corpus of our real site pages (`--test-corpus`), which
shares no page with the training data.

Writes model/sun_classifier/heads/head-short.npz (committed; labels, providers, weights, bias,
feature scaling, and the provider head) and data/results/short_head_eval.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SUMMARY_DIR = Path("data/corpus/summaries")
SHORT_DIR = Path("data/corpus/short")
TEST_CORPUS = Path("data/corpus/cli")
CACHE = Path("data/models/sun_chat/short-embeddings.npz")
HEAD = Path("model/sun_classifier/heads/head-short.npz")  # committed: small, no private data
RESULTS = Path("data/results/short_head_eval.json")


def load_answers(corpus_dir: Path = SUMMARY_DIR) -> list[dict]:
    """Rows with a text; rows that recorded a failed call (no text) are skipped."""
    rows = []
    for path in sorted(corpus_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:  # a line still being written by a running collector
                continue
            if row.get("text"):
                rows.append(row)
    return rows


def split_by_question(rows: list[dict], test_share: float) -> tuple[list[int], list[int]]:
    """Row positions for train and test; the highest prompt indices go to test, for every model."""
    questions = sorted({row["prompt_idx"] for row in rows})
    cut = questions[int(round(len(questions) * (1 - test_share)))] if test_share > 0 else None
    train = [i for i, row in enumerate(rows) if cut is None or row["prompt_idx"] < cut]
    test = [i for i, row in enumerate(rows) if cut is not None and row["prompt_idx"] >= cut]
    return train, test


def cache_key(source: str, row: dict) -> str:
    """One vector per text: corpus, model, page or question, and condition."""
    if "id" in row:  # 2b rows carry their own unique id
        return f"{source}|{row['id']}"
    return f"{source}|{row['model']}|{row['prompt_idx']}|{row.get('condition', '')}"


def embed_all(rows: list[dict], source: str, cache: Path = CACHE) -> np.ndarray:
    """Backbone vectors for every row, reusing cached ones."""
    keys = [cache_key(source, row) for row in rows]
    known: dict[str, np.ndarray] = {}
    if cache.exists():
        stored = np.load(cache, allow_pickle=False)
        known = dict(zip(stored["keys"].tolist(), stored["vectors"], strict=True))
    missing = [i for i, key in enumerate(keys) if key not in known]
    if missing:
        from model.sun_classifier.classify import SunChatClassifier

        clf = SunChatClassifier()
        for done, i in enumerate(missing, start=1):
            known[keys[i]] = clf.embed(rows[i]["text"]).float().cpu().numpy()
            if done % 200 == 0:
                print(f"embedded {done}/{len(missing)}", flush=True)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, keys=np.array(list(known)), vectors=np.stack(list(known.values())))
    return np.stack([known[key] for key in keys])


def fit_head(x: np.ndarray, y: list[str], c: float = 1.0):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(x)
    model = LogisticRegression(C=c, max_iter=3000).fit(scaler.transform(x), y)
    return scaler, model


def softmax_weights(model) -> tuple[np.ndarray, np.ndarray]:
    """One weight row and bias per class. A two-class sklearn model stores one row (for classes_[1]);
    a zero row for classes_[0] gives the same probabilities under a softmax."""
    weight, bias = model.coef_, model.intercept_
    if len(model.classes_) == 2:
        weight = np.vstack([np.zeros_like(weight), weight])
        bias = np.concatenate([np.zeros_like(bias), bias])
    return weight.astype(np.float32), bias.astype(np.float32)


def head_arrays(scaler, model, providers: dict[str, str], provider_model=None) -> dict[str, np.ndarray]:
    """Both heads share one feature scaling: they are fitted on the same vectors."""
    labels = [str(label) for label in model.classes_]
    weight, bias = softmax_weights(model)
    arrays = {
        "labels": np.array(labels),
        "providers": np.array([providers[label] for label in labels]),
        "weight": weight,
        "bias": bias,
        "mean": scaler.mean_.astype(np.float32),
        "scale": scaler.scale_.astype(np.float32),
    }
    if provider_model is not None:
        provider_weight, provider_bias = softmax_weights(provider_model)
        arrays |= {
            "provider_labels": np.array([str(label) for label in provider_model.classes_]),
            "provider_weight": provider_weight,
            "provider_bias": provider_bias,
        }
    return arrays


def report(model, scaler, x: np.ndarray, y: list[str], providers: dict[str, str]) -> dict:
    predicted = model.predict(scaler.transform(x))
    labels = sorted(set(y) | {str(label) for label in model.classes_})
    confusion = {
        t: {p: int(sum(1 for a, b in zip(y, predicted, strict=True) if a == t and b == p)) for p in labels}
        for t in sorted(set(y))
    }
    return {
        "n": len(y),
        "model_accuracy": float(np.mean([a == b for a, b in zip(y, predicted, strict=True)])),
        "provider_accuracy": float(
            np.mean([providers.get(a) == providers.get(b) for a, b in zip(y, predicted, strict=True)])
        ),
        "confusion": confusion,
    }


def provider_accuracy(
    provider_model, scaler, x: np.ndarray, y: list[str], providers: dict[str, str]
) -> float:
    """Share of texts whose provider the provider head names; `y` holds model ids."""
    predicted = provider_model.predict(scaler.transform(x))
    return float(np.mean([providers[a] == b for a, b in zip(y, predicted, strict=True)]))


def external_test(model, scaler, providers: dict[str, str], corpus_dir: Path, provider_model=None) -> dict:
    """Score the heads on 2b's real site-page corpus, overall and per condition."""
    from model.api_corpus import load_corpus

    corpus = load_corpus(corpus_dir)
    rows = corpus.to_dict("records")
    x = embed_all(rows, source="2b")
    y = corpus["label_model"].tolist()
    groups = {"all": np.ones(len(y), dtype=bool)}
    if "condition" in corpus:
        for condition in sorted(corpus["condition"].dropna().unique()):
            groups[condition] = (corpus["condition"] == condition).to_numpy()
    result = {}
    for name, keep in groups.items():
        truth = [y[i] for i in np.flatnonzero(keep)]
        result[name] = report(model, scaler, x[keep], truth, providers)
        if provider_model is not None:
            result[name]["provider_head_accuracy"] = provider_accuracy(
                provider_model, scaler, x[keep], truth, providers
            )
    return result


def _summary(name: str, scores: dict) -> str:
    line = (
        f"{name:10s} n={scores['n']:4d}  provider {scores['provider_accuracy']:.1%}  "
        f"exact model {scores['model_accuracy']:.1%}"
    )
    if "provider_head_accuracy" in scores:
        line += f"  provider head {scores['provider_head_accuracy']:.1%}"
    return line


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus-dir", type=Path, default=SUMMARY_DIR)
    parser.add_argument("--test-corpus", type=Path, default=TEST_CORPUS, help="2b corpus to score on")
    parser.add_argument("--test-share", type=float, default=0.25)
    parser.add_argument("--c", type=float, default=0.01, help="inverse regularization strength")
    parser.add_argument(
        "--provider-c",
        type=float,
        default=0.001,
        help="the same for the provider head (0.001 scored best on held-out pages)",
    )
    args = parser.parse_args(argv)

    rows = load_answers(args.corpus_dir)
    providers = {row["model"]: row["provider"] for row in rows}
    x = embed_all(rows, source=args.corpus_dir.name)
    y = [row["model"] for row in rows]
    train, test = split_by_question(rows, args.test_share)
    y_provider = [providers[label] for label in y]
    scaler, model = fit_head(x[train], [y[i] for i in train], args.c)
    held_out = report(model, scaler, x[test], [y[i] for i in test], providers)
    _, provider_model = fit_head(x[train], [y_provider[i] for i in train], args.provider_c)
    held_out["provider_head_accuracy"] = provider_accuracy(
        provider_model, scaler, x[test], [y[i] for i in test], providers
    )
    print(_summary("held-out", held_out), flush=True)
    for truth, row in held_out["confusion"].items():
        print(f"  {truth:18s} {row}")

    # The shipped head is refitted on every page once the held-out score is recorded.
    scaler, model = fit_head(x, y, args.c)
    _, provider_model = fit_head(x, y_provider, args.provider_c)
    result = {
        "corpus": str(args.corpus_dir),
        "train": len(rows),
        "c": args.c,
        "provider_c": args.provider_c,
        "held_out": held_out,
    }
    if args.test_corpus.exists():
        result["site_pages_2b"] = external_test(model, scaler, providers, args.test_corpus, provider_model)
        for name, scores in result["site_pages_2b"].items():
            print(_summary(f"2b {name}", scores), flush=True)
    HEAD.parent.mkdir(parents=True, exist_ok=True)
    np.savez(HEAD, **head_arrays(scaler, model, providers, provider_model))
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"saved {HEAD} and {RESULTS}")


if __name__ == "__main__":
    main()
