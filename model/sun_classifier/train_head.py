"""Train a new output head over our current models, on top of the frozen 4-bit Sun et al. backbone.

    python -m model.sun_classifier.train_head

Sun et al.'s head knows five 2024 chatbots. This replaces it with one over the models in
data/corpus/short/*.jsonl (collected by agent_answers.py): each two-sentence answer goes through
the frozen backbone once (mean-pooled 4,096 numbers, cached), then a multinomial logistic
regression is fitted on those vectors. Only the head is trained; the backbone is unchanged.

Questions are split, not answers: every model's answers to the last `--test-share` of the questions
are held out, so test questions were never seen in training.

Writes model/sun_classifier/heads/head-short.npz (committed; labels, providers, weights, bias,
feature scaling)
and data/results/short_head_eval.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SHORT_DIR = Path("data/corpus/short")
CACHE = Path("data/models/sun_chat/short-embeddings.npz")
HEAD = Path("model/sun_classifier/heads/head-short.npz")  # committed: small, no private data
RESULTS = Path("data/results/short_head_eval.json")


def load_answers(short_dir: Path = SHORT_DIR) -> list[dict]:
    rows = []
    for path in sorted(short_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:  # a line still being written by a running collector
                continue
    return rows


def split_by_question(rows: list[dict], test_share: float) -> tuple[list[int], list[int]]:
    """Row positions for train and test; the highest prompt indices go to test, for every model."""
    questions = sorted({row["prompt_idx"] for row in rows})
    cut = questions[int(round(len(questions) * (1 - test_share)))] if test_share > 0 else None
    train = [i for i, row in enumerate(rows) if cut is None or row["prompt_idx"] < cut]
    test = [i for i, row in enumerate(rows) if cut is not None and row["prompt_idx"] >= cut]
    return train, test


def embed_all(rows: list[dict], cache: Path = CACHE) -> np.ndarray:
    """Backbone vectors for every row, reusing cached ones (keyed by model and question)."""
    keys = [f"{row['model']}|{row['prompt_idx']}" for row in rows]
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


def head_arrays(scaler, model, providers: dict[str, str]) -> dict[str, np.ndarray]:
    labels = [str(label) for label in model.classes_]
    return {
        "labels": np.array(labels),
        "providers": np.array([providers[label] for label in labels]),
        "weight": model.coef_.astype(np.float32),
        "bias": model.intercept_.astype(np.float32),
        "mean": scaler.mean_.astype(np.float32),
        "scale": scaler.scale_.astype(np.float32),
    }


def report(model, scaler, x: np.ndarray, y: list[str], providers: dict[str, str]) -> dict:
    predicted = model.predict(scaler.transform(x))
    labels = [str(label) for label in model.classes_]
    confusion = {
        t: {p: int(sum(1 for a, b in zip(y, predicted, strict=True) if a == t and b == p)) for p in labels}
        for t in labels
    }
    return {
        "n": len(y),
        "model_accuracy": float(np.mean([a == b for a, b in zip(y, predicted, strict=True)])),
        "provider_accuracy": float(
            np.mean([providers[a] == providers[b] for a, b in zip(y, predicted, strict=True)])
        ),
        "confusion": confusion,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--test-share", type=float, default=0.25)
    parser.add_argument("--c", type=float, default=0.01, help="inverse regularization strength")
    args = parser.parse_args(argv)

    rows = load_answers()
    providers = {row["model"]: row["provider"] for row in rows}
    x = embed_all(rows)
    y = [row["model"] for row in rows]
    train, test = split_by_question(rows, args.test_share)
    scaler, model = fit_head(x[train], [y[i] for i in train], args.c)
    result = {
        "train": len(train),
        "c": args.c,
        "test": report(model, scaler, x[test], [y[i] for i in test], providers),
    }
    print(json.dumps({k: v for k, v in result["test"].items() if k != "confusion"}), flush=True)
    for truth, row in result["test"]["confusion"].items():
        print(f"  {truth:18s} {row}")

    # The shipped head is refitted on every question once the held-out score is recorded.
    scaler, model = fit_head(x, y, args.c)
    HEAD.parent.mkdir(parents=True, exist_ok=True)
    np.savez(HEAD, **head_arrays(scaler, model, providers))
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=1))
    print(f"saved {HEAD} and {RESULTS}")


if __name__ == "__main__":
    main()
