import http.client
import json
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

from infra.certs import generate
from infra.server.__main__ import Handler, Server
from infra.server.logwriter import LogWriter
from infra.server.sites import safe_site_path

ROOT = Path(__file__).parents[2]


@pytest.fixture
def running_server(tmp_path):
    ca, cert, key = generate(tmp_path / "certs")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    context.set_alpn_protocols(["h2", "http/1.1"])
    writer = LogWriter(tmp_path / "logs", "dev-test")
    server = Server(
        ("127.0.0.1", 0),
        Handler,
        options={
            "tls": True,
            "context": context,
            "writer": writer,
            "source": "dev-test",
            "sites_dir": ROOT / "infra" / "sites",
        },
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], ca, tmp_path / "logs"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def read_records(log_dir):
    paths = list(log_dir.glob("*.jsonl"))
    return [json.loads(line) for path in paths for line in path.read_text().splitlines()]


def test_http1_keeps_header_order_run_id_and_submit_body(running_server):
    port, ca, logs = running_server
    context = ssl.create_default_context(cafile=ca)
    conn = http.client.HTTPSConnection("127.0.0.1", port, context=context)
    conn.putrequest("POST", "/r/a-one/submit", skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", "site1.test")
    conn.putheader("X-First", "one")
    conn.putheader("X-Second", "two")
    conn.putheader("Content-Type", "application/x-www-form-urlencoded")
    conn.putheader("Content-Length", "14")
    conn.endheaders(b"text=hello+you")
    response = conn.getresponse()
    assert response.status == 200
    response.read()
    conn.close()

    record = read_records(logs)[0]
    assert record["header_order"][:3] == ["Host", "X-First", "X-Second"]
    assert record["http_version"] == "HTTP/1.1"
    assert record["run_id"] == "a-one"
    assert record["kind"] == "request"
    assert record["body"] == "text=hello+you"
    assert record["body_len"] == 14
    assert record["submitted_text"] == "hello you"
    assert record["ja3"] and record["ja4"] and record["client_hello_hex"]


def test_path_traversal_returns_404(running_server):
    port, ca, logs = running_server
    conn = http.client.HTTPSConnection("127.0.0.1", port, context=ssl.create_default_context(cafile=ca))
    conn.request("GET", "/../../etc/passwd", headers={"Host": "site1.test"})
    response = conn.getresponse()
    assert response.status == 404
    response.read()
    conn.close()
    assert read_records(logs)[0]["status"] == 404


def test_static_path_traversal_is_rejected(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    assert safe_site_path(root, "/index.html") == root / "index.html"
    assert safe_site_path(root, "/../../secret") is None


def test_http2_request_is_logged(running_server):
    httpx = pytest.importorskip("httpx")
    port, ca, logs = running_server
    context = ssl.create_default_context(cafile=str(ca))
    with httpx.Client(http2=True, verify=context) as client:
        for path in ("/r/b-two/", "/r/b-two/input.html"):
            response = client.get(f"https://127.0.0.1:{port}{path}", headers={"Host": "site1.test"})
            assert response.status_code == 200
            assert response.http_version == "HTTP/2"
    first, second = sorted(read_records(logs), key=lambda r: r["req_index_on_conn"])
    assert first["http_version"] == "HTTP/2"
    assert first["run_id"] == "b-two"
    assert first["conn_id"] == second["conn_id"]
    # Akamai format SETTINGS|WINDOW_UPDATE|PRIORITY|pseudo order, stable across the connection
    assert re.fullmatch(r"(\d+:\d+;?)+\|\d+\|[\d:,]+\|[masp](,[masp]){3}", first["h2_fp"])
    assert first["h2_fp"] == second["h2_fp"]


def test_failed_handshake_still_logs_client_hello(running_server):
    port, _, logs = running_server
    untrusting = ssl.create_default_context()  # does not trust the test CA
    with socket.create_connection(("127.0.0.1", port)) as raw:
        with pytest.raises(ssl.SSLCertVerificationError):
            untrusting.wrap_socket(raw, server_hostname="site1.test")
    deadline = time.monotonic() + 2
    while not list(logs.glob("*.jsonl")) and time.monotonic() < deadline:
        time.sleep(0.05)
    record = read_records(logs)[0]
    # depending on timing the rejection lands before or after the server finishes its handshake
    assert record["kind"] in ("tls_failure", "no_request")
    assert record["sni"] == "site1.test"
    assert record["ja4"].startswith("t13d")
    assert record["tls_error"]


def test_curl_tls_request_when_available(running_server):
    curl = shutil.which("curl")
    if not curl:
        pytest.skip("curl is not installed")
    port, ca, logs = running_server
    subprocess.run(
        [
            curl,
            "--silent",
            "--show-error",
            "--cacert",
            str(ca),
            "--resolve",
            f"site1.test:{port}:127.0.0.1",
            f"https://site1.test:{port}/r/dev-curl/",
        ],
        check=True,
        capture_output=True,
    )
    record = read_records(logs)[0]
    assert record["ja4"]
    assert record["run_id"] == "dev-curl"


def test_plain_ip_unwraps_ipv4_mapped_addresses():
    from infra.server.__main__ import plain_ip

    assert plain_ip("::ffff:192.0.2.7") == "192.0.2.7"
    assert plain_ip("192.0.2.7") == "192.0.2.7"
    assert plain_ip("2001:db8::1") == "2001:db8::1"
    assert plain_ip("::1") == "::1"
    assert plain_ip("not-an-ip") == "not-an-ip"


def _ipv6_loopback_works() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _ipv6_loopback_works(), reason="no IPv6 loopback on this machine")
def test_dual_stack_server_logs_ipv4_and_ipv6_clients(tmp_path):
    writer = LogWriter(tmp_path / "logs", "dev-test")
    options = {"tls": False, "writer": writer, "source": "dev-test", "sites_dir": ROOT / "infra" / "sites"}
    server = Server(("::", 0), Handler, options=options)
    assert server.address_family == socket.AF_INET6
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        for host, run_id in (("127.0.0.1", "dev-v4"), ("::1", "dev-v6")):
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", f"/r/{run_id}/index.html", headers={"Host": "site1.test"})
            assert conn.getresponse().status == 200
            conn.close()
        deadline = time.time() + 5
        while time.time() < deadline and len(read_records(tmp_path / "logs")) < 2:
            time.sleep(0.05)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    ips = {r["run_id"]: r["client_ip"] for r in read_records(tmp_path / "logs") if r.get("kind") == "request"}
    assert ips == {"dev-v4": "127.0.0.1", "dev-v6": "::1"}


def test_ipv4_host_keeps_an_ipv4_socket(tmp_path):
    writer = LogWriter(tmp_path / "logs", "dev-test")
    options = {"tls": False, "writer": writer, "source": "dev-test", "sites_dir": ROOT / "infra" / "sites"}
    server = Server(("127.0.0.1", 0), Handler, options=options)
    try:
        assert server.address_family == socket.AF_INET
    finally:
        server.server_close()


def test_site_hosts_map_the_vm_domains(tmp_path):
    from infra.server.sites import parse_site_hosts, site_for_host

    sites = ROOT / "infra" / "sites"
    hosts = parse_site_hosts("wh-site1.duckdns.org=site1, WH-Site2.duckdns.org=site2")
    assert hosts == {"wh-site1.duckdns.org": "site1", "wh-site2.duckdns.org": "site2"}
    assert site_for_host("wh-site2.duckdns.org", sites, hosts) == ("site2", sites / "site2")
    assert site_for_host("WH-SITE2.duckdns.org.:443", sites, hosts)[0] == "site2"
    assert site_for_host("wh-site1.duckdns.org", sites, hosts)[0] == "site1"
    # the local names keep working, and without the mapping a VM domain falls back to site1
    assert site_for_host("site2.test:8443", sites, hosts)[0] == "site2"
    assert site_for_host("wh-site2.duckdns.org", sites)[0] == "site1"
    assert parse_site_hosts(None) == {}
    with pytest.raises(ValueError, match="host=site"):
        parse_site_hosts("wh-site1.duckdns.org")


def test_site_hosts_with_an_unknown_site_is_refused(tmp_path, capsys):
    from infra.certs import generate as make_certs
    from infra.server.__main__ import main

    _, cert, key = make_certs(tmp_path / "certs")
    argv = ["--source", "dev-test", "--port", "0", "--cert", str(cert), "--key", str(key)]
    argv += ["--log-dir", str(tmp_path / "logs"), "--site-hosts", "wh-site3.duckdns.org=site3"]
    with pytest.raises(SystemExit):
        main(argv)
    assert "no folder" in capsys.readouterr().err
