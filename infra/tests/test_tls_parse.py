from infra.server.tls_parse import ja3_fingerprint, parse_client_hello


def test_ja3_readme_reference_digest():
    sample = "769,47-53-5-10-49161-49162-49171-49172-50-56-19-4,0-10-11,23-24-25,0"
    assert ja3_fingerprint(sample) == (
        sample,
        "ada70206e40642a3e4461f35503241d5",
    )


def test_ja4_reference_vectors_and_grease_invariance():
    import json
    from pathlib import Path

    from infra.server.tls_parse import ja4_fingerprint

    vectors = json.loads((Path(__file__).parent / "fixtures" / "ja4_vectors.json").read_text())
    for vector in vectors:
        extensions = [(ext, bytes.fromhex(data)) for ext, data in vector["extensions"]]
        actual, raw = ja4_fingerprint(
            vector["legacy_version"],
            vector["ciphers"],
            extensions,
            vector["sni"],
            vector["alpn"],
        )
        assert actual == vector["ja4"], vector["source"]
        assert raw.startswith("t13d1516h2_")

        encoded_extensions = bytearray()
        for ext, data in extensions:
            if ext == 0:
                hostname = b"example.test"
                data = b"\x00" + bytes([len(hostname) + 3, 0]) + len(hostname).to_bytes(2, "big") + hostname
            elif ext == 16:
                data = b"\x00\x03\x02h2"
            encoded_extensions.extend(ext.to_bytes(2, "big"))
            encoded_extensions.extend(len(data).to_bytes(2, "big"))
            encoded_extensions.extend(data)
        cipher_bytes = b"".join(c.to_bytes(2, "big") for c in vector["ciphers"])
        hello_body = (
            b"\x03\x03"
            + bytes(32)
            + b"\x00"
            + len(cipher_bytes).to_bytes(2, "big")
            + cipher_bytes
            + b"\x01\x00"
            + len(encoded_extensions).to_bytes(2, "big")
            + encoded_extensions
        )
        handshake = b"\x01" + len(hello_body).to_bytes(3, "big") + hello_body
        record = b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake
        parsed = parse_client_hello(record)
        assert parsed["ja4"] == vector["ja4"], vector["source"]
