"""Run Sun et al.'s chat API classifier, converted to 4-bit, on short texts.

    from model.sun_classifier.classify import SunChatClassifier

    clf = SunChatClassifier()                    # loads data/models/sun_chat/nf4 on the GPU
    clf.predict_proba(["Two sentences ..."])     # DataFrame, one p_<label> column per label

Architecture (LLM2Vec, Sun et al. 2025): Llama-3-8B-Instruct with bidirectional attention and
merged LoRA adapters, mean pooling over the tokens, then a linear head with five outputs.
Texts are run one at a time. LLM2Vec's pooling for plain text averages over every position,
padding included, so a batch of one (no padding) matches their unpadded case exactly.
"""

from __future__ import annotations

from pathlib import Path

from model.sun_classifier import LABELS, PROVIDERS
from model.sun_classifier.prepare import wrap_text

MODEL_DIR = Path("data/models/sun_chat/nf4")
SHORT_HEAD = Path(__file__).parent / "heads" / "head-short.npz"  # written by train_head.py
MAX_TOKENS = 512


class SunChatClassifier:
    def __init__(
        self,
        model_dir: Path | str = MODEL_DIR,
        chat_wrapper: bool = True,
        device: int = 0,
        head: Path | str | None = None,
    ):
        """`head=None` keeps Sun et al.'s five 2024 labels; a path loads a head from train_head.py."""
        import torch
        from safetensors.torch import load_file
        from transformers import AutoTokenizer, LlamaModel

        self.torch = torch
        self.chat_wrapper = chat_wrapper
        self.device = torch.device("cuda", device)
        model_dir = Path(model_dir)
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(
                f"{model_dir} has no model. Build it first: python -m model.sun_classifier.convert merge, "
                "then quantize (see model/sun_classifier/README.md)."
            )
        # The stored pre-tokenizer regex is Llama 3's own. transformers 4.57 warns about Mistral's
        # regex bug for any local tokenizer; applying its "fix" would swap in Mistral's pattern.
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), fix_mistral_regex=False)
        self.model = LlamaModel.from_pretrained(
            str(model_dir), device_map={"": device}, attn_implementation="sdpa", dtype=torch.bfloat16
        )
        for layer in self.model.layers:  # LLM2Vec: every token attends to every other token
            layer.self_attn.is_causal = False
        self.model.eval()
        self.short_head = head is not None
        if self.short_head:
            import numpy as np

            arrays = np.load(head, allow_pickle=False)
            self.labels = arrays["labels"].tolist()
            self.providers = arrays["providers"].tolist()
            to_gpu = lambda name: torch.from_numpy(arrays[name]).to(self.device, torch.float32)  # noqa: E731
            self.head_weight, self.head_bias = to_gpu("weight"), to_gpu("bias")
            self.feature_mean, self.feature_scale = to_gpu("mean"), to_gpu("scale")
            # Optional two-way provider head, on the same standardized vector.
            self.provider_labels = arrays["provider_labels"].tolist() if "provider_labels" in arrays else []
            if self.provider_labels:
                self.provider_weight = to_gpu("provider_weight")
                self.provider_bias = to_gpu("provider_bias")
        else:
            self.provider_labels = []
            self.labels = list(LABELS)
            self.providers = [PROVIDERS[label] for label in LABELS]
            sun = load_file(str(model_dir / "head.safetensors"))
            self.head_weight = sun["head.weight"].to(self.device, torch.bfloat16)
            self.head_bias = sun["head.bias"].to(self.device, torch.bfloat16)

    def embed(self, text: str):
        """Mean-pooled 4096-dimensional representation of one text."""
        torch = self.torch
        ids = self.tokenizer(
            wrap_text(text, self.chat_wrapper), return_tensors="pt", truncation=True, max_length=MAX_TOKENS
        )["input_ids"].to(self.device)
        length = ids.shape[1]
        # An explicit all-zero additive mask: no causal masking and no padding.
        mask = torch.zeros((1, 1, length, length), dtype=torch.bfloat16, device=self.device)
        with torch.inference_mode():
            hidden = self.model(input_ids=ids, attention_mask=mask).last_hidden_state
        return hidden[0].mean(dim=0)

    def logits(self, text: str):
        """One score per label: Sun et al.'s head in bf16 as in training, or the trained short head."""
        return self._scores(self.embed(text))[0]

    def _scores(self, vector):
        """Model logits, and provider logits when the head has a provider head (else None)."""
        vector = vector.to(self.head_weight.dtype)
        if not self.short_head:
            return vector @ self.head_weight.T + self.head_bias, None
        vector = (vector - self.feature_mean) / self.feature_scale
        provider = vector @ self.provider_weight.T + self.provider_bias if self.provider_labels else None
        return vector @ self.head_weight.T + self.head_bias, provider

    def predict_proba(self, texts: list[str]):
        """One row per text: p_<label> per model and, with a provider head, provider_<name>."""
        import pandas as pd

        softmax = lambda scores: self.torch.softmax(scores.float(), dim=-1).cpu().tolist()  # noqa: E731
        rows = []
        for text in texts:
            model_scores, provider_scores = self._scores(self.embed(text))
            row = {
                f"p_{label.lower()}": p for label, p in zip(self.labels, softmax(model_scores), strict=True)
            }
            if provider_scores is not None:
                row |= {
                    f"provider_{name}": p
                    for name, p in zip(self.provider_labels, softmax(provider_scores), strict=True)
                }
            rows.append(row)
        return pd.DataFrame(rows)

    def is_bidirectional(self) -> bool:
        """True if the first token's representation depends on later tokens (it can't when causal)."""
        torch = self.torch
        outputs = []
        for text in ("The cat sat on the mat.", "The cat sat on the dog."):
            ids = self.tokenizer(text, return_tensors="pt")["input_ids"].to(self.device)
            length = ids.shape[1]
            mask = torch.zeros((1, 1, length, length), dtype=torch.bfloat16, device=self.device)
            with torch.inference_mode():
                outputs.append(self.model(input_ids=ids, attention_mask=mask).last_hidden_state[0, 1].float())
        return not torch.allclose(outputs[0], outputs[1], atol=1e-3)
