"""Python requests with its defaults: module-level calls, a new session per request."""

import sys

import requests
from common import parse_args, visit

if __name__ == "__main__":
    base_url, text = parse_args(sys.argv)
    sys.exit(
        visit(
            base_url,
            text,
            get=lambda url: requests.get(url, timeout=30).status_code,
            post_form=lambda url, value: requests.post(url, data={"text": value}, timeout=30).status_code,
        )
    )
