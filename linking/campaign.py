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
import json
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
    """Per user, setting and network: distinct addresses and /24 or /64 prefixes, and the IPv6 share."""
    data = _with_setting(sessions)
    rows = []
    for (user, setting, network), group in data.groupby(["label_user", "setting", "network"], dropna=False):
        rows.append(
            {
                "label_user": user,
                "setting": setting,
                "network": network,
                "sessions": len(group),
                "distinct_ips": group["ip"].nunique(),
                "distinct_prefixes": group["ip"].map(ip_prefix).nunique(),
                "ipv6_share": group["ip"].map(lambda ip: _version(ip) == 6).mean(),
            }
        )
    return pd.DataFrame(rows)


def browser_overlap(sessions: pd.DataFrame) -> pd.DataFrame:
    """Per user and network, across settings: do the browser visits (setting 3, their own run ids) share an
    address or prefix with the agent runs on the same network (setting 1)? Counts only."""
    data = _with_setting(sessions)
    rows = []
    for (user, network), group in data.groupby(["label_user", "network"], dropna=False):
        browser = group.loc[group["is_browser"]]
        agents = group.loc[~group["is_browser"]]
        if browser.empty or agents.empty:
            continue
        agent_ips, agent_prefixes = set(agents["ip"].dropna()), set(agents["ip"].map(ip_prefix).dropna())
        rows.append(
            {
                "label_user": user,
                "network": network,
                "browser_sessions": len(browser),
                "agent_sessions": len(agents),
                "browser_same_ip_as_an_agent": browser["ip"].isin(agent_ips).mean(),
                "browser_same_prefix_as_an_agent": browser["ip"].map(ip_prefix).isin(agent_prefixes).mean(),
            }
        )
    return pd.DataFrame(rows)


def _with_setting(sessions: pd.DataFrame) -> pd.DataFrame:
    return sessions.assign(setting=sessions["run_id"].str.extract(T3_RUN)["setting"]).dropna(
        subset=["setting"]
    )


def tool_summary(sessions: pd.DataFrame) -> pd.DataFrame:
    agents = sessions.loc[~sessions["is_browser"] & sessions["run_id"].str.contains("-t3-")]
    return agents.groupby(["label_agent", "machine", "tools"]).size().rename("sessions").reset_index()


def load_pool(path: str = "infra/sites/visit-variants.json") -> dict[str, list[str]]:
    """Keyword ids of the per-visit sentences, per site."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {site: [entry["id"] for entry in entries] for site, entries in data.items()}


def _names(keyword: str, text: str) -> bool:
    return bool(re.search(rf"\b{re.escape(str(keyword).lower())}", str(text).lower()))


def variant_reflection(logs: pd.DataFrame, runs: pd.DataFrame, pool: dict[str, list[str]]) -> pd.DataFrame:
    """Per submitted Track 3 run: every sentence its fetches were served (in order), whether the summary names
    one of them and which fetch it came from, and, as a control, how many keywords of sentences it was NOT
    served the summary names (the pool sentences share the page's topic, so a match can be chance)."""
    columns = [
        "run_id",
        "label_agent",
        "served",
        "reflected",
        "reflected_fetch",
        "n_not_served",
        "control_hits",
    ]
    if "visit_variant" not in logs:
        return pd.DataFrame(columns=columns)
    t3 = logs.loc[logs["kind"].eq("request") & logs["run_id"].isin(runs["run_id"])].sort_values("ts")
    served = t3.dropna(subset=["visit_variant"]).groupby("run_id")["visit_variant"].agg(list)
    texts = t3.dropna(subset=["submitted_text"]).groupby("run_id")["submitted_text"].apply(" ".join)
    rows = []
    for run in runs.itertuples(index=False):
        if run.run_id not in served.index or run.run_id not in texts.index:
            continue
        shown, text = served[run.run_id], texts[run.run_id]
        hits = [i for i, keyword in enumerate(shown, start=1) if _names(keyword, text)]
        others = [keyword for keyword in pool.get(run.site, []) if keyword not in set(shown)]
        rows.append(
            {
                "run_id": run.run_id,
                "label_agent": run.label_agent,
                "served": ", ".join(shown),
                "reflected": bool(hits),
                "reflected_fetch": hits[0] if hits else None,
                "n_not_served": len(others),
                "control_hits": sum(_names(keyword, text) for keyword in others),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def reflection_summary(reflected: pd.DataFrame) -> pd.DataFrame:
    """Per agent: hit rate on the served sentence vs the chance rate on sentences the run was not served."""
    rows = []
    for agent, group in reflected.groupby("label_agent"):
        rows.append(
            {
                "label_agent": agent,
                "submitted_runs": len(group),
                "named_served_sentence": group["reflected"].mean(),
                "chance_per_unserved_keyword": group["control_hits"].sum()
                / max(group["n_not_served"].sum(), 1),
            }
        )
    return pd.DataFrame(rows)


SIDE_FILE = r"/(robots\.txt|llms\.txt|favicon\.ico|[^/?]+\.md)(?:\?.*)?$"  # group 1: the file name


def side_requests(logs: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    """Requests for robots.txt, llms.txt, favicon.ico or a Markdown copy, per agent (VM pages link them)."""
    t3 = logs.loc[logs["kind"].eq("request") & logs["run_id"].isin(runs["run_id"])].copy()
    t3["file"] = t3["path"].astype(str).str.extract(SIDE_FILE)[0]
    t3 = t3.dropna(subset=["file"])
    if t3.empty:
        return pd.DataFrame(columns=["label_agent", "file", "requests", "runs"])
    t3["file"] = t3["file"].where(~t3["file"].str.endswith(".md"), "*.md")
    return (
        t3.groupby(["label_agent", "file"])
        .agg(requests=("run_id", "size"), runs=("run_id", "nunique"))
        .reset_index()
    )


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
    parser.add_argument("--pool", default="infra/sites/visit-variants.json")
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
    _print("Browser visits vs agent runs on the same network (setting 3 vs 1)", browser_overlap(sessions))
    _print("Tool sequences of agent sessions", tool_summary(sessions))
    reflected = variant_reflection(logs, runs, load_pool(args.pool))
    _print(
        "Per-visit sentence named in the summary (decision A), with chance control",
        reflection_summary(reflected),
    )
    _print("Side requests (robots.txt, llms.txt, favicon, Markdown copies)", side_requests(logs, runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
