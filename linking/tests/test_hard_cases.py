import pandas as pd

from linking.hard_cases import (
    anonymity_sets,
    anonymity_summary,
    collision_table,
    ip_change_table,
    shared_ip_table,
    with_session_labels,
)
from linking.pairs import build_pairs
from linking.sessions import ip_prefix
from linking.tests.helpers import session as base_session
from linking.tests.helpers import sessions


def session(key, user, ip, **overrides):
    return base_session(key, user, ip=ip, ip_prefix=ip_prefix(ip), **overrides)


def campaign():
    """u changes network (home -> vpn) with the same curl; v and w share one IP; w copies u's setup."""
    return sessions(
        session("u1", "u", signature="u-curl", ip="192.0.2.1", network="home", tools="curl"),
        session("u2", "u", signature="u-curl", ip="198.51.100.7", network="vpn", tools="curl"),
        session("v1", "v", signature="v-curl", ip="203.0.113.5", network="campus", tools="curl"),
        session("w1", "w", signature="u-curl", ip="203.0.113.5", network="campus", tools="curl"),
        session("x1", "x", signature="wf", ip="192.0.2.9", network="home", tools="webfetch"),
        session("y1", "y", signature="wf", ip="198.51.100.9", network="home", tools="webfetch"),
    )


def data_and_scores():
    rows = campaign()
    pairs = build_pairs(rows)
    data = with_session_labels(rows, pairs)
    # a scorer that links on the full signature, and one that links nothing
    signature = data.full_signature_match.astype(float)
    return rows, data, {"sig": signature, "never": pd.Series(0.0, index=data.index)}


def test_ip_change_reports_recall_by_network_pair():
    _, data, scores = data_and_scores()
    table = ip_change_table(data, scores).set_index("network_pair")
    assert table.loc["all", "n_pairs"] == 1
    assert table.loc["home / vpn", "recall_sig"] == 1.0
    assert table.loc["home / vpn", "recall_never"] == 0.0
    assert table.loc["home / vpn", "same_prefix"] == 0.0


def test_shared_ip_reports_false_links():
    _, data, scores = data_and_scores()
    table = shared_ip_table(data, scores).set_index("tools_pair")
    # v1 and w1 share an IP but not a signature
    assert table.loc["all", "n_pairs"] == 1
    assert table.loc["all", "false_link_sig"] == 0.0
    assert table.loc["all", "n_scored_sig"] == 1


def test_collisions_and_anonymity_sets():
    rows, data, _ = data_and_scores()
    collisions = collision_table(data).set_index("tools_pair")
    # w copies u's setup (2 pairs: u1-w1, u2-w1); x and y both use WebFetch (1 pair)
    assert collisions.loc["curl / curl", "n_full_match"] == 2
    assert collisions.loc["webfetch / webfetch", "n_full_match"] == 1
    assert collisions.loc["all", "n_full_match"] == 3
    anonymity = anonymity_sets(rows, data).set_index("session_key").other_users_same_signature
    assert anonymity.to_dict() == {"u1": 1, "u2": 1, "v1": 0, "w1": 1, "x1": 1, "y1": 1}
    summary = anonymity_summary(anonymity_sets(rows, data)).set_index("tools")
    assert summary.loc["all", "share_unique"] == 1 / 6
    assert summary.loc["webfetch", "share_unique"] == 0.0


def test_unscored_pairs_are_left_out_of_the_rates():
    _, data, scores = data_and_scores()
    scores = {"none": pd.Series(float("nan"), index=data.index)}
    table = ip_change_table(data, scores).set_index("network_pair")
    assert table.loc["all", "n_scored_none"] == 0
    assert pd.isna(table.loc["all", "recall_none"])


def test_empty_signature_columns_count_as_identical():
    rows = sessions(
        base_session("p1", "p", signature="wf", h2_fp=(), http_ua_version=()),
        base_session("q1", "q", signature="wf", h2_fp=(), http_ua_version=()),
        base_session("r1", "r", signature="wf", h2_fp=("2:0",), http_ua_version=()),
    )
    data = with_session_labels(rows, build_pairs(rows)).set_index(["a", "b"])
    assert bool(data.loc[("p1", "q1"), "full_signature_match"])
    assert not data.loc[("p1", "r1"), "full_signature_match"]
