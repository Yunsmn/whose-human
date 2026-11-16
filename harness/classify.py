"""Grouped harness attribution models and command-line evaluation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from harness.features import CATEGORICAL_COLUMNS, FEATURE_GROUPS, extract_features

DEFAULT_FEATURE_SETS = {
    "tls_only": ["tls"],
    "http_only": ["http", "h2"],
    "tls+http": ["tls", "http", "h2"],
    "all": ["tls", "http", "h2", "timing", "body"],
}


def _pipeline(columns: list[str], categorical: list[str]) -> Pipeline:
    numeric = [column for column in columns if column not in categorical]
    transformers = []
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="constant", fill_value="missing")),
                        ("encode", OneHotEncoder(handle_unknown="ignore", min_frequency=2)),
                    ]
                ),
                categorical,
            )
        )
    if numeric:
        transformers.append(("numeric", Pipeline([("impute", SimpleImputer(strategy="median"))]), numeric))
    return Pipeline(
        [
            ("features", ColumnTransformer(transformers)),
            ("classifier", ExtraTreesClassifier(n_estimators=300, random_state=0, class_weight="balanced")),
        ]
    )


def build_model(feature_groups: list[str]) -> Pipeline:
    """Build the pipeline for one or more named ``FEATURE_GROUPS``."""
    unknown = sorted(set(feature_groups) - FEATURE_GROUPS.keys())
    if unknown:
        raise ValueError(f"unknown feature group(s): {', '.join(unknown)}")
    columns = list(dict.fromkeys(column for group in feature_groups for column in FEATURE_GROUPS[group]))
    return _pipeline(columns, [column for column in columns if column in CATEGORICAL_COLUMNS])


def _columns(features: pd.DataFrame, groups: Sequence[str] | None = None) -> list[str]:
    candidates = (column for group in groups or FEATURE_GROUPS for column in FEATURE_GROUPS[group])
    return [column for column in dict.fromkeys(candidates) if column in features.columns]


def _model_for_columns(columns: list[str]) -> Pipeline:
    return _pipeline(columns, [column for column in columns if column in CATEGORICAL_COLUMNS])


def _require_labelled(features: pd.DataFrame, label: str, groups: str) -> pd.DataFrame:
    if label not in features or groups not in features:
        raise ValueError(f"features must contain {label!r} and {groups!r}")
    labelled = features.loc[features[label].notna() & features[groups].notna()].copy()
    if labelled.empty:
        raise ValueError(f"no labelled rows found for {label}")
    return labelled


def _splitter_and_count(data: pd.DataFrame, label: str, groups: str):
    group_counts = data.groupby(label)[groups].nunique()
    if len(group_counts) < 2 or group_counts.min() < 2:
        raise ValueError("need at least 2 groups per class for grouped cross-validation")
    n_splits = min(5, int(group_counts.min()))
    return StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=0), n_splits


def evaluate(
    features: pd.DataFrame,
    label: str = "label_agent",
    groups: str = "run_id",
    feature_sets: dict | None = None,
) -> pd.DataFrame:
    """Evaluate feature groups with folds that never share a run between sides."""
    data = _require_labelled(features, label, groups)
    splitter, n_splits = _splitter_and_count(data, label, groups)
    selected_sets = feature_sets or DEFAULT_FEATURE_SETS
    rows = []
    for name, feature_groups in selected_sets.items():
        columns = _columns(data, feature_groups)
        if not columns:
            raise ValueError(f"feature set {name!r} has no available columns")
        truth, predicted = [], []
        for train_idx, test_idx in splitter.split(data, data[label], data[groups]):
            train, test = data.iloc[train_idx], data.iloc[test_idx]
            model = _model_for_columns(columns)
            model.fit(train[columns], train[label])
            truth.extend(test[label])
            predicted.extend(model.predict(test[columns]))
        rows.append(
            {
                "feature_set": name,
                "n_rows": len(data),
                "n_classes": data[label].nunique(),
                "accuracy": accuracy_score(truth, predicted),
                "macro_f1": f1_score(truth, predicted, average="macro"),
                "n_splits": n_splits,
            }
        )
    return pd.DataFrame(rows)


def fit_and_predict_proba(
    train: pd.DataFrame, test: pd.DataFrame, groups: str = "run_id", label: str = "label_agent"
) -> pd.DataFrame:
    """Fit on ``train`` and return class probabilities for ``test`` rows (index matches ``test``).

    Train and test must not share a value of ``groups``, which would leak runs across the split.
    """
    if label not in train or groups not in train or groups not in test:
        raise ValueError(f"train/test must contain {label!r} and grouping column {groups!r}")
    overlap = set(train[groups].dropna()) & set(test[groups].dropna())
    if overlap:
        raise ValueError(f"train and test share {groups} values: {sorted(overlap)[:5]}")
    train = train.loc[train[label].notna()]
    columns = _columns(train)
    if not columns:
        raise ValueError("no feature columns available for fitting")
    model = _model_for_columns(columns)
    model.fit(train[columns], train[label])
    return pd.DataFrame(model.predict_proba(test[columns]), columns=model.classes_, index=test.index)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate grouped Track 1 harness classifiers")
    parser.add_argument("--logs", default="data/logs")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--include-dev", action="store_true")
    parser.add_argument("--label", default="label_agent")
    args = parser.parse_args(argv)
    from infra.loader import load_logs

    records = load_logs(args.logs, runs_dir=args.runs, include_dev=args.include_dev)
    features = extract_features(records)
    if args.label not in features or features[args.label].notna().sum() == 0:
        print(f"No labelled rows for {args.label}; add labels to runs/*.csv before evaluation.")
        return 1
    print("Class counts:")
    print(features.loc[features[args.label].notna()].groupby(args.label)["run_id"].nunique().to_string())
    try:
        print(evaluate(features, label=args.label).to_string(index=False))
    except ValueError as error:
        print(f"Evaluation unavailable: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
