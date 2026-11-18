"""Per-request features for Track 1 and the Track 3b environment signature.

``ID_COLUMNS`` and ``FEATURE_GROUPS`` are a public contract: Track 3b can
select the same stable TLS/HTTP/HTTP2/timing/body columns by group name.
"""

from __future__ import annotations

import hashlib
import re
import warnings

import pandas as pd

from infra.server.tls_parse import is_grease, parse_client_hello

ID_COLUMNS = ["run_id", "session_id", "conn_id", "ts", "kind", "label_agent", "label_model", "label_user"]
TLS_COLUMNS = [
    "tls_ja4",
    "tls_ja4_a",
    "tls_ja4_b",
    "tls_ja4_c",
    "tls_ja3_md5",
    "tls_n_ciphers",
    "tls_n_extensions",
    "tls_has_grease",
    "tls_alpn_first",
    "tls_alpn_offered",
    "tls_max_version",
    "tls_groups",
    "tls_has_pq",
    "tls_sigalgs",
    "tls_ext_order",
    "tls_ext_order_hash",
    "tls_has_sni",
    "tls_has_session_ticket",
    "tls_has_psk",
    "tls_has_ech",
    "tls_has_compress_cert",
    "tls_has_padding",
    "tls_record_version",
]
HTTP_COLUMNS = [
    "http_version",
    "http_method",
    "http_n_headers",
    "http_header_order",
    "http_header_order_hash",
    "http_header_set_hash",
    "http_header_case",
    "http_ua",
    "http_ua_family",
    "http_ua_version",
    "http_accept",
    "http_accept_encoding",
    "http_has_accept_language",
    "http_has_sec_fetch",
    "http_connection",
    "http_has_cookie",
]
H2_COLUMNS = ["h2_fp", "h2_settings", "h2_window_update", "h2_pseudo_order", "h2_n_settings"]
TIMING_COLUMNS = [
    "conn_req_index",
    "conn_n_requests",
    "run_n_requests",
    "run_n_conns",
    "run_gap_prev_s",
    "conn_setup_s",
    "run_max_gap_s",
    "run_submit_wait_s",
]
BODY_COLUMNS = ["body_len", "body_has_submit"]
FEATURE_GROUPS = {
    "tls": TLS_COLUMNS,
    "http": HTTP_COLUMNS,
    "h2": H2_COLUMNS,
    "timing": TIMING_COLUMNS,
    "body": BODY_COLUMNS,
}

# String-valued features (one-hot encoded by the classifier); every other feature column is numeric.
CATEGORICAL_COLUMNS = [
    "tls_ja4",
    "tls_ja4_a",
    "tls_ja4_b",
    "tls_ja4_c",
    "tls_ja3_md5",
    "tls_alpn_first",
    "tls_alpn_offered",
    "tls_groups",
    "tls_sigalgs",
    "tls_ext_order",
    "tls_ext_order_hash",
    "http_version",
    "http_method",
    "http_header_order",
    "http_header_order_hash",
    "http_header_set_hash",
    "http_header_case",
    "http_ua",
    "http_ua_family",
    "http_ua_version",
    "http_accept",
    "http_accept_encoding",
    "http_connection",
    "h2_fp",
    "h2_settings",
    "h2_pseudo_order",
]
FEATURE_COLUMNS = [column for group in FEATURE_GROUPS.values() for column in group]
NUMERIC_COLUMNS = [column for column in FEATURE_COLUMNS if column not in CATEGORICAL_COLUMNS]

_GROUP_NAMES = {
    0x001D: "x25519",
    0x0017: "secp256r1",
    0x0018: "secp384r1",
    0x0019: "secp521r1",
    0x0100: "ffdhe2048",
    0x0101: "ffdhe3072",
    0x11EC: "x25519mlkem768",
    0x6399: "x25519kyber768draft00",
}
_UA_RULES = [
    ("curl", re.compile(r"\bcurl(?:/([\w.+-]+))?\b", re.I)),
    ("wget", re.compile(r"\bwget(?:/([\w.+-]+))?\b", re.I)),
    ("node/undici", re.compile(r"\b(?:undici|node)(?:/([\w.+-]+))?\b", re.I)),
    ("axios", re.compile(r"\baxios(?:/([\w.+-]+))?\b", re.I)),
    ("got", re.compile(r"\bgot(?:/([\w.+-]+))?\b", re.I)),
    ("python-requests", re.compile(r"\bpython-requests(?:/([\w.+-]+))?\b", re.I)),
    ("python-urllib", re.compile(r"\bpython-urllib(?:/([\w.+-]+))?\b", re.I)),
    ("python-httpx", re.compile(r"\bpython-httpx(?:/([\w.+-]+))?\b", re.I)),
    ("aiohttp", re.compile(r"\baiohttp(?:/([\w.+-]+))?\b", re.I)),
    ("go-http-client", re.compile(r"\bgo-http-client(?:/([\w.+-]+))?\b", re.I)),
    ("okhttp", re.compile(r"\bokhttp(?:/([\w.+-]+))?\b", re.I)),
    ("java", re.compile(r"\b(?:java|jdk)(?:/([\w.+-]+))?\b", re.I)),
]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _ids(row: pd.Series) -> dict:
    return {column: row.get(column) for column in ID_COLUMNS if column in row.index}


def _parse_tls(row: pd.Series) -> dict:
    raw = row.get("client_hello_hex")
    if not isinstance(raw, str) or not raw:
        return {column: None for column in TLS_COLUMNS}
    try:
        parsed = parse_client_hello(bytes.fromhex(raw))
        return _tls_features(parsed, bytes.fromhex(raw))
    except (ValueError, TypeError, IndexError, OverflowError):
        return {column: None for column in TLS_COLUMNS}


def _tls_features(parsed: dict, raw: bytes) -> dict:
    ciphers, extensions = parsed["ciphers"], parsed["extensions"]
    ext_ids = [ext for ext, _ in extensions if not is_grease(ext)]
    grease = any(
        is_grease(value) for value in ciphers + [e for e, _ in extensions] + parsed["supported_groups"]
    )
    versions = _extension_values(extensions, 43, 2, 1)
    max_version = max((v for v in versions if not is_grease(v)), default=parsed["legacy_version"])
    ja4 = parsed.get("ja4")
    ja4_parts = ja4.split("_") if ja4 else []
    alpn = parsed["alpn_offered"]
    groups = [g for g in parsed["supported_groups"] if not is_grease(g)]
    return {
        "tls_ja4": ja4,
        "tls_ja4_a": ja4_parts[0] if len(ja4_parts) > 0 else None,
        "tls_ja4_b": ja4_parts[1] if len(ja4_parts) > 1 else None,
        "tls_ja4_c": ja4_parts[2] if len(ja4_parts) > 2 else None,
        "tls_ja3_md5": parsed.get("ja3_md5"),
        "tls_n_ciphers": sum(not is_grease(c) for c in ciphers),
        "tls_n_extensions": len(ext_ids),
        "tls_has_grease": grease,
        "tls_alpn_first": alpn[0] if alpn else None,
        "tls_alpn_offered": ",".join(alpn),
        "tls_max_version": max_version,
        "tls_groups": ",".join(_GROUP_NAMES.get(g, f"0x{g:04x}") for g in groups),
        "tls_has_pq": any(g in (0x11EC, 0x6399) for g in groups),
        "tls_sigalgs": ",".join(f"{v:04x}" for v in parsed["signature_algorithms"]),
        "tls_ext_order": ",".join(map(str, ext_ids)),
        "tls_ext_order_hash": _digest(",".join(map(str, ext_ids))),
        "tls_has_sni": bool(parsed.get("sni")),
        "tls_has_session_ticket": 35 in ext_ids,
        "tls_has_psk": 41 in ext_ids,
        "tls_has_ech": 0xFE0D in ext_ids,
        "tls_has_compress_cert": 27 in ext_ids,
        "tls_has_padding": 21 in ext_ids,
        "tls_record_version": int.from_bytes(raw[1:3], "big") if len(raw) >= 3 else None,
    }


def _extension_values(extensions: list, ext_id: int, width: int, offset: int) -> list[int]:
    data = next((data for ext, data in extensions if ext == ext_id), b"")
    end = min(len(data), offset + int.from_bytes(data[:offset], "big"))
    return [
        int.from_bytes(data[pos : pos + width], "big")
        for pos in range(offset, end, width)
        if pos + width <= end
    ]


def _headers(row: pd.Series) -> tuple[list[tuple[str, str]], dict[str, str]]:
    raw = row.get("headers")
    pairs = (
        [(str(k), str(v)) for k, v in raw if isinstance(raw, list) and isinstance(k, str)]
        if isinstance(raw, list)
        else []
    )
    values = {}
    for name, value in pairs:
        values.setdefault(name.lower(), value)
    return pairs, values


def _header_case(names: list[str], version) -> str | None:
    if version != "HTTP/1.1" or not names:
        return None
    styles = {
        "lower"
        if n == n.lower()
        else "title"
        if n == "-".join(p.capitalize() for p in n.split("-"))
        else "mixed"
        for n in names
    }
    return styles.pop() if len(styles) == 1 else "mixed"


def _ua_family(value: str | None) -> tuple[str, str | None]:
    if not value:
        return "missing", None
    for family, pattern in _UA_RULES:
        match = pattern.search(value)
        if match:
            return family, match.group(1)
    if value.lower().startswith("mozilla/"):
        return "browser", None
    return "other", None


def _http_features(row: pd.Series) -> dict:
    pairs, headers = _headers(row)
    names = [name for name, _ in pairs]
    order = ",".join(name.lower() for name in names)
    sorted_names = ",".join(sorted({name.lower() for name in names}))
    ua = headers.get("user-agent")
    family, version = _ua_family(ua)
    return {
        "http_version": row.get("http_version"),
        "http_method": row.get("method"),
        "http_n_headers": len(pairs),
        "http_header_order": order,
        "http_header_order_hash": _digest(order),
        "http_header_set_hash": _digest(sorted_names),
        "http_header_case": _header_case(names, row.get("http_version")),
        "http_ua": ua,
        "http_ua_family": family,
        "http_ua_version": version,
        "http_accept": headers.get("accept"),
        "http_accept_encoding": headers.get("accept-encoding"),
        "http_has_accept_language": "accept-language" in headers,
        "http_has_sec_fetch": any(name.startswith("sec-fetch-") for name in headers),
        "http_connection": headers.get("connection", "").lower() or None,
        "http_has_cookie": "cookie" in headers,
    }


def _h2_features(row: pd.Series) -> dict:
    settings, pseudo = row.get("h2_settings"), row.get("h2_pseudo_order")
    codes = {":method": "m", ":authority": "a", ":scheme": "s", ":path": "p"}
    return {
        "h2_fp": row.get("h2_fp"),
        "h2_settings": ";".join(settings) if isinstance(settings, list) else None,
        "h2_window_update": row.get("h2_window_update"),
        "h2_pseudo_order": ",".join(codes.get(item, item) for item in pseudo)
        if isinstance(pseudo, list)
        else None,
        "h2_n_settings": len(settings) if isinstance(settings, list) else None,
    }


def _timing_features(rows: pd.DataFrame) -> list[dict]:
    result = [{} for _ in range(len(rows))]
    valid = rows.copy()
    valid["_position"] = range(len(valid))
    conn_counts = valid.groupby("conn_id", dropna=False)["conn_id"].transform("size")
    run_counts = valid.groupby("run_id", dropna=False)["run_id"].transform("size")
    run_conns = valid.groupby("run_id", dropna=False)["conn_id"].transform("nunique")
    ordered = valid.sort_values(["run_id", "ts"], kind="stable")
    gaps = ordered.groupby("run_id", dropna=False)["ts"].diff()
    gap_by_pos = dict(zip(ordered["_position"], gaps, strict=True))
    # Run-level values, repeated on every request of the run: they use the whole run, so they suit
    # scoring a finished run rather than a single request as it arrives.
    run_max_gap = gaps.groupby(ordered["run_id"]).transform("max")
    max_gap_by_pos = dict(zip(ordered["_position"], run_max_gap, strict=True))
    is_submit = (
        ordered["path"].astype("string").str.fullmatch(r"(?:/r/[^/?]+)?/submit(?:\?.*)?", na=False)
        if "path" in ordered
        else None
    )
    submit_wait = {}
    if is_submit is not None:
        for run_id, group in ordered.assign(_gap=gaps, _submit=is_submit).groupby("run_id"):
            first = group[group["_submit"]].head(1)
            submit_wait[run_id] = first["_gap"].iloc[0] if not first.empty else None
    for position, (_, row) in enumerate(valid.iterrows()):
        conn_ts, ts = row.get("conn_ts"), row.get("ts")
        result[position] = {
            "conn_req_index": row.get("req_index_on_conn"),
            "conn_n_requests": conn_counts.iloc[position],
            "run_n_requests": run_counts.iloc[position],
            "run_n_conns": run_conns.iloc[position],
            "run_gap_prev_s": gap_by_pos.get(position),
            "conn_setup_s": ts - conn_ts if pd.notna(ts) and pd.notna(conn_ts) else None,
            "run_max_gap_s": max_gap_by_pos.get(position),
            "run_submit_wait_s": submit_wait.get(row.get("run_id")),
        }
    return result


def extract_features(logs: pd.DataFrame, include_tls_only: bool = False) -> pd.DataFrame:
    """Return per-request model features; optionally include TLS-only records."""
    kinds = ["request", "no_request", "tls_failure"] if include_tls_only else ["request"]
    rows = logs.loc[logs["kind"].isin(kinds)].copy() if "kind" in logs else logs.iloc[0:0].copy()
    records = []
    malformed = 0
    timings = _timing_features(rows)
    for position, (_, row) in enumerate(rows.iterrows()):
        tls = _parse_tls(row)
        malformed += int(
            isinstance(row.get("client_hello_hex"), str)
            and bool(row.get("client_hello_hex"))
            and tls["tls_ja4"] is None
        )
        record = _ids(row)
        record.update(tls)
        record.update(_http_features(row))
        record.update(_h2_features(row))
        record.update(timings[position])
        record.update(
            {"body_len": row.get("body_len"), "body_has_submit": pd.notna(row.get("submitted_text"))}
        )
        records.append(record)
    if malformed:
        warnings.warn(
            f"{malformed} malformed ClientHello value(s); TLS features set to None",
            RuntimeWarning,
            stacklevel=2,
        )
    columns = [column for column in ID_COLUMNS if column in logs.columns]
    columns += TLS_COLUMNS + HTTP_COLUMNS + H2_COLUMNS + TIMING_COLUMNS + BODY_COLUMNS
    result = pd.DataFrame(records, columns=columns)
    # Booleans become 0/1 floats and numeric strings (e.g. h2_window_update) become numbers, with NaN
    # for missing values, so the numeric/categorical split in CATEGORICAL_COLUMNS always holds.
    numeric = {
        column: pd.to_numeric(result[column], errors="coerce").astype(float) for column in NUMERIC_COLUMNS
    }
    return result.assign(**numeric)
