"""Shared visit sequence for the Python baselines.

Every stack does exactly the same four requests, so differences in the logs come from the HTTP
stack, not from the script. Usage of each script: ``python <script>.py <base_url> <text>``.

``WH_THINK_TIME`` (set by the runner's ``--think-time``) adds a pause before every request after
the first: ``3`` waits 3 seconds, ``2-6`` waits a random time between 2 and 6 seconds. Unset, the
requests go back to back.
"""

from __future__ import annotations

import os
import random
import sys
import time
from collections.abc import Callable
from urllib.parse import urlencode, urljoin

THINK_ENV = "WH_THINK_TIME"


def think_range(value: str | None) -> tuple[float, float]:
    """Parse WH_THINK_TIME: unset or empty means no pause, ``3`` is 3 s, ``2-6`` is 2 to 6 s."""
    if not value or not value.strip():
        return 0.0, 0.0
    low, dash, high = value.strip().partition("-")
    try:
        lo = float(low)
        hi = float(high) if dash else lo
    except ValueError:
        lo, hi = -1.0, -1.0
    if not 0 <= lo <= hi:
        print(f"invalid {THINK_ENV}={value!r}: use seconds (3) or a range (2-6)", file=sys.stderr)
        raise SystemExit(2)
    return lo, hi


def think_seconds() -> float:
    """How long to pause before the next request (0 when WH_THINK_TIME is unset)."""
    lo, hi = think_range(os.environ.get(THINK_ENV))
    return random.uniform(lo, hi) if hi > 0 else 0.0


def parse_args(argv: list[str]) -> tuple[str, str]:
    if len(argv) != 3:
        print(f"usage: python {argv[0]} <base_url> <text>", file=sys.stderr)
        raise SystemExit(2)
    think_range(os.environ.get(THINK_ENV))  # fail before the first request, not halfway through
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
    steps: list[tuple[str, Callable[[], int]]] = [
        ("GET index.html", lambda: get(index)),
        ("GET input.html", lambda: get(page)),
        ("GET submit", lambda: get(get_submit)),
        ("POST submit", lambda: post_form(post_submit, text)),
    ]
    results = []
    for number, (step, call) in enumerate(steps):
        if number:
            time.sleep(think_seconds())
        results.append((step, call()))
    return report(results)
