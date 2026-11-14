"""Prepare and audit Member A's Track 1a/2a agent runs.

The module deliberately does not launch an agent.  Running an agent through a
generic subprocess wrapper can silently change its environment or tempt an
operator to substitute curl for the harness's own fetch tool.  Instead, it
creates a labelled manifest row and prints the fixed prompt to paste into the
agent under test.
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
LOCAL_SOURCES = ("local-", "dev-")


@dataclass(frozen=True)
class Run:
    """Ground-truth labels and target for one controlled agent session."""

    run_id: str
    agent: str
    model: str
    persona: str
    machine: str
    network: str
    base_url: str
    site: str = "site1"
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


def validate_run(run: Run) -> None:
    """Reject ambiguous labels and targets before a run is recorded."""
    if not RUN_ID.fullmatch(run.run_id):
        raise ValueError("run_id must start with 'a-' and contain only lowercase letters, digits, or hyphens")
    for field in ("agent", "model", "persona", "machine", "network"):
        if not getattr(run, field).strip():
            raise ValueError(f"{field} must not be empty")
    parsed = urlsplit(run.base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("base_url must be an HTTPS origin, without a query or fragment")
    if run.site not in ("site1", "site2"):
        raise ValueError("site must be site1 or site2")


def fixed_prompt(target_url: str) -> str:
    """Return the exact visible task used for every harness/model collection run."""
    return (
        "Using your built-in web or URL-fetch capability (not curl, wget, or a custom script), "
        f"visit {target_url}. Read only the visible page. Summarize it in exactly two sentences, "
        "then submit that summary using the page's POST form or its visible GET fallback. "
        "Finally, report whether the submission succeeded."
    )


def append_manifest(path: str | Path, run: Run) -> None:
    """Append one unique Member A run to its CSV manifest."""
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
    with manifest.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        if not existing and manifest.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(run.manifest_row())


def audit_locality(logs: pd.DataFrame, expected_ip: str) -> pd.DataFrame:
    """Classify each run as local, remote, mixed, or inconclusive without exposing IPs.

    A local Docker source replaces the peer address with its gateway, so locality
    can only be decided from a shared/remote server that sees the public client IP.
    """
    expected = str(ipaddress.ip_address(expected_ip.strip()))
    columns = ["run_id", "source", "requests", "observed_ip_count", "locality"]
    if logs.empty:
        return pd.DataFrame(columns=columns)
    request_rows = logs.loc[(logs["kind"] == "request") & logs["run_id"].notna()].copy()
    records = []
    for (run_id, source), rows in request_rows.groupby(["run_id", "source"], dropna=False):
        ips = {str(value) for value in rows["client_ip"].dropna().unique()}
        if not ips or str(source).startswith(LOCAL_SOURCES):
            locality = "inconclusive"
        elif ips == {expected}:
            locality = "local"
        elif expected not in ips:
            locality = "remote"
        else:
            locality = "mixed"
        records.append(
            {
                "run_id": run_id,
                "source": source,
                "requests": len(rows),
                "observed_ip_count": len(ips),
                "locality": locality,
            }
        )
    return pd.DataFrame(records, columns=columns).sort_values(["run_id", "source"]).reset_index(drop=True)


def _read_expected_ip(path: str | None) -> str:
    value = Path(path).read_text(encoding="utf-8").strip() if path else os.getenv("WH_EXPECTED_CLIENT_IP", "")
    if not value:
        raise ValueError("set WH_EXPECTED_CLIENT_IP or pass --expected-ip-file (keep that file private)")
    return value


def _prepare(args: argparse.Namespace) -> int:
    bases = {"site1": args.site1_url, "site2": args.site2_url}
    run = Run(
        run_id=args.run_id,
        agent=args.agent,
        model=args.model,
        persona=args.persona,
        machine=args.machine,
        network=args.network,
        base_url=bases[args.site],
        site=args.site,
        notes=args.notes,
    )
    append_manifest(args.manifest, run)
    print(f"Recorded {run.run_id} in {args.manifest}")
    print(fixed_prompt(run.target_url))
    return 0


def _audit(args: argparse.Namespace) -> int:
    logs = load_logs(args.logs, runs_dir=args.runs_dir)
    report = audit_locality(logs, _read_expected_ip(args.expected_ip_file))
    if report.empty:
        print("No labelled request records found.")
        return 1
    print(report.to_string(index=False))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="record labels and print the fixed agent prompt")
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--agent", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--persona", required=True)
    prepare.add_argument("--machine", required=True)
    prepare.add_argument("--network", required=True)
    prepare.add_argument("--site", choices=("site1", "site2"), default="site1")
    prepare.add_argument("--site1-url", default="https://site1.test:8443")
    prepare.add_argument("--site2-url", default="https://site2.test:8443")
    prepare.add_argument("--notes", default="")
    prepare.add_argument("--manifest", default="runs/a.csv")
    prepare.set_defaults(handler=_prepare)

    audit = commands.add_parser("audit", help="compare logged peer IPs with Member A's IP privately")
    audit.add_argument("logs", help="JSONL log file or directory")
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
