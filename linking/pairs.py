"""Pairwise same-user labels and comparison features."""

from __future__ import annotations

import math

import pandas as pd

from linking.sessions import SIGNATURE_COLUMNS

IP_FEATURES = ["same_ip", "same_ip_prefix"]
# The run id carried in the URL: shared only by an agent session and the browser visit that followed its
# relayed link. Labels are per run, so a shared token always means the same user here.
TOKEN_FEATURES = ["same_token"]
# How far apart two sessions started. Partly a property of our campaign schedule, not of the user.
SCHEDULE_FEATURES = ["log_dt_start"]
NETWORK_FEATURES = [
    *[f"same_{column}" for column in SIGNATURE_COLUMNS],
    "n_signature_matches",
    "same_tools",
    "submit_wait_diff_s",
    "max_gap_ratio",
]
PAIR_FEATURES = [*IP_FEATURES, *TOKEN_FEATURES, *SCHEDULE_FEATURES, *NETWORK_FEATURES]
# Slices for reporting only; `ip_changed` and `shared_ip` use the label or the IP, never model features.
SLICE_COLUMNS = ["cross_agent", "cross_site", "agent_browser", "ip_changed", "shared_ip"]
MAX_SESSIONS = 5000


def _same(left, right) -> bool:
    return pd.notna(left) and pd.notna(right) and left == right


def _overlap(left, right) -> bool:
    return bool(set(left or ()) & set(right or ()))


def _abs_diff(left, right) -> float:
    return abs(left - right) if pd.notna(left) and pd.notna(right) else float("nan")


def _ratio(left, right) -> float:
    if pd.isna(left) or pd.isna(right) or not max(left, right):
        return float("nan")
    return min(left, right) / max(left, right)


def _pair(a: pd.Series, b: pd.Series) -> dict:
    signature = {f"same_{column}": _overlap(a[column], b[column]) for column in SIGNATURE_COLUMNS}
    dt = _abs_diff(a.t_start, b.t_start)
    same_user = a.label_user == b.label_user
    same_ip = _same(a.ip, b.ip)
    return {
        "a": a.session_key,
        "b": b.session_key,
        "same_user": same_user,
        "same_ip": same_ip,
        "same_ip_prefix": _same(a.ip_prefix, b.ip_prefix),
        "same_token": _same(a.run_id, b.run_id),
        "log_dt_start": math.log1p(dt) if pd.notna(dt) else float("nan"),
        **signature,
        "n_signature_matches": sum(signature.values()),
        "same_tools": _same(a.tools, b.tools),
        "submit_wait_diff_s": _abs_diff(a.submit_wait_s, b.submit_wait_s),
        "max_gap_ratio": _ratio(a.max_gap_s, b.max_gap_s),
        "cross_agent": a.label_agent != b.label_agent,
        "cross_site": a.site != b.site,
        "agent_browser": bool(a.is_browser) != bool(b.is_browser),
        "ip_changed": bool(same_user and pd.notna(a.ip) and pd.notna(b.ip) and a.ip != b.ip),
        "shared_ip": same_ip,
    }


def build_pairs(sessions: pd.DataFrame) -> pd.DataFrame:
    """All unordered session pairs, with the same-user label; O(n^2), so capped at MAX_SESSIONS."""
    if len(sessions) > MAX_SESSIONS:
        raise ValueError(f"pair generation is limited to {MAX_SESSIONS} sessions")
    rows = [
        _pair(sessions.iloc[i], sessions.iloc[j])
        for i in range(len(sessions))
        for j in range(i + 1, len(sessions))
    ]
    return pd.DataFrame(rows, columns=["a", "b", "same_user", *PAIR_FEATURES, *SLICE_COLUMNS])
