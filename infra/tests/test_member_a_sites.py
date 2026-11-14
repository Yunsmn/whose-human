from pathlib import Path

import pytest

SITES = Path(__file__).parents[1] / "sites"


@pytest.mark.parametrize("site", ["site1", "site2"])
def test_input_page_has_visible_post_and_get_submission_paths(site):
    page = (SITES / site / "input.html").read_text(encoding="utf-8")

    assert '<form method="post" action="submit">' in page
    assert 'name="text"' in page
    assert '<a href="submit?text=YOUR_SUMMARY">' in page
    assert "exactly two sentences" in page
    assert 'type="hidden"' not in page
    assert "display: none" not in page
    assert "visibility: hidden" not in page


@pytest.mark.parametrize("site", ["site1", "site2"])
def test_site_discloses_research_context(site):
    index = (SITES / site / "index.html").read_text(encoding="utf-8").lower()

    assert "instrumented" in index
    assert "fictional" in index
