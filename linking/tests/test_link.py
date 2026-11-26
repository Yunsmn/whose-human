import pytest

import linking.link as linking
from linking.link import cluster, cluster_metrics, cross_val_scores, evaluate
from linking.pairs import build_pairs
from linking.tests.helpers import session, sessions


def toy_sessions():
    rows = [
        session(
            f"{user}{index}", user, signature=user, ip=f"192.0.2.{1 if user == 'u' else 2}", t_start=index
        )
        for user in ("u", "v")
        for index in range(4)
    ]
    return sessions(*rows)


def test_cv_evaluate_and_clusters(monkeypatch):
    sessions = toy_sessions()
    pairs = build_pairs(sessions)
    scores = pairs.same_user.astype(float)
    result = evaluate(pairs, scores)
    assert result.iloc[0].precision == result.iloc[0].recall == 1
    clusters = cluster(sessions, pairs, scores)
    metrics = cluster_metrics(sessions, clusters)
    assert metrics["adjusted_rand"] == 1
    assert metrics["bcubed_f1"] == 1
    original_fit = linking.fit_pair_model
    checked_splits = []

    class ObservedModel:
        def __init__(self, model, train_pairs):
            self.model = model
            self.train_pairs = train_pairs
            self.classes_ = model.classes_

        def predict_proba(self, test_features):
            train_keys = set(self.train_pairs.a) | set(self.train_pairs.b)
            test_pairs = pairs.loc[test_features.index]
            test_keys = set(test_pairs.a) | set(test_pairs.b)
            checked_splits.append(train_keys.isdisjoint(test_keys))
            return self.model.predict_proba(test_features.astype(float))

    def observing_fit(train_pairs, features):
        return ObservedModel(original_fit(train_pairs, features), train_pairs)

    monkeypatch.setattr(linking, "fit_pair_model", observing_fit)
    cv = cross_val_scores(sessions, pairs, features=["same_tls_ja4"], n_splits=4)
    assert cv.notna().all()  # every pair scored, including pairs across folds
    assert checked_splits and all(checked_splits)  # never by a model trained on either of its sessions
    clusters = cluster(sessions, pairs, cv)
    assert cluster_metrics(sessions, clusters)["bcubed_f1"] == 1


def test_cv_needs_three_folds():
    sessions = toy_sessions()
    with pytest.raises(ValueError):
        cross_val_scores(sessions, build_pairs(sessions), features=["same_tls_ja4"], n_splits=2)


def test_average_linkage_survives_one_false_link_that_merges_components():
    frame = toy_sessions()
    pairs = build_pairs(frame)
    scores = pairs.same_user.astype(float)
    false_link = pairs.index[(pairs.a == "u0") & (pairs.b == "v0")]
    scores.loc[false_link] = 0.9
    assert cluster(frame, pairs, scores, method="components").nunique() == 1
    clusters = cluster(frame, pairs, scores, method="average")
    assert clusters.nunique() == 2
    assert cluster_metrics(frame, clusters)["bcubed_f1"] == 1


def test_unknown_cluster_method():
    frame = toy_sessions()
    pairs = build_pairs(frame)
    with pytest.raises(ValueError):
        cluster(frame, pairs, pairs.same_user.astype(float), method="single")
