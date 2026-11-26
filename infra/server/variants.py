"""Per-visit sentences for the VM sites (linking/protocol.md, "Site changes on the VM", A).

With ``--visit-variants <pool file>`` every HTML page view gets one sentence drawn at random from
its site's pool, as an ordinary paragraph, and the request record logs the sentence's id as
``visit_variant``. Without the flag pages are served unchanged.

Pool file (JSON), one list per site; ids are unique within a site and name the sentence's keyword::

    {"site1": [{"id": "lighthouse", "text": "The library's oldest map shows a lighthouse."}, ...],
     "site2": [...]}
"""

from __future__ import annotations

import html
import json
from pathlib import Path


def load_pool(path: str | Path) -> dict[str, list[dict]]:
    """Read and check a pool file; raise ValueError naming the first problem."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected an object of site name -> list of sentences")
    for site, entries in data.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{path}: {site} needs a non-empty list")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("id") or not entry.get("text"):
                raise ValueError(f"{path}: every {site} entry needs a non-empty id and text")
            if entry["id"] in seen:
                raise ValueError(f"{path}: duplicate id {entry['id']!r} in {site}")
            seen.add(entry["id"])
    return data


def insert_sentence(page: bytes, text: str) -> bytes | None:
    """Add ``<p>text</p>`` at the end of the page's ``<article>``, or after its first paragraph when
    it has none. Returns None when the page has neither, so it is served unchanged."""
    source = page.decode("utf-8")
    paragraph = f"<p>{html.escape(text, quote=False)}</p>"
    end = source.find("</article>")
    if end != -1:
        line_start = source.rfind("\n", 0, end) + 1
        indent = source[line_start:end]
        indent = indent if indent.isspace() else ""
        return (source[:line_start] + f"{indent}  {paragraph}\n" + source[line_start:]).encode("utf-8")
    end = source.find("</p>")
    if end == -1:
        return None
    end += len("</p>")
    line = source[source.rfind("\n", 0, end) + 1 : end]
    indent = line[: len(line) - len(line.lstrip())]
    return (source[:end] + f"\n{indent}{paragraph}" + source[end:]).encode("utf-8")


def apply(page: bytes, pool: dict[str, list[dict]] | None, site: str, rng) -> tuple[bytes, str | None]:
    """Return (page to send, id of the sentence inserted or None)."""
    entries = (pool or {}).get(site)
    if not entries:
        return page, None
    entry = rng.choice(entries)
    changed = insert_sentence(page, entry["text"])
    return (changed, entry["id"]) if changed is not None else (page, None)
