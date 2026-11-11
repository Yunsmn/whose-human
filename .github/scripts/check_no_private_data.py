"""Fail if raw log files or public IPv4 addresses are committed (see the ethics rules in AGENTS.md)."""

import ipaddress
import re
import subprocess
import sys

FORBIDDEN_SUFFIXES = (".jsonl", ".pcap", ".pcapng", ".har", ".log")
IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# RFC 5737 documentation ranges are safe to use in examples and tests.
DOC_NETWORKS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def is_reportable(candidate: str) -> bool:
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if any(ip in network for network in DOC_NETWORKS):
        return False
    return ip.is_global


def find_problems(paths: list[str]) -> list[str]:
    problems = []
    for path in paths:
        if path.startswith("data/") or path.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"{path}: raw data file must not be committed")
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for number, line in enumerate(lines, start=1):
            for match in IPV4_PATTERN.findall(line):
                if is_reportable(match):
                    problems.append(f"{path}:{number}: public IP address {match}")
    return problems


def main() -> int:
    problems = find_problems(tracked_files())
    for problem in problems:
        print(problem)
    if problems:
        print("\nUse documentation addresses (192.0.2.x, 198.51.100.x, 203.0.113.x) in examples.")
        return 1
    print("OK: no raw logs or public IP addresses found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
