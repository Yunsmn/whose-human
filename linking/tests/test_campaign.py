import pandas as pd

from linking.campaign import coverage, manifest_runs, network_summary, variant_reflection
from linking.tests.helpers import session, sessions

HEADER = "run_id,label_agent,label_model,label_user,machine,network,notes\n"


def _runs(tmp_path):
    (tmp_path / "c.csv").write_text(
        HEADER
        + "c-0001,script_curl,,baseline,c-linux,local,\n"
        + "c-t3-claude-sh-site1-s1-001,claude-code,claude-opus-5-5,persona-c1,c-linux,campus,\n"
        + "c-t3-codex-site2-s1-001,codex-cli,gpt-6-luna,persona-c1,c-linux,campus,\n"
        + "c-t3-browser-site1-s3-001,browser,none,persona-c1,c-linux,campus,\n"
    )
    return manifest_runs(str(tmp_path))


def _logs():
    rows = [
        ("c-t3-claude-sh-site1-s1-001", 1.0, "/r/c-t3-claude-sh-site1-s1-001/input.html", None, "glacier"),
        (
            "c-t3-claude-sh-site1-s1-001",
            4.0,
            "/r/c-t3-claude-sh-site1-s1-001/submit",
            "A glacier report.",
            None,
        ),
        ("c-t3-browser-site1-s3-001", 9.0, "/r/c-t3-browser-site1-s3-001/input.html", None, "atlas"),
    ]
    return pd.DataFrame(
        [
            {"kind": "request", "run_id": r, "ts": t, "path": p, "submitted_text": s, "visit_variant": v}
            for r, t, p, s, v in rows
        ]
    )


def test_manifest_runs_keeps_track3_rows_and_parses_them(tmp_path):
    runs = _runs(tmp_path)
    assert list(runs.run_id) == [
        "c-t3-claude-sh-site1-s1-001",
        "c-t3-codex-site2-s1-001",
        "c-t3-browser-site1-s3-001",
    ]
    assert list(runs.setting) == ["1", "1", "3"] and list(runs.site) == ["site1", "site2", "site1"]


def test_coverage_statuses(tmp_path):
    cover = coverage(_runs(tmp_path), _logs()).set_index("run_id")
    assert cover.loc["c-t3-claude-sh-site1-s1-001", "status"] == "submitted"
    assert cover.loc["c-t3-codex-site2-s1-001", "status"] == "missing"
    assert cover.loc["c-t3-browser-site1-s3-001", "status"] == "fetched only"


def test_variant_reflection_matches_the_keyword_shown_on_that_visit(tmp_path):
    reflected = variant_reflection(_logs(), _runs(tmp_path)).set_index("run_id")
    assert reflected.loc["c-t3-claude-sh-site1-s1-001", "reflected"]
    assert "c-t3-browser-site1-s3-001" not in reflected.index  # no submit, nothing to check


def test_network_summary_counts_without_addresses():
    frame = sessions(
        session(
            "c-t3-claude-sh-site1-s1-001#agent", "u", run_id="c-t3-claude-sh-site1-s1-001", network="campus"
        ),
        session(
            "c-t3-claude-sh-site1-s1-001#browser",
            "u",
            run_id="c-t3-claude-sh-site1-s1-001",
            network="campus",
            is_browser=True,
        ),
        session(
            "c-t3-codex-site2-s1-001#agent",
            "u",
            run_id="c-t3-codex-site2-s1-001",
            ip="2001:db8::5",
            network="campus",
        ),
    )
    table = network_summary(frame)
    row = table.iloc[0]
    assert row.distinct_ips == 2 and row.distinct_prefixes == 2
    assert row.browser_shares_agent_ip
    assert abs(row.ipv6_share - 1 / 3) < 1e-9
    assert not table.astype(str).apply(lambda col: col.str.contains("192.0.2|2001:db8")).any().any()
