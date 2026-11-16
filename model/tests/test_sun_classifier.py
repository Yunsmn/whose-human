"""Tests for the pure parts of model/sun_classifier. No torch, GPU or downloads needed."""

import numpy as np
import pytest

from model.sun_classifier import LABELS, PROVIDERS, TRAINED_ON
from model.sun_classifier.prepare import LORA_SCALE, merge_lora, plan_keys, their_test_indices, wrap_text

P = "model.base_model.model."


def test_labels_map_to_providers_and_trained_models():
    assert LABELS == ["ChatGPT", "Claude", "Grok", "Gemini", "DeepSeek"]
    assert set(PROVIDERS) == set(TRAINED_ON) == set(LABELS)


def test_wrap_text_matches_llm2vec_llama3_user_turn():
    assert wrap_text("  hello  ", chat_wrapper=False) == "  hello  "
    assert wrap_text("  hello  ", chat_wrapper=True) == (
        "<|start_header_id|>user<|end_header_id|>\n\nhello<|eot_id|>"
    )


def test_plan_keys_groups_lora_parts_and_skips_the_head():
    keys = [
        "head.weight",
        "head.bias",
        P + "embed_tokens.weight",
        P + "norm.weight",
        P + "layers.0.input_layernorm.weight",
        P + "layers.0.self_attn.q_proj.base_layer.weight",
        P + "layers.0.self_attn.q_proj.lora_A.default.weight",
        P + "layers.0.self_attn.q_proj.lora_B.default.weight",
    ]
    plan = plan_keys(keys)
    assert set(plan) == {
        "embed_tokens.weight",
        "norm.weight",
        "layers.0.input_layernorm.weight",
        "layers.0.self_attn.q_proj.weight",
    }
    assert plan["layers.0.self_attn.q_proj.weight"] == {"base": keys[5], "A": keys[6], "B": keys[7]}
    assert plan["norm.weight"] == {"base": keys[3]}


def test_plan_keys_rejects_a_lora_group_missing_a_part():
    with pytest.raises(ValueError, match="incomplete"):
        plan_keys(
            [P + "layers.0.mlp.up_proj.base_layer.weight", P + "layers.0.mlp.up_proj.lora_A.default.weight"]
        )
    with pytest.raises(ValueError, match="unexpected"):
        plan_keys(["something.else"])


def test_merge_lora_matches_peft_formula():
    rng = np.random.default_rng(0)
    base, a, b = rng.normal(size=(6, 5)), rng.normal(size=(2, 5)), rng.normal(size=(6, 2))
    merged = merge_lora(base, a, b)
    x = rng.normal(size=5)
    # The merged layer must give what the adapted layer gives: base(x) + scale * B(A(x)).
    assert np.allclose(merged @ x, base @ x + LORA_SCALE * (b @ (a @ x)))
    assert LORA_SCALE == 2.0


def test_their_test_split_is_deterministic_and_disjoint_from_train():
    test = their_test_indices(11_000)
    assert len(test) == len(set(test)) == 1000
    assert np.array_equal(test, their_test_indices(11_000))
    train = np.random.default_rng(42).permutation(11_000)[1000:11_000]
    assert not set(test) & set(train)
