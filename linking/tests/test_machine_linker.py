import pandas as pd

from linking.machine_linker import (
    add_decisions,
    build_pairs,
    build_profiles,
    evaluate_profiles,
    score_pairs,
)


def synthetic_records(machine_count=9):
    rows = []
    for machine_index in range(machine_count):
        speed = 12.0 + machine_index * 4.0
        for agent_index, agent in enumerate(("omen", "queen")):
            session = f"pc-{machine_index}-{agent}"
            for case_index, case in enumerate(("short-32", "long-128")):
                for repeat in range(3):
                    noise = (repeat - 1) * 0.01
                    rows.append(
                        {
                            "session_id": session,
                            "machine": f"pc-{machine_index}",
                            "agent": agent,
                            "model": "local-test-model",
                            "engine": "ollama",
                            "quantization": "q4",
                            "case": case,
                            "success": True,
                            "phase": "first" if case_index == 0 and repeat == 0 else "warm",
                            "wall_total_s": (case_index + 1) * 4.0 / speed + noise,
                            "first_chunk_s": 1.0 / speed + noise,
                            "chunk_interval_median_s": 1.0 / speed + noise,
                            "chunk_interval_p95_s": 1.2 / speed + noise,
                            "chunk_interval_stdev_s": 0.1 / speed,
                            "load_s": 2.0 / speed,
                            "model_total_s": (case_index + 1) * 3.0 / speed,
                            "prompt_tokens_per_s": speed * 2.0,
                            "eval_tokens_per_s": speed * (1 + agent_index * 0.002),
                        }
                    )
    return pd.DataFrame(rows)


def test_profiles_and_pairs_keep_machine_ground_truth_separate_from_agent():
    profiles = build_profiles(synthetic_records(3))
    pairs = build_pairs(profiles, negative_ratio=None)

    assert len(profiles) == 6
    assert pairs["same_machine"].sum() == 3
    assert pairs["cross_agent"].eq(1).all()
    same = pairs.loc[pairs["same_machine"] == 1, "relative_difference_median"]
    different = pairs.loc[pairs["same_machine"] == 0, "relative_difference_median"]
    assert same.median() < different.median()


def test_whole_machine_holdout_returns_probabilities_and_metrics():
    profiles = build_profiles(synthetic_records())

    bundle, report = evaluate_profiles(profiles, threshold=0.8, random_state=7)
    pairs = build_pairs(profiles, negative_ratio=None)
    scored = score_pairs(bundle, pairs)
    decided = add_decisions(scored, probable_same_threshold=0.8)

    assert report["train_machines"] + report["test_machines"] == 9
    assert 0.0 <= report["roc_auc"] <= 1.0
    assert 0.0 <= report["false_match_rate"] <= 1.0
    assert 0.0 <= report["false_nonmatch_rate"] <= 1.0
    assert scored["same_pc_probability"].between(0, 1).all()
    assert set(decided["decision"]) <= {"probably_same_pc", "unknown"}
