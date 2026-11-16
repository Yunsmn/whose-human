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

from model.sun_classifier import LABELS
from model.sun_classifier.prepare import wrap_text

MODEL_DIR = Path("data/models/sun_chat/nf4")
MAX_TOKENS = 512


class SunChatClassifier:
    def __init__(self, model_dir: Path | str = MODEL_DIR, chat_wrapper: bool = True, device: int = 0):
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
        head = load_file(str(model_dir / "head.safetensors"))
        self.head_weight = head["head.weight"].to(self.device, torch.bfloat16)
        self.head_bias = head["head.bias"].to(self.device, torch.bfloat16)

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
        """The head's five scores, in bf16 as in training."""
        return self.embed(text).to(self.head_weight.dtype) @ self.head_weight.T + self.head_bias

    def predict_proba(self, texts: list[str]):
        import pandas as pd

        rows = []
        for text in texts:
            probs = self.torch.softmax(self.logits(text).float(), dim=-1).cpu().tolist()
            rows.append({f"p_{label.lower()}": p for label, p in zip(LABELS, probs, strict=True)})
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
