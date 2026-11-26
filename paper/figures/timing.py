"""Figure: slowest gap between consecutive requests of each run, scripts vs agents (H2).

Usage, from the repository root: python paper/figures/timing.py <logs_dir> [--runs runs] [--out paper/figures/timing.pdf]
Reads the private logs; writes only the figure (no addresses).
"""

import argparse
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from harness.features import extract_features  # noqa: E402
from infra.loader import load_logs  # noqa: E402

GROUPS = [  # (label, colour, linestyle)
    ("Plain scripts (3 machines)", "#4b5563", "-"),
    ("Scripts pausing 2-6 s", "#9ca3af", "--"),
    ("Claude Code, curl", "#2563eb", "-"),
    ("Claude Code, WebFetch", "#dc2626", "-"),
    ("Codex", "#059669", "-"),
]


def group_of(run_id: str, agent: str, uas: set, notes: str) -> str | None:
    if agent.startswith("script_"):
        return GROUPS[1][0] if "think " in notes else GROUPS[0][0]
    if agent == "codex-cli":
        return GROUPS[4][0]
    if agent == "claude-code" and "-t3-" not in run_id and run_id != "c-claude-i-001":
        webfetch = any(str(ua).startswith("Claude-User") for ua in uas)
        return GROUPS[3][0] if webfetch else GROUPS[2][0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--out", default="paper/figures/timing.pdf")
    args = parser.parse_args()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logs = load_logs(args.logs_dir, runs_dir=args.runs)
        features = extract_features(logs)
    requests = logs.loc[logs["kind"].eq("request")].reset_index(drop=True)
    features["notes"] = requests["notes"].astype(str).to_numpy() if "notes" in requests else ""
    runs = features.dropna(subset=["label_agent"]).groupby("run_id").agg(
        agent=("label_agent", "first"),
        gap=("run_max_gap_s", "first"),
        uas=("http_ua", lambda s: set(s.dropna())),
        notes=("notes", "first"),
    )
    runs["group"] = [group_of(r, a, u, n) for r, a, u, n in zip(runs.index, runs.agent, runs.uas, runs.notes)]
    runs = runs.dropna(subset=["group", "gap"])

    fig, ax = plt.subplots(figsize=(3.4, 2.7))
    for label, colour, style in GROUPS:
        gaps = np.sort(runs.loc[runs.group == label, "gap"].to_numpy())
        if not len(gaps):
            continue
        ax.step(gaps, np.arange(1, len(gaps) + 1) / len(gaps), where="post", color=colour, linestyle=style,
                lw=1.4, label=f"{label} ({len(gaps)})")
        print(f"{label}: n={len(gaps)} min={gaps.min():.3f} median={np.median(gaps):.3f} max={gaps.max():.3f}")
    ax.axvline(1.0, color="black", lw=0.8, linestyle=":")
    ax.text(0.9, 0.9, "1 s", fontsize=7, ha="right")
    ax.set_xscale("log")
    ax.set_xlabel("Slowest gap between requests in a run (s)", fontsize=7)
    ax.set_ylabel("Share of runs", fontsize=7)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=5.5, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.28), ncol=2)
    fig.tight_layout(pad=0.3)
    fig.savefig(args.out, bbox_inches="tight")


if __name__ == "__main__":
    main()
