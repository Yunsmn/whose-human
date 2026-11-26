"""Static site routing and path safety."""

from pathlib import Path
from urllib.parse import unquote

LOCAL_HOSTS = {"site1.test": "site1", "localhost": "site1", "127.0.0.1": "site1", "site2.test": "site2"}


def parse_site_hosts(value: str | None) -> dict[str, str]:
    """Parse ``--site-hosts`` (``host=site,host=site``) into a lowercase host -> site mapping."""
    mapping = {}
    for item in filter(None, (part.strip() for part in (value or "").split(","))):
        host, sep, site = item.partition("=")
        if not sep or not host.strip() or not site.strip():
            raise ValueError(f"--site-hosts: expected host=site, got {item!r}")
        mapping[host.strip().lower().rstrip(".")] = site.strip()
    return mapping


def site_for_host(
    host: str, sites_dir: str | Path, site_hosts: dict[str, str] | None = None
) -> tuple[str, Path]:
    """Map a Host / :authority value to (site name, its folder). ``site_hosts`` (from
    ``--site-hosts``) adds hosts such as the VM's domains to the local ones; an unknown host,
    or a site without a folder, falls back to site1."""
    name = host.lower().split(":", 1)[0].strip("[]").rstrip(".")
    site = {**LOCAL_HOSTS, **(site_hosts or {})}.get(name, "default")
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
