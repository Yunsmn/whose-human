"""Train and evaluate pairwise user-linking rules and models."""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import adjusted_rand_score, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline

from infra.loader import load_logs
from linking.pairs import (
    IP_FEATURES,
    NETWORK_FEATURES,
    PAIR_FEATURES,
    SLICE_COLUMNS,
    build_pairs,
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
    for fold in range(n_splits):
        # A pair is tested only when both sessions are held out, and trained on only when neither is.
        test_mask = fold_a.eq(fold) & fold_b.eq(fold)
        train_mask = fold_a.ne(fold) & fold_b.ne(fold)
        train, test = pairs.loc[train_mask], pairs.loc[test_mask]
        if train.empty or test.empty or train.same_user.nunique() < 2:
            continue
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


def cluster(
    sessions: pd.DataFrame, pairs: pd.DataFrame, scores: pd.Series, threshold: float = 0.5
) -> pd.Series:
    parent = {key: key for key in sessions.session_key}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for index, pair in pairs.iterrows():
        if pd.notna(scores.get(index)) and scores[index] >= threshold:
            left, right = find(pair.a), find(pair.b)
            parent[right] = left
    names = {}
    return pd.Series(
        [names.setdefault(find(key), len(names)) for key in sessions.session_key], index=sessions.session_key
    )


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
    metrics = cluster_metrics(sessions, cluster(sessions, pairs, scores, threshold))
    print("cluster metrics:", ", ".join(f"{key}={value:.3f}" for key, value in metrics.items()))


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
