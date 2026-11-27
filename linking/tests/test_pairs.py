import pandas as pd
import pytest

from linking.pairs import PAIR_FEATURES, build_pairs
from linking.tests.helpers import session, sessions


def test_pairs_labels_slices_and_counts():
    frame = sessions(
        session("r#agent", "u", run_id="r", tools="webfetch>curl"),
        session(
            "r#browser",
            "u",
            run_id="r",
            label_agent="browser",
            is_browser=True,
            site="site2",
            ip="198.51.100.1",
            ip_prefix="198.51.100.0/24",
            tools="browser",
        ),
        session("z#agent", "v", run_id="z", t_start=4.0, tools="curl"),
    )
    pairs = build_pairs(frame)
    assert len(pairs) == 3
    relay = pairs[(pairs.a == "r#agent") & (pairs.b == "r#browser")].iloc[0]
    assert relay.same_user and relay.same_token and relay.cross_site and relay.agent_browser
    assert relay.ip_changed and not relay.shared_ip
    other = pairs[(pairs.a == "r#agent") & (pairs.b == "z#agent")].iloc[0]
    assert not other.same_user and not other.ip_changed and other.shared_ip and not other.same_tools


def test_signature_columns_match_on_any_shared_value():
    # An agent that read with WebFetch and submitted with curl shows two JA4s; it matches a curl-only session.
    mixed = session("a", "u", tls_ja4=("ja4-curl", "ja4-webfetch"))
    curl_only = session("b", "u", tls_ja4=("ja4-curl",))
    other = session("c", "v", tls_ja4=("ja4-go",))
    pairs = build_pairs(sessions(mixed, curl_only, other)).set_index(["a", "b"])
    assert pairs.loc[("a", "b"), "same_tls_ja4"]
    assert not pairs.loc[("a", "c"), "same_tls_ja4"]


def test_missing_timing_gives_nan_not_an_error():
    pairs = build_pairs(sessions(session("a", "u", submit_wait_s=None, max_gap_s=None), session("b", "v")))
    assert pairs.submit_wait_diff_s.isna().all() and pairs.max_gap_ratio.isna().all()
    assert set(PAIR_FEATURES) <= set(pairs.columns)


def test_pair_limit():
    with pytest.raises(ValueError):
        build_pairs(pd.DataFrame({"session_key": range(5001)}))


def test_two_empty_value_sets_count_as_a_match():
    # WebFetch sends no HTTP/2: both sessions have an empty h2_fp set, which is the same fingerprint.
    a = session("a", "u", h2_fp=())
    b = session("b", "v", h2_fp=())
    c = session("c", "w", h2_fp=("h2-curl",))
    pairs = build_pairs(sessions(a, b, c)).set_index(["a", "b"])
    assert pairs.loc[("a", "b"), "same_h2_fp"]
    assert not pairs.loc[("a", "c"), "same_h2_fp"]


def test_rare_shared_values_weigh_more_than_common_ones():
    # three sessions share the common "webfetch" JA4; only a and d share the rare "curl-rare" JA4
    a = session("a", "u", tls_ja4=("curl-rare",))
    d = session("d", "u", tls_ja4=("curl-rare",))
    w = [session(k, "v", tls_ja4=("webfetch",)) for k in ("w1", "w2", "w3", "w4")]
    pairs = build_pairs(sessions(a, d, *w)).set_index(["a", "b"])
    rare = pairs.loc[("a", "d")]
    common = pairs.loc[("w1", "w2")]
    assert rare.same_tls_ja4 and common.same_tls_ja4  # both match...
    assert rare.rarest_match > common.rarest_match  # ...but the rare match carries more weight
    assert pairs.loc[("a", "w1"), "signature_rarity"] < rare.signature_rarity


def test_rarity_uses_no_labels():
    a = session("a", "u", tls_ja4=("x",))
    b = session("b", "v", tls_ja4=("x",))
    relabelled = [session("a", "z", tls_ja4=("x",)), session("b", "z", tls_ja4=("x",))]
    first = build_pairs(sessions(a, b)).signature_rarity.iloc[0]
    second = build_pairs(sessions(*relabelled)).signature_rarity.iloc[0]
    assert first == second
