import pandas as pd

from linking.campaign import (
    browser_overlap,
    coverage,
    manifest_runs,
    network_summary,
    reflection_summary,
    side_requests,
    variant_reflection,
)
from linking.tests.helpers import session, sessions

HEADER = "run_id,label_agent,label_model,label_user,machine,network,notes\n"
POOL = {"site1": ["glacier", "atlas", "cedar", "lighthouse"]}


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
    run, browser = "c-t3-claude-sh-site1-s1-001", "c-t3-browser-site1-s3-001"
    rows = [
        # the agent reads the page twice (WebFetch, then curl) and is served two different sentences
        (run, 1.0, f"/r/{run}/input.html", None, "glacier"),
        (run, 9.0, f"/r/{run}/input.html", None, "atlas"),
        (run, 9.1, f"/r/{run}/submit", "A glacier report sits in the library; a cedar index too.", None),
        (run, 9.2, f"/r/{run}/llms.txt", None, None),
        (browser, 20.0, f"/r/{browser}/input.html", None, "cedar"),
    ]
    return pd.DataFrame(
        [
            {
                "kind": "request",
                "run_id": r,
                "label_agent": "browser" if "browser" in r else "claude-code",
                "ts": t,
                "path": p,
                "submitted_text": s,
                "visit_variant": v,
            }
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


def test_every_served_sentence_counts_and_the_fetch_is_named(tmp_path):
    reflected = variant_reflection(_logs(), _runs(tmp_path), POOL).set_index("run_id")
    row = reflected.loc["c-t3-claude-sh-site1-s1-001"]
    assert row.served == "glacier, atlas"
    assert row.reflected and row.reflected_fetch == 1  # named the FIRST sentence, not the last
    assert "c-t3-browser-site1-s3-001" not in reflected.index  # no submit, nothing to check


def test_chance_control_counts_unserved_keywords(tmp_path):
    reflected = variant_reflection(_logs(), _runs(tmp_path), POOL)
    row = reflected.iloc[0]
    assert row.n_not_served == 2 and row.control_hits == 1  # "cedar" was never served to this run
    summary = reflection_summary(reflected).iloc[0]
    assert summary.named_served_sentence == 1.0 and summary.chance_per_unserved_keyword == 0.5


def test_side_requests_count_llms_txt(tmp_path):
    table = side_requests(_logs(), _runs(tmp_path))
    assert table.to_dict("records") == [
        {"label_agent": "claude-code", "file": "llms.txt", "requests": 1, "runs": 1}
    ]


def test_browser_visits_are_compared_with_agent_runs_across_settings():
    frame = sessions(
        session(
            "c-t3-claude-sh-site1-s1-001#agent", "u", run_id="c-t3-claude-sh-site1-s1-001", network="campus"
        ),
        session(
            "c-t3-browser-site1-s3-001#browser",
            "u",
            run_id="c-t3-browser-site1-s3-001",
            network="campus",
            is_browser=True,
        ),
        session(
            "c-t3-browser-site2-s3-001#browser",
            "u",
            run_id="c-t3-browser-site2-s3-001",
            network="campus",
            is_browser=True,
            ip="198.51.100.7",
            ip_prefix="198.51.100.0/24",
        ),
    )
    row = browser_overlap(frame).iloc[0]
    assert row.browser_sessions == 2 and row.agent_sessions == 1
    assert row.browser_same_ip_as_an_agent == 0.5


def test_network_summary_counts_without_addresses():
    frame = sessions(
        session(
            "c-t3-claude-sh-site1-s1-001#agent", "u", run_id="c-t3-claude-sh-site1-s1-001", network="campus"
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
    assert row.distinct_ips == 2 and row.distinct_prefixes == 2 and row.ipv6_share == 0.5
    assert not table.astype(str).apply(lambda col: col.str.contains("192.0.2|2001:db8")).any().any()
