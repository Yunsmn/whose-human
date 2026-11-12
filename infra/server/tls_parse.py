"""TLS ClientHello decoding and JA3/JA4 fingerprints."""

from __future__ import annotations

import hashlib
import socket
import time


def is_grease(value: int) -> bool:
    return value & 0x0F0F == 0x0A0A and value >> 8 == (value & 0xFF)


def ja3_fingerprint(value: str) -> tuple[str, str]:
    return value, hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


def _hash12(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else "000000000000"


def ja4_fingerprint(
    legacy_version: int,
    ciphers: list[int],
    extensions: list[tuple[int, bytes]],
    sni: str | None,
    alpn: list[str],
) -> tuple[str, str]:
    ciphers = [value for value in ciphers if not is_grease(value)]
    ext_ids = [value for value, _ in extensions if not is_grease(value)]
    versions: list[int] = []
    sigalgs: list[int] = []
    for ext, data in extensions:
        if ext == 43 and len(data) > 1:
            size = data[0]
            versions = [int.from_bytes(data[i : i + 2], "big") for i in range(1, min(size + 1, len(data)), 2)]
        if ext == 13 and len(data) > 1:
            size = int.from_bytes(data[:2], "big")
            sigalgs = [int.from_bytes(data[i : i + 2], "big") for i in range(2, min(size + 2, len(data)), 2)]
    versions = [v for v in versions if not is_grease(v)]
    version = max(versions, default=legacy_version)
    ver = {0x0304: "13", 0x0303: "12", 0x0302: "11", 0x0301: "10", 0x0300: "s3"}.get(version, "00")
    first_alpn = alpn[0].encode() if alpn else b""
    if not first_alpn:
        alpn_code = "00"
    else:

        def edge(byte: int, first: bool) -> str:
            char = chr(byte)
            if char.isascii() and char.isalnum():
                return char.lower()
            encoded = f"{byte:02x}"
            return encoded[0] if first else encoded[-1]

        alpn_code = edge(first_alpn[0], True) + edge(first_alpn[-1], False)
    prefix = f"t{ver}{'d' if sni else 'i'}{min(len(ciphers), 99):02d}{min(len(ext_ids), 99):02d}{alpn_code}"
    sig_order = ",".join(f"{v:04x}" for v in sigalgs)
    cipher_sorted = ",".join(sorted(f"{v:04x}" for v in ciphers))
    ext_sorted = ",".join(sorted(f"{v:04x}" for v in ext_ids if v not in (0, 16)))
    sorted_c = f"{ext_sorted}_{sig_order}" if sig_order else ext_sorted
    raw = f"{prefix}_{cipher_sorted}_{sorted_c}"
    ja4 = f"{prefix}_{_hash12(cipher_sorted)}_{_hash12(sorted_c)}"
    return ja4, raw


def parse_client_hello(raw: bytes) -> dict:
    """Parse one TLS handshake message provided as complete TLS records."""
    handshake = bytearray()
    offset = 0
    while offset + 5 <= len(raw):
        length = int.from_bytes(raw[offset + 3 : offset + 5], "big")
        handshake.extend(raw[offset + 5 : offset + 5 + length])
        offset += 5 + length
        if handshake and handshake[0] == 1 and len(handshake) >= 4 + int.from_bytes(handshake[1:4], "big"):
            break
    if len(handshake) < 4 or handshake[0] != 1:
        raise ValueError("incomplete or invalid ClientHello")
    payload = memoryview(handshake)[4 : 4 + int.from_bytes(handshake[1:4], "big")]
    pos = 0
    legacy = int.from_bytes(payload[pos : pos + 2], "big")
    pos += 2
    pos += 32
    sid_len = payload[pos]
    pos += 1 + sid_len
    c_len = int.from_bytes(payload[pos : pos + 2], "big")
    pos += 2
    ciphers = [int.from_bytes(payload[i : i + 2], "big") for i in range(pos, pos + c_len, 2)]
    pos += c_len
    comp_len = payload[pos]
    pos += 1 + comp_len
    extensions: list[tuple[int, bytes]] = []
    sni = None
    groups: list[int] = []
    points: list[int] = []
    sigalgs: list[int] = []
    alpn: list[str] = []
    if pos + 2 <= len(payload):
        ext_len = int.from_bytes(payload[pos : pos + 2], "big")
        pos += 2
        end = min(pos + ext_len, len(payload))
        while pos + 4 <= end:
            ext = int.from_bytes(payload[pos : pos + 2], "big")
            size = int.from_bytes(payload[pos + 2 : pos + 4], "big")
            pos += 4
            data = bytes(payload[pos : pos + size])
            pos += size
            extensions.append((ext, data))
            if ext == 0 and len(data) >= 5:
                name_len = int.from_bytes(data[3:5], "big")
                sni = data[5 : 5 + name_len].decode("ascii", "replace")
            elif ext == 10 and len(data) >= 2:
                n = int.from_bytes(data[:2], "big")
                groups = [int.from_bytes(data[i : i + 2], "big") for i in range(2, min(2 + n, len(data)), 2)]
            elif ext == 11 and data:
                points = list(data[1 : 1 + data[0]])
            elif ext == 13 and len(data) >= 2:
                n = int.from_bytes(data[:2], "big")
                sigalgs = [int.from_bytes(data[i : i + 2], "big") for i in range(2, min(2 + n, len(data)), 2)]
            elif ext == 16 and len(data) >= 2:
                end_alpn = min(2 + int.from_bytes(data[:2], "big"), len(data))
                i = 2
                while i < end_alpn:
                    n = data[i]
                    i += 1
                    alpn.append(data[i : i + n].decode("ascii", "replace"))
                    i += n
    clean_c = [v for v in ciphers if not is_grease(v)]
    clean_e = [v for v, _ in extensions if not is_grease(v)]
    clean_g = [v for v in groups if not is_grease(v)]
    ja3 = ",".join([str(legacy), *("-".join(map(str, part)) for part in (clean_c, clean_e, clean_g, points))])
    ja3, digest = ja3_fingerprint(ja3)
    ja4, ja4_r = ja4_fingerprint(legacy, ciphers, extensions, sni, alpn)
    versions = next((data for ext, data in extensions if ext == 43), b"")
    return {
        "legacy_version": legacy,
        "ciphers": ciphers,
        "extensions": extensions,
        "supported_groups": groups,
        "ec_point_formats": points,
        "signature_algorithms": sigalgs,
        "alpn_offered": alpn,
        "sni": sni,
        "ja3": ja3,
        "ja3_md5": digest,
        "ja4": ja4,
        "ja4_r": ja4_r,
        "supported_versions": versions,
        "client_hello_hex": raw.hex(),
    }


def peek_client_hello(sock: socket.socket, timeout: float = 5.0, max_size: int = 65536) -> bytes:
    """Peek until all records needed for the first handshake message are buffered."""
    deadline = time.monotonic() + timeout
    sock.settimeout(timeout)
    while time.monotonic() < deadline:
        data = sock.recv(max_size, socket.MSG_PEEK)
        end = 0
        handshake = bytearray()
        while end + 5 <= len(data):
            record_len = int.from_bytes(data[end + 3 : end + 5], "big")
            record_end = end + 5 + record_len
            if record_end > max_size:
                raise ValueError("ClientHello exceeds configured size cap")
            if len(data) < record_end:
                break
            if data[end] != 22:
                raise ValueError("expected TLS handshake record")
            handshake.extend(data[end + 5 : record_end])
            end = record_end
            if len(handshake) >= 4 and len(handshake) >= 4 + int.from_bytes(handshake[1:4], "big"):
                return data[:end]
        if len(data) >= max_size:
            raise ValueError("ClientHello exceeds configured size cap")
        time.sleep(0.01)
    raise TimeoutError("timed out waiting for complete ClientHello")
