"""Prepare and audit Member A's combined Track 1a and 2a agent runs.

The runner does not launch or wrap an agent. The operator pastes one short,
visible task into the harness under test, and the agent chooses its normal web
tool. That client choice is part of the measured HTTP/TLS behavior.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from infra.loader import load_logs

MANIFEST_FIELDS = [
    "run_id",
    "label_agent",
    "label_model",
    "label_user",
    "machine",
    "network",
    "notes",
]
RUN_ID = re.compile(r"^a-[a-z0-9][a-z0-9-]*$")
LOCAL_SOURCE_PREFIXES = ("local-", "dev-")
REPORT_COLUMNS = [
    "run_id",
    "label_agent",
    "source",
    "requests",
    "observed_ip_count",
    "locality",
]


@dataclass(frozen=True)
class AgentRun:
    """Ground-truth labels and target origin for one controlled run."""

    run_id: str
    agent: str
    model: str
    persona: str
    machine: str
    network: str
    base_url: str
    notes: str = ""

    @property
    def target_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/r/{self.run_id}/input.html"

    def manifest_row(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "label_agent": self.agent,
            "label_model": self.model,
            "label_user": self.persona,
            "machine": self.machine,
            "network": self.network,
            "notes": self.notes,
        }


def validate_run(run: AgentRun) -> None:
    if not RUN_ID.fullmatch(run.run_id):
        raise ValueError("run_id must start with 'a-' and contain lowercase letters, digits, or hyphens")
    for field in ("agent", "model", "persona", "machine", "network"):
        if not getattr(run, field).strip():
            raise ValueError(f"{field} must not be empty")
    parsed = urlsplit(run.base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("base_url must be an HTTPS origin without a query or fragment")


def fixed_fetch_prompt(target_url: str) -> str:
    """Return the same visible 1a/2a task for every harness run."""
    return (
        f"Visit {target_url}, summarize the page in two sentences, and submit your summary. "
        "Use the web or network tool you would normally choose for this task."
    )


def append_manifest(path: str | Path, run: AgentRun) -> None:
    """Append one unique, validated row to Member A's run manifest."""
    validate_run(run)
    manifest = Path(path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, str]] = []
    if manifest.exists() and manifest.stat().st_size:
        with manifest.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != MANIFEST_FIELDS:
                raise ValueError(f"manifest header must be {','.join(MANIFEST_FIELDS)}")
            existing = list(reader)
    if any(row["run_id"] == run.run_id for row in existing):
        raise ValueError(f"run_id already exists in manifest: {run.run_id}")
    write_header = not manifest.exists() or manifest.stat().st_size == 0
    with manifest.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow(run.manifest_row())


def parse_expected_ips(value: str) -> frozenset[str]:
    """Parse newline/comma-separated private egress addresses into canonical form."""
    parts = re.split(r"[,\s]+", value.strip())
    addresses = frozenset(str(ipaddress.ip_address(part)) for part in parts if part)
    if not addresses:
        raise ValueError("at least one expected client IP is required")
    return addresses


def audit_locality(logs: pd.DataFrame, expected_ips: str | frozenset[str]) -> pd.DataFrame:
    """Classify run locality without returning or printing any address."""
    expected = parse_expected_ips(expected_ips) if isinstance(expected_ips, str) else expected_ips
    if not expected:
        raise ValueError("at least one expected client IP is required")
    if logs.empty or not {"kind", "run_id", "source", "client_ip"} <= set(logs.columns):
        return pd.DataFrame(columns=REPORT_COLUMNS)
    rows = logs.loc[(logs["kind"] == "request") & logs["run_id"].notna()].copy()
    records: list[dict[str, object]] = []
    group_columns = ["run_id", "source"]
    for (run_id, source), group in rows.groupby(group_columns, dropna=False):
        observed: set[str] = set()
        for value in group["client_ip"].dropna().astype(str).unique():
            try:
                observed.add(str(ipaddress.ip_address(value)))
            except ValueError:
                continue
        source_text = str(source)
        if not observed or source_text.startswith(LOCAL_SOURCE_PREFIXES):
            locality = "inconclusive"
        elif observed <= expected:
            locality = "local"
        elif observed.isdisjoint(expected):
            locality = "remote"
        else:
            locality = "mixed"
        labels = group["label_agent"].dropna().astype(str) if "label_agent" in group else pd.Series(dtype=str)
        records.append(
            {
                "run_id": str(run_id),
                "label_agent": labels.iloc[0] if not labels.empty else None,
                "source": source_text,
                "requests": len(group),
                "observed_ip_count": len(observed),
                "locality": locality,
            }
        )
    return (
        pd.DataFrame(records, columns=REPORT_COLUMNS).sort_values(["run_id", "source"]).reset_index(drop=True)
    )


def locality_summary(report: pd.DataFrame) -> pd.DataFrame:
    """Count run-level locality outcomes per harness label."""
    columns = ["label_agent", "locality", "runs"]
    if report.empty:
        return pd.DataFrame(columns=columns)
    labelled = report.assign(label_agent=report["label_agent"].fillna("unlabelled"))
    return (
        labelled.groupby(["label_agent", "locality"], dropna=False)
        .size()
        .rename("runs")
        .reset_index()[columns]
        .sort_values(["label_agent", "locality"])
        .reset_index(drop=True)
    )


def _read_expected_ips(path: str | None) -> frozenset[str]:
    value = Path(path).read_text(encoding="utf-8") if path else os.getenv("WH_EXPECTED_CLIENT_IPS", "")
    if not value.strip():
        raise ValueError("set WH_EXPECTED_CLIENT_IPS or pass --expected-ip-file; keep the addresses private")
    return parse_expected_ips(value)


def _prepare(args: argparse.Namespace) -> int:
    run = AgentRun(
        run_id=args.run_id,
        agent=args.agent,
        model=args.model,
        persona=args.persona,
        machine=args.machine,
        network=args.network,
        base_url=args.base_url,
        notes=args.notes,
    )
    append_manifest(args.manifest, run)
    print(f"Recorded {run.run_id} in {args.manifest}")
    print(fixed_fetch_prompt(run.target_url))
    return 0


def _audit(args: argparse.Namespace) -> int:
    logs = load_logs(args.logs, runs_dir=args.runs_dir)
    report = audit_locality(logs, _read_expected_ips(args.expected_ip_file))
    if report.empty:
        print("No labelled request records found.")
        return 1
    print(report.to_string(index=False))
    print("\nRun counts by harness and locality:")
    print(locality_summary(report).to_string(index=False))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="record labels and print the fixed visible 1a/2a task")
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--agent", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--persona", required=True)
    prepare.add_argument("--machine", required=True)
    prepare.add_argument("--network", required=True)
    prepare.add_argument("--base-url", required=True, help="instrumented HTTPS origin")
    prepare.add_argument("--notes", default="")
    prepare.add_argument("--manifest", default="runs/a.csv")
    prepare.set_defaults(handler=_prepare)

    audit = commands.add_parser("audit", help="compare logged peers with private expected addresses")
    audit.add_argument("logs", help="private JSONL log file or directory")
    audit.add_argument("--runs-dir", default="runs")
    audit.add_argument("--expected-ip-file")
    audit.set_defaults(handler=_audit)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        parser().error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
