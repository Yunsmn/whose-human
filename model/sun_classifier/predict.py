"""Score texts with the 2c classifier and write one probability vector per text.

    python -m model.sun_classifier.predict data/corpus/agent/member-a-agent-text.csv

The classifier sees nothing but the text. From the input file only two columns are read:

- the text: `submitted_text` (2a's agent CSV) or `text` (2b's API corpus), or `--text-column`
- an optional key, passed through untouched so results can be joined back later: `run_id` if the
  file has one, or `--id-column`. Without a key, rows are numbered.

Labels (`label_model`, `label_agent`, ...) are never read, so the same command works on text from a
real visitor where no run or label exists. Scoring against labels is a separate step.

`--head short` (default) uses the head trained on our current models (train_head.py);
`--head sun` uses Sun et al.'s original five 2024 labels.

Output, in the gitignored data/predictions/2c/ (CSV), named `<input>-<head>-texts.csv` and
`<input>-<head>-ids.csv`:

- texts: one row per text: `id`, `p_<model>` for every model the head knows (summing to 1),
  `provider_<name>` (from the short head's own two-way provider head, summing to 1; for a head
  without one, the sum over that provider's models), `top_model`, `top_provider`. The two heads
  are separate, so `top_provider` can differ from the provider of `top_model`.
- ids, only when there is a key: one row per key (per run in our tests), the mean of its texts'
  vectors, `n_texts`, `top_model` and `top_provider`.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

OUT_DIR = Path("data/predictions/2c")
TEXT_COLUMNS = ("submitted_text", "text")
ID_COLUMNS = ("run_id",)

# Takes a list of texts, returns a DataFrame with one p_<model> column per model, one row per text.
ScoreFn = Callable[[Sequence[str]], pd.DataFrame]


def _read(path: Path) -> pd.DataFrame:
    if path.suffix == ".jsonl":
        return pd.read_json(path, lines=True, dtype=False)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_texts(
    path: Path | str, text_column: str | None = None, id_column: str | None = None
) -> pd.DataFrame:
    """Return only `id` and `text` from the input; every other column is dropped here."""
    frame = _read(Path(path))
    text_column = text_column or next((c for c in TEXT_COLUMNS if c in frame.columns), None)
    if text_column not in frame.columns:
        raise ValueError(f"{path} has no text column (looked for {', '.join(TEXT_COLUMNS)})")
    if id_column is not None and id_column not in frame.columns:
        raise ValueError(f"{path} has no column {id_column!r}")
    id_column = id_column or next((c for c in ID_COLUMNS if c in frame.columns), None)
    ids = frame[id_column].astype(str) if id_column else pd.Series(range(len(frame))).astype(str)
    texts = pd.DataFrame({"id": ids.values, "text": frame[text_column].fillna("").astype(str).values})
    texts = texts[texts["text"].str.strip().ne("")].reset_index(drop=True)
    texts.attrs["has_key"] = id_column is not None
    return texts


def score_texts(texts: pd.DataFrame, score: ScoreFn, providers: dict[str, str]) -> pd.DataFrame:
    """One row per text: id, p_<model>, provider_<name>, top_model, top_provider."""
    probs = score(list(texts["text"])).reset_index(drop=True)
    out = pd.concat([texts[["id"]].reset_index(drop=True), probs], axis=1)
    return _add_providers(out, providers)


def per_id(scored: pd.DataFrame, providers: dict[str, str]) -> pd.DataFrame:
    """Average the vectors of all texts that share an id (several submissions in one run)."""
    grouped = scored.groupby("id", sort=True)
    out = grouped[_model_columns(scored) + _provider_columns(scored)].mean().reset_index()
    out.insert(1, "n_texts", grouped.size().values)
    return _add_providers(out, providers)


def _model_columns(frame: pd.DataFrame) -> list[str]:
    return [column for column in frame.columns if column.startswith("p_")]


def _provider_columns(frame: pd.DataFrame) -> list[str]:
    return [column for column in frame.columns if column.startswith("provider_")]


def _add_providers(frame: pd.DataFrame, providers: dict[str, str]) -> pd.DataFrame:
    """Provider columns the scorer already gave (a provider head) are kept; missing ones are sums."""
    models = _model_columns(frame)
    for provider in sorted(set(providers.values())):
        if f"provider_{provider}" not in frame:
            mine = [f"p_{model}" for model, owner in providers.items() if owner == provider]
            frame[f"provider_{provider}"] = frame[mine].sum(axis=1)
    frame["top_model"] = frame[models].idxmax(axis=1).str.removeprefix("p_")
    frame["top_provider"] = frame[_provider_columns(frame)].idxmax(axis=1).str.removeprefix("provider_")
    return frame


def gpu_scorer(head: str) -> tuple[ScoreFn, dict[str, str]]:
    from model.sun_classifier.classify import SHORT_HEAD, SunChatClassifier

    clf = SunChatClassifier(head=SHORT_HEAD if head == "short" else None)
    providers = {label.lower(): provider for label, provider in zip(clf.labels, clf.providers, strict=True)}
    return (lambda texts: clf.predict_proba(list(texts))), providers


def predict_file(
    path: Path | str,
    out_dir: Path | str = OUT_DIR,
    scorer: tuple[ScoreFn, dict[str, str]] | None = None,
    text_column: str | None = None,
    id_column: str | None = None,
    head: str = "short",
) -> list[Path]:
    path, out_dir = Path(path), Path(out_dir)
    texts = read_texts(path, text_column, id_column)
    score, providers = scorer or gpu_scorer(head)
    scored = score_texts(texts, score, providers)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [out_dir / f"{path.stem}-{head}-texts.csv"]
    scored.to_csv(written[0], index=False)
    if texts.attrs["has_key"]:
        written.append(out_dir / f"{path.stem}-{head}-ids.csv")
        per_id(scored, providers).to_csv(written[1], index=False)
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="CSV or JSONL with one text per row")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--text-column", help="default: submitted_text, else text")
    parser.add_argument("--id-column", help="key to pass through; default: run_id if present")
    parser.add_argument("--head", choices=["short", "sun"], default="short")
    args = parser.parse_args(argv)
    written = predict_file(args.input, args.out_dir, None, args.text_column, args.id_column, args.head)
    for path in written:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
