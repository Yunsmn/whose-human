import json

import pytest

from infra.loader import load_logs


def test_loader_joins_manifests_filters_development_and_counts_bad_lines(
    tmp_path,
):
    logs = tmp_path / "logs"
    runs = tmp_path / "runs"
    logs.mkdir()
    runs.mkdir()
    (runs / "a.csv").write_text(
        "run_id,label_agent,label_model,label_user,machine,network,notes\n"
        "a-one,codex,m,persona,host,lan,note\n"
    )
    records = [
        {"ts": 1, "run_id": "a-one", "client_ip": "192.0.2.1"},
        {"ts": 2, "run_id": "dev-one", "client_ip": "127.0.0.1"},
    ]
    path = logs / "server.jsonl"
    path.write_text("\n".join(map(json.dumps, records)) + "\nnot-json\n")

    with pytest.warns(RuntimeWarning, match="Skipped 1 malformed"):
        frame = load_logs(logs, runs_dir=runs)

    assert len(frame) == 1
    assert frame.loc[0, "label_agent"] == "codex"
    assert frame.loc[0, "ip"] == "192.0.2.1"

    with pytest.warns(RuntimeWarning):
        included = load_logs(logs, runs_dir=runs, include_dev=True)
    assert len(included) == 2
