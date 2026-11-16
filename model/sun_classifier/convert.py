"""Turn Sun et al.'s chat API classifier checkpoint into a 4-bit model that fits a 6 GB GPU.

Steps (each can be run on its own):

1. merge     LoRA adapters into the base weights -> plain bf16 LlamaModel shards (about 15 GB)
2. quantize  load those shards in 4-bit NF4 on the GPU and save the 4-bit model (about 5.5 GB)

    python -m model.sun_classifier.convert merge
    python -m model.sun_classifier.convert quantize

Inputs come from data/models/sun_chat/download/ (model.safetensors and head.pt from
huggingface.co/Yida/classifier_chat; tokenizer and config from the ungated
McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp). Nothing here contacts Meta's gated repository:
the checkpoint already holds every weight. The result is a Llama 3 derivative, under Meta's
Llama 3 license.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from model.sun_classifier.prepare import LORA_SCALE, plan_keys

ROOT = Path("data/models/sun_chat")
DOWNLOAD, MERGED, QUANTIZED = ROOT / "download", ROOT / "merged-bf16", ROOT / "nf4"
SHARD_BYTES = 2 * 1024**3
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")


def _config() -> dict:
    config = json.loads((DOWNLOAD / "mcgill-config.json").read_text())
    config.pop("auto_map", None)  # plain LlamaModel; bidirectionality is set at load time
    config["architectures"] = ["LlamaModel"]
    return config


def merge() -> None:
    import torch
    from safetensors.torch import save_file

    MERGED.mkdir(parents=True, exist_ok=True)
    source = DOWNLOAD / "model.safetensors"
    weight_map, shard, shard_bytes, shard_index = {}, {}, 0, 0

    def flush() -> None:
        nonlocal shard, shard_bytes, shard_index
        if not shard:
            return
        shard_index += 1
        name = f"model-{shard_index:05d}.safetensors"
        save_file(shard, str(MERGED / name), metadata={"format": "pt"})
        weight_map.update(dict.fromkeys(shard, name))
        print(f"wrote {name} ({shard_bytes / 1024**3:.2f} GiB, {len(shard)} tensors)", flush=True)
        shard, shard_bytes = {}, 0

    # safetensors' memory-mapped safe_open crashes on this 15 GB file on Windows, so tensors are read
    # with plain file reads instead (see _RawSafetensors).
    with _RawSafetensors(source) as stream:
        plan = plan_keys(stream.keys())
        for target, parts in sorted(plan.items(), key=lambda item: _layer_order(item[0])):
            weight = stream.get_tensor(parts["base"])
            if "A" in parts:
                a = stream.get_tensor(parts["A"]).float()
                b = stream.get_tensor(parts["B"]).float()
                weight = (weight.float() + LORA_SCALE * (b @ a)).to(torch.bfloat16)
            shard[target] = weight.contiguous()
            shard_bytes += weight.numel() * weight.element_size()
            if shard_bytes >= SHARD_BYTES:
                flush()
        flush()
        head = {key: stream.get_tensor(key) for key in ("head.weight", "head.bias")}

    save_file(head, str(MERGED / "head.safetensors"))
    (MERGED / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {}, "weight_map": weight_map}, indent=1)
    )
    (MERGED / "config.json").write_text(json.dumps(_config(), indent=1))
    print(f"merged {len(plan)} tensors into {MERGED}")


class _RawSafetensors:
    """Read tensors from a .safetensors file with ordinary seeks and reads (no memory map)."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        import struct

        self.stream = self.path.open("rb")
        header_len = struct.unpack("<Q", self.stream.read(8))[0]
        self.header = json.loads(self.stream.read(header_len))
        self.header.pop("__metadata__", None)
        self.data_start = 8 + header_len
        return self

    def __exit__(self, *exc):
        self.stream.close()

    def keys(self) -> list[str]:
        return list(self.header)

    def get_tensor(self, key: str):
        import torch

        dtypes = {"BF16": torch.bfloat16, "F32": torch.float32, "F16": torch.float16}
        entry = self.header[key]
        start, end = entry["data_offsets"]
        self.stream.seek(self.data_start + start)
        raw = bytearray(self.stream.read(end - start))
        return torch.frombuffer(raw, dtype=dtypes[entry["dtype"]]).reshape(entry["shape"]).clone()


def _layer_order(key: str) -> tuple[int, str]:
    parts = key.split(".")
    return (int(parts[1]) if parts[0] == "layers" else (-1 if parts[0] == "embed_tokens" else 10**6), key)


def quantize() -> None:
    import torch
    from transformers import BitsAndBytesConfig, LlamaModel

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = LlamaModel.from_pretrained(
        str(MERGED),
        quantization_config=quant,
        dtype=torch.bfloat16,
        device_map={"": 0},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    QUANTIZED.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(QUANTIZED))
    shutil.copy(MERGED / "head.safetensors", QUANTIZED / "head.safetensors")
    for name in TOKENIZER_FILES:
        shutil.copy(DOWNLOAD / f"mcgill-{name}", QUANTIZED / name)
    gib = sum(p.stat().st_size for p in QUANTIZED.glob("*.safetensors")) / 1024**3
    print(
        f"saved 4-bit model to {QUANTIZED} ({gib:.2f} GiB); GPU memory used "
        f"{torch.cuda.max_memory_allocated() / 1024**3:.2f} GiB"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=["merge", "quantize"])
    args = parser.parse_args(argv)
    {"merge": merge, "quantize": quantize}[args.step]()


if __name__ == "__main__":
    main()
