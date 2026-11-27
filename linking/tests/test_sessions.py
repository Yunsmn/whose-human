import pandas as pd

from linking.sessions import build_sessions


def test_relay_clients_split_and_submit_wait_is_per_session():
    logs = pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "r1",
                "ts": 1.0,
                "client_ip": "192.0.2.8",
                "site": "s1",
                "path": "/r/r1/",
                "label_user": "u",
                "label_agent": "claude",
                "headers": [],
            },
            {
                "kind": "request",
                "run_id": "r1",
                "ts": 6.0,
                "client_ip": "192.0.2.8",
                "site": "s1",
                "path": "/r/r1/submit",
                "label_user": "u",
                "label_agent": "claude",
                "headers": [],
            },
            {
                "kind": "request",
                "run_id": "r1",
                "ts": 3.0,
                "client_ip": "198.51.100.9",
                "site": "s2",
                "path": "/r/r1/",
                "label_user": "u",
                "label_agent": "browser",
                "headers": [],
            },
        ]
    )
    features = pd.DataFrame(
        {
            "tls_ja4": ["agent", "agent", None],
            "http_ua": ["curl", "curl", "Mozilla/5"],
            "http_ua_family": ["curl", "curl", None],
        }
    )
    sessions = build_sessions(logs, features=features)
    assert len(sessions) == 2
    assert sessions.session_key.tolist() == ["r1#agent", "r1#browser"]
    assert sessions.is_browser.tolist() == [False, True]
    assert sessions.submit_wait_s.iloc[0] == 5
    assert pd.isna(sessions.submit_wait_s.iloc[1])
    assert sessions.ip_prefix.tolist() == ["192.0.2.0/24", "198.51.100.0/24"]


def test_ipv6_and_invalid_ip_prefix():
    logs = pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "a",
                "ts": 1,
                "client_ip": "2001:db8::1",
                "path": "/",
                "label_user": "u",
                "headers": [],
            },
            {
                "kind": "request",
                "run_id": "b",
                "ts": 2,
                "client_ip": "bad",
                "path": "/",
                "label_user": "v",
                "headers": [],
            },
        ]
    )
    features = pd.DataFrame(
        {"tls_ja4": ["x", "y"], "http_ua": ["curl", "curl"], "http_ua_family": ["curl", "curl"]}
    )
    prefixes = build_sessions(logs, features=features).ip_prefix
    assert prefixes.iloc[0] == "2001:db8::/64"
    assert pd.isna(prefixes.iloc[1])


def test_one_agent_session_per_run_even_when_the_tool_changes():
    logs = pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "r",
                "ts": 1.0,
                "client_ip": "192.0.2.8",
                "path": "/r/r/input.html",
                "label_user": "u",
                "label_agent": "claude-code",
                "headers": [],
            },
            {
                "kind": "request",
                "run_id": "r",
                "ts": 11.0,
                "client_ip": "192.0.2.8",
                "path": "/r/r/submit",
                "label_user": "u",
                "label_agent": "claude-code",
                "headers": [],
            },
        ]
    )
    features = pd.DataFrame(
        {
            "tls_ja4": ["ja4-webfetch", "ja4-curl"],
            "http_ua": ["Claude-User (claude-code/2.1.319)", "curl/8.23.0"],
            "http_ua_family": ["other", "curl"],
        }
    )
    sessions = build_sessions(logs, features=features)
    assert sessions.session_key.tolist() == ["r#agent"]
    assert sessions.tools.iloc[0] == "webfetch>curl"
    assert sessions.tls_ja4.iloc[0] == ("ja4-curl", "ja4-webfetch")
    assert sessions.submit_wait_s.iloc[0] == 10.0


def test_baselines_are_dropped_by_default():
    logs = pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "b-0001",
                "ts": 1.0,
                "client_ip": "192.0.2.8",
                "path": "/",
                "label_user": "baseline",
                "label_agent": "script_curl",
                "headers": [],
            }
        ]
    )
    features = pd.DataFrame({"tls_ja4": ["x"], "http_ua": ["curl/8"], "http_ua_family": ["curl"]})
    assert build_sessions(logs, features=features).empty
    assert len(build_sessions(logs, include_baselines=True, features=features)) == 1


def test_mozilla_prefix_alone_is_not_a_browser():
    from linking.sessions import tool_of

    chrome = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/158.0 Safari/537.36"
    )
    assert tool_of(chrome) == "browser"
    assert tool_of("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0") == "browser"
    assert (
        tool_of("Mozilla/5.0 (Windows NT 10.0; Microsoft Windows 10.0.26200; en-US) PowerShell/7.6.9")
        == "powershell"
    )
    assert tool_of("Mozilla/5.0 (compatible; ClaudeCode)") == "custom-mozilla"
    assert tool_of("Claude-User (claude-code/2.1.332; +https://support.anthropic.com/)") == "webfetch"
    assert tool_of("curl/8.23.0") == "curl"
