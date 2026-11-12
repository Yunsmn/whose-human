"""HTTP/2 handling and raw-frame (Akamai) fingerprint extraction."""

from __future__ import annotations

from urllib.parse import urlsplit

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import ConnectionTerminated, DataReceived, RequestReceived, StreamEnded, StreamReset

from .http1 import MAX_BODY

PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
FRAME_HEADERS, FRAME_PRIORITY, FRAME_SETTINGS, FRAME_WINDOW_UPDATE = 1, 2, 4, 8
PSEUDO_CODES = {":method": "m", ":authority": "a", ":scheme": "s", ":path": "p"}


class FrameFingerprint:
    """Collects the client's frames sent before its first HEADERS frame (Akamai fingerprint inputs)."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.settings: list[str] = []
        self.window_update: str | None = None
        self.priority: list[str] = []
        self.done = False

    def feed(self, data: bytes) -> None:
        if self.done:
            return
        self.buffer.extend(data)
        if self.buffer.startswith(PREFACE):
            del self.buffer[: len(PREFACE)]
        while not self.done and len(self.buffer) >= 9:
            length = int.from_bytes(self.buffer[:3], "big")
            if len(self.buffer) < 9 + length:
                return
            frame_type, flags = self.buffer[3], self.buffer[4]
            stream = int.from_bytes(self.buffer[5:9], "big") & 0x7FFFFFFF
            payload = bytes(self.buffer[9 : 9 + length])
            del self.buffer[: 9 + length]
            self._frame(frame_type, flags, stream, payload)

    def _frame(self, frame_type: int, flags: int, stream: int, payload: bytes) -> None:
        if frame_type == FRAME_HEADERS:
            self.done = True
            self.buffer.clear()
        elif frame_type == FRAME_SETTINGS and not flags & 0x1 and not self.settings:
            for offset in range(0, len(payload) - 5, 6):
                key = int.from_bytes(payload[offset : offset + 2], "big")
                value = int.from_bytes(payload[offset + 2 : offset + 6], "big")
                self.settings.append(f"{key}:{value}")
        elif frame_type == FRAME_WINDOW_UPDATE and stream == 0 and len(payload) == 4:
            if self.window_update is None:
                self.window_update = str(int.from_bytes(payload, "big") & 0x7FFFFFFF)
        elif frame_type == FRAME_PRIORITY and len(payload) == 5:
            exclusive = payload[0] >> 7
            parent = int.from_bytes(payload[:4], "big") & 0x7FFFFFFF
            self.priority.append(f"{stream}:{exclusive}:{parent}:{payload[4] + 1}")

    def akamai(self, pseudo_order: list[str]) -> str:
        """Akamai format: SETTINGS|WINDOW_UPDATE|PRIORITY|pseudo-header order (e.g. m,a,s,p)."""
        return "|".join(
            [
                ";".join(self.settings),
                self.window_update or "00",
                ",".join(self.priority) or "0",
                ",".join(PSEUDO_CODES.get(key, "?") for key in pseudo_order),
            ]
        )


def _request_from_headers(headers: list[list[str]]) -> dict:
    pseudo = dict(h for h in headers if h[0].startswith(":"))
    target = pseudo.get(":path", "/")
    return {
        "method": pseudo.get(":method", "GET"),
        "target": target,
        "path": urlsplit(target).path,
        "headers": headers,
        "pseudo_order": [h[0] for h in headers if h[0].startswith(":")],
        "authority": pseudo.get(":authority", ""),
        "body": bytearray(),
    }


def _respond(h2conn: H2Connection, stream_id: int, response: dict) -> None:
    body = response["body"]
    headers = [
        (":status", str(response["status"])),
        ("content-type", response["content_type"]),
        ("content-length", str(len(body))),
    ]
    if response["new_cookie"]:
        headers.append(("set-cookie", f"wh_session={response['new_cookie']}; Path=/; SameSite=Lax"))
    h2conn.send_headers(stream_id, headers, end_stream=not body)
    if body:
        h2conn.send_data(stream_id, body, end_stream=True)


def handle_http2(handler, conn, tls: dict) -> None:
    """Serve HTTP/2 streams and write one log record per completed stream."""
    h2conn = H2Connection(config=H2Configuration(client_side=False, header_encoding="utf-8"))
    h2conn.initiate_connection()
    conn.sendall(h2conn.data_to_send())
    fingerprint = FrameFingerprint()
    pending: dict[int, dict] = {}
    index = 0
    while True:
        data = conn.recv(65535)
        if not data:
            return
        fingerprint.feed(data)
        for event in h2conn.receive_data(data):
            if isinstance(event, RequestReceived):
                pending[event.stream_id] = _request_from_headers([[k, v] for k, v in event.headers])
            elif isinstance(event, DataReceived) and event.stream_id in pending:
                body = pending[event.stream_id]["body"]
                if len(body) + len(event.data) > MAX_BODY:
                    raise ValueError("HTTP/2 request body too large")
                body.extend(event.data)
                h2conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            elif isinstance(event, StreamReset):
                pending.pop(event.stream_id, None)
            elif isinstance(event, ConnectionTerminated):
                conn.sendall(h2conn.data_to_send())
                return
            elif isinstance(event, StreamEnded) and event.stream_id in pending:
                req = pending.pop(event.stream_id)
                index += 1
                request = {**req, "body_bytes": bytes(req["body"])}
                extra = {
                    "h2_settings": fingerprint.settings,
                    "h2_window_update": fingerprint.window_update,
                    "h2_priority": fingerprint.priority,
                    "h2_pseudo_order": req["pseudo_order"],
                    "h2_fp": fingerprint.akamai(req["pseudo_order"]),
                }
                response = handler.process(request, tls, index, "HTTP/2", ":authority", extra)
                _respond(h2conn, event.stream_id, response)
        outgoing = h2conn.data_to_send()
        if outgoing:
            conn.sendall(outgoing)
