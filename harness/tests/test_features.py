import copy

import pandas as pd
import pytest

from harness.features import FEATURE_GROUPS, ID_COLUMNS, extract_features


def _ext(ext_id, data=b""):
    return ext_id.to_bytes(2, "big") + len(data).to_bytes(2, "big") + data


def client_hello(*, grease=False, pq=False, reverse_ext=False):
    ciphers = [0x1301, 0x1302]
    groups = [29, 23, 0x11EC if pq else 29]
    extensions = [
        (0, b"\x00\x0f\x00\x00\x0cexample.test"),
        (10, len(groups * 2).to_bytes(2, "big") + b"".join(g.to_bytes(2, "big") for g in groups)),
        (13, b"\x00\x04\x08\x04\x04\x03"),
        (16, b"\x00\x06\x02h2\x02h3"),
        (43, b"\x04\x03\x04\x03\x03"),
    ]
    if grease:
        ciphers.insert(0, 0x0A0A)
        extensions.insert(0, (0x2A2A, b""))
        extensions[1] = (extensions[1][0], extensions[1][1])
        groups.insert(0, 0x1A1A)
    if reverse_ext:
        extensions.reverse()
    cipher_bytes = b"".join(c.to_bytes(2, "big") for c in ciphers)
    ext_bytes = b"".join(_ext(i, data) for i, data in extensions)
    body = (
        b"\x03\x03"
        + bytes(32)
        + b"\x00"
        + len(cipher_bytes).to_bytes(2, "big")
        + cipher_bytes
        + b"\x01\x00"
        + len(ext_bytes).to_bytes(2, "big")
        + ext_bytes
    )
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    record = b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake
    return record.hex()


def _row(**values):
    return {
        "kind": "request",
        "run_id": "r1",
        "session_id": "s1",
        "conn_id": "c1",
        "ts": 10.0,
        "conn_ts": 9.5,
        "req_index_on_conn": 1,
        "client_hello_hex": client_hello(),
        "ja4": "t13d0205h2_abc_def",
        "ja3_md5": "digest",
        "http_version": "HTTP/1.1",
        "method": "GET",
        "headers": [["User-Agent", "curl/8.4.0"], ["Accept", "*/*"]],
        "header_order": ["User-Agent", "Accept"],
        "h2_settings": [],
        "h2_pseudo_order": [],
        "h2_window_update": None,
        "h2_fp": None,
        "body_len": 0,
        "submitted_text": None,
        "label_agent": "curl",
        "label_model": None,
        "label_user": None,
        **values,
    }


def test_feature_contract_and_tls_decoding():
    result = extract_features(pd.DataFrame([_row(client_hello_hex=client_hello(grease=True, pq=True))]))
    assert list(result.columns[: len(ID_COLUMNS)]) == ID_COLUMNS
    assert set(FEATURE_GROUPS) == {"tls", "http", "h2", "timing", "body"}
    assert pd.api.types.is_numeric_dtype(result["tls_n_ciphers"])
    assert pd.api.types.is_numeric_dtype(result["tls_has_grease"])
    assert pd.api.types.is_string_dtype(result["http_ua_family"])
    row = result.iloc[0]
    assert row.tls_has_grease and row.tls_has_pq
    assert row.tls_n_ciphers == 2
    assert row.tls_max_version == 0x0304
    assert row.tls_record_version == 0x0301
    assert row.tls_has_sni and row.tls_alpn_first == "h2"
    assert (
        row.tls_ext_order
        != extract_features(pd.DataFrame([_row(client_hello_hex=client_hello(reverse_ext=True))]))
        .iloc[0]
        .tls_ext_order
    )


@pytest.mark.parametrize(
    "ua,family,version",
    [
        ("curl/8.4.0", "curl", "8.4.0"),
        ("Wget/1.21", "wget", "1.21"),
        ("node", "node/undici", None),
        ("axios/1.8.4", "axios", "1.8.4"),
        ("got/14.0.0", "got", "14.0.0"),
        ("Python-urllib/3.12", "python-urllib", "3.12"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", "browser", None),
        (None, "missing", None),
    ],
)
def test_user_agent_families(ua, family, version):
    headers = [["uSeR-AgEnT", ua]] if ua else []
    row = extract_features(pd.DataFrame([_row(headers=headers, header_order=[h[0] for h in headers])])).iloc[
        0
    ]
    assert row.http_ua_family == family
    assert row.http_ua_version == version


def test_http_case_and_timing_features():
    rows = [
        _row(ts=10.0, conn_id="c1", run_id="r1", req_index_on_conn=1),
        _row(ts=13.0, conn_id="c1", run_id="r1", req_index_on_conn=2),
        _row(
            ts=20.0,
            conn_id="c2",
            run_id="r1",
            req_index_on_conn=1,
            headers=[["user-agent", "node"]],
            header_order=["user-agent"],
        ),
        _row(ts=30.0, conn_id="c3", run_id="r2"),
    ]
    result = extract_features(pd.DataFrame(rows))
    assert result.iloc[1].run_gap_prev_s == 3
    assert result.iloc[1].conn_n_requests == 2
    assert result.iloc[0].run_n_requests == 3
    assert result.iloc[0].run_n_conns == 2
    assert result.iloc[0].conn_setup_s == 0.5
    assert result.iloc[0].http_header_case == "title"
    assert result.iloc[2].http_header_case == "lower"
    assert pd.isna(result.iloc[0].run_gap_prev_s)


def test_tls_only_and_malformed_hello_warn_without_mutating_input():
    source = pd.DataFrame([_row(client_hello_hex="not hex"), _row(kind="tls_failure", run_id=None)])
    before = copy.deepcopy(source)
    with pytest.warns(RuntimeWarning, match="malformed"):
        result = extract_features(source, include_tls_only=True)
    pd.testing.assert_frame_equal(source, before)
    assert len(result) == 2
    assert pd.isna(result.iloc[0].tls_ja4)
    assert result.iloc[1].kind == "tls_failure"
