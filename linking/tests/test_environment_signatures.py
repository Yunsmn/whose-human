import pandas as pd

from linking.environment_signatures import (
    SIGNATURE_COLUMNS,
    add_environment_signatures,
    per_run_signatures,
    signature_report,
)


def feature_row(run_id, user, agent, marker):
    row = {column: None for column in SIGNATURE_COLUMNS}
    row.update(
        {
            "run_id": run_id,
            "label_user": user,
            "label_agent": agent,
            "tls_ja4": marker,
            "http_ua_family": "test-runtime",
        }
    )
    return row


def test_signature_is_deterministic_and_ignores_unselected_values():
    first = feature_row("a-one", "user-a", "codex", "tls-a")
    second = {**first, "run_id": "a-two", "label_user": "user-b", "path": "/different"}
    signed = add_environment_signatures(pd.DataFrame([first, second]))

    assert signed.loc[0, "environment_signature"] == signed.loc[1, "environment_signature"]
    assert signed.loc[0, "environment_signature"].startswith("env-v1:")


def test_per_run_uses_modal_signature_and_reports_variants():
    rows = [
        feature_row("a-one", "user-a", "codex", "tls-a"),
        feature_row("a-one", "user-a", "codex", "tls-a"),
        feature_row("a-one", "user-a", "codex", "tls-b"),
    ]
    signed = add_environment_signatures(pd.DataFrame(rows))

    runs = per_run_signatures(signed)

    assert runs.loc[0, "request_count"] == 3
    assert runs.loc[0, "signature_variants"] == 2
    assert runs.loc[0, "environment_signature"] == signed.loc[0, "environment_signature"]


def test_report_separates_stability_cross_agent_and_collisions():
    rows = [
        feature_row("a-one", "user-a", "codex", "tls-a"),
        feature_row("a-two", "user-a", "claude", "tls-a"),
        feature_row("b-one", "user-b", "codex", "tls-b"),
        feature_row("c-one", "user-c", "cline", "tls-a"),
    ]
    report = signature_report(add_environment_signatures(pd.DataFrame(rows)))

    assert report["within_user_pairs"] == 1
    assert report["within_user_match_rate"] == 1.0
    assert report["cross_agent_within_user_pairs"] == 1
    assert report["cross_agent_within_user_match_rate"] == 1.0
    assert report["between_user_pairs"] == 5
    assert report["between_user_collision_rate"] == 0.4


def test_empty_input_has_zero_coverage():
    empty = pd.DataFrame(columns=SIGNATURE_COLUMNS + ["run_id", "label_user", "label_agent"])

    report = signature_report(add_environment_signatures(empty))

    assert report["run_count"] == 0
    assert report["signature_coverage"] == 0.0
    assert report["within_user_match_rate"] is None
