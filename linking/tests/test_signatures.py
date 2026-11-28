import pandas as pd

from linking.signatures import build_signature_pairs, column_summary, pair_summary, track3_sessions
from linking.tests.helpers import session, sessions


def test_column_summary_reports_counts_without_raw_values():
    frame = sessions(
        session("a", "u", signature="rare"),
        session("b", "u", signature="common"),
        session("c", "v", signature="common"),
    )
    result = column_summary(frame).set_index("column")
    assert result.loc["tls_ja4", "observed"] == 3
    assert result.loc["tls_ja4", "n_values"] == 2
    assert result.loc["tls_ja4", "largest_share"] == 2 / 3
    assert "rare" not in result.to_string()
    assert "common" not in result.to_string()


def test_pair_summary_separates_stability_from_collisions():
    frame = sessions(
        session(
            "u-curl-1",
            "u",
            signature="curl-u",
            machine="u-pc",
            site="site1",
            network="campus",
            ip="192.0.2.1",
        ),
        session(
            "u-curl-2",
            "u",
            signature="curl-u",
            machine="u-pc",
            site="site2",
            network="campus",
            ip="198.51.100.2",
        ),
        session("u-web", "u", signature="webfetch", machine="u-pc", tools="webfetch"),
        session("v-curl", "v", signature="curl-v", machine="v-pc"),
        session("v-web", "v", signature="webfetch", machine="v-pc", tools="webfetch"),
    )
    pairs = build_signature_pairs(frame).set_index(["a", "b"])
    stable = pairs.loc[("u-curl-1", "u-curl-2")]
    collision = pairs.loc[("u-web", "v-web")]
    distinct = pairs.loc[("u-curl-1", "v-curl")]
    assert stable.same_user and stable.same_machine and stable.exact_signature
    assert stable.cross_site and stable.cross_network
    assert not stable.cross_network_label
    assert not collision.same_user and collision.exact_signature
    assert not distinct.exact_signature

    summary = pair_summary(pairs.reset_index())
    stable_row = summary.loc[
        (summary.relation == "same-user stability") & (summary.tool_pair == "curl / curl")
    ].iloc[0]
    collision_row = summary.loc[
        (summary.relation == "different-user collision") & (summary.tool_pair == "webfetch / webfetch")
    ].iloc[0]
    assert stable_row.exact_rate == 1
    assert stable_row.cross_site_exact_rate == 1
    assert stable_row.cross_network_exact_rate == 1
    assert stable_row.cross_network_label_pairs == 0
    assert collision_row.exact_rate == 1


def test_address_change_not_public_label_defines_cross_network():
    frame = sessions(
        session("same-address-a", "u", network="campus", ip="192.0.2.1"),
        session("same-address-b", "u", network="mobile", ip="192.0.2.1"),
        session("missing-address", "u", network="mobile", ip=None),
    )
    pairs = build_signature_pairs(frame).set_index(["a", "b"])
    same_address = pairs.loc[("same-address-a", "same-address-b")]
    unknown_address = pairs.loc[("same-address-a", "missing-address")]
    assert not same_address.cross_network
    assert same_address.cross_network_label
    assert not unknown_address.cross_network


def test_track3_sessions_filters_other_labelled_runs():
    frame = sessions(
        session("a-t3-codex-site1-s1-001", "u"),
        session("a-codex-site1-001", "u"),
        session("dev-a-t3-check", "u"),
    )
    result = track3_sessions(frame)
    assert result.run_id.tolist() == ["a-t3-codex-site1-s1-001"]


def test_empty_pair_inputs_have_stable_columns():
    empty = pd.DataFrame(columns=build_signature_pairs(sessions()).columns)
    result = pair_summary(empty)
    assert result.empty
    assert "exact_rate" in result
