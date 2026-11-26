"""Request routing and log-record helpers shared by the HTTP/1.1 and HTTP/2 handlers."""

from __future__ import annotations

import http.cookies
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .sites import safe_site_path

MAX_LOG_BODY = 65536
TLS_FIELDS = (
    "sni",
    "alpn_offered",
    "alpn_negotiated",
    "tls_version",
    "tls_cipher",
    "client_hello_hex",
    "ja3",
    "ja3_md5",
    "ja4",
    "ja4_r",
)
THANK_YOU = b"<!doctype html><html><body><p>Thank you for contributing.</p></body></html>"
HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
# llms.txt and the Markdown copies of each page (linking/protocol.md, "Site changes on the VM", B);
# any other file goes out as application/octet-stream.
CONTENT_TYPES = {
    ".html": HTML,
    ".htm": HTML,
    ".md": "text/markdown; charset=utf-8",
    ".txt": TEXT,
}


def split_run_id(path: str) -> tuple[str | None, str]:
    """Strip a `/r/<run_id>/` prefix; return (run_id, remaining path)."""
    if not path.startswith("/r/"):
        return None, path
    parts = path.split("/", 3)
    if len(parts) < 3 or not parts[2]:
        return None, path
    return parts[2], "/" + (parts[3] if len(parts) > 3 else "")


def body_fields(raw: bytes) -> dict:
    return {
        "body": raw[:MAX_LOG_BODY].decode("utf-8", "replace"),
        "body_len": len(raw),
        "body_truncated": len(raw) > MAX_LOG_BODY,
    }


def session_for(headers: list[list[str]], response_html: bool) -> tuple[str | None, str | None]:
    """Return (existing session id, new session id to set via cookie)."""
    cookie_value = next((v for k, v in headers if k.lower() == "cookie"), "")
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(cookie_value)
    except http.cookies.CookieError:
        pass
    current = cookie.get("wh_session")
    session = current.value if current else None
    return session, secrets.token_hex(16) if response_html and not session else None


def _submitted_text(request: dict, params: dict) -> str:
    if request["method"] == "GET":
        return params.get("text", [""])[0]
    raw_text = request["body_bytes"].decode("utf-8", "replace")
    content_types = {v.lower() for k, v in request["headers"] if k.lower() == "content-type"}
    if any("application/x-www-form-urlencoded" in value for value in content_types):
        return parse_qs(raw_text, keep_blank_values=True).get("text", [raw_text])[0]
    return raw_text


def route(request: dict, root: Path, run_id: str | None) -> dict:
    """Decide the response for a request whose `path` already has the run prefix removed.

    Returns a dict with status, body, content_type, run_id and submitted_text (None unless /submit).
    """
    method, path = request["method"], request["path"]
    params = parse_qs(urlsplit(request["target"]).query, keep_blank_values=True)
    result = {"run_id": run_id or params.get("run", [None])[0], "submitted_text": None}
    if path == "/submit":
        if method not in ("GET", "POST"):
            return {**result, "status": 405, "body": b"Method Not Allowed", "content_type": TEXT}
        submitted = _submitted_text(request, params)
        return {**result, "status": 200, "body": THANK_YOU, "content_type": HTML, "submitted_text": submitted}
    if method not in ("GET", "HEAD"):
        return {**result, "status": 405, "body": b"Method Not Allowed", "content_type": TEXT}
    candidate = safe_site_path(root, path)
    if candidate is not None and candidate.is_dir():
        candidate = candidate / "index.html"
    try:
        body = candidate.read_bytes() if candidate is not None else None
    except OSError:
        body = None
    if body is None:
        return {**result, "status": 404, "body": b"Not Found", "content_type": TEXT}
    content_type = CONTENT_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
    return {**result, "status": 200, "body": body if method != "HEAD" else b"", "content_type": content_type}


def tls_fields(tls: dict) -> dict:
    return {key: tls.get(key) for key in TLS_FIELDS} if tls.get("tls_version") or tls.get("ja4") else {}
