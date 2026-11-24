import numpy as np

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
    cv = cross_val_scores(sessions, pairs, features=["same_tls_ja4"], n_splits=2)
    assert cv.notna().sum() > 0
    assert np.isnan(cv).any()
    assert checked_splits and all(checked_splits)
