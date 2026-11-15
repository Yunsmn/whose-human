"""Track 3b environment signatures and stability/collision measurements.

The signature intentionally excludes IP addresses, cookies, paths, site names,
timing, and submitted text.  It consumes the per-request output contract from
``harness.features`` and hashes only transport/runtime characteristics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import combinations

import pandas as pd

from infra.loader import load_logs

SIGNATURE_VERSION = "env-v1"
SIGNATURE_COLUMNS = [
    "tls_ja4",
    "tls_ja3_md5",
    "tls_max_version",
    "tls_groups",
    "tls_sigalgs",
    "tls_ext_order_hash",
    "tls_record_version",
    "http_version",
    "http_header_order_hash",
    "http_header_set_hash",
    "http_header_case",
    "http_ua_family",
    "http_ua_version",
    "http_accept_encoding",
    "h2_fp",
]
REPORT_FIELDS = [
    "run_count",
    "machine_labelled_run_count",
    "signature_coverage",
    "within_machine_pairs",
    "within_machine_match_rate",
    "between_machine_pairs",
    "between_machine_collision_rate",
    "cross_agent_within_machine_pairs",
    "cross_agent_within_machine_match_rate",
]
RUN_COLUMNS = [
    "run_id",
    "environment_signature",
    "request_count",
    "signature_variants",
    "label_user",
    "label_agent",
    "machine",
    "network",
]


def _normalise(value) -> str | None:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def add_environment_signatures(features: pd.DataFrame) -> pd.DataFrame:
    """Add a versioned, deterministic signature to per-request feature rows."""
    missing = sorted(set(SIGNATURE_COLUMNS) - set(features.columns))
    if missing:
        raise ValueError(f"feature frame is missing signature columns: {', '.join(missing)}")
    result = features.copy()
    signatures = []
    populated = []
    for _, row in result.iterrows():
        values = {column: _normalise(row[column]) for column in SIGNATURE_COLUMNS}
        present = sum(value is not None for value in values.values())
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(f"{SIGNATURE_VERSION}:{payload}".encode()).hexdigest()[:24]
        signatures.append(f"{SIGNATURE_VERSION}:{digest}" if present else None)
        populated.append(present)
    result["environment_signature"] = signatures
    result["environment_feature_count"] = populated
    return result


def per_run_signatures(signed: pd.DataFrame) -> pd.DataFrame:
    """Collapse repeated requests to one modal signature per experimental run."""
    required = {"run_id", "environment_signature"}
    missing = sorted(required - set(signed.columns))
    if missing:
        raise ValueError(f"signed frame is missing columns: {', '.join(missing)}")
    rows = []
    labelled = signed.loc[signed["run_id"].notna()].copy()
    for run_id, group in labelled.groupby("run_id", sort=True):
        available = group["environment_signature"].dropna()
        counts = available.value_counts()
        signature = sorted(counts[counts == counts.max()].index)[0] if not counts.empty else None
        record = {
            "run_id": run_id,
            "environment_signature": signature,
            "request_count": len(group),
            "signature_variants": available.nunique(),
        }
        for column in ("label_user", "label_agent", "machine", "network"):
            if column in group:
                values = group[column].dropna().astype(str).unique()
                record[column] = values[0] if len(values) == 1 else None
        rows.append(record)
    return pd.DataFrame(rows, columns=RUN_COLUMNS)


def _pair_rate(rows: pd.DataFrame, same_machine: bool, cross_agent: bool = False) -> tuple[int, float | None]:
    matches = []
    usable = rows.dropna(subset=["environment_signature", "machine"])
    for (_, left), (_, right) in combinations(usable.iterrows(), 2):
        machines_match = left["machine"] == right["machine"]
        if machines_match != same_machine:
            continue
        if cross_agent and (
            pd.isna(left.get("label_agent"))
            or pd.isna(right.get("label_agent"))
            or left.get("label_agent") == right.get("label_agent")
        ):
            continue
        matches.append(left["environment_signature"] == right["environment_signature"])
    return len(matches), float(sum(matches) / len(matches)) if matches else None


def signature_report(signed: pd.DataFrame) -> dict[str, int | float | None]:
    """Measure within-machine stability and between-machine exact collisions per run."""
    runs = per_run_signatures(signed)
    labelled = runs.dropna(subset=["machine"])
    within_n, within_rate = _pair_rate(labelled, same_machine=True)
    between_n, between_rate = _pair_rate(labelled, same_machine=False)
    cross_n, cross_rate = _pair_rate(labelled, same_machine=True, cross_agent=True)
    covered = runs["environment_signature"].notna().sum() if not runs.empty else 0
    return {
        "run_count": len(runs),
        "machine_labelled_run_count": len(labelled),
        "signature_coverage": float(covered / len(runs)) if len(runs) else 0.0,
        "within_machine_pairs": within_n,
        "within_machine_match_rate": within_rate,
        "between_machine_pairs": between_n,
        "between_machine_collision_rate": between_rate,
        "cross_agent_within_machine_pairs": cross_n,
        "cross_agent_within_machine_match_rate": cross_rate,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("logs", help="private JSONL log file or directory")
    result.add_argument("--runs-dir", default="runs")
    result.add_argument("--output", help="optional CSV for per-run signatures (must remain private)")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        from harness.features import extract_features
    except ImportError as exc:
        parser().error("harness.features is required; merge Member C's Track 1c feature branch first")
        raise AssertionError from exc
    logs = load_logs(args.logs, runs_dir=args.runs_dir)
    # Machine and network are manifest columns and therefore need to be restored
    # after extraction, whose public ID contract intentionally stays small.
    features = extract_features(logs)
    metadata_columns = [column for column in ("run_id", "machine", "network") if column in logs]
    if "run_id" in metadata_columns:
        metadata = logs[metadata_columns].drop_duplicates("run_id")
        features = features.merge(metadata, on="run_id", how="left")
    signed = add_environment_signatures(features)
    report = signature_report(signed)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output:
        per_run_signatures(signed).to_csv(args.output, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
