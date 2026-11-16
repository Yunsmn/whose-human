"""Pure helpers shared by conversion, inference and evaluation. No torch needed."""

from __future__ import annotations

import re

import numpy as np

LORA_SCALE = 32 / 16  # lora_alpha / r of McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised
PREFIX = "model.base_model.model."
LLAMA3_USER_TURN = "<|start_header_id|>user<|end_header_id|>\n\n{text}<|eot_id|>"
_LORA_KEY = re.compile(r"^(?P<module>.+)\.lora_(?P<part>[AB])\.default\.weight$")


def wrap_text(text: str, chat_wrapper: bool) -> str:
    """Text as LLM2Vec.prepare_for_tokenization sees it.

    LLM2Vec wraps text in a Llama 3 user turn only when the model config names
    meta-llama/Meta-Llama-3-8B-Instruct. Whether that held during Sun et al.'s training is decided
    empirically by evaluate.py, so both forms are supported.
    """
    return LLAMA3_USER_TURN.format(text=text.strip()) if chat_wrapper else text


def plan_keys(checkpoint_keys: list[str]) -> dict[str, dict[str, str]]:
    """Map checkpoint tensors to plain LlamaModel weights.

    Returns {target_key: {"base": key, "A": key, "B": key}} for LoRA-adapted linear layers and
    {target_key: {"base": key}} for everything else. ``head.*`` is left out (saved separately).
    """
    plan: dict[str, dict[str, str]] = {}
    for key in checkpoint_keys:
        if key.startswith("head."):
            continue
        if not key.startswith(PREFIX):
            raise ValueError(f"unexpected checkpoint key {key!r}")
        rest = key[len(PREFIX) :]
        lora = _LORA_KEY.match(rest)
        if lora:
            target = f"{lora.group('module')}.weight"
            plan.setdefault(target, {})[lora.group("part")] = key
        elif rest.endswith(".base_layer.weight"):
            target = rest.replace(".base_layer.weight", ".weight")
            plan.setdefault(target, {})["base"] = key
        else:
            plan.setdefault(rest, {})["base"] = key
    incomplete = {
        t: parts for t, parts in plan.items() if "base" not in parts or ("A" in parts) != ("B" in parts)
    }
    if incomplete:
        raise ValueError(f"incomplete LoRA groups: {sorted(incomplete)[:5]}")
    return plan


def merge_lora(
    base: np.ndarray, lora_a: np.ndarray, lora_b: np.ndarray, scale: float = LORA_SCALE
) -> np.ndarray:
    """W + scale * (B @ A), as peft's merge_and_unload does for a LoRA linear layer."""
    return base + scale * (lora_b @ lora_a)


def their_test_indices(n_responses: int, n_test: int = 1000, seed: int = 42) -> np.ndarray:
    """Indices of Sun et al.'s test split for one model's responses.

    classification.py calls datasets' train_test_split(train_size=10_000, test_size=1_000, seed=42),
    which draws np.random.default_rng(seed).permutation(n) and takes the first test_size indices.
    """
    return np.random.default_rng(seed).permutation(n_responses)[:n_test]
