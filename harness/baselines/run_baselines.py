"""Run the Track 1b plain script baselines against our own partner sites.

Each trial gets its own run id (``b-0001``, ``b-0002``, ...), which goes into the URL as
``/r/<run_id>/`` and into one row of ``runs/b.csv`` with the label ``script_<stack>``. The
server logs the traffic; ``infra.loader.load_logs`` joins the labels later.

The scripts run natively on this machine, never in Docker: the host's runtime and TLS library
are what we measure. They only ever contact hosts on an explicit allowlist.

    python -m harness.baselines.run_baselines --list
    python -m harness.baselines.run_baselines --dev --trials 1
    python -m harness.baselines.run_baselines --trials 30

See harness/baselines/README.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import re
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "harness" / "baselines"
MANIFEST = ROOT / "runs" / "b.csv"
MANIFEST_COLUMNS = ["run_id", "label_agent", "label_model", "label_user", "machine", "network", "notes"]
DEFAULT_CA = ROOT / "data" / "certs" / "ca.pem"
DEFAULT_URL_TEMPLATE = "https://{site}.test:8443/r/{run_id}/"
DEFAULT_ALLOWED_HOSTS = ("site1.test", "site2.test", "localhost", "127.0.0.1")
SUBMISSION_TEXT = "baseline script submission"
RUN_ID_PATTERN = re.compile(r"^b-(\d+)$")
TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Stack:
    """One HTTP stack. ``kind`` decides how the command is built and the version probed."""

    name: str
    kind: str  # node, python, curl or go
    target: str  # script path relative to its folder, or the Go package; unused for curl
    package: str | None = None  # npm package (node), distribution name (python), module (go)
    extra_args: tuple[str, ...] = field(default=())

    @property
    def label(self) -> str:
        return f"script_{self.name}"


STACKS: dict[str, Stack] = {
    stack.name: stack
    for stack in (
        Stack("axios-1.8.4", "node", "fetch_axios.mjs", "axios-1.8.4", ("axios-1.8.4",)),
        Stack("axios", "node", "fetch_axios.mjs", "axios-current", ("axios-current",)),
        Stack("got", "node", "fetch_got.mjs", "got"),
        Stack("node-fetch", "node", "fetch_native.mjs"),
        Stack("node-https", "node", "fetch_https.mjs"),
        Stack("curl", "curl", ""),
        Stack("requests", "python", "fetch_requests.py", "requests"),
        Stack("httpx", "python", "fetch_httpx.py", "httpx"),
        Stack("urllib", "python", "fetch_urllib.py"),
        Stack("aiohttp", "python", "fetch_aiohttp.py", "aiohttp"),
        Stack("go-nethttp", "go", "./nethttp"),
        Stack("colly", "go", "./colly", "github.com/gocolly/colly/v2"),
    )
}


# ---------------------------------------------------------------- run ids and the manifest


def next_run_number(manifest: Path) -> int:
    """Return the next free number for ``b-<number>`` ids in the manifest."""
    if not manifest.exists():
        return 1
    with manifest.open(encoding="utf-8", newline="") as stream:
        numbers = [
            int(match.group(1))
            for row in csv.DictReader(stream)
            if (match := RUN_ID_PATTERN.match((row.get("run_id") or "").strip()))
        ]
    return max(numbers, default=0) + 1


def format_run_id(number: int) -> str:
    return f"b-{number:04d}"


def dev_run_id() -> str:
    return f"dev-b-{secrets.token_hex(3)}"


def append_manifest_row(manifest: Path, row: dict[str, str]) -> None:
    """Append one row, writing the header first if the file is new or empty."""
    missing = [column for column in MANIFEST_COLUMNS if column not in row]
    if missing:
        raise ValueError(f"manifest row is missing {missing}")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    new_file = not manifest.exists() or manifest.stat().st_size == 0
    if not new_file:
        with manifest.open("rb") as stream:
            stream.seek(-1, os.SEEK_END)
            needs_newline = stream.read(1) not in (b"\n", b"\r")
    with manifest.open("a", encoding="utf-8", newline="") as stream:
        if not new_file and needs_newline:
            stream.write("\n")
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        if new_file:
            writer.writeheader()
        writer.writerow({column: row[column] for column in MANIFEST_COLUMNS})


# ------------------------------------------------------------------- privacy-safe notes


_FOUR_PART = re.compile(r"\b(\d+\.\d+\.\d+)(?:\.\d+)+\b")


def safe_version(text: str) -> str:
    """Cut version numbers to three parts.

    runs/b.csv is committed, and the CI private-data guard reads any four-part number as an IP
    address.
    """
    return _FOUR_PART.sub(r"\1", text)


def os_description() -> str:
    return safe_version(f"{platform.system()} {platform.release()} ({platform.version()})")


# ---------------------------------------------------------------- hosts and commands


def allowed_hosts(environ: dict[str, str] | None = None) -> set[str]:
    environ = os.environ if environ is None else environ
    extra = {host.strip().lower() for host in environ.get("WH_ALLOWED_HOSTS", "").split(",") if host.strip()}
    return set(DEFAULT_ALLOWED_HOSTS) | extra


def base_url(template: str, site: str, run_id: str, hosts: set[str]) -> str:
    """Build the run's base URL and refuse any host outside the allowlist."""
    url = template.format(site=site, run_id=run_id)
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise ValueError(f"unsupported scheme in {url!r}")
    host = (parts.hostname or "").lower()
    if host not in hosts:
        raise ValueError(
            f"refusing to contact {host!r}: not in the allowlist {sorted(hosts)}. "
            "This project only sends traffic to its own servers; add a host with WH_ALLOWED_HOSTS."
        )
    return url if url.endswith("/") else url + "/"


def commands(stack: Stack, url: str, text: str = SUBMISSION_TEXT) -> list[tuple[list[str], Path]]:
    """Return the (argv, working directory) pairs that make one visit with this stack."""
    if stack.kind == "node":
        return [(["node", stack.target, *stack.extra_args, url, text], HERE / "node")]
    if stack.kind == "python":
        return [([sys.executable, stack.target, url, text], HERE / "python")]
    if stack.kind == "go":
        return [(["go", "run", stack.target, url, text], HERE / "go")]
    if stack.kind == "curl":
        # One curl process per request, as agents that shell out to curl do. -sS, -o and -w only
        # change what curl prints, not what it sends.
        quiet = ["curl", "-sS", "-o", os.devnull, "-w", "%{http_code}\\n"]
        return [
            ([*quiet, url + "index.html"], HERE),
            ([*quiet, url + "input.html"], HERE),
            ([*quiet, "-G", "--data-urlencode", f"text={text}", url + "submit"], HERE),
            ([*quiet, "--data-urlencode", f"text={text}", url + "submit"], HERE),
        ]
    raise ValueError(f"unknown stack kind {stack.kind!r}")


def child_environment(ca: Path | None, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Point every stack at our local CA. This changes which certificates are trusted, never
    what the client sends in its ClientHello. Go on Windows and macOS ignores these variables
    and needs the CA in the system store (infra/README.md, step 3)."""
    env = dict(os.environ if environ is None else environ)
    if ca is not None:
        for variable in ("NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            env[variable] = str(ca)
    return env


# ---------------------------------------------------------------------- versions


def _output(argv: list[str], cwd: Path = HERE) -> str | None:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _python_version(distribution: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _go_module_version(module: str) -> str | None:
    match = re.search(rf"{re.escape(module)}\s+(v[\w.\-]+)", (HERE / "go" / "go.mod").read_text())
    return match.group(1) if match else None


def probe(stack: Stack) -> str | None:
    """Describe the stack's library and runtime versions, or return None if it can't run here."""
    if stack.kind == "node":
        node = _output(["node", "--version"])
        if node is None:
            return None
        if stack.package:
            package_json = HERE / "node" / "node_modules" / stack.package / "package.json"
            if not package_json.exists():
                return None
            library = f"{stack.package.split('-')[0]} {json.loads(package_json.read_text())['version']}"
        elif stack.name == "node-fetch":
            library = f"undici {_output(['node', '-p', 'process.versions.undici'])}"
        else:
            library = "node https"
        return f"{library}; node {node.lstrip('v')}"
    if stack.kind == "python":
        python = platform.python_version()
        if stack.package:
            version = _python_version(stack.package)
            return None if version is None else f"{stack.package} {version}; python {python}"
        return f"urllib; python {python}"
    if stack.kind == "curl":
        if shutil.which("curl") is None:
            return None
        first = (_output(["curl", "--version"]) or "").splitlines()[:1]
        if not first:
            return None
        words = first[0].split()
        backend = next(
            (
                w
                for w in words
                if w.split("/")[0]
                in (
                    "OpenSSL",
                    "Schannel",
                    "SecureTransport",
                    "LibreSSL",
                    "BoringSSL",
                    "GnuTLS",
                    "wolfSSL",
                    "mbedTLS",
                    "rustls",
                )
            ),
            "?",
        )
        return f"curl {words[1]}; tls {backend}"
    if stack.kind == "go":
        go = _output(["go", "version"])
        if go is None:
            return None
        runtime = go.split()[2] if len(go.split()) > 2 else go
        if stack.package:
            return f"colly {_go_module_version(stack.package)}; {runtime}"
        return f"net/http; {runtime}"
    raise ValueError(f"unknown stack kind {stack.kind!r}")


# ---------------------------------------------------------------------- running


@dataclass
class Job:
    stack: Stack
    site: str
    trial: int


def plan(stacks: list[Stack], sites: list[str], trials: int, seed: int) -> list[Job]:
    """All (stack, site, trial) jobs in a random order, so time of day doesn't track the stack."""
    jobs = [Job(stack, site, trial) for stack in stacks for site in sites for trial in range(1, trials + 1)]
    random.Random(seed).shuffle(jobs)
    return jobs


def run_job(argv_list: list[tuple[list[str], Path]], env: dict[str, str]) -> tuple[int, str]:
    """Run one visit. Returns (exit code, combined output)."""
    output, code = [], 0
    for argv, cwd in argv_list:
        try:
            result = subprocess.run(
                argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, f"{exc}"
        output.append((result.stdout + result.stderr).strip())
        if result.returncode != 0:
            code = result.returncode
        elif argv[0] == "curl" and result.stdout.strip() != "200":
            code = 1
    return code, "\n".join(output)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--stacks", nargs="+", default=["all"], help=f"stack names, or all: {', '.join(STACKS)}"
    )
    parser.add_argument("--sites", nargs="+", default=["site1", "site2"])
    parser.add_argument("--trials", type=int, default=30, help="trials per stack per site (default 30)")
    parser.add_argument("--dev", action="store_true", help="use dev- run ids and write no manifest row")
    parser.add_argument("--user", default="baseline", help="label_user for these runs (default baseline)")
    parser.add_argument(
        "--machine",
        default=f"b-{platform.system().lower()}",
        help="short machine label, never a hostname",
    )
    parser.add_argument("--network", default="local", help="one word: local, home, campus, mobile or vpn")
    parser.add_argument("--url-template", default=DEFAULT_URL_TEMPLATE)
    parser.add_argument("--ca", type=Path, default=DEFAULT_CA, help="CA certificate the stacks should trust")
    parser.add_argument("--gap", type=float, default=2.0, help="seconds between trials (default 2)")
    parser.add_argument("--seed", type=int, default=None, help="random seed for the trial order")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--list", action="store_true", help="list stacks and their versions, then exit")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and commands, run nothing")
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials must be at least 1")
    unknown = [name for name in args.stacks if name != "all" and name not in STACKS]
    if unknown:
        parser.error(f"unknown stack(s): {', '.join(unknown)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected = list(STACKS.values()) if "all" in args.stacks else [STACKS[name] for name in args.stacks]
    versions = {stack.name: probe(stack) for stack in selected}

    if args.list:
        for stack in selected:
            print(f"{stack.name:12} {stack.label:22} {versions[stack.name] or 'NOT AVAILABLE'}")
        return 0

    unavailable = [name for name, version in versions.items() if version is None]
    if unavailable:
        print(f"skipping stacks that can't run here: {', '.join(unavailable)}", file=sys.stderr)
    stacks = [stack for stack in selected if versions[stack.name] is not None]
    if not stacks:
        print("no stack can run on this machine", file=sys.stderr)
        return 1

    hosts = allowed_hosts()
    for site in args.sites:  # fail before running anything if a site is outside the allowlist
        base_url(args.url_template, site, "check", hosts)

    seed = args.seed if args.seed is not None else secrets.randbelow(2**31)
    jobs = plan(stacks, args.sites, args.trials, seed)
    ca = args.ca if args.ca.exists() else None
    if ca is None:
        print(f"warning: CA file {args.ca} not found; stacks will use their default trust", file=sys.stderr)
    env = child_environment(ca)
    machine_os = os_description()
    print(f"{len(jobs)} trials, seed {seed}, {'dev' if args.dev else 'manifest ' + str(args.manifest)}")

    number = next_run_number(args.manifest)
    failures = 0
    for index, job in enumerate(jobs, 1):
        run_id = dev_run_id() if args.dev else format_run_id(number)
        url = base_url(args.url_template, job.site, run_id, hosts)
        argv_list = commands(job.stack, url)
        prefix = f"[{index}/{len(jobs)}] {run_id} {job.stack.name} {job.site} trial {job.trial}"
        if args.dry_run:
            print(prefix)
            for argv, cwd in argv_list:
                print(f"    (cd {cwd.relative_to(ROOT)}) {' '.join(argv)}")
            number += 1
            continue

        code, output = run_job(argv_list, env)
        status = "ok" if code == 0 else f"FAILED exit {code}"
        print(f"{prefix}: {status}")
        if code != 0:
            failures += 1
            print("    " + output.replace("\n", "\n    "), file=sys.stderr)
        if not args.dev:
            notes = (
                f"{versions[job.stack.name]}; os {machine_os}; site {job.site}; "
                f"trial {job.trial}/{args.trials}; seed {seed}; exit {code}"
            )
            append_manifest_row(
                args.manifest,
                {
                    "run_id": run_id,
                    "label_agent": job.stack.label,
                    "label_model": "",
                    "label_user": args.user,
                    "machine": args.machine,
                    "network": args.network,
                    "notes": safe_version(notes),
                },
            )
            number += 1
        if index < len(jobs):
            time.sleep(args.gap)

    if failures:
        print(f"{failures} of {len(jobs)} trials failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
