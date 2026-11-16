"""httpx with its defaults: module-level calls, HTTP/1.1 (httpx only uses HTTP/2 when asked)."""

import sys

import httpx
from common import parse_args, visit

if __name__ == "__main__":
    base_url, text = parse_args(sys.argv)
    sys.exit(
        visit(
            base_url,
            text,
            get=lambda url: httpx.get(url).status_code,
            post_form=lambda url, value: httpx.post(url, data={"text": value}).status_code,
        )
    )
