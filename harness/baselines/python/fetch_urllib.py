"""Python's built-in urllib.request with its defaults."""

import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode

from common import parse_args, visit


def status(request: urllib.request.Request | str) -> int:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


if __name__ == "__main__":
    base_url, text = parse_args(sys.argv)
    sys.exit(
        visit(
            base_url,
            text,
            get=status,
            # Passing data makes urllib send a POST with a form Content-Type, as any form post must.
            post_form=lambda url, value: status(
                urllib.request.Request(url, data=urlencode({"text": value}).encode())
            ),
        )
    )
