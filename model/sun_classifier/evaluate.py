"""Check the 4-bit classifier against Sun et al.'s own test data.

Their published responses (one JSON file per model, 11,000 answers each) are split exactly as in
their classification.py, and a random subset of the 1,000 test answers per model is classified.
Their full-precision classifier reports 97.1% accuracy on this test set.

    python -m model.sun_classifier.evaluate --download            # fetch the five files (Google Drive)
    python -m model.sun_classifier.evaluate --per-class 200       # accuracy of the 4-bit model
    python -m model.sun_classifier.evaluate --per-class 40 --both-wrappers

Results go to data/results/sun_chat_eval.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from model.sun_classifier import LABELS
from model.sun_classifier.prepare import their_test_indices

RESPONSES = Path("data/corpus/sun_et_al")
RESULTS = Path("data/results/sun_chat_eval.json")
# Google Drive ids from the README of github.com/locuslab/llm-idiosyncrasies
DRIVE_IDS = {
    "ChatGPT": "1O1dEROw21KePNMF9ewlkXkkzL8Z-5qrN",
    "Claude": "1sifL_hsFiSDKZgnEeahiT20wPW8NDmRG",
    "Grok": "1yUA-8RYYXIkSV2xMbUCqTU8o6F6LrEFg",
    "Gemini": "1dsvpXmLCNa4Gehd9jmantMNSDiw2eS4f",
    "DeepSeek": "1a31HZgMwppwXjzEiY1fj3VfhAco5RWhG",
}


def download() -> None:
    import gdown

    RESPONSES.mkdir(parents=True, exist_ok=True)
    for label, file_id in DRIVE_IDS.items():
        target = RESPONSES / f"{label}.json"
        if not target.exists():
            gdown.download(id=file_id, output=str(target), quiet=False)
        print(f"{label}: {target.stat().st_size / 1024**2:.1f} MiB")


def test_texts(label: str) -> list[str]:
    """Their 1,000 test answers for one model, in their split."""
    data = json.loads((RESPONSES / f"{label}.json").read_text(encoding="utf-8"))
    return [data[i][-1]["content"] for i in their_test_indices(len(data))]


def evaluate(per_class: int, chat_wrapper: bool, seed: int = 0) -> dict:
    import gc

    import torch

    from model.sun_classifier.classify import SunChatClassifier

    torch.cuda.reset_peak_memory_stats()
    clf = SunChatClassifier(chat_wrapper=chat_wrapper)
    if not clf.is_bidirectional():
        raise RuntimeError("attention is still causal; the bidirectional setup did not take effect")
    rng = random.Random(seed)
    confusion = {truth: dict.fromkeys(LABELS, 0) for truth in LABELS}
    started = time.time()
    for truth in LABELS:
        texts = test_texts(truth)
        for text in rng.sample(texts, per_class):
            scores = clf.logits(text).float().cpu().tolist()
            confusion[truth][LABELS[scores.index(max(scores))]] += 1
        print(f"  {truth}: {confusion[truth][truth]}/{per_class} correct", flush=True)
    correct = sum(confusion[label][label] for label in LABELS)
    total = per_class * len(LABELS)
    seconds = (time.time() - started) / total
    del clf  # free the GPU before another variant loads its own copy
    gc.collect()
    torch.cuda.empty_cache()
    return {
        "chat_wrapper": chat_wrapper,
        "per_class": per_class,
        "accuracy": correct / total,
        "correct": correct,
        "total": total,
        "confusion": confusion,
        "seconds_per_text": seconds,
        "peak_gpu_gib": torch.cuda.max_memory_allocated() / 1024**3,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--download", action="store_true", help="download their response files and stop")
    parser.add_argument("--per-class", type=int, default=200, help="test answers per model (max 1000)")
    parser.add_argument("--both-wrappers", action="store_true", help="also run with the Llama 3 chat wrapper")
    parser.add_argument(
        "--no-chat-wrapper", action="store_true", help="run only without the Llama 3 chat wrapper"
    )
    args = parser.parse_args(argv)
    if args.download:
        download()
        return
    variants = [False, True] if args.both_wrappers else [not args.no_chat_wrapper]
    results = []
    for wrapper in variants:
        print(f"chat wrapper {wrapper}:")
        result = evaluate(args.per_class, wrapper)
        print(
            f"  accuracy {result['accuracy']:.3f} ({result['correct']}/{result['total']}), "
            f"{result['seconds_per_text']:.2f} s/text, peak GPU {result['peak_gpu_gib']:.2f} GiB"
        )
        results.append(result)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=1))
    print(f"saved {RESULTS}")


if __name__ == "__main__":
    main()
