"""Measure Track 3b environment-signature stability and collisions."""

from __future__ import annotations

import argparse

import pandas as pd

from infra.loader import load_logs
from linking.pairs import MAX_SESSIONS, value_shares
from linking.sessions import SIGNATURE_COLUMNS, build_sessions

PAIR_COLUMNS = [
    "a",
    "b",
    "same_user",
    "same_machine",
    "tool_pair",
    "cross_site",
    "cross_network",
    "cross_network_label",
    "exact_signature",
    "n_column_matches",
    "column_match_rate",
]


def _values(cell) -> tuple:
    """Canonical session values for one signature column, including an empty set."""
    return tuple(cell or ())


def column_summary(sessions: pd.DataFrame) -> pd.DataFrame:
    """Coverage and population distinctiveness of every signature column, without printing values."""
    shares = value_shares(sessions)
    rows = []
    for column in SIGNATURE_COLUMNS:
        cells = sessions[column] if column in sessions else pd.Series(dtype=object)
        observed = int(cells.map(lambda cell: bool(_values(cell))).sum())
        distribution = shares.get(column, {})
        rows.append(
            {
                "column": column,
                "sessions": len(sessions),
                "observed": observed,
                "coverage": observed / len(sessions) if len(sessions) else float("nan"),
                "n_values": len(distribution),
                "largest_share": max(distribution.values(), default=float("nan")),
                "smallest_share": min(distribution.values(), default=float("nan")),
            }
        )
    return pd.DataFrame(rows)


def track3_sessions(sessions: pd.DataFrame) -> pd.DataFrame:
    """Keep only controlled Track 3 campaign runs (public ids start ``a-t3-``, ``b-t3-`` or ``c-t3-``)."""
    if "run_id" not in sessions:
        return sessions.iloc[0:0].copy()
    controlled = sessions.run_id.astype("string").str.match(r"^[abc]-t3-", na=False)
    return sessions.loc[controlled].reset_index(drop=True)


def _different_observed_values(left, right) -> bool:
    """Whether two known values differ; missing observations are not evidence of a change."""
    return bool(pd.notna(left) and pd.notna(right) and str(left) != str(right))


def build_signature_pairs(sessions: pd.DataFrame) -> pd.DataFrame:
    """Compare every unordered pair on the declared IP-free, timing-free environment signature."""
    if len(sessions) > MAX_SESSIONS:
        raise ValueError(f"pair generation is limited to {MAX_SESSIONS} sessions")
    rows = []
    for i in range(len(sessions)):
        left = sessions.iloc[i]
        for j in range(i + 1, len(sessions)):
            right = sessions.iloc[j]
            matches = sum(_values(left[column]) == _values(right[column]) for column in SIGNATURE_COLUMNS)
            tools = sorted((str(left.tools), str(right.tools)))
            rows.append(
                {
                    "a": left.session_key,
                    "b": right.session_key,
                    "same_user": left.label_user == right.label_user,
                    "same_machine": left.machine == right.machine,
                    "tool_pair": " / ".join(tools),
                    "cross_site": left.site != right.site,
                    # The campaign's public labels describe the network kind (for example, campus), not the
                    # individual egress. The private observed address is what establishes an actual change.
                    "cross_network": _different_observed_values(left.ip, right.ip),
                    "cross_network_label": _different_observed_values(left.network, right.network),
                    "exact_signature": matches == len(SIGNATURE_COLUMNS),
                    "n_column_matches": matches,
                    "column_match_rate": matches / len(SIGNATURE_COLUMNS),
                }
            )
    return pd.DataFrame(rows, columns=PAIR_COLUMNS)


def _summarise(data: pd.DataFrame, relation: str) -> pd.DataFrame:
    columns = [
        "relation",
        "tool_pair",
        "pairs",
        "exact_matches",
        "exact_rate",
        "cross_site_pairs",
        "cross_site_exact_rate",
        "cross_network_pairs",
        "cross_network_exact_rate",
        "cross_network_label_pairs",
        "cross_network_label_exact_rate",
        "mean_column_match_rate",
    ]
    if data.empty:
        return pd.DataFrame(columns=columns)

    def rate(group: pd.DataFrame) -> float:
        return group.exact_signature.mean() if len(group) else float("nan")

    rows = []
    groups = [("all tools", data), *data.groupby("tool_pair", sort=True, dropna=False)]
    for tool_pair, group in groups:
        exact = int(group.exact_signature.sum())
        cross_site = group.loc[group.cross_site]
        cross_network = group.loc[group.cross_network]
        cross_network_label = group.loc[group.cross_network_label]
        rows.append(
            {
                "relation": relation,
                "tool_pair": tool_pair,
                "pairs": len(group),
                "exact_matches": exact,
                "exact_rate": exact / len(group),
                "cross_site_pairs": len(cross_site),
                "cross_site_exact_rate": rate(cross_site),
                "cross_network_pairs": len(cross_network),
                "cross_network_exact_rate": rate(cross_network),
                "cross_network_label_pairs": len(cross_network_label),
                "cross_network_label_exact_rate": rate(cross_network_label),
                "mean_column_match_rate": group.column_match_rate.mean(),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def pair_summary(pairs: pd.DataFrame) -> pd.DataFrame:
    """Same-person stability and different-person collision rates, separated by tool and condition."""
    stable = pairs.loc[pairs.same_user & pairs.same_machine]
    collisions = pairs.loc[~pairs.same_user & ~pairs.same_machine]
    return pd.concat(
        [
            _summarise(stable, "same-user stability"),
            _summarise(collisions, "different-user collision"),
        ],
        ignore_index=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    parser.add_argument(
        "--all-labelled",
        action="store_true",
        help="include non-Track-3 labelled sessions and baselines (default: only a-t3-/b-t3-/c-t3- run ids)",
    )
    parser.add_argument(
        "--include-baselines", dest="all_labelled", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)

    sessions = build_sessions(
        load_logs(args.logs_dir, runs_dir=args.runs), include_baselines=args.all_labelled
    )
    if not args.all_labelled:
        sessions = track3_sessions(sessions)
    pairs = build_signature_pairs(sessions)
    print(f"Sessions: {len(sessions)}; pairs: {len(pairs)}")
    print("\nSignature column coverage and population shares:")
    print(column_summary(sessions).to_string(index=False))
    print("\nExact-signature stability and different-user collisions:")
    print(pair_summary(pairs).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
