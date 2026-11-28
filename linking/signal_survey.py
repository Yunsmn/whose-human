"""Survey every candidate signal in the server log: does it identify the person, and does it bridge tools?

`python -m linking.signal_survey <logs_dir> [--runs runs]`

For each signal (TLS ClientHello details beyond JA4, header values and casing, how the submitted text is
encoded, connection behaviour, source ports, connection setup time, tool versions, timing), every Track 3
session gets the set of values it showed, and every pair of sessions is compared. Reported per signal:
coverage, how often it matches for the same person with the same tool, for the same person across
different tools (the gap the fingerprints don't close), and for different people (collisions), plus a single
linking score (TPR - FPR). Numeric signals are compared by closeness. Prints aggregates only.
"""

from __future__ import annotations

import argparse
import re
import warnings
from urllib.parse import unquote_plus

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from infra.loader import load_logs
from infra.server.tls_parse import is_grease, parse_client_hello
from linking.sessions import build_sessions

KNOWN_EXT = {
    5: "status_request",
    18: "sct",
    21: "padding",
    22: "encrypt_then_mac",
    23: "ems",
    27: "cert_compress",
    28: "record_size_limit",
    34: "delegated_cred",
    35: "session_ticket",
    41: "psk",
    42: "early_data",
    45: "psk_modes",
    49: "post_handshake_auth",
    50: "sigalgs_cert",
    51: "key_share",
    17513: "alps",
    17613: "alps_new",
    65037: "ech",
    65281: "renegotiation_info",
}


def tls_details(hex_hello) -> dict:
    """ClientHello details JA4 leaves out: order, values, lengths."""
    if not isinstance(hex_hello, str) or not hex_hello:
        return {}
    try:
        hello = parse_client_hello(bytes.fromhex(hex_hello))
    except (ValueError, IndexError):
        return {}
    raw = bytes.fromhex(hex_hello)
    body = raw[5 + 4 :]  # record header + handshake header
    sid_len = body[2 + 32] if len(body) > 34 else None
    ext = dict(hello["extensions"])
    order = [e for e, _ in hello["extensions"]]
    grease_positions = tuple(i for i, e in enumerate(order) if is_grease(e))
    key_share = []
    if 51 in ext and len(ext[51]) >= 2:
        data, i = ext[51], 2
        while i + 4 <= len(data):
            group, length = int.from_bytes(data[i : i + 2], "big"), int.from_bytes(data[i + 2 : i + 4], "big")
            key_share.append(group if not is_grease(group) else "G")
            i += 4 + length
    return {
        "tls_cipher_order": "-".join(str(c) for c in hello["ciphers"] if not is_grease(c)),
        "tls_ext_order_raw": "-".join("G" if is_grease(e) else str(e) for e in order),
        "tls_grease_positions": str(grease_positions),
        "tls_key_share": str(key_share),
        "tls_psk_modes": ext.get(45, b"").hex() or None,
        "tls_cert_compress": ext.get(27, b"").hex() or None,
        "tls_record_size_limit": ext.get(28, b"").hex() or None,
        "tls_padding_len": len(ext[21]) if 21 in ext else None,
        "tls_session_id_len": sid_len,
        "tls_hello_len": len(raw),
        "tls_session_ticket_len": len(ext[35]) if 35 in ext else None,
        "tls_rare_exts": ",".join(KNOWN_EXT[e] for e in order if e in KNOWN_EXT) or None,
        "tls_alpn_list": ",".join(hello["alpn_offered"]) or None,
        "tls_versions_raw": hello["supported_versions"].hex() or None,
    }


def http_details(row: pd.Series) -> dict:
    headers = row.get("headers")
    pairs = headers if isinstance(headers, list) else []
    names = [str(k) for k, _ in pairs]
    lower = {str(k).lower(): str(v) for k, v in pairs}
    ua = lower.get("user-agent", "")
    versions = re.findall(r"[A-Za-z][\w.-]*/(\d+(?:\.\d+)+)", ua)
    content_type = lower.get("content-type", "")
    boundary = re.search(r"boundary=(\S+)", content_type)
    text = row.get("submitted_text")
    query = str(row.get("query") or "")
    body = str(row.get("body") or "")
    encoded = query if "text=" in query else body
    return {
        "http_header_case": "".join("U" if n[:1].isupper() else "l" for n in names) or None,
        "http_ua_full": ua or None,
        "http_tool_version": versions[0] if versions else None,
        "http_accept_encoding_raw": lower.get("accept-encoding"),
        "http_connection_raw": lower.get("connection"),
        "http_host_has_port": (":" in lower.get("host", lower.get(":authority", ""))) if pairs else None,
        "http_content_type_kind": content_type.split(";")[0] or None,
        "http_boundary_shape": (re.sub(r"[0-9A-Za-z]", "x", boundary.group(1)) if boundary else None),
        "http_space_encoding": ("+" if "+" in encoded else ("%20" if "%20" in encoded else None))
        if text
        else None,
        "http_escapes_apostrophe": ("%27" in encoded.upper())
        if text and "'" in unquote_plus(encoded)
        else None,
        "http_submit_method": row.get("method") if text else None,
        "http_path_style": re.sub(r"/r/[^/]+", "/r/ID", str(row.get("path") or "")) or None,
    }


NUMERIC = ["net_setup_s", "net_port"]


def request_signals(logs: pd.DataFrame) -> pd.DataFrame:
    requests = logs.loc[logs["kind"].eq("request")].reset_index(drop=True)
    rows = []
    for _, row in requests.iterrows():
        port = row.get("client_port")
        rows.append(
            {
                **tls_details(row.get("client_hello_hex")),
                **http_details(row),
                "net_port_range": ("<32768" if port < 32768 else "32768-49151" if port < 49152 else ">=49152")
                if pd.notna(port)
                else None,
                "net_port_parity": int(port) % 2 if pd.notna(port) else None,
                "conn_reuse": int(row.get("req_index_on_conn") or 1) > 1,
                "net_setup_s": (row["ts"] - row["conn_ts"]) if row.get("req_index_on_conn") == 1 else np.nan,
                "net_port": port,
            }
        )
    return pd.DataFrame(rows)


def session_signals(logs: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Per session: the set of values of each signal (numeric ones: the median)."""
    requests = logs.loc[logs["kind"].eq("request")].reset_index(drop=True)
    signals = request_signals(logs)
    tool = sessions.set_index("session_key")["tools"]
    browser = sessions.set_index("session_key")["is_browser"]
    from linking.sessions import tool_of

    ua = requests["headers"].map(lambda h: dict((str(k).lower(), v) for k, v in (h or [])).get("user-agent"))
    is_br = ua.map(tool_of).eq("browser") | requests.get("label_agent", pd.Series(index=requests.index)).eq(
        "browser"
    )
    keys = requests["run_id"].astype(str) + "#" + is_br.map({True: "browser", False: "agent"})
    signals["session_key"] = keys.to_numpy()
    signals = signals.loc[signals["session_key"].isin(tool.index)]
    out = {}
    for key, group in signals.groupby("session_key"):
        record = {}
        for column in group.columns.drop("session_key"):
            values = group[column].dropna()
            record[column] = values.median() if column in NUMERIC else tuple(sorted({str(v) for v in values}))
        out[key] = record
    frame = pd.DataFrame.from_dict(out, orient="index")
    return frame.assign(tools=tool, is_browser=browser).loc[sessions.session_key]


def evaluate(sessions: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    users = sessions.set_index("session_key")["label_user"]
    keys = list(signals.index)
    idx_a, idx_b = np.triu_indices(len(keys), k=1)
    a, b = np.array(keys)[idx_a], np.array(keys)[idx_b]
    same_user = users.loc[a].to_numpy() == users.loc[b].to_numpy()
    same_tool = signals.loc[a, "tools"].to_numpy() == signals.loc[b, "tools"].to_numpy()
    rows = []
    for column in signals.columns.drop(["tools", "is_browser"]):
        left, right = signals.loc[a, column].to_numpy(), signals.loc[b, column].to_numpy()
        if column in NUMERIC:
            have = ~(pd.isna(left) | pd.isna(right))
            if have.sum() < 10 or len(set(same_user[have])) < 2:
                continue
            closeness = -np.abs(left[have].astype(float) - right[have].astype(float))
            rows.append(
                {
                    "signal": column,
                    "coverage": float(np.mean(~pd.isna(signals[column]))),
                    "auc_closeness": roc_auc_score(same_user[have], closeness),
                }
            )
            continue
        have = np.array([bool(x) and bool(y) for x, y in zip(left, right, strict=True)])
        match = np.array([bool(set(x) & set(y)) for x, y in zip(left, right, strict=True)]) & have
        if have.sum() == 0:
            continue

        def rate(mask, have=have, match=match):
            m = mask & have
            return float(match[m].mean()) if m.sum() else float("nan")

        tpr, fpr = rate(same_user), rate(~same_user)
        rows.append(
            {
                "signal": column,
                "coverage": float(np.mean([bool(x) for x in signals[column]])),
                "n_values": len({v for cell in signals[column] for v in cell}),
                "same_person_same_tool": rate(same_user & same_tool),
                "same_person_cross_tool": rate(same_user & ~same_tool),
                "different_people": fpr,
                "tpr_minus_fpr": tpr - fpr if not (np.isnan(tpr) or np.isnan(fpr)) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore")
    logs = load_logs(args.logs_dir, runs_dir=args.runs)
    logs = logs.loc[logs["run_id"].astype(str).str.contains("-t3-")].reset_index(drop=True)
    sessions = build_sessions(logs).reset_index(drop=True)
    signals = session_signals(logs, sessions)
    table = evaluate(sessions, signals)
    categorical = table.loc[table.get("tpr_minus_fpr").notna()].sort_values("tpr_minus_fpr", ascending=False)
    print(f"Sessions: {len(sessions)} ({sessions.label_user.nunique()} users)")
    print("\nCategorical signals (match = sets share a value):")
    print(
        categorical.drop(columns=["auc_closeness"], errors="ignore").to_string(
            index=False, float_format=lambda v: f"{v:.2f}"
        )
    )
    numeric = table.loc[table.get("auc_closeness").notna()] if "auc_closeness" in table else table.iloc[0:0]
    print("\nNumeric signals (AUC of closeness for same person):")
    print(
        numeric[["signal", "coverage", "auc_closeness"]].to_string(
            index=False, float_format=lambda v: f"{v:.2f}"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
