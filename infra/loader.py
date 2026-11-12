"""Load server JSONL logs and join the team's run manifests."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pandas as pd

LOG_COLUMNS = [
    "ts",
    "kind",
    "source",
    "conn_id",
    "req_index_on_conn",
    "conn_ts",
    "client_ip",
    "ip",
    "client_port",
    "site",
    "sni",
    "alpn_offered",
    "alpn_negotiated",
    "tls_version",
    "tls_cipher",
    "client_hello_hex",
    "ja3",
    "ja3_md5",
    "ja4",
    "ja4_r",
    "http_version",
    "method",
    "path",
    "query",
    "run_id",
    "session_id",
    "headers",
    "header_order",
    "h2_settings",
    "h2_window_update",
    "h2_priority",
    "h2_pseudo_order",
    "h2_fp",
    "body",
    "body_truncated",
    "body_len",
    "submitted_text",
    "status",
    "tls_error",
    "label_agent",
    "label_model",
    "label_user",
]
MANIFEST_COLUMNS = [
    "run_id",
    "label_agent",
    "label_model",
    "label_user",
    "machine",
    "network",
    "notes",
]


def _log_files(paths_or_dir) -> list[Path]:
    if isinstance(paths_or_dir, (str, Path)):
        path = Path(paths_or_dir)
        return sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    return [Path(path) for path in paths_or_dir]


def load_logs(paths_or_dir, runs_dir="runs", include_dev=False) -> pd.DataFrame:
    """Read JSONL logs, warn with malformed count, filter dev runs and join labels."""
    records = []
    malformed = 0
    for path in _log_files(paths_or_dir):
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("record must be an object")
                except (json.JSONDecodeError, ValueError) as exc:
                    malformed += 1
                    warnings.warn(
                        f"Skipping malformed line {line_number} in {path}: {exc}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    continue
                record.setdefault("source", path.stem)
                if "ip" not in record and "client_ip" in record:
                    record["ip"] = record["client_ip"]
                records.append(record)
    if malformed:
        warnings.warn(f"Skipped {malformed} malformed log line(s)", RuntimeWarning, stacklevel=2)
    frame = pd.DataFrame(records)
    if "run_id" not in frame:
        frame["run_id"] = pd.Series(dtype="object")
    if not include_dev:
        frame = frame[~frame["run_id"].fillna("").astype(str).str.startswith("dev-")]
    manifests = []
    for path in sorted(Path(runs_dir).glob("*.csv")) if Path(runs_dir).exists() else []:
        try:
            manifests.append(pd.read_csv(path, dtype=str))
        except (OSError, pd.errors.ParserError) as exc:
            warnings.warn(
                f"Could not read run manifest {path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    if manifests:
        manifest = pd.concat(manifests, ignore_index=True)
        if "run_id" in manifest:
            duplicated = sorted(set(manifest.loc[manifest["run_id"].duplicated(), "run_id"]))
            if duplicated:
                warnings.warn(
                    f"run_id listed more than once in runs/, keeping the last entry: {duplicated}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            manifest = manifest.drop_duplicates("run_id", keep="last")
            labels = [column for column in MANIFEST_COLUMNS if column in manifest]
            frame = frame.merge(manifest[labels], how="left", on="run_id", suffixes=("", "_manifest"))
            for column in ("label_agent", "label_model", "label_user"):
                duplicate = column + "_manifest"
                if duplicate in frame:
                    frame[column] = frame[duplicate].combine_first(frame.get(column))
                    frame = frame.drop(columns=duplicate)
    if "ip" not in frame:
        frame["ip"] = frame.get("client_ip")
    for column in LOG_COLUMNS:
        if column not in frame:
            frame[column] = None
    extra = [
        column
        for column in frame.columns
        if column not in LOG_COLUMNS and column not in ("machine", "network", "notes")
    ]
    return frame[
        LOG_COLUMNS + [column for column in ("machine", "network", "notes") if column in frame] + extra
    ].reset_index(drop=True)
