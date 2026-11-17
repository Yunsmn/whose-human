from pathlib import Path

import pytest


@pytest.mark.parametrize("site", ["site1", "site2"])
def test_input_page_has_visible_post_form_and_get_fallback(site):
    page = (Path("infra/sites") / site / "input.html").read_text(encoding="utf-8")

    assert '<form method="post" action="submit">' in page
    assert "in two sentences" in page
    assert '<a href="submit?text=YOUR_SUMMARY">' in page
    assert "GET fallback" in page
    assert 'type="hidden"' not in page
    assert "<script" not in page
