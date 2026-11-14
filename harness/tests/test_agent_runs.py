import pandas as pd
import pytest

from harness.agent_runs import Run, append_manifest, audit_locality, fixed_prompt


def sample_run(**changes):
    values = {
        "run_id": "a-codex-001",
        "agent": "codex-cli",
        "model": "test-model",
        "persona": "persona-a1",
        "machine": "machine-a1",
        "network": "test-network",
        "base_url": "https://site1.test:8443",
    }
    values.update(changes)
    return Run(**values)


def test_append_manifest_writes_unique_labelled_run(tmp_path):
    manifest = tmp_path / "a.csv"
    run = sample_run()

    append_manifest(manifest, run)

    frame = pd.read_csv(manifest)
    assert frame.loc[0, "run_id"] == "a-codex-001"
    assert frame.loc[0, "label_agent"] == "codex-cli"
    assert run.target_url == "https://site1.test:8443/r/a-codex-001/input.html"
    with pytest.raises(ValueError, match="already exists"):
        append_manifest(manifest, run)


def test_run_rejects_wrong_member_prefix(tmp_path):
    with pytest.raises(ValueError, match="must start"):
        append_manifest(tmp_path / "a.csv", sample_run(run_id="b-wrong"))


def test_fixed_prompt_requires_native_fetch_and_visible_submission():
    prompt = fixed_prompt("https://site1.test/r/a-one/input.html")
    assert "built-in web or URL-fetch" in prompt
    assert "not curl" in prompt
    assert "exactly two sentences" in prompt
    assert "visible GET fallback" in prompt


def test_audit_locality_does_not_return_addresses():
    logs = pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": "a-local",
                "source": "vm",
                "client_ip": "192.0.2.10",
            },
            {
                "kind": "request",
                "run_id": "a-remote",
                "source": "vm",
                "client_ip": "198.51.100.7",
            },
            {
                "kind": "request",
                "run_id": "a-docker",
                "source": "local-a",
                "client_ip": "192.0.2.10",
            },
        ]
    )

    result = audit_locality(logs, "192.0.2.10").set_index("run_id")

    assert result.loc["a-local", "locality"] == "local"
    assert result.loc["a-remote", "locality"] == "remote"
    assert result.loc["a-docker", "locality"] == "inconclusive"
    assert "client_ip" not in result.columns
