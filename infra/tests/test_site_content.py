"""VM-only site content agreed in linking/protocol.md."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
SITES = ROOT / "infra" / "sites"


def test_markdown_alternates_and_llms_files_exist():
    for site in ("site1", "site2"):
        root = SITES / site
        assert (root / "llms.txt").is_file()
        for stem in ("index", "input"):
            assert (root / f"{stem}.md").is_file()
            html = (root / f"{stem}.html").read_text(encoding="utf-8")
            assert f'<link rel="alternate" type="text/markdown" href="{stem}.md">' in html


def test_visit_variant_pool_has_distinctive_keywords():
    pool = json.loads((SITES / "visit-variants.json").read_text(encoding="utf-8"))
    assert set(pool) == {"site1", "site2"}
    for entries in pool.values():
        assert len(entries) == 20
        ids = [entry["id"] for entry in entries]
        assert len(ids) == len(set(ids))
        assert all(entry["id"].lower() in entry["text"].lower() for entry in entries)
