import pandas as pd

from linking.experiments import pair_masks, split_sessions
from linking.pairs import build_pairs
from linking.tests.helpers import session, sessions


def _frame():
    rows = [
        session(f"{u}-t3-x-site1-s1-{i:03d}#agent", u, run_id=f"{u}-t3-x-site1-s1-{i:03d}")
        for u in ("a", "b")
        for i in range(10)
    ]
    return sessions(*rows)


def test_split_is_stratified_and_disjoint():
    frame = _frame()
    part = split_sessions(frame, seed=0)
    assert set(part) == {"train", "val", "test"}
    for user in ("a", "b"):
        own = part[part.index.str.startswith(user)]
        assert own.value_counts().to_dict() == {"train": 6, "val": 2, "test": 2}


def test_pair_masks_never_mix_evaluation_sessions_into_training():
    frame = _frame()
    part = split_sessions(frame, seed=1)
    pairs = build_pairs(frame)
    masks = pair_masks(pairs, part)
    train = pairs.loc[masks["train"]]
    assert set(train.a.map(part)) | set(train.b.map(part)) == {"train"}
    assert not (masks["val"] & masks["test"]).any()
    assert (masks["train"] | masks["val"] | masks["test"]).all()
    assert pd.Series(masks["test"]).sum() > 0
