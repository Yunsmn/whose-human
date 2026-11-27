"""Train and evaluate pairwise user-linking rules and models."""

from __future__ import annotations

import argparse
from itertools import combinations_with_replacement

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import adjusted_rand_score, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from infra.loader import load_logs
from linking.pairs import (
    IP_FEATURES,
    NETWORK_FEATURES,
    PAIR_FEATURES,
    RARITY_FEATURES,
    SLICE_COLUMNS,
    build_pairs,
    rarity_columns,
    value_shares,
)
from linking.sessions import SIGNATURE_COLUMNS, build_sessions

NO_IP_FEATURES = [column for column in PAIR_FEATURES if column not in IP_FEATURES]
# The three feature sets the CLI scores: everything; without IP (H2); the network trace alone, without the IP,
# the relay token or the session schedule (what links two sessions that share nothing but the user's setup).
FEATURE_SETS = {"all": PAIR_FEATURES, "no_ip": NO_IP_FEATURES, "network_only": NETWORK_FEATURES}


def rule_same_ip(pairs: pd.DataFrame) -> pd.Series:
    return pairs.same_ip.astype(float)


def rule_signature(pairs: pd.DataFrame, min_matches: int) -> pd.Series:
    return pairs.n_signature_matches.ge(min_matches).astype(float)


def fit_pair_model(pairs: pd.DataFrame, features=PAIR_FEATURES) -> Pipeline:
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="constant", fill_value=0)),
            ("scaler", StandardScaler()),  # rarity sums are on another scale than 0/1 matches
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )
    model.fit(pairs[list(features)].astype(float), pairs.same_user.astype(bool))
    return model


def score(model, pairs: pd.DataFrame) -> pd.Series:
    columns = model.feature_names_in_
    return pd.Series(
        model.predict_proba(pairs[columns].astype(float))[:, list(model.classes_).index(True)],
        index=pairs.index,
    )


def cross_val_scores(
    sessions: pd.DataFrame, pairs: pd.DataFrame, features=PAIR_FEATURES, n_splits: int = 5, seed: int = 0
) -> pd.Series:
    """Out-of-sample same-user probability for every pair; needs n_splits >= 3 to score pairs across folds."""
    if n_splits < 3:
        raise ValueError("n_splits must be at least 3: pairs across two folds need a third to train on")
    labels = sessions.label_user
    if labels.value_counts().min() >= n_splits:
        splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        folds = splitter.split(sessions, labels)
    else:
        splitter = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
        folds = splitter.split(sessions)
    fold_by_session = {}
    for fold, (_, test_indices) in enumerate(folds):
        for index in test_indices:
            fold_by_session[sessions.iloc[index].session_key] = fold
    scores = pd.Series(np.nan, index=pairs.index, dtype=float)
    fold_a, fold_b = pairs.a.map(fold_by_session), pairs.b.map(fold_by_session)
    low, high = np.minimum(fold_a, fold_b), np.maximum(fold_a, fold_b)
    # Every pair is scored by a model that saw neither of its sessions: the pairs between folds k and m
    # (k == m for pairs inside one fold) are scored by a model trained only on pairs touching neither fold.
    for k, m in combinations_with_replacement(range(n_splits), 2):
        test_mask = low.eq(k) & high.eq(m)
        train_mask = ~fold_a.isin([k, m]) & ~fold_b.isin([k, m])
        train, test = pairs.loc[train_mask], pairs.loc[test_mask]
        if train.empty or test.empty or train.same_user.nunique() < 2:
            continue
        if set(features) & set(RARITY_FEATURES):
            # value shares from this fold's training sessions only: test sessions don't shape their features
            in_train = sessions.session_key.map(fold_by_session).isin([k, m]).eq(False)
            shares = value_shares(sessions.loc[in_train])
            train = train.assign(**rarity_columns(train, sessions, shares))
            test = test.assign(**rarity_columns(test, sessions, shares))
        model = fit_pair_model(train, features)
        positive_index = list(model.classes_).index(True)
        scores.loc[test.index] = model.predict_proba(test[list(features)].astype(float))[:, positive_index]
    return scores


def evaluate(pairs: pd.DataFrame, scores: pd.Series, threshold: float = 0.5) -> pd.DataFrame:
    data = pairs.copy()
    data["score"] = scores
    data = data.loc[data.score.notna()]
    rows = []
    for name in ["all", *SLICE_COLUMNS]:
        subset = data if name == "all" else data.loc[data[name]]
        truth = subset.same_user.astype(bool).to_numpy()
        predicted = subset.score.ge(threshold).to_numpy()
        tp = int((truth & predicted).sum())
        fp = int((~truth & predicted).sum())
        fn = int((truth & ~predicted).sum())
        precision = tp / (tp + fp) if tp + fp else float("nan")
        recall = tp / (tp + fn) if tp + fn else float("nan")
        if name == "ip_changed":
            precision = float("nan")
        f1 = (
            2 * precision * recall / (precision + recall)
            if pd.notna(precision) and pd.notna(recall) and precision + recall
            else float("nan")
        )
        auc = roc_auc_score(truth, subset.score) if len(set(truth)) == 2 else float("nan")
        rows.append(
            {
                "slice": name,
                "n_pairs": len(subset),
                "n_pos": int(truth.sum()),
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "auc": auc,
            }
        )
    return pd.DataFrame(rows)


def _connected_components(keys: list, pairs: pd.DataFrame, linked: pd.Series) -> list[int]:
    parent = {key: key for key in keys}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for a, b in zip(pairs.a[linked], pairs.b[linked], strict=True):
        parent[find(b)] = find(a)
    names: dict = {}
    return [names.setdefault(find(key), len(names)) for key in keys]


def _average_linkage(keys: list, pairs: pd.DataFrame, scores: pd.Series, threshold: float) -> list[int]:
    if len(keys) < 2:
        return [0] * len(keys)
    position = {key: i for i, key in enumerate(keys)}
    distance = np.ones((len(keys), len(keys)))  # unscored pairs count as unlinked
    np.fill_diagonal(distance, 0.0)
    rows, cols = pairs.a.map(position).to_numpy(), pairs.b.map(position).to_numpy()
    values = 1.0 - scores.reindex(pairs.index).fillna(0.0).to_numpy()
    distance[rows, cols] = distance[cols, rows] = values
    model = AgglomerativeClustering(
        n_clusters=None, metric="precomputed", linkage="average", distance_threshold=1.0 - threshold
    )
    return model.fit_predict(distance).tolist()


def cluster(
    sessions: pd.DataFrame,
    pairs: pd.DataFrame,
    scores: pd.Series,
    threshold: float = 0.5,
    method: str = "average",
) -> pd.Series:
    """Group sessions into users from pair scores.

    "average" (default) merges two groups when their pairs' mean score reaches the threshold, so a few false
    links don't merge two people. "components" links every pair at or above the threshold (single linkage):
    one false link merges two users, as happens with WebFetch, whose sessions look the same for everyone.
    """
    keys = sessions.session_key.tolist()
    if method == "components":
        labels = _connected_components(keys, pairs, scores.ge(threshold) & scores.notna())
    elif method == "average":
        labels = _average_linkage(keys, pairs, scores, threshold)
    else:
        raise ValueError(f"unknown clustering method {method!r}")
    return pd.Series(labels, index=sessions.session_key)


def cluster_metrics(sessions: pd.DataFrame, clusters: pd.Series) -> dict:
    truth = sessions.label_user.astype(str).to_numpy()
    predicted = clusters.reindex(sessions.session_key).to_numpy()
    precision_sum = recall_sum = 0.0
    for i, label in enumerate(truth):
        same_cluster = predicted == predicted[i]
        same_user = truth == label
        precision_sum += same_cluster[same_user].sum() / max(same_cluster.sum(), 1)
        recall_sum += same_cluster[same_user].sum() / max(same_user.sum(), 1)
    precision, recall = precision_sum / len(truth), recall_sum / len(truth)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "adjusted_rand": adjusted_rand_score(truth, predicted),
        "bcubed_precision": precision,
        "bcubed_recall": recall,
        "bcubed_f1": f1,
    }


def _report(name, sessions, pairs, scores, threshold):
    print(f"\n{name}")
    print(evaluate(pairs, scores, threshold).to_string(index=False))
    for method in ("average", "components"):
        metrics = cluster_metrics(sessions, cluster(sessions, pairs, scores, threshold, method))
        print(f"clusters ({method}):", ", ".join(f"{key}={value:.3f}" for key, value in metrics.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Track 3 same-user linking")
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--include-baselines", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args(argv)
    sessions = build_sessions(
        load_logs(args.logs_dir, runs_dir=args.runs), include_baselines=args.include_baselines
    )
    pairs = build_pairs(sessions)
    print(f"Sessions: {len(sessions)}; pairs: {len(pairs)}")
    for column in ("label_user", "label_agent", "machine", "tools"):
        print(f"Sessions per {column}:")
        print(sessions.groupby(column, dropna=False).size().to_string())
    _report("rule_same_ip", sessions, pairs, rule_same_ip(pairs), args.threshold)
    _report("rule_signature", sessions, pairs, rule_signature(pairs, len(SIGNATURE_COLUMNS)), args.threshold)
    for name, features in FEATURE_SETS.items():
        scores = cross_val_scores(sessions, pairs, features=features)
        _report(f"CV model, features: {name}", sessions, pairs, scores, args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
