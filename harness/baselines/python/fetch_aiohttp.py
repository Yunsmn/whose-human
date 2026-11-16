"""aiohttp with its defaults. aiohttp has no module-level calls, so one session serves the run."""

import asyncio
import sys

import aiohttp
from common import parse_args, report, urls


async def main(base_url: str, text: str) -> int:
    index, page, get_submit, post_submit = urls(base_url, text)
    results = []
    async with aiohttp.ClientSession() as session:
        for step, url in (("GET index.html", index), ("GET input.html", page), ("GET submit", get_submit)):
            async with session.get(url) as response:
                await response.read()
                results.append((step, response.status))
        async with session.post(post_submit, data={"text": text}) as response:
            await response.read()
            results.append(("POST submit", response.status))
    return report(results)


if __name__ == "__main__":
    base_url, text = parse_args(sys.argv)
    sys.exit(asyncio.run(main(base_url, text)))
