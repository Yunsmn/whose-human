"""Run the Track 1b plain script baselines against our own partner sites.

Each trial gets its own run id (``b-0001``, ``b-0002``, ...; ``--member c`` gives ``c-0001``, ...),
which goes into the URL as ``/r/<run_id>/`` and into one row of ``runs/<member>.csv`` with the label
``script_<stack>``. The
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
MEMBERS = ("a", "b", "c")
MANIFEST_COLUMNS = ["run_id", "label_agent", "label_model", "label_user", "machine", "network", "notes"]
DEFAULT_CA = ROOT / "data" / "certs" / "ca.pem"
DEFAULT_URL_TEMPLATE = "https://{site}.test:8443/r/{run_id}/"
DEFAULT_ALLOWED_HOSTS = ("site1.test", "site2.test", "localhost", "127.0.0.1")
SUBMISSION_TEXT = "baseline script submission"
TIMEOUT_SECONDS = 180
THINK_ENV = "WH_THINK_TIME"
CURL_ENV = "WH_CURL"  # the curl binary fetch_curl.sh runs; the same one probe() reports
MAX_THINK_SECONDS = 30  # 3 pauses per visit must stay well inside TIMEOUT_SECONDS


@dataclass(frozen=True)
class Stack:
    """One HTTP stack. ``kind`` decides how the command is built and the version probed."""

    name: str
    kind: str  # node, python, curl or go
    target: str  # script path relative to its folder, or the Go package
    package: str | None = None  # npm package (node), distribution name (python), module (go)
    extra_args: tuple[str, ...] = field(default=())  # node: script arguments; curl: curl flags

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
        Stack("curl", "curl", "fetch_curl.sh"),
        # Schannel only: skips the revocation check our local CA can't pass. That drops one
        # ClientHello extension (status_request), exactly as `curl -k` does; see README.
        Stack("curl-norevoke", "curl", "fetch_curl.sh", extra_args=("--ssl-no-revoke",)),
        Stack("requests", "python", "fetch_requests.py", "requests"),
        Stack("httpx", "python", "fetch_httpx.py", "httpx"),
        Stack("urllib", "python", "fetch_urllib.py"),
        Stack("aiohttp", "python", "fetch_aiohttp.py", "aiohttp"),
        Stack("go-nethttp", "go", "./nethttp"),
        Stack("colly", "go", "./colly", "github.com/gocolly/colly/v2"),
    )
}


# ---------------------------------------------------------------- run ids and the manifest


def next_run_number(manifest: Path, member: str = "b") -> int:
    """Return the next free number for ``<member>-<number>`` ids in the manifest."""
    pattern = re.compile(rf"^{re.escape(member)}-(\d+)$")
    if not manifest.exists():
        return 1
    with manifest.open(encoding="utf-8", newline="") as stream:
        numbers = [
            int(match.group(1))
            for row in csv.DictReader(stream)
            if (match := pattern.match((row.get("run_id") or "").strip()))
        ]
    return max(numbers, default=0) + 1


def format_run_id(number: int, member: str = "b") -> str:
    return f"{member}-{number:04d}"


def dev_run_id(member: str = "b") -> str:
    return f"dev-{member}-{secrets.token_hex(3)}"


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
        return [([bash_binary(), stack.target, url, text, *stack.extra_args], HERE / "curl")]
    raise ValueError(f"unknown stack kind {stack.kind!r}")


def skipped_by_default(stack: Stack, version: str | None) -> str | None:
    """Return why a stack is left out of ``--stacks all`` on this machine, or None.

    Schannel curl (Windows) can't check revocation for our local CA and fails every request,
    while flags that skip the check change its ClientHello. It still runs when named
    explicitly, for example against the shared VM's publicly trusted certificate. Its
    ``curl-norevoke`` variant is the opposite: it exists only for Schannel curl.
    """
    schannel = stack.kind == "curl" and bool(version) and "Schannel" in version
    if stack.name == "curl" and schannel:
        return "Schannel curl fails the revocation check against the local CA (see README)"
    if stack.name == "curl-norevoke" and not schannel:
        return "--ssl-no-revoke only applies to Schannel curl (see README)"
    return None


def parse_think_time(value: str | None) -> str:
    """Validate --think-time and return it normalized ("" for none, "3", or "2-6").

    Every stack pauses for a random time in this range (seconds) before each request after the
    first, so H2 can compare agents with scripts that wait between requests too.
    """
    if value is None or not value.strip():
        return ""
    low, dash, high = value.strip().partition("-")
    try:
        lo = float(low)
        hi = float(high) if dash else lo
    except ValueError as exc:
        raise ValueError(f"--think-time {value!r}: use seconds (3) or a range (2-6)") from exc
    if not 0 <= lo <= hi:
        raise ValueError(f"--think-time {value!r}: the range must be non-negative and not decrease")
    if hi > MAX_THINK_SECONDS:
        raise ValueError(f"--think-time {value!r}: at most {MAX_THINK_SECONDS} seconds per pause")
    if hi == 0:
        return ""
    return f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}"


def bash_binary() -> str:
    """The bash on PATH. Windows starts a bare "bash" from System32 first, which is WSL's: a
    Linux bash with Linux's curl, which also doesn't receive our environment variables."""
    return shutil.which("bash") or "bash"


def curl_binary() -> str | None:
    """The curl on PATH, as a path bash can run.

    On Windows several curls can differ: Windows itself looks in System32 first, and PATH may
    name Git's mingw64 curl (Schannel), which agents that run Git Bash use. The runner resolves
    PATH once and gives fetch_curl.sh that exact binary, so the version in the notes is the one
    that ran."""
    found = shutil.which("curl")
    return Path(found).as_posix() if found else None


def child_environment(
    ca: Path | None, environ: dict[str, str] | None = None, think_time: str = ""
) -> dict[str, str]:
    """Point every stack at our local CA. This changes which certificates are trusted, never
    what the client sends in its ClientHello. Go on Windows and macOS ignores these variables
    and needs the CA in the system store (infra/README.md, step 3).

    ``think_time`` goes to the stacks as WH_THINK_TIME; without it any inherited value is removed,
    so a stray variable in the shell can't add pauses to a run that doesn't record them."""
    env = dict(os.environ if environ is None else environ)
    if ca is not None:
        for variable in ("NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            env[variable] = str(ca)
    env.pop(THINK_ENV, None)
    if think_time:
        env[THINK_ENV] = think_time
    env.pop(CURL_ENV, None)
    if curl := curl_binary():
        env[CURL_ENV] = curl
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
        curl = curl_binary()
        if curl is None:
            return None
        first = (_output([curl, "--version"]) or "").splitlines()[:1]
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
        "--member",
        choices=MEMBERS,
        default="b",
        help="who runs the baselines: sets the run id prefix and the default manifest (default b)",
    )
    parser.add_argument(
        "--machine",
        default=None,
        help="short machine label, never a hostname (default <member>-<os>)",
    )
    parser.add_argument("--network", default="local", help="one word: local, home, campus, mobile or vpn")
    parser.add_argument("--url-template", default=DEFAULT_URL_TEMPLATE)
    parser.add_argument("--ca", type=Path, default=DEFAULT_CA, help="CA certificate the stacks should trust")
    parser.add_argument("--gap", type=float, default=2.0, help="seconds between trials (default 2)")
    parser.add_argument(
        "--think-time",
        default="",
        help="pause in seconds before each request after the first, inside a visit: 3, or a random "
        f"range such as 2-6 (at most {MAX_THINK_SECONDS}; default none)",
    )
    parser.add_argument("--seed", type=int, default=None, help="random seed for the trial order")
    parser.add_argument("--manifest", type=Path, default=None, help="default runs/<member>.csv")
    parser.add_argument("--list", action="store_true", help="list stacks and their versions, then exit")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and commands, run nothing")
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials must be at least 1")
    try:
        args.think_time = parse_think_time(args.think_time)
    except ValueError as exc:
        parser.error(str(exc))
    unknown = [name for name in args.stacks if name != "all" and name not in STACKS]
    if unknown:
        parser.error(f"unknown stack(s): {', '.join(unknown)}")
    if args.manifest is None:
        args.manifest = ROOT / "runs" / f"{args.member}.csv"
    if args.machine is None:
        args.machine = f"{args.member}-{platform.system().lower()}"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected = list(STACKS.values()) if "all" in args.stacks else [STACKS[name] for name in args.stacks]
    versions = {stack.name: probe(stack) for stack in selected}

    explicit = "all" not in args.stacks
    skips = {
        stack.name: (
            "not installed"
            if versions[stack.name] is None
            else skipped_by_default(stack, versions[stack.name])
        )
        for stack in selected
    }
    if explicit:  # a stack named on the command line runs if it's installed, whatever its TLS library
        skips = {name: reason if versions[name] is None else None for name, reason in skips.items()}

    if args.list:
        for stack in selected:
            note = (
                f"  [skipped by default: {skips[stack.name]}]"
                if skips[stack.name] and versions[stack.name]
                else ""
            )
            print(f"{stack.name:12} {stack.label:22} {versions[stack.name] or 'NOT AVAILABLE'}{note}")
        return 0

    for name, reason in skips.items():
        if reason:
            print(f"skipping {name}: {reason}", file=sys.stderr)
    stacks = [stack for stack in selected if not skips[stack.name]]
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
    env = child_environment(ca, think_time=args.think_time)
    machine_os = os_description()
    think_note = f", think time {args.think_time} s" if args.think_time else ""
    print(
        f"{len(jobs)} trials, seed {seed}{think_note}, "
        f"{'dev' if args.dev else 'manifest ' + str(args.manifest)}"
    )

    number = next_run_number(args.manifest, args.member)
    failures = 0
    for index, job in enumerate(jobs, 1):
        run_id = dev_run_id(args.member) if args.dev else format_run_id(number, args.member)
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
                f"trial {job.trial}/{args.trials}; seed {seed}; "
                + (f"think {args.think_time}s; " if args.think_time else "")
                + f"exit {code}"
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
