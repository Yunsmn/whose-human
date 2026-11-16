import pandas as pd
import pytest

from harness.classify import evaluate, fit_and_predict_proba


def sample_data(runs_per_class=3):
    rows = []
    for label, marker in [("a", "red"), ("b", "blue"), ("c", "green")]:
        for run in range(runs_per_class):
            for item in range(2):
                rows.append(
                    {
                        "run_id": f"{label}-{run}",
                        "label_agent": label,
                        "http_ua_family": marker,
                        "tls_n_ciphers": item,
                    }
                )
    return pd.DataFrame(rows)


def test_evaluate_uses_grouped_splits_and_separable_features():
    result = evaluate(sample_data(), feature_sets={"ua": ["http"]})
    assert result.iloc[0].macro_f1 > 0.9
    assert result.iloc[0].n_classes == 3


def test_evaluate_requires_two_groups_per_class():
    with pytest.raises(ValueError, match="at least 2 groups per class"):
        evaluate(sample_data(runs_per_class=1), feature_sets={"ua": ["http"]})


def test_fit_and_predict_proba_sums_to_one():
    data = sample_data()
    train = data[data.run_id.isin(["a-0", "a-1", "b-0", "b-1", "c-0", "c-1"])]
    test = data[data.run_id.isin(["a-2", "b-2", "c-2"])]
    probabilities = fit_and_predict_proba(train, test, "run_id")
    assert probabilities.shape == (len(test), 3)
    assert probabilities.sum(axis=1).tolist() == pytest.approx([1.0] * len(test))
