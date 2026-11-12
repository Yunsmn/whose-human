"""Small ordered HTTP/1 parser and response writer."""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

MAX_HEADERS = 65536
MAX_BODY = 1024 * 1024


def _read_exact(reader, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = reader.read(length - len(chunks))
        if not chunk:
            raise ConnectionError("client closed during request body")
        chunks.extend(chunk)
    return bytes(chunks)


def read_request(sock: socket.socket) -> dict | None:
    reader = sock.makefile("rb", buffering=0)
    line = reader.readline(8193)
    if not line:
        return None
    if len(line) > 8192 or not line.endswith(b"\r\n"):
        raise ValueError("invalid or oversized request line")
    try:
        method, target, version = line[:-2].decode("latin-1").split(" ", 2)
    except ValueError as exc:
        raise ValueError("malformed request line") from exc
    headers: list[list[str]] = []
    total = 0
    while True:
        raw = reader.readline(8193)
        total += len(raw)
        if total > MAX_HEADERS:
            raise ValueError("headers too large")
        if raw == b"\r\n":
            break
        if not raw or b":" not in raw:
            raise ValueError("malformed header")
        name, value = raw[:-2].split(b":", 1)
        headers.append([name.decode("latin-1"), value.strip().decode("latin-1")])
    header_map = {name.lower(): value for name, value in headers}
    if "chunked" in header_map.get("transfer-encoding", "").lower():
        body = bytearray()
        while True:
            size_line = reader.readline(128).split(b";", 1)[0].strip()
            size = int(size_line, 16)
            if size == 0:
                while True:
                    trailer = reader.readline(8193)
                    if trailer == b"\r\n":
                        break
                    if not trailer:
                        raise ConnectionError("client closed in chunk trailer")
                break
            chunk = _read_exact(reader, size + 2)
            if not chunk.endswith(b"\r\n"):
                raise ValueError("malformed chunk terminator")
            body.extend(chunk[:-2])
            if len(body) > MAX_BODY:
                raise ValueError("request body too large")
    else:
        size = int(header_map.get("content-length", "0"))
        if size > MAX_BODY:
            raise ValueError("request body too large")
        body = bytearray()
        while len(body) < size:
            chunk = reader.read(size - len(body))
            if not chunk:
                raise ConnectionError("client closed during request body")
            body.extend(chunk)
    parsed = urlsplit(target)
    return {
        "method": method,
        "target": target,
        "path": parsed.path,
        "query": parsed.query,
        "headers": headers,
        "body_bytes": bytes(body),
        "version": version,
        "keep_alive": version == "HTTP/1.1" and header_map.get("connection", "").lower() != "close",
    }


def send_response(
    sock: socket.socket,
    status: int,
    body: bytes,
    content_type: str,
    cookie: str | None = None,
    keep_alive: bool = True,
) -> None:
    phrases = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        405: "Method Not Allowed",
    }
    headers = [
        f"HTTP/1.1 {status} {phrases.get(status, 'Error')}",
        f"Content-Length: {len(body)}",
        f"Content-Type: {content_type}",
        "Connection: keep-alive" if keep_alive else "Connection: close",
    ]
    if cookie:
        headers.append(f"Set-Cookie: wh_session={cookie}; Path=/; SameSite=Lax")
    sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body)
