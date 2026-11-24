"""Turn request logs into visit sessions: one per run, split into the agent's part and the browser's part."""

from __future__ import annotations

import ipaddress

import pandas as pd

from harness.features import extract_features

# Placeholder environment signature; 3b (member A, environment signatures) owns and will replace this list.
# Each session keeps the set of values it showed (an agent that reads with WebFetch and submits with curl
# shows two JA4s); two sessions match on a column when their sets share a value.
SIGNATURE_COLUMNS = [
    "tls_ja4",
    "tls_ja3_md5",
    "h2_fp",
    "http_header_order_hash",
    "http_header_set_hash",
    "http_ua_family",
    "http_ua_version",
    "http_accept",
    "http_accept_encoding",
    "tls_groups",
    "tls_has_pq",
]
LABEL_COLUMNS = ["label_user", "label_agent", "label_model", "machine", "network"]
SESSION_COLUMNS = [
    "session_key",
    "run_id",
    *LABEL_COLUMNS,
    "site",
    "is_browser",
    "ip",
    "ip_prefix",
    *SIGNATURE_COLUMNS,
    "tools",
    "t_start",
    "t_end",
    "n_requests",
    "max_gap_s",
    "submit_wait_s",
]
SUBMIT_PATTERN = r"(?:/r/[^/?]+)?/submit(?:\?.*)?"
ATTACH_COLUMNS = ["client_ip", "site", "path", "run_id", "ts", *LABEL_COLUMNS]


def ip_prefix(value) -> str | None:
    """The /24 (IPv4) or /64 (IPv6) network of an address, or None if it doesn't parse."""
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        return None
    return str(ipaddress.ip_network(f"{address}/{24 if address.version == 4 else 64}", strict=False))


def tool_of(ua) -> str:
    """Which client sent a request, from its User-Agent: webfetch, curl, browser, or the UA family."""
    ua = "" if pd.isna(ua) else str(ua)
    if ua.startswith("Claude-User"):
        return "webfetch"
    if ua.lower().startswith("mozilla/"):
        return "browser"
    return ua.split("/")[0].lower() or "missing"


def _first(series: pd.Series):
    values = series.dropna()
    return values.iloc[0] if len(values) else None


def _value_set(series: pd.Series) -> tuple:
    return tuple(sorted({str(value) for value in series.dropna()}))


def _requests_with_features(logs: pd.DataFrame, features: pd.DataFrame | None) -> pd.DataFrame:
    requests = logs.loc[logs["kind"].eq("request")].reset_index(drop=True)
    extracted = (extract_features(logs) if features is None else features).reset_index(drop=True).copy()
    if len(extracted) != len(requests):
        raise ValueError("features must have one row per request, in log order")
    for column in ATTACH_COLUMNS:
        if column not in extracted:
            extracted[column] = requests[column].to_numpy() if column in requests else None
    for column in [*SIGNATURE_COLUMNS, "http_ua"]:
        if column not in extracted:
            extracted[column] = None
    extracted["ts"] = pd.to_numeric(extracted["ts"], errors="coerce")
    extracted["tool"] = extracted["http_ua"].map(tool_of)
    extracted["is_browser"] = extracted["tool"].eq("browser") | extracted["label_agent"].eq("browser")
    return extracted


def _session(run_id: str, is_browser: bool, group: pd.DataFrame) -> dict:
    group = group.sort_values("ts", kind="stable")
    gaps = group["ts"].diff()
    is_submit = group["path"].astype("string").str.fullmatch(SUBMIT_PATTERN, na=False)
    tools = group["tool"].tolist()
    return {
        "session_key": f"{run_id}#{'browser' if is_browser else 'agent'}",
        "run_id": run_id,
        **{column: _first(group[column]) for column in LABEL_COLUMNS},
        "site": _first(group["site"]),
        "is_browser": is_browser,
        "ip": _first(group["client_ip"]),
        "ip_prefix": ip_prefix(_first(group["client_ip"])),
        **{column: _value_set(group[column]) for column in SIGNATURE_COLUMNS},
        "tools": ">".join(tool for i, tool in enumerate(tools) if i == 0 or tool != tools[i - 1]),
        "t_start": group["ts"].min(),
        "t_end": group["ts"].max(),
        "n_requests": len(group),
        "max_gap_s": gaps.max() if len(group) > 1 else None,
        "submit_wait_s": gaps[is_submit].iloc[0]
        if is_submit.any() and pd.notna(gaps[is_submit].iloc[0])
        else None,
    }


def build_sessions(
    logs: pd.DataFrame, include_baselines: bool = False, features: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per (run_id, agent or browser).

    On the Track 3 VM every visit goes to /r/<run_id>/. A browser request under an agent's run id is the user
    opening a link the agent relayed, so it becomes its own session sharing the run id (the relay link).
    `features` (one row per request, in log order) skips `extract_features`, for tests.
    """
    requests = _requests_with_features(logs, features)
    requests = requests.loc[requests["run_id"].notna() & requests["label_user"].notna()]
    if not include_baselines:
        requests = requests.loc[requests["label_user"].ne("baseline")]
    records = [
        _session(run_id, bool(is_browser), group)
        for (run_id, is_browser), group in requests.groupby(["run_id", "is_browser"], sort=True)
    ]
    return pd.DataFrame(records, columns=SESSION_COLUMNS)
