"""Static site routing and path safety."""

from pathlib import Path
from urllib.parse import unquote


def site_for_host(host: str, sites_dir: str | Path) -> tuple[str, Path]:
    name = host.lower().split(":", 1)[0].strip("[]")
    site = (
        "site1"
        if name in ("site1.test", "localhost", "127.0.0.1")
        else "site2"
        if name == "site2.test"
        else "default"
    )
    root = Path(sites_dir) / site
    if not root.is_dir():
        root = Path(sites_dir) / "site1"
        site = "site1"
    return site, root


def safe_site_path(root: str | Path, url_path: str) -> Path | None:
    root_path = Path(root).resolve()
    relative = unquote(url_path).lstrip("/") or "index.html"
    candidate = (root_path / relative).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        return None
    return candidate
