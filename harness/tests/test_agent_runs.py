import pandas as pd
import pytest

from harness.agent_runs import (
    AgentRun,
    append_manifest,
    audit_locality,
    fixed_fetch_prompt,
    locality_summary,
    parse_expected_ips,
)


def sample_run(**changes):
    values = {
        "run_id": "a-codex-001",
        "agent": "codex-cli",
        "model": "test-model",
        "persona": "persona-a1",
        "machine": "machine-a1",
        "network": "test-network",
        "base_url": "https://site1.example.test",
    }
    values.update(changes)
    return AgentRun(**values)


def test_manifest_writes_one_unique_member_a_run(tmp_path):
    manifest = tmp_path / "a.csv"
    run = sample_run()

    append_manifest(manifest, run)

    frame = pd.read_csv(manifest)
    assert frame.loc[0, "run_id"] == "a-codex-001"
    assert frame.loc[0, "label_agent"] == "codex-cli"
    assert run.target_url == "https://site1.example.test/r/a-codex-001/input.html"
    with pytest.raises(ValueError, match="already exists"):
        append_manifest(manifest, run)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"run_id": "d-wrong"}, "member letter"),
        ({"agent": ""}, "agent must not be empty"),
        ({"base_url": "http://site1.example.test"}, "HTTPS origin"),
        ({"base_url": "https://site1.example.test/?x=1"}, "without a query"),
    ],
)
def test_invalid_run_is_rejected(tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        append_manifest(tmp_path / "a.csv", sample_run(**changes))


def test_fetch_prompt_is_natural_and_does_not_forbid_normal_tools():
    prompt = fixed_fetch_prompt("https://site1.example.test/r/a-one/input.html")
    assert prompt.startswith("Visit https://site1.example.test/r/a-one/input.html")
    assert "summarize the page in two sentences" in prompt
    assert "submit your summary" in prompt
    assert "normally choose" in prompt
    assert "not curl" not in prompt
    assert "without trying" not in prompt


def test_expected_addresses_accept_ipv4_ipv6_and_reject_empty():
    assert parse_expected_ips("192.0.2.10\n2001:db8::1") == frozenset({"192.0.2.10", "2001:db8::1"})
    with pytest.raises(ValueError, match="at least one"):
        parse_expected_ips("  ")


def test_locality_audit_hides_addresses_and_classifies_each_outcome():
    logs = pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "a-local",
                "source": "vm",
                "client_ip": "192.0.2.10",
                "label_agent": "codex",
            },
            {
                "kind": "request",
                "run_id": "a-remote",
                "source": "vm",
                "client_ip": "198.51.100.7",
                "label_agent": "cline",
            },
            {
                "kind": "request",
                "run_id": "a-mixed",
                "source": "vm",
                "client_ip": "192.0.2.10",
                "label_agent": "aider",
            },
            {
                "kind": "request",
                "run_id": "a-mixed",
                "source": "vm",
                "client_ip": "198.51.100.8",
                "label_agent": "aider",
            },
            {
                "kind": "request",
                "run_id": "a-docker",
                "source": "local-a",
                "client_ip": "192.0.2.10",
                "label_agent": "claude",
            },
        ]
    )

    report = audit_locality(logs, "192.0.2.10").set_index("run_id")

    assert report.loc["a-local", "locality"] == "local"
    assert report.loc["a-remote", "locality"] == "remote"
    assert report.loc["a-mixed", "locality"] == "mixed"
    assert report.loc["a-docker", "locality"] == "inconclusive"
    assert "client_ip" not in report.columns
    assert "192.0.2.10" not in report.to_string()


def test_locality_summary_counts_runs_by_agent():
    report = pd.DataFrame(
        [
            {"label_agent": "codex", "locality": "local"},
            {"label_agent": "codex", "locality": "local"},
            {"label_agent": "cline", "locality": "remote"},
        ]
    )

    summary = locality_summary(report).set_index(["label_agent", "locality"])

    assert summary.loc[("codex", "local"), "runs"] == 2
    assert summary.loc[("cline", "remote"), "runs"] == 1


def test_other_members_run_ids_go_to_their_own_manifest(tmp_path, monkeypatch, capsys):
    from harness import agent_runs

    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    argv = [
        "prepare",
        "--run-id",
        "c-claude-001",
        "--agent",
        "claude-code",
        "--model",
        "m",
        "--persona",
        "persona-c1",
        "--machine",
        "c-linux",
        "--network",
        "local",
        "--base-url",
        "https://site1.test:8443",
    ]
    assert agent_runs.main(argv) == 0
    assert (tmp_path / "runs" / "c.csv").read_text().count("c-claude-001") == 1
    assert not (tmp_path / "runs" / "a.csv").exists()
    argv[2] = ""
    with pytest.raises(SystemExit) as exc:
        agent_runs.main(argv)
    assert exc.value.code == 2
    assert "member letter" in capsys.readouterr().err
    assert not (tmp_path / "runs" / ".csv").exists()
    with pytest.raises(ValueError, match="member letter"):
        agent_runs.validate_run(agent_runs.AgentRun("d-x", "a", "m", "p", "m", "n", "https://site1.test"))
