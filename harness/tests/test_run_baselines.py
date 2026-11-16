"""Tests for the Track 1b runner. No network, Node or Go needed."""

import csv
import os
import sys

import pytest

from harness.baselines import run_baselines as rb

ALLOWED = set(rb.DEFAULT_ALLOWED_HOSTS)


def test_next_run_number_skips_other_ids_and_continues_after_the_highest(tmp_path):
    manifest = tmp_path / "b.csv"
    assert rb.next_run_number(manifest) == 1
    manifest.write_text(
        ",".join(rb.MANIFEST_COLUMNS) + "\n"
        "b-0003,script_got,,baseline,b-windows,local,\n"
        "dev-b-abc123,script_got,,baseline,b-windows,local,\n"
        "b-0010,script_curl,,baseline,b-windows,local,\n"
        "a-0099,codex,,persona,a-mac,home,\n"
    )
    assert rb.next_run_number(manifest) == 11
    assert rb.format_run_id(11) == "b-0011"


def test_dev_ids_are_dropped_by_the_loader_prefix():
    assert rb.dev_run_id().startswith("dev-")


def test_manifest_rows_append_after_existing_header_and_missing_newline(tmp_path):
    manifest = tmp_path / "b.csv"
    manifest.write_text(",".join(rb.MANIFEST_COLUMNS))  # header only, no trailing newline
    row = {
        "run_id": "b-0001",
        "label_agent": "script_axios-1.8.4",
        "label_model": "",
        "label_user": "baseline",
        "machine": "b-windows",
        "network": "local",
        "notes": "axios 1.8.4; node 22.23.2; site site1",
    }
    rb.append_manifest_row(manifest, row)
    rb.append_manifest_row(manifest, {**row, "run_id": "b-0002"})
    with manifest.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["run_id"] for r in rows] == ["b-0001", "b-0002"]
    assert rows[0]["notes"] == row["notes"]


def test_manifest_header_is_written_for_a_new_file(tmp_path):
    manifest = tmp_path / "runs" / "b.csv"
    rb.append_manifest_row(manifest, dict.fromkeys(rb.MANIFEST_COLUMNS, "x"))
    assert manifest.read_text().splitlines()[0] == ",".join(rb.MANIFEST_COLUMNS)


def test_manifest_row_must_have_every_column(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        rb.append_manifest_row(tmp_path / "b.csv", {"run_id": "b-0001"})


def test_four_part_versions_are_cut_for_the_private_data_guard():
    assert (
        rb.safe_version("Windows 10 (10.0.26200.1234); curl 8.21.0") == "Windows 10 (10.0.26200); curl 8.21.0"
    )
    assert rb.safe_version("python 3.12.9") == "python 3.12.9"


def test_base_url_refuses_hosts_outside_the_allowlist():
    url = rb.base_url(rb.DEFAULT_URL_TEMPLATE, "site1", "b-0001", ALLOWED)
    assert url == "https://site1.test:8443/r/b-0001/"
    with pytest.raises(ValueError, match="refusing"):
        rb.base_url("https://example.org/r/{run_id}/", "site1", "b-0001", ALLOWED)
    with pytest.raises(ValueError, match="scheme"):
        rb.base_url("ftp://site1.test/r/{run_id}/", "site1", "b-0001", ALLOWED)


def test_allowlist_can_be_extended_from_the_environment():
    hosts = rb.allowed_hosts({"WH_ALLOWED_HOSTS": "Site1.Example.org, other.example.org"})
    assert {"site1.example.org", "other.example.org", "site1.test"} <= hosts


@pytest.mark.parametrize("name", list(rb.STACKS))
def test_every_stack_builds_a_command_ending_in_the_run_url(name):
    url = "https://site1.test:8443/r/b-0001/"
    built = rb.commands(rb.STACKS[name], url)
    assert built
    for argv, cwd in built:
        assert any(url in part for part in argv)
        assert cwd.is_dir()


def test_curl_makes_the_same_four_requests_as_the_scripts():
    built = [argv for argv, _ in rb.commands(rb.STACKS["curl"], "https://site1.test:8443/r/b-0001/")]
    assert [argv[-1].rsplit("/", 1)[-1] for argv in built] == ["index.html", "input.html", "submit", "submit"]
    assert "-G" in built[2] and "-G" not in built[3]
    assert all(argv[0] == "curl" for argv in built)


def test_script_files_exist_for_node_and_python_stacks():
    for stack in rb.STACKS.values():
        if stack.kind in ("node", "python"):
            assert (rb.HERE / stack.kind / stack.target).is_file(), stack.name
        if stack.kind == "go":
            assert (rb.HERE / "go" / stack.target / "main.go").is_file(), stack.name


def test_python_stacks_use_the_current_interpreter():
    argv, _ = rb.commands(rb.STACKS["requests"], "https://site1.test:8443/r/b-0001/")[0]
    assert argv[0] == sys.executable


def test_child_environment_points_every_stack_at_the_ca(tmp_path):
    ca = tmp_path / "ca.pem"
    env = rb.child_environment(ca, {"PATH": "x"})
    for variable in ("NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        assert env[variable] == str(ca)
    assert env["PATH"] == "x"
    assert "SSL_CERT_FILE" not in rb.child_environment(None, {})


def test_plan_covers_every_combination_once_in_a_reproducible_order():
    stacks = [rb.STACKS["got"], rb.STACKS["curl"]]
    first = rb.plan(stacks, ["site1", "site2"], 3, seed=7)
    again = rb.plan(stacks, ["site1", "site2"], 3, seed=7)
    assert [(j.stack.name, j.site, j.trial) for j in first] == [
        (j.stack.name, j.site, j.trial) for j in again
    ]
    assert len({(j.stack.name, j.site, j.trial) for j in first}) == 12


def test_dry_run_writes_no_manifest_row(tmp_path, capsys):
    manifest = tmp_path / "b.csv"
    code = rb.main(
        ["--stacks", "urllib", "--trials", "2", "--sites", "site1", "--dry-run", "--manifest", str(manifest)]
    )
    assert code == 0
    assert not manifest.exists()
    out = capsys.readouterr().out
    assert "b-0001" in out and "b-0002" in out and os.path.basename(sys.executable) in out


def test_unknown_stack_is_rejected():
    with pytest.raises(SystemExit):
        rb.parse_args(["--stacks", "wget"])
