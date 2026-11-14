"""Extract and audit agent-written text for Member A's Track 2a corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from infra.loader import MANIFEST_COLUMNS, load_logs

OUTCOME_COLUMNS = [
    "run_id",
    "label_agent",
    "label_model",
    "request_count",
    "submission_count",
    "outcome",
]


def load_manifest(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str).fillna("")
    missing = sorted(set(MANIFEST_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"manifest is missing columns: {', '.join(missing)}")
    if frame["run_id"].duplicated().any():
        raise ValueError("manifest contains duplicate run_id values")
    return frame


def submission_corpus(logs: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    """Return one row per non-empty submitted text, with manifest labels."""
    submitted = logs.loc[
        (logs["kind"] == "request")
        & logs["submitted_text"].notna()
        & logs["submitted_text"].astype(str).str.strip().ne("")
    ].copy()
    columns = ["run_id", "ts", "site", "method", "submitted_text", "status"]
    submitted = submitted[columns]
    labels = manifest[MANIFEST_COLUMNS]
    return (
        submitted.merge(labels, on="run_id", how="inner").sort_values(["run_id", "ts"]).reset_index(drop=True)
    )


def run_outcomes(logs: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    """Classify submission behavior for every planned run, including absent runs."""
    records = []
    for _, planned in manifest.iterrows():
        run_id = planned["run_id"]
        rows = logs.loc[(logs["run_id"] == run_id) & (logs["kind"] == "request")]
        submissions = rows.loc[rows["submitted_text"].notna()]
        methods = set(submissions["method"].dropna().astype(str).str.upper())
        input_fetches = rows[rows["path"].astype(str).str.contains("/input.html", regex=False)]
        if "POST" in methods:
            outcome = "post_submitted"
        elif "GET" in methods:
            outcome = "get_submitted"
        elif not input_fetches.empty:
            outcome = "fetched_but_not_submitted"
        elif not rows.empty:
            outcome = "request_observed_without_input_fetch"
        else:
            outcome = "no_request_observed"
        records.append(
            {
                "run_id": run_id,
                "label_agent": planned["label_agent"],
                "label_model": planned["label_model"],
                "request_count": len(rows),
                "submission_count": len(submissions),
                "outcome": outcome,
            }
        )
    return pd.DataFrame(records, columns=OUTCOME_COLUMNS)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("logs", help="private JSONL log file or directory")
    result.add_argument("--manifest", default="runs/a.csv")
    result.add_argument("--runs-dir", default="runs")
    result.add_argument("--output", help="optional private CSV containing submitted text")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    logs = load_logs(args.logs, runs_dir=args.runs_dir)
    outcomes = run_outcomes(logs, manifest)
    print(json.dumps(outcomes["outcome"].value_counts().sort_index().to_dict(), indent=2))
    if args.output:
        submission_corpus(logs, manifest).to_csv(args.output, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
