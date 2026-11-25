"""Threaded TLS/HTTP logging server for the local partner sites."""

from __future__ import annotations

import argparse
import ipaddress
import random
import secrets
import socket
import socketserver
import ssl
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import app, variants
from .http1 import read_request, send_response
from .logwriter import LogWriter
from .sites import parse_site_hosts, site_for_host
from .tls_parse import parse_client_hello, peek_client_hello

IDLE_TIMEOUT = 60.0


def plain_ip(address: str) -> str:
    """The peer address as logged: an IPv4 client on a dual-stack socket arrives as
    ``::ffff:a.b.c.d`` and is logged as plain ``a.b.c.d``, so IPv4 and IPv6 clients keep their
    own prefixes (/24 and /64) in linking/. Anything that isn't an address is returned unchanged."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    mapped = getattr(parsed, "ipv4_mapped", None)
    return str(mapped) if mapped else address


class Server(socketserver.ThreadingTCPServer):
    """A host with a ":" (for example ``::``) opens one IPv6 socket that also accepts IPv4
    (dual stack); any other host is IPv4 only, as before."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, options):
        self.options = options
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, handler)

    def server_bind(self):
        if self.address_family == socket.AF_INET6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


class Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.conn_ts = time.time()
        self.conn_id = secrets.token_hex(12)
        self.client_ip, self.client_port = plain_ip(self.client_address[0]), self.client_address[1]
        self.requests_logged = 0

    def _warn(self, what: str, exc: BaseException) -> None:
        print(f"{what} conn={self.conn_id} peer={self.client_ip}:{self.client_port}: {exc}", file=sys.stderr)

    def _connection_record(self) -> dict:
        return {
            "ts": time.time(),
            "source": self.server.options["source"],
            "conn_id": self.conn_id,
            "conn_ts": self.conn_ts,
            "client_ip": self.client_ip,
            "client_port": self.client_port,
            "ip": self.client_ip,
        }

    def _handshake(self) -> tuple[socket.socket | None, dict]:
        """Capture the ClientHello, then complete TLS. Failed handshakes are logged, not dropped."""
        tls: dict = {}
        try:
            hello_raw = peek_client_hello(self.request)
            tls = parse_client_hello(hello_raw)
            conn = self.server.options["context"].wrap_socket(self.request, server_side=True)
        except Exception as exc:
            self._warn("TLS error", exc)
            if tls:
                record = {**self._connection_record(), "kind": "tls_failure", "tls_error": str(exc)}
                self.server.options["writer"].write({**record, **app.tls_fields(tls)})
            return None, tls
        tls.update(
            tls_version=conn.version(),
            tls_cipher=conn.cipher()[0],
            alpn_negotiated=conn.selected_alpn_protocol(),
        )
        return conn, tls

    def handle(self):
        conn, tls = (self.request, {})
        if self.server.options["tls"]:
            conn, tls = self._handshake()
            if conn is None:
                return
        conn.settimeout(IDLE_TIMEOUT)
        error = None
        try:
            if tls.get("alpn_negotiated") == "h2":
                from .http2 import handle_http2

                handle_http2(self, conn, tls)
            else:
                self._serve_http1(conn, tls)
        except TimeoutError:
            pass  # idle keep-alive connection
        except Exception as exc:
            error = exc
            if self.requests_logged:
                self._warn("HTTP error", exc)
        if not self.requests_logged:
            self._log_empty_connection(tls, error)

    def _log_empty_connection(self, tls: dict, error: BaseException | None) -> None:
        """Keep the fingerprint of connections that completed TLS but never sent a request.

        With TLS 1.3 the server finishes its handshake before the client checks our certificate, so a
        client that rejects the certificate lands here (kind "no_request", error in tls_error), not in
        _handshake (kind "tls_failure", which means the server-side handshake itself failed).
        """
        kind = "no_request"
        record = {**self._connection_record(), "kind": kind, "tls_error": str(error) if error else None}
        self.server.options["writer"].write({**record, **app.tls_fields(tls)})

    def _serve_http1(self, conn, tls: dict) -> None:
        index = 0
        while True:
            request = read_request(conn)
            if request is None:
                return
            index += 1
            response = self.process(request, tls, index, "HTTP/1.1", host_header="host")
            send_response(
                conn,
                response["status"],
                response["body"],
                response["content_type"],
                response["new_cookie"],
                request["keep_alive"],
            )
            if not request["keep_alive"]:
                return

    def process(
        self,
        request: dict,
        tls: dict,
        index: int,
        http_version: str,
        host_header: str,
        extra: dict | None = None,
    ) -> dict:
        """Route one request, write its log record, and return the response to send."""
        headers = request["headers"]
        host = next((v for k, v in reversed(headers) if k.lower() == host_header), "")
        site, root = site_for_host(
            host, self.server.options["sites_dir"], self.server.options.get("site_hosts")
        )
        run_id, path = app.split_run_id(request["path"])
        response = app.route({**request, "path": path}, root, run_id)
        visit_variant = None
        if path != "/submit" and response["status"] == 200 and response["content_type"] == app.HTML:
            options = self.server.options
            body, visit_variant = variants.apply(
                response["body"], options.get("visit_variants"), site, options.get("rng", random)
            )
            response = {**response, "body": body}
        session, new_cookie = app.session_for(headers, response["content_type"].startswith("text/html"))
        record = {
            **self._connection_record(),
            "kind": "request",
            "req_index_on_conn": index,
            "site": site,
            **app.tls_fields(tls),
            "http_version": http_version,
            "method": request["method"],
            "path": request["target"],
            "query": urlsplit(request["target"]).query,
            "run_id": response["run_id"],
            "session_id": session or new_cookie,
            "headers": [h for h in headers if not h[0].startswith(":")],
            "header_order": [h[0] for h in headers if not h[0].startswith(":")],
            **app.body_fields(request["body_bytes"]),
            "submitted_text": response["submitted_text"],
            "status": response["status"],
            "visit_variant": visit_variant,
            **(extra or {}),
        }
        self.server.options["writer"].write(record)
        self.requests_logged += 1
        return {**response, "new_cookie": new_cookie}


def build_servers(args) -> list[Server]:
    writer = LogWriter(args.log_dir, args.source)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    context.set_alpn_protocols(args.alpn.split(","))
    site_hosts = parse_site_hosts(args.site_hosts)
    missing = sorted({site for site in site_hosts.values() if not (Path(args.sites_dir) / site).is_dir()})
    if missing:
        raise ValueError(f"--site-hosts: no folder in {args.sites_dir} for {', '.join(missing)}")
    common = {
        "writer": writer,
        "source": args.source,
        "sites_dir": args.sites_dir,
        "site_hosts": site_hosts,
        "visit_variants": variants.load_pool(args.visit_variants) if args.visit_variants else None,
        "rng": random.SystemRandom(),
    }
    servers = [Server((args.host, args.port), Handler, {**common, "tls": True, "context": context})]
    if args.plain_port:
        servers.append(Server((args.host, args.plain_port), Handler, {**common, "tls": False}))
    return servers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="'::' listens on IPv6 and IPv4 (dual stack)")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--plain-port", type=int)
    parser.add_argument("--cert", default="data/certs/server.pem")
    parser.add_argument("--key", default="data/certs/server-key.pem")
    parser.add_argument("--log-dir", default="data/logs")
    parser.add_argument("--source", default="", help="label for this server's logs, e.g. local-c or vm")
    parser.add_argument("--sites-dir", default="infra/sites")
    parser.add_argument("--alpn", default="h2,http/1.1")
    parser.add_argument(
        "--site-hosts",
        metavar="HOST=SITE,...",
        help="extra host names per site, e.g. the VM's domains; site1.test and site2.test always work",
    )
    parser.add_argument(
        "--visit-variants",
        metavar="POOL",
        help="JSON pool of per-visit sentences (VM only; see infra/server/variants.py); off by default",
    )
    args = parser.parse_args(argv)
    if not args.source:
        parser.error("--source is required (with Docker: set WH_SOURCE in .env, e.g. WH_SOURCE=local-c)")
    try:
        servers = build_servers(args)
    except ValueError as exc:  # a malformed --site-hosts or --visit-variants pool
        parser.error(str(exc))
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        scheme = "https" if server.options["tls"] else "http"
        print(f"Listening on {scheme}://{args.host}:{server.server_address[1]} (source={args.source})")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
