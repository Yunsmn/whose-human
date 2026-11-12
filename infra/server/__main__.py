"""Threaded TLS/HTTP logging server for the local partner sites."""

from __future__ import annotations

import argparse
import secrets
import socket
import socketserver
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

from . import app
from .http1 import read_request, send_response
from .logwriter import LogWriter
from .sites import site_for_host
from .tls_parse import parse_client_hello, peek_client_hello

IDLE_TIMEOUT = 60.0


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, options):
        self.options = options
        super().__init__(address, handler)


class Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.conn_ts = time.time()
        self.conn_id = secrets.token_hex(12)
        self.client_ip, self.client_port = self.client_address[:2]
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
        site, root = site_for_host(host, self.server.options["sites_dir"])
        run_id, path = app.split_run_id(request["path"])
        response = app.route({**request, "path": path}, root, run_id)
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
    common = {"writer": writer, "source": args.source, "sites_dir": args.sites_dir}
    servers = [Server((args.host, args.port), Handler, {**common, "tls": True, "context": context})]
    if args.plain_port:
        servers.append(Server((args.host, args.plain_port), Handler, {**common, "tls": False}))
    return servers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--plain-port", type=int)
    parser.add_argument("--cert", default="data/certs/server.pem")
    parser.add_argument("--key", default="data/certs/server-key.pem")
    parser.add_argument("--log-dir", default="data/logs")
    parser.add_argument("--source", default="", help="label for this server's logs, e.g. local-c or vm")
    parser.add_argument("--sites-dir", default="infra/sites")
    parser.add_argument("--alpn", default="h2,http/1.1")
    args = parser.parse_args(argv)
    if not args.source:
        parser.error("--source is required (with Docker: set WH_SOURCE in .env, e.g. WH_SOURCE=local-c)")
    servers = build_servers(args)
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
