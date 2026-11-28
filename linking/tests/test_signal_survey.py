import pandas as pd

from harness.tests.test_features import client_hello
from linking.signal_survey import http_details, tls_details


def test_tls_details_reads_what_ja4_leaves_out():
    raw_hex = client_hello(grease=True)  # the helper returns the ClientHello as hex
    details = tls_details(raw_hex)
    assert details["tls_hello_len"] == len(bytes.fromhex(raw_hex))
    assert details["tls_ext_order_raw"].startswith("G-")  # GREASE position kept, not sorted away
    assert details["tls_cipher_order"] == "4865-4866"
    assert tls_details("zz") == {} and tls_details(None) == {}


def test_http_details_encoding_and_versions():
    row = pd.Series(
        {
            "headers": [["Host", "site1.test"], ["User-Agent", "Claude-User (claude-code/2.1.332; +x)"]],
            "submitted_text": "it's a test",
            "query": "text=it%27s+a+test",
            "body": "",
            "method": "GET",
            "path": "/r/c-t3-x-001/submit",
        }
    )
    details = http_details(row)
    assert details["http_tool_version"] == "2.1.332"
    assert details["http_space_encoding"] == "+"
    assert details["http_escapes_apostrophe"] is True
    assert details["http_header_case"] == "UU"
    assert details["http_path_style"] == "/r/ID/submit"
