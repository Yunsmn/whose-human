import pandas as pd

from linking.paper_tables import _compact, latex


def test_latex_escapes_and_formats():
    text = latex(
        pd.DataFrame({"Scorer": ["Model: no_ip"], "AUC": [0.876], "n": [float("nan")]}), "Cap", "tab:x"
    )
    assert "Model: no\\_ip & 0.88 & -- \\\\" in text
    assert text.startswith("\\begin{table}") and "\\label{tab:x}" in text and "{lrr}" in text


def test_compact_keeps_one_rate_column_per_scorer():
    table = pd.DataFrame(
        {"tools_pair": ["all"], "n_pairs": [10], "false_link_rule": [1.0], "n_scored_rule": [10]}
    )
    out = _compact(table, "tools_pair", "false_link")
    assert list(out.columns) == ["Tools", "Pairs", "rule"]


def test_compact_says_so_when_empty():
    out = _compact(pd.DataFrame(), "network_pair", "recall")
    assert out.to_dict("list") == {"Networks": ["no pairs yet"]}
