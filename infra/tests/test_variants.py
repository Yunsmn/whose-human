"""Per-visit sentences (--visit-variants) and the content types for llms.txt and Markdown pages."""

import http.client
import json
import random
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from infra.server import variants
from infra.server.__main__ import Handler, Server
from infra.server.logwriter import LogWriter

ROOT = Path(__file__).parents[2]
SITES = ROOT / "infra" / "sites"
POOL = {
    "site1": [{"id": "lighthouse", "text": "The oldest map in the collection shows a lighthouse."}],
    "site2": [{"id": "orchard", "text": "A & B: the archive began in an orchard."}],
}


@contextmanager
def plain_server(tmp_path, sites_dir=SITES, pool=None):
    logs = tmp_path / "logs"
    options = {
        "tls": False,
        "writer": LogWriter(logs, "dev-test"),
        "source": "dev-test",
        "sites_dir": sites_dir,
        "visit_variants": pool,
        "rng": random.Random(0),
    }
    server = Server(("127.0.0.1", 0), Handler, options=options)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], logs
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def get(port, path, host="site1.test", method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, headers={"Host": host})
    response = conn.getresponse()
    result = response.status, response.getheader("Content-Type"), response.read()
    conn.close()
    return result


def records(logs, n):
    deadline = time.time() + 5
    rows = []
    while time.time() < deadline:
        rows = [json.loads(line) for p in logs.glob("*.jsonl") for line in p.read_text().splitlines()]
        if len(rows) >= n:
            break
        time.sleep(0.05)
    return [r for r in rows if r["kind"] == "request"]


def test_sentence_goes_at_the_end_of_the_article():
    page = (SITES / "site1" / "input.html").read_bytes()
    out = variants.insert_sentence(page, "A new sentence.").decode()
    assert "<p>A new sentence.</p>\n      </article>" in out
    assert out.replace("        <p>A new sentence.</p>\n", "") == page.decode()


def test_sentence_follows_the_first_paragraph_without_an_article():
    page = (SITES / "site1" / "index.html").read_bytes()
    out = variants.insert_sentence(page, "A new sentence.").decode()
    first_p_end = page.decode().index("</p>") + len("</p>")
    assert out[first_p_end:].startswith("\n      <p>A new sentence.</p>")
    assert out.replace("\n      <p>A new sentence.</p>", "", 1) == page.decode()


def test_sentence_is_escaped_and_pages_without_paragraphs_are_left_alone():
    out = variants.insert_sentence(b"<article>\n</article>", "a < b & c")
    assert b"<p>a &lt; b &amp; c</p>" in out
    assert variants.insert_sentence(b"<html><body>no paragraphs</body></html>", "x") is None


@pytest.mark.parametrize(
    "pool, problem",
    [
        ([], "object"),
        ({"site1": []}, "non-empty list"),
        ({"site1": [{"id": "a"}]}, "id and text"),
        ({"site1": [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]}, "duplicate"),
    ],
)
def test_bad_pool_files_are_refused(tmp_path, pool, problem):
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(pool), encoding="utf-8")
    with pytest.raises(ValueError, match=problem):
        variants.load_pool(path)


def test_server_inserts_and_logs_the_visit_variant(tmp_path):
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(POOL), encoding="utf-8")
    with plain_server(tmp_path, pool=variants.load_pool(path)) as (port, logs):
        _, _, page1 = get(port, "/r/dev-v/input.html")
        _, _, page2 = get(port, "/r/dev-v/", host="site2.test")
        _, _, head = get(port, "/r/dev-v/input.html", method="HEAD")
        _, _, thanks = get(port, "/r/dev-v/submit?text=hi")
        rows = records(logs, 4)
    assert b"<p>The oldest map in the collection shows a lighthouse.</p>" in page1
    assert b"<p>A &amp; B: the archive began in an orchard.</p>" in page2
    assert head == b"" and b"lighthouse" not in thanks
    assert [r["visit_variant"] for r in rows] == ["lighthouse", "orchard", None, None]


def test_without_the_flag_pages_are_byte_for_byte_unchanged(tmp_path):
    with plain_server(tmp_path) as (port, logs):
        status, _, body = get(port, "/r/dev-v/input.html")
        rows = records(logs, 1)
    assert status == 200 and body == (SITES / "site1" / "input.html").read_bytes()
    assert rows[0]["visit_variant"] is None


def test_llms_txt_and_markdown_content_types(tmp_path):
    sites = tmp_path / "sites"
    shutil.copytree(SITES, sites)
    (sites / "site1" / "llms.txt").write_bytes(b"# Research Library\n")
    (sites / "site1" / "input.md").write_bytes(b"# Research Library\n")
    (sites / "site1" / "data.bin").write_bytes(b"\x00")
    pool = {"site1": [{"id": "lighthouse", "text": "A lighthouse."}]}
    with plain_server(tmp_path, sites_dir=sites, pool=pool) as (port, logs):
        txt = get(port, "/llms.txt")
        md = get(port, "/input.md")
        other = get(port, "/data.bin")
        html_page = get(port, "/index.html")
        rows = records(logs, 4)
    assert txt[:2] == (200, "text/plain; charset=utf-8")
    assert md[:2] == (200, "text/markdown; charset=utf-8")
    assert md[2] == b"# Research Library\n"  # Markdown copies are never changed
    assert other[1] == "application/octet-stream"
    assert html_page[1] == "text/html; charset=utf-8"
    assert [r["visit_variant"] for r in rows] == [None, None, None, "lighthouse"]
