"""Shared visit sequence for the Python baselines.

Every stack does exactly the same four requests, so differences in the logs come from the HTTP
stack, not from the script. Usage of each script: ``python <script>.py <base_url> <text>``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from urllib.parse import urlencode, urljoin


def parse_args(argv: list[str]) -> tuple[str, str]:
    if len(argv) != 3:
        print(f"usage: python {argv[0]} <base_url> <text>", file=sys.stderr)
        raise SystemExit(2)
    base_url, text = argv[1], argv[2]
    return (base_url if base_url.endswith("/") else base_url + "/"), text


def urls(base_url: str, text: str) -> tuple[str, str, str, str]:
    """Return (index, input, GET submit, POST submit) URLs."""
    submit = urljoin(base_url, "submit")
    return (
        urljoin(base_url, "index.html"),
        urljoin(base_url, "input.html"),
        submit + "?" + urlencode({"text": text}),
        submit,
    )


def report(results: list[tuple[str, int]]) -> int:
    for step, status in results:
        print(f"{step} {status}")
    return 0 if all(status == 200 for _, status in results) else 1


def visit(base_url: str, text: str, get: Callable[[str], int], post_form: Callable[[str, str], int]) -> int:
    index, page, get_submit, post_submit = urls(base_url, text)
    return report(
        [
            ("GET index.html", get(index)),
            ("GET input.html", get(page)),
            ("GET submit", get(get_submit)),
            ("POST submit", post_form(post_submit, text)),
        ]
    )
