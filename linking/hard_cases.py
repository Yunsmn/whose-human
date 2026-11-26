"""Track 3d: the hard cases for linking (TEAM.md, 3d; owner B).

Built on 3c's sessions and pairs (`linking.sessions`, `linking.pairs`) and its cross-validated scores
(`linking.link`). Three questions:

- IP change (Track 3 H2, protocol setting 4): do a user's sessions on a second network still link, without
  the IP? Same-user pairs whose IPs differ, by the two networks' labels (home, mobile, vpn, campus).
- Shared IP (setting 5): how often are different users behind one IP linked anyway? Different-user pairs
  with the same IP, by the tools the two sessions used.
- Identical setups: how often do two different users show the same environment signature, so that the
  network trace can't tell them apart? Different-user pairs whose every signature column matches, and each
  session's anonymity set: how many other users have a session with its exact signature.

`python -m linking.hard_cases <logs_dir> [--runs runs] [--threshold 0.5]`
"""

from __future__ import annotations

import argparse

import pandas as pd

from infra.loader import load_logs
from linking.link import FEATURE_SETS, cross_val_scores, rule_same_ip
from linking.pairs import build_pairs
from linking.sessions import SIGNATURE_COLUMNS, build_sessions

# The scorers each table reports: the IP rule, and 3c's model without the IP (H2) and on the network trace
# alone. Scores are NaN for pairs a cross-validation fold didn't score; rates count only scored pairs.
MODEL_SETS = ("no_ip", "network_only")


def with_session_labels(sessions: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Add each side's network label, tool sequence and agent to the pairs, as an unordered pair label."""
    by_key = sessions.set_index("session_key")
    data = pairs.copy()
    for column in ("network", "tools", "label_agent"):
        left = data.a.map(by_key[column]).fillna("unknown").astype(str)
        right = data.b.map(by_key[column]).fillna("unknown").astype(str)
        data[f"{column}_pair"] = [" / ".join(sorted(sides)) for sides in zip(left, right, strict=True)]
    # Identical setup: the same set of values on every signature column, where two empty sets count as equal
    # (WebFetch sends no HTTP/2 and no UA version). 3c's `same_<column>` needs a shared value, so it calls two
    # empty sets different, which would hide exactly these collisions.
    signature = {
        key: tuple(frozenset(row[c] or ()) for c in SIGNATURE_COLUMNS) for key, row in by_key.iterrows()
    }
    data["full_signature_match"] = [signature[a] == signature[b] for a, b in zip(data.a, data.b, strict=True)]
    return data


def scores_by_scorer(sessions: pd.DataFrame, pairs: pd.DataFrame, seed: int = 0) -> dict[str, pd.Series]:
    scores = {"rule_same_ip": rule_same_ip(pairs)}
    for name in MODEL_SETS:
        scores[f"model_{name}"] = cross_val_scores(sessions, pairs, features=FEATURE_SETS[name], seed=seed)
    return scores


def _rates(subset: pd.DataFrame, scores: dict[str, pd.Series], threshold: float, prefix: str) -> dict:
    """For each scorer: the share of the subset's scored pairs at or above the threshold, and how many were
    scored. On same-user pairs that share is recall; on different-user pairs it is the false-link rate."""
    row = {}
    for name, series in scores.items():
        values = series.reindex(subset.index).dropna()
        row[f"{prefix}_{name}"] = values.ge(threshold).mean() if len(values) else float("nan")
        row[f"n_scored_{name}"] = len(values)
    return row


def _grouped(
    subset: pd.DataFrame, by: str, scores, threshold: float, prefix: str, extra=None
) -> pd.DataFrame:
    rows = []
    for name, group in [("all", subset), *sorted(subset.groupby(by), key=lambda item: item[0])]:
        if group.empty:
            continue
        row = {by: name, "n_pairs": len(group), **(extra(group) if extra else {})}
        rows.append({**row, **_rates(group, scores, threshold, prefix)})
    return pd.DataFrame(rows)


def ip_change_table(data: pd.DataFrame, scores, threshold: float = 0.5) -> pd.DataFrame:
    """Same-user pairs whose IPs differ, by network pair: recall of each scorer, and how often the /24 or
    /64 prefix still matched (a new IP on the same network keeps it, a VPN or hotspot does not)."""
    subset = data.loc[data.same_user.astype(bool) & data.ip_changed.astype(bool)]
    return _grouped(
        subset,
        "network_pair",
        scores,
        threshold,
        "recall",
        extra=lambda group: {"same_prefix": group.same_ip_prefix.mean()},
    )


def shared_ip_table(data: pd.DataFrame, scores, threshold: float = 0.5) -> pd.DataFrame:
    """Different-user pairs behind the same IP, by tool pair: the false-link rate of each scorer (the IP
    rule links all of them by construction)."""
    subset = data.loc[~data.same_user.astype(bool) & data.same_ip.astype(bool)]
    return _grouped(subset, "tools_pair", scores, threshold, "false_link")


def collision_table(data: pd.DataFrame) -> pd.DataFrame:
    """Different-user pairs, by tool pair: how many show the same value on every signature column."""
    subset = data.loc[~data.same_user.astype(bool)]
    rows = []
    for name, group in [("all", subset), *sorted(subset.groupby("tools_pair"), key=lambda item: item[0])]:
        if group.empty:
            continue
        matches = int(group.full_signature_match.sum())
        rows.append(
            {
                "tools_pair": name,
                "n_pairs": len(group),
                "n_full_match": matches,
                "share_full_match": matches / len(group),
            }
        )
    return pd.DataFrame(rows)


def anonymity_sets(sessions: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    """Per session: how many other users have at least one session with its exact signature (0: unique)."""
    collisions = data.loc[~data.same_user.astype(bool) & data.full_signature_match, ["a", "b"]]
    user = sessions.set_index("session_key").label_user
    others = {key: set() for key in sessions.session_key}
    for left, right in collisions.itertuples(index=False):
        others[left].add(user[right])
        others[right].add(user[left])
    result = sessions[["session_key", "label_user", "label_agent", "tools"]].copy()
    result["other_users_same_signature"] = result.session_key.map(lambda key: len(others[key]))
    return result


def anonymity_summary(anonymity: pd.DataFrame) -> pd.DataFrame:
    """By tool sequence: sessions, and the share whose signature no other user shares."""
    rows = []
    for name, group in [("all", anonymity), *sorted(anonymity.groupby("tools"), key=lambda item: item[0])]:
        rows.append(
            {
                "tools": name,
                "n_sessions": len(group),
                "share_unique": group.other_users_same_signature.eq(0).mean(),
                "max_other_users": int(group.other_users_same_signature.max()),
            }
        )
    return pd.DataFrame(rows)


def _print(title: str, table: pd.DataFrame) -> None:
    print(f"\n{title}")
    print(
        table.to_string(index=False, float_format=lambda value: f"{value:.3f}")
        if len(table)
        else "(no pairs)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track 3d: IP change, shared IP and identical setups")
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--include-baselines", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args(argv)
    sessions = build_sessions(
        load_logs(args.logs_dir, runs_dir=args.runs), include_baselines=args.include_baselines
    )
    pairs = build_pairs(sessions)
    data = with_session_labels(sessions, pairs)
    scores = scores_by_scorer(sessions, pairs)
    print(f"Sessions: {len(sessions)}; users: {sessions.label_user.nunique()}; pairs: {len(pairs)}")
    _print(
        "IP change: same-user pairs with different IPs (recall)",
        ip_change_table(data, scores, args.threshold),
    )
    _print(
        "Shared IP: different users, same IP (false-link rate)", shared_ip_table(data, scores, args.threshold)
    )
    _print("Identical setups: different-user pairs matching on every signature column", collision_table(data))
    _print(
        "Anonymity: sessions whose signature no other user shares",
        anonymity_summary(anonymity_sets(sessions, data)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
