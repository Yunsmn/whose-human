"""Track 3 campaign report: is every planned run in the VM log, and what did each run show?

Run it as soon as a VM log lands in the data repo, before the linking itself (`linking.link`,
`linking.hard_cases`). It never prints an address, only counts.

- Coverage: every Track 3 run in the manifests (`<letter>-t3-...`), as missing, fetched only, or submitted.
- Network: per user, setting and network label, how many distinct client addresses and /24 or /64 prefixes the
  runs showed, the IPv6 share, and whether the browser visits shared an address with the agents.
- Tools: the tool sequence of each agent session, per agent and machine.
- Per-visit sentence (VM decision A): for each submitted run, whether the summary contains the keyword of the
  sentence that visit's page carried (`visit_variant`, the keyword is the sentence's id).

`python -m linking.campaign <logs_dir> [--runs runs]`
"""

from __future__ import annotations

import argparse
import ipaddress
import re
from pathlib import Path

import pandas as pd

from infra.loader import load_logs
from linking.sessions import build_sessions, ip_prefix

T3_RUN = re.compile(r"^(?P<member>[a-z])-t3-.*-(?P<site>site\d)-s(?P<setting>\d)-\d{3}$")
SUBMIT = re.compile(r"(?:/r/[^/?]+)?/submit(?:\?.*)?$")


def manifest_runs(runs_dir: str = "runs") -> pd.DataFrame:
    """All Track 3 rows of the manifests, with member, site and setting parsed from the run id."""
    frames = [pd.read_csv(path, dtype=str) for path in sorted(Path(runs_dir).glob("*.csv"))]
    runs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["run_id"])
    parsed = runs["run_id"].astype(str).str.extract(T3_RUN)
    return runs.join(parsed).dropna(subset=["setting"]).reset_index(drop=True)


def coverage(runs: pd.DataFrame, logs: pd.DataFrame) -> pd.DataFrame:
    """Per Track 3 run: requests logged, whether it submitted, and its status."""
    requests = logs.loc[logs["kind"].eq("request") & logs["run_id"].isin(runs["run_id"])].copy()
    requests["is_submit"] = (
        requests["path"].astype(str).str.contains(SUBMIT) & requests["submitted_text"].notna()
    )
    counts = requests.groupby("run_id").agg(n_requests=("run_id", "size"), submitted=("is_submit", "any"))
    result = runs[["run_id", "member", "setting", "site", "label_agent", "network"]].join(counts, on="run_id")
    result["n_requests"] = result["n_requests"].fillna(0).astype(int)
    result["submitted"] = result["submitted"].astype("boolean").fillna(False).astype(bool)
    result["status"] = [
        "missing" if n == 0 else ("submitted" if sub else "fetched only")
        for n, sub in zip(result["n_requests"], result["submitted"], strict=True)
    ]
    return result


def coverage_summary(cover: pd.DataFrame) -> pd.DataFrame:
    table = cover.groupby(["member", "setting", "label_agent", "status"]).size().unstack(fill_value=0)
    return table.reset_index()


def network_summary(sessions: pd.DataFrame) -> pd.DataFrame:
    """Per user, setting and network: distinct addresses and prefixes (counts only), agent/browser overlap."""
    data = sessions.assign(
        setting=sessions["run_id"].str.extract(T3_RUN)["setting"],
        is_v6=sessions["ip"].map(lambda ip: _version(ip) == 6),
    ).dropna(subset=["setting"])
    rows = []
    for (user, setting, network), group in data.groupby(["label_user", "setting", "network"], dropna=False):
        agent_ips = set(group.loc[~group["is_browser"], "ip"].dropna())
        browser_ips = set(group.loc[group["is_browser"], "ip"].dropna())
        rows.append(
            {
                "label_user": user,
                "setting": setting,
                "network": network,
                "sessions": len(group),
                "distinct_ips": group["ip"].nunique(),
                "distinct_prefixes": group["ip"].map(ip_prefix).nunique(),
                "ipv6_share": group["is_v6"].mean(),
                "browser_shares_agent_ip": bool(agent_ips & browser_ips) if browser_ips else None,
            }
        )
    return pd.DataFrame(rows)


def tool_summary(sessions: pd.DataFrame) -> pd.DataFrame:
    agents = sessions.loc[~sessions["is_browser"] & sessions["run_id"].str.contains("-t3-")]
    return agents.groupby(["label_agent", "machine", "tools"]).size().rename("sessions").reset_index()


def variant_reflection(logs: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    """Per submitted Track 3 run: the variant its input page carried, and whether the summary names it."""
    if "visit_variant" not in logs:
        return pd.DataFrame(columns=["run_id", "label_agent", "visit_variant", "reflected"])
    t3 = logs.loc[logs["kind"].eq("request") & logs["run_id"].isin(runs["run_id"])]
    shown = t3.dropna(subset=["visit_variant"]).sort_values("ts").groupby("run_id")["visit_variant"].last()
    texts = t3.dropna(subset=["submitted_text"]).groupby("run_id")["submitted_text"].apply(" ".join)
    data = runs[["run_id", "label_agent"]].join(shown, on="run_id").join(texts, on="run_id")
    data = data.dropna(subset=["visit_variant", "submitted_text"])
    data["reflected"] = [
        bool(re.search(rf"\b{re.escape(str(keyword).lower())}", str(text).lower()))
        for keyword, text in zip(data["visit_variant"], data["submitted_text"], strict=True)
    ]
    return data[["run_id", "label_agent", "visit_variant", "reflected"]]


def _version(ip) -> int | None:
    try:
        return ipaddress.ip_address(ip).version
    except (TypeError, ValueError):
        return None


def _print(title: str, table: pd.DataFrame) -> None:
    print(f"\n{title}")
    print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}") if len(table) else "(none)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track 3 campaign report (counts only, no addresses)")
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    args = parser.parse_args(argv)
    runs = manifest_runs(args.runs)
    logs = load_logs(args.logs_dir, runs_dir=args.runs)
    cover = coverage(runs, logs)
    _print("Coverage: Track 3 runs per member, setting and agent", coverage_summary(cover))
    missing = cover.loc[cover["status"].ne("submitted") & cover["label_agent"].ne("browser"), "run_id"]
    if len(missing):
        print("Agent runs not submitted:", ", ".join(missing))
    sessions = build_sessions(logs.loc[logs["run_id"].isin(runs["run_id"])])
    _print("Network (counts only)", network_summary(sessions))
    _print("Tool sequences of agent sessions", tool_summary(sessions))
    reflected = variant_reflection(logs, runs)
    _print(
        "Per-visit sentence named in the summary (decision A)",
        reflected.groupby("label_agent")["reflected"].agg(["size", "sum", "mean"]).reset_index()
        if len(reflected)
        else reflected,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
