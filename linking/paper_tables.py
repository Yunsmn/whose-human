"""Write the Track 3 tables of the paper from the logs, in one command.

`python -m linking.paper_tables <logs_dir> [--runs runs] [--out paper/tables] [--all-runs]`

Writes LaTeX tables (booktabs) into `--out` and prints them. Only counts and rates, never an address.
By default only Track 3 runs (`<letter>-t3-...`) are used; `--all-runs` uses every labelled agent run, which
is how the pipeline is checked on the local data before the campaign log exists.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score

from infra.loader import load_logs
from linking.campaign import coverage, manifest_runs
from linking.hard_cases import anonymity_sets, ip_change_table, shared_ip_table, with_session_labels
from linking.link import FEATURE_SETS, cluster, cluster_metrics, cross_val_scores, evaluate, rule_same_ip
from linking.pairs import build_pairs
from linking.sessions import build_sessions

SCORERS = {"Same IP (rule)": None, **{f"Model: {name}": name for name in ("all", "no_ip", "network_only")}}
SLICES = {"cross_agent": "Across agents", "cross_site": "Across sites", "agent_browser": "Agent and browser"}


def latex(table: pd.DataFrame, caption: str, label: str) -> str:
    """A small booktabs table; numbers as given (format them before)."""
    columns = list(table.columns)
    lines = [
        "\\begin{table}[t]",
        "\\centering\\small",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        # shrink to the column only when wider than it (needs graphicx)
        "\\resizebox{\\ifdim\\width>\\columnwidth\\columnwidth\\else\\width\\fi}{!}{%",
        "\\begin{tabular}{l" + "r" * (len(columns) - 1) + "}",
        "\\toprule",
        " & ".join(_tex(c) for c in columns) + " \\\\",
        "\\midrule",
        *(" & ".join(_tex(v) for v in row) + " \\\\" for row in table.itertuples(index=False)),
        "\\bottomrule",
        "\\end{tabular}}",
        "\\end{table}",
    ]
    return "\n".join(lines) + "\n"


def _tex(value) -> str:
    if isinstance(value, float):
        return "--" if pd.isna(value) else f"{value:.2f}"
    return str(value).replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")


def scores(sessions: pd.DataFrame, pairs: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        name: rule_same_ip(pairs) if key is None else cross_val_scores(sessions, pairs, FEATURE_SETS[key])
        for name, key in SCORERS.items()
    }


def linking_table(
    sessions: pd.DataFrame, pairs: pd.DataFrame, all_scores: dict[str, pd.Series]
) -> pd.DataFrame:
    rows = []
    for name, score in all_scores.items():
        overall = evaluate(pairs, score).set_index("slice").loc["all"]
        clusters = cluster_metrics(sessions, cluster(sessions, pairs, score))
        rows.append(
            {
                "Scorer": name,
                "AUC": roc_auc_score(pairs.same_user, score)
                if pairs.same_user.nunique() == 2
                else float("nan"),
                "Precision": overall.precision,
                "Recall": overall.recall,
                "ARI": clusters["adjusted_rand"],
                "B-cubed F1": clusters["bcubed_f1"],
            }
        )
    return pd.DataFrame(rows)


def slice_table(pairs: pd.DataFrame, all_scores: dict[str, pd.Series]) -> pd.DataFrame:
    """Recall on same-person pairs per slice (precision is not defined inside a same-person slice)."""
    rows = []
    for name, score in all_scores.items():
        result = evaluate(pairs, score).set_index("slice")
        rows.append({"Scorer": name, **{label: result.loc[key, "recall"] for key, label in SLICES.items()}})
    return pd.DataFrame(rows)


def _compact(table: pd.DataFrame, group: str, rate: str, keep: tuple[str, ...] = ()) -> pd.DataFrame:
    """One column per scorer (the rate only), plus the group and pair count; a row saying so when empty."""
    title = {"network_pair": "Networks", "tools_pair": "Tools"}.get(group, group)
    if table.empty:
        return pd.DataFrame({title: ["no pairs yet"]})
    columns = {c: c.removeprefix(f"{rate}_") for c in table.columns if c.startswith(f"{rate}_")}
    out = table[[group, "n_pairs", *keep, *columns]].rename(columns={**columns, "n_pairs": "Pairs"})
    return out.rename(columns={group: title, "same_prefix": "Same prefix"})


def hard_case_tables(sessions, pairs, all_scores) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    data = with_session_labels(sessions, pairs)
    chosen = {name: all_scores[name] for name in ("Same IP (rule)", "Model: no_ip", "Model: network_only")}
    anonymity = anonymity_sets(sessions, data)
    return (
        _compact(ip_change_table(data, chosen), "network_pair", "recall", keep=("same_prefix",)),
        _compact(shared_ip_table(data, chosen), "tools_pair", "false_link"),
        float(anonymity.other_users_same_signature.eq(0).mean()) if len(anonymity) else float("nan"),
    )


def coverage_table(runs: pd.DataFrame, logs: pd.DataFrame) -> pd.DataFrame:
    cover = coverage(runs, logs)
    cover["agent"] = cover["label_agent"].where(cover["label_agent"].ne("browser"), "browser")
    table = cover.groupby(["member", "setting", "agent"]).agg(
        Runs=("run_id", "size"),
        Submitted=("submitted", "sum"),
        Logged=("n_requests", lambda n: int((n > 0).sum())),
    )
    return table.reset_index().rename(columns={"member": "Member", "setting": "Setting", "agent": "Agent"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--out", default="paper/tables")
    parser.add_argument("--all-runs", action="store_true")
    args = parser.parse_args(argv)
    logs = load_logs(args.logs_dir, runs_dir=args.runs)
    runs = manifest_runs(args.runs)
    sessions = build_sessions(logs if args.all_runs else logs.loc[logs["run_id"].isin(runs["run_id"])])
    if sessions["label_user"].nunique() < 2:
        parser.error("need sessions of at least two users")
    pairs = build_pairs(sessions)
    all_scores = scores(sessions, pairs)
    ip_change, shared_ip, unique_share = hard_case_tables(sessions, pairs, all_scores)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "coverage": (
            coverage_table(runs, logs),
            "Track 3 runs per member and setting: planned, logged and submitted.",
        ),
        "linking": (
            linking_table(sessions, pairs, all_scores),
            "Linking sessions to people: pair scores and clusters.",
        ),
        "slices": (slice_table(pairs, all_scores), "Recall on same-person pairs, by kind of pair."),
        "ip_change": (ip_change, "Same person, different IP: recall by network pair."),
        "shared_ip": (shared_ip, "Different people, same IP: false-link rate by tool pair."),
    }
    for name, (table, caption) in tables.items():
        text = latex(table, caption, f"tab:t3-{name}")
        (out / f"t3_{name}.tex").write_text(text, encoding="utf-8")
        print(f"\n% {name}\n{text}")
    print(f"Sessions: {len(sessions)}; users: {sessions.label_user.nunique()}; pairs: {len(pairs)}")
    print(f"Share of sessions whose signature no other user shares: {unique_share:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
