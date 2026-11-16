"""Extract and audit agent-written text for Member A's Track 2a corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from infra.loader import MANIFEST_COLUMNS, load_logs

PLACEHOLDER_TEXT = "YOUR_SUMMARY"
OUTCOME_COLUMNS = [
    "run_id",
    "label_agent",
    "label_model",
    "request_count",
    "submission_count",
    "placeholder_count",
    "outcome",
]
CORPUS_COLUMNS = [
    "run_id",
    "ts",
    "site",
    "method",
    "submitted_text",
    "status",
    *[column for column in MANIFEST_COLUMNS if column != "run_id"],
]


def load_manifest(path: str | Path) -> pd.DataFrame:
    """Load a run manifest and reject missing fields or ambiguous run ids."""
    frame = pd.read_csv(path, dtype=str).fillna("")
    missing = sorted(set(MANIFEST_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"manifest is missing columns: {', '.join(missing)}")
    if frame["run_id"].duplicated().any():
        raise ValueError("manifest contains duplicate run_id values")
    return frame[MANIFEST_COLUMNS]


def _non_empty_submissions(logs: pd.DataFrame) -> pd.DataFrame:
    required = {"kind", "submitted_text"}
    if logs.empty or not required <= set(logs.columns):
        return logs.iloc[0:0].copy()
    text = logs["submitted_text"]
    return logs.loc[(logs["kind"] == "request") & text.notna() & text.astype(str).str.strip().ne("")].copy()


def _placeholder_mask(submissions: pd.DataFrame) -> pd.Series:
    if submissions.empty or "submitted_text" not in submissions:
        return pd.Series(False, index=submissions.index, dtype=bool)
    return submissions["submitted_text"].astype(str).str.strip().eq(PLACEHOLDER_TEXT)


def submission_corpus(logs: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    """Return labelled submissions, excluding the literal GET placeholder."""
    submitted = _non_empty_submissions(logs)
    submitted = submitted.loc[~_placeholder_mask(submitted)].copy()
    if submitted.empty:
        return pd.DataFrame(columns=CORPUS_COLUMNS)
    request_columns = ["run_id", "ts", "site", "method", "submitted_text", "status"]
    missing = sorted(set(request_columns) - set(submitted.columns))
    if missing:
        raise ValueError(f"logs are missing columns: {', '.join(missing)}")
    return (
        submitted[request_columns]
        .merge(manifest[MANIFEST_COLUMNS], on="run_id", how="inner", validate="many_to_one")
        .sort_values(["run_id", "ts"])
        .reset_index(drop=True)[CORPUS_COLUMNS]
    )


def run_outcomes(logs: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    """Classify 2a submission behavior for every planned run, including absent runs."""
    records: list[dict[str, object]] = []
    for planned in manifest[MANIFEST_COLUMNS].to_dict("records"):
        run_id = planned["run_id"]
        if logs.empty or not {"run_id", "kind"} <= set(logs.columns):
            rows = logs.iloc[0:0]
        else:
            rows = logs.loc[(logs["run_id"] == run_id) & (logs["kind"] == "request")]
        submissions = _non_empty_submissions(rows)
        placeholder_mask = _placeholder_mask(submissions)
        placeholders = submissions.loc[placeholder_mask]
        corpus_submissions = submissions.loc[~placeholder_mask]
        methods = set(corpus_submissions.get("method", pd.Series(dtype=str)).dropna().astype(str).str.upper())
        paths = rows.get("path", pd.Series(index=rows.index, dtype=str)).fillna("").astype(str)
        input_fetches = rows.loc[paths.str.contains("/input.html", regex=False)]
        if "POST" in methods:
            outcome = "post_submitted"
        elif "GET" in methods:
            outcome = "get_submitted"
        elif not placeholders.empty:
            outcome = "placeholder_submitted"
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
                "submission_count": len(corpus_submissions),
                "placeholder_count": len(placeholders),
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
    try:
        manifest = load_manifest(args.manifest)
        logs = load_logs(args.logs, runs_dir=args.runs_dir)
        outcomes = run_outcomes(logs, manifest)
        print(json.dumps(outcomes["outcome"].value_counts().sort_index().to_dict(), indent=2))
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            submission_corpus(logs, manifest).to_csv(output, index=False)
        return 0
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        parser().error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
