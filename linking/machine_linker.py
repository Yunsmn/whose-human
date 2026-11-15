"""Build and evaluate a probabilistic same-PC linker for local-model sessions.

The linker compares benchmark *profiles*, not individual requests.  Ground
truth comes from the manifest's pseudonymous ``machine`` label.  A high score
means "probably the same enrolled PC"; it is never proof of a human identity.
"""

from __future__ import annotations

import argparse
import json
import statistics
from itertools import combinations
from pathlib import Path

import pandas as pd

PROFILE_METADATA = ["session_id", "machine", "agent", "model", "engine", "quantization"]
BENCHMARK_METRICS = [
    "wall_total_s",
    "first_chunk_s",
    "chunk_interval_median_s",
    "chunk_interval_p95_s",
    "chunk_interval_stdev_s",
    "load_s",
    "model_total_s",
    "prompt_tokens_per_s",
    "eval_tokens_per_s",
]
PAIR_METADATA = ["left_session", "right_session", "same_machine"]
EQUALITY_FEATURES = ["model_match", "engine_match", "quantization_match"]
MODEL_VERSION = "same-pc-v1"


def load_jsonl(paths: list[str | Path]) -> pd.DataFrame:
    records = []
    for value in paths:
        path = Path(value)
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"record at {path}:{line_number} is not an object")
                records.append(record)
    return pd.DataFrame(records)


def _one_value(group: pd.DataFrame, column: str):
    values = group[column].dropna().astype(str).unique() if column in group else []
    if len(values) != 1:
        raise ValueError(f"session {group.name!r} must have exactly one {column} value")
    return values[0]


def _safe_case(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")


def build_profiles(records: pd.DataFrame) -> pd.DataFrame:
    """Aggregate repeated benchmark records into one feature row per agent session."""
    required = set(PROFILE_METADATA + ["case", "success"])
    missing = sorted(required - set(records.columns))
    if missing:
        raise ValueError(f"benchmark records are missing columns: {', '.join(missing)}")
    usable = records.loc[records["success"].fillna(False).astype(bool)].copy()
    if usable.empty:
        return pd.DataFrame(columns=PROFILE_METADATA + ["measurement_count", "case_coverage"])
    for metric in BENCHMARK_METRICS:
        if metric not in usable:
            usable[metric] = None
        usable[metric] = pd.to_numeric(usable[metric], errors="coerce")
    cases = sorted(usable["case"].dropna().astype(str).unique())
    rows = []
    for session_id, group in usable.groupby("session_id", sort=True):
        group.name = session_id
        row = {column: _one_value(group, column) for column in PROFILE_METADATA}
        row["measurement_count"] = len(group)
        row["case_coverage"] = group["case"].nunique() / len(cases) if cases else 0.0
        for case in cases:
            case_rows = group.loc[group["case"].astype(str) == case]
            case_name = _safe_case(case)
            for metric in BENCHMARK_METRICS:
                values = case_rows[metric].dropna().astype(float)
                row[f"{case_name}__{metric}__median"] = values.median() if not values.empty else None
                if metric == "eval_tokens_per_s":
                    row[f"{case_name}__{metric}__iqr"] = (
                        values.quantile(0.75) - values.quantile(0.25) if len(values) > 1 else 0.0
                    )
        phases = (
            group["phase"].astype(str)
            if "phase" in group
            else pd.Series("", index=group.index, dtype="string")
        )
        first_rows = group.loc[phases == "first"]
        first = first_rows["wall_total_s"].dropna()
        first_case = first_rows["case"].iloc[0] if not first_rows.empty else None
        warm = group.loc[(phases == "warm") & (group["case"] == first_case), "wall_total_s"].dropna()
        row["warmup_ratio"] = (
            float(first.median() / warm.median())
            if not first.empty and not warm.empty and warm.median()
            else None
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("session_id").reset_index(drop=True)


def _relative_difference(left, right) -> float | None:
    if pd.isna(left) or pd.isna(right):
        return None
    left_value, right_value = float(left), float(right)
    return abs(left_value - right_value) / (abs(left_value) + abs(right_value) + 1e-12)


def pair_row(left: pd.Series, right: pd.Series, numeric_columns: list[str]) -> dict:
    """Create symmetric comparison features for two benchmark sessions."""
    record = {
        "left_session": left["session_id"],
        "right_session": right["session_id"],
        "same_machine": int(left["machine"] == right["machine"]),
        "cross_agent": int(left["agent"] != right["agent"]),
        "model_match": int(left["model"] == right["model"]),
        "engine_match": int(left["engine"] == right["engine"]),
        "quantization_match": int(left["quantization"] == right["quantization"]),
    }
    differences = []
    for column in numeric_columns:
        difference = _relative_difference(left.get(column), right.get(column))
        record[f"rel__{column}"] = difference
        if difference is not None:
            differences.append(difference)
    record["relative_difference_median"] = statistics.median(differences) if differences else None
    record["relative_difference_max"] = max(differences) if differences else None
    record["comparable_feature_count"] = len(differences)
    return record


def _numeric_profile_columns(profiles: pd.DataFrame) -> list[str]:
    excluded = set(PROFILE_METADATA)
    return [
        column
        for column in profiles.columns
        if column not in excluded and pd.api.types.is_numeric_dtype(profiles[column])
    ]


def build_pairs(
    profiles: pd.DataFrame,
    cross_agent_only: bool = True,
    negative_ratio: int | None = 3,
    random_state: int = 42,
) -> pd.DataFrame:
    """Build labelled session pairs and optionally limit the negative-pair explosion."""
    missing = sorted(set(PROFILE_METADATA) - set(profiles.columns))
    if missing:
        raise ValueError(f"profiles are missing columns: {', '.join(missing)}")
    numeric = _numeric_profile_columns(profiles)
    rows = []
    for (_, left), (_, right) in combinations(profiles.iterrows(), 2):
        if cross_agent_only and left["agent"] == right["agent"]:
            continue
        rows.append(pair_row(left, right, numeric))
    pairs = pd.DataFrame(rows)
    if pairs.empty or negative_ratio is None:
        return pairs
    positives = pairs.loc[pairs["same_machine"] == 1]
    negatives = pairs.loc[pairs["same_machine"] == 0]
    limit = len(positives) * negative_ratio
    if limit and len(negatives) > limit:
        negatives = negatives.sample(n=limit, random_state=random_state)
    return (
        pd.concat([positives, negatives], ignore_index=True)
        .sample(frac=1, random_state=random_state)
        .reset_index(drop=True)
    )


def model_feature_columns(pairs: pd.DataFrame) -> list[str]:
    excluded = set(PAIR_METADATA)
    return [
        column
        for column in pairs.columns
        if column not in excluded and pd.api.types.is_numeric_dtype(pairs[column])
    ]


def fit_linker(pairs: pd.DataFrame, random_state: int = 42) -> dict:
    """Fit a probability-producing baseline and return a serialisable bundle."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if pairs.empty or pairs["same_machine"].nunique() != 2:
        raise ValueError("training requires both same-machine and different-machine pairs")
    features = model_feature_columns(pairs)
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "classifier",
                LogisticRegression(class_weight="balanced", max_iter=2000, random_state=random_state),
            ),
        ]
    )
    pipeline.fit(pairs[features], pairs["same_machine"])
    return {"version": MODEL_VERSION, "pipeline": pipeline, "features": features}


def score_pairs(bundle: dict, pairs: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(bundle["features"]) - set(pairs.columns))
    if missing:
        raise ValueError(f"pairs are missing model features: {', '.join(missing)}")
    result = pairs.copy()
    result["same_pc_probability"] = bundle["pipeline"].predict_proba(result[bundle["features"]])[:, 1]
    return result


def add_decisions(scored: pd.DataFrame, probable_same_threshold: float = 0.95) -> pd.DataFrame:
    """Add a conservative decision; every sub-threshold pair remains unknown."""
    if not 0 < probable_same_threshold <= 1:
        raise ValueError("probable-same threshold must be in (0, 1]")
    result = scored.copy()
    result["decision"] = "unknown"
    result.loc[result["same_pc_probability"] >= probable_same_threshold, "decision"] = "probably_same_pc"
    return result


def evaluate_profiles(
    profiles: pd.DataFrame,
    threshold: float = 0.95,
    test_fraction: float = 0.34,
    random_state: int = 42,
) -> tuple[dict, dict]:
    """Hold out entire machines, then train and evaluate cross-agent session pairs."""
    from sklearn.metrics import (
        brier_score_loss,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split

    machines = sorted(profiles["machine"].dropna().astype(str).unique())
    if len(machines) < 6:
        raise ValueError("evaluation requires at least six labelled machines")
    train_machines, test_machines = train_test_split(
        machines, test_size=test_fraction, random_state=random_state
    )
    train = profiles.loc[profiles["machine"].isin(train_machines)]
    test = profiles.loc[profiles["machine"].isin(test_machines)]
    train_pairs = build_pairs(train, random_state=random_state)
    test_pairs = build_pairs(test, negative_ratio=None, random_state=random_state)
    bundle = fit_linker(train_pairs, random_state=random_state)
    scored = score_pairs(bundle, test_pairs)
    truth = scored["same_machine"].astype(int)
    probability = scored["same_pc_probability"]
    predicted = (probability >= threshold).astype(int)
    true_negative, false_positive, false_negative, true_positive = confusion_matrix(
        truth, predicted, labels=[0, 1]
    ).ravel()
    report = {
        "model_version": MODEL_VERSION,
        "train_machines": len(train_machines),
        "test_machines": len(test_machines),
        "train_pairs": len(train_pairs),
        "test_pairs": len(test_pairs),
        "threshold": threshold,
        "precision": float(precision_score(truth, predicted, zero_division=0)),
        "recall": float(recall_score(truth, predicted, zero_division=0)),
        "f1": float(f1_score(truth, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(truth, probability)) if truth.nunique() == 2 else None,
        "brier": float(brier_score_loss(truth, probability)),
        "true_positive": int(true_positive),
        "false_positive": int(false_positive),
        "false_negative": int(false_negative),
        "true_negative": int(true_negative),
        "false_match_rate": float(false_positive / (false_positive + true_negative))
        if false_positive + true_negative
        else None,
        "false_nonmatch_rate": float(false_negative / (false_negative + true_positive))
        if false_negative + true_positive
        else None,
    }
    return bundle, report


def _write_json(path: str | Path, value: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    profiles = commands.add_parser("profiles", help="aggregate private benchmark JSONL into session profiles")
    profiles.add_argument("inputs", nargs="+")
    profiles.add_argument("--output", default="data/benchmarks/profiles.csv")

    train = commands.add_parser("train", help="train and evaluate with whole-machine holdout")
    train.add_argument("profiles")
    train.add_argument("--model-output", default="data/benchmarks/same-pc.joblib")
    train.add_argument("--report-output", default="data/benchmarks/same-pc-report.json")
    train.add_argument("--threshold", type=float, default=0.95)

    score = commands.add_parser("score", help="score all cross-agent pairs in a profile CSV")
    score.add_argument("profiles")
    score.add_argument("--model", default="data/benchmarks/same-pc.joblib")
    score.add_argument("--output", default="data/benchmarks/same-pc-scores.csv")
    score.add_argument("--threshold", type=float, default=0.95)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "profiles":
        profiles = build_profiles(load_jsonl(args.inputs))
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        profiles.to_csv(args.output, index=False)
        print(f"wrote {len(profiles)} session profiles to {args.output}")
        return 0
    profiles = pd.read_csv(args.profiles)
    if args.command == "train":
        import joblib

        bundle, report = evaluate_profiles(profiles, threshold=args.threshold)
        Path(args.model_output).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, args.model_output)
        _write_json(args.report_output, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    import joblib

    bundle = joblib.load(args.model)
    scored = add_decisions(
        score_pairs(bundle, build_pairs(profiles, negative_ratio=None)),
        probable_same_threshold=args.threshold,
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(args.output, index=False)
    print(f"wrote {len(scored)} pair scores to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
