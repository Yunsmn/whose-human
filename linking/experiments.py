"""Model selection for 3c: train / validation / test split by session, test set touched once.

`python -m linking.experiments <vm_logs_dir> --runs runs [--extra-train <local_logs_dir>] [--seeds 5]`

Sessions (not pairs) are split 60/20/20, stratified by user and setting, so a session's pairs never cross
from training into evaluation:
- training pairs: both sessions in train;
- validation pairs: at least one session in validation, none in test (val-val and val-train);
- test pairs: at least one session in test.
Clusters are scored on the validation (or test) sessions alone. Each configuration is a feature set, a
model and a clustering threshold; the one with the best mean validation B-cubed F1 over the seeds is then
scored once on the test sets, next to the IP rule. Prints counts and rates only.
"""

from __future__ import annotations

import argparse
import ipaddress
import math
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline

from infra.loader import load_logs
from linking.link import cluster, cluster_metrics
from linking.pairs import (
    IP_FEATURES,
    NETWORK_FEATURES,
    SCHEDULE_FEATURES,
    TOKEN_FEATURES,
    build_pairs,
    rarity_columns,
    value_shares,
)
from linking.sessions import SIGNATURE_COLUMNS, build_sessions

RARITY = ["signature_rarity", "rarest_match"]
TRACE = [f for f in NETWORK_FEATURES if f not in RARITY]
ORG = ["same_ip_16"]  # stand-in for "same network owner" (ASN): the /16 around an IPv4 address
FEATURE_SETS = {
    "trace": TRACE,
    "trace+rarity": TRACE + RARITY,
    "trace+rarity+org": TRACE + RARITY + ORG,
    "trace+rarity+ip": TRACE + RARITY + IP_FEATURES,
    "trace+rarity+org+ip": TRACE + RARITY + ORG + IP_FEATURES,
    "all+schedule (diagnostic)": TRACE + RARITY + ORG + IP_FEATURES + TOKEN_FEATURES + SCHEDULE_FEATURES,
}
MODELS = {
    "logreg": lambda: LogisticRegression(class_weight="balanced", max_iter=2000),
    "gboost": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.1, class_weight="balanced"),
    "extratrees": lambda: ExtraTreesClassifier(
        n_estimators=300, min_samples_leaf=3, class_weight="balanced", random_state=0
    ),
}
# Second round: extra trees settings, on the strongest feature sets only.
for _leaf in (1, 3, 10):
    for _maxf in ("sqrt", 0.5, None):
        MODELS[f"extratrees-leaf{_leaf}-mf{_maxf}"] = lambda leaf=_leaf, maxf=_maxf: ExtraTreesClassifier(
            n_estimators=300,
            min_samples_leaf=leaf,
            max_features=maxf,
            class_weight="balanced",
            random_state=0,
        )
ROUND2 = ("trace+rarity", "trace+rarity+ip")
THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
FS_COLUMNS = [*SIGNATURE_COLUMNS, "tools"]


# ---- splits -------------------------------------------------------------------------------------------
def split_sessions(sessions: pd.DataFrame, seed: int) -> pd.Series:
    """'train' / 'val' / 'test' per session, 60/20/20 within each (user, setting) group."""
    rng = np.random.default_rng(seed)
    setting = sessions["run_id"].str.extract(r"-s(\d)-")[0].fillna("x")
    part = pd.Series("train", index=sessions.index)
    for _, group in sessions.groupby([sessions["label_user"], setting]):
        order = rng.permutation(group.index.to_numpy())
        n_val = int(round(0.2 * len(order)))
        n_test = int(round(0.2 * len(order)))
        part[order[:n_test]] = "test"
        part[order[n_test : n_test + n_val]] = "val"
    return pd.Series(part.to_numpy(), index=sessions["session_key"])


def pair_masks(pairs: pd.DataFrame, part: pd.Series) -> dict[str, pd.Series]:
    a, b = pairs["a"].map(part), pairs["b"].map(part)
    test = a.eq("test") | b.eq("test")
    val = (a.eq("val") | b.eq("val")) & ~test
    return {"train": a.eq("train") & b.eq("train"), "val": val, "test": test}


# ---- extra features -------------------------------------------------------------------------------
def _ip16(ip):
    try:
        address = ipaddress.ip_address(ip)
    except (TypeError, ValueError):
        return None
    if address.version != 4:
        return str(ipaddress.ip_network(f"{address}/48", strict=False))
    return str(ipaddress.ip_network(f"{address}/16", strict=False))


def add_org(sessions: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    org = sessions.set_index("session_key")["ip"].map(_ip16)
    a, b = pairs["a"].map(org), pairs["b"].map(org)
    return pairs.assign(same_ip_16=(a.notna() & b.notna() & a.eq(b)))


# ---- scorers --------------------------------------------------------------------------------------
def fit_model(name: str, train: pd.DataFrame, features: list[str]):
    model = Pipeline([("impute", SimpleImputer(strategy="constant", fill_value=0)), ("clf", MODELS[name]())])
    model.fit(train[features].astype(float), train["same_user"].astype(bool))
    return model


def predict(model, pairs: pd.DataFrame, features: list[str]) -> pd.Series:
    proba = model.predict_proba(pairs[features].astype(float))
    return pd.Series(proba[:, list(model.classes_).index(True)], index=pairs.index)


class FellegiSunter:
    """Supervised Fellegi-Sunter with value-specific (frequency-based) agreement weights.

    m = P(agree | same person), per column; u(v) = P(two different people both show value v) ≈ f(v)²,
    smoothed; disagreement uses the column's overall u. The summed log-likelihood ratio is mapped to a
    probability by a one-variable logistic fit on the training pairs."""

    def __init__(self, sessions: pd.DataFrame, columns: list[str]):
        self.columns = columns
        indexed = sessions.set_index("session_key")
        self.values = {c: indexed[c].map(lambda cell: frozenset(_as_set(cell))) for c in columns}

    def _agree_values(self, pairs: pd.DataFrame, column: str) -> list[frozenset]:
        left, right = pairs["a"].map(self.values[column]), pairs["b"].map(self.values[column])
        pairs_ = zip(left, right, strict=True)
        return [x & y if (x & y) else (x if x == y else frozenset()) for x, y in pairs_]

    def fit(self, train_sessions: pd.Series, train: pd.DataFrame) -> FellegiSunter:
        """m per column from same-person training pairs; u per shared value from different-person ones."""
        del train_sessions  # u comes from the pairs themselves
        self.m, self.u, self.u_value = {}, {}, {}
        same = train["same_user"].astype(bool).to_numpy()
        n_diff = max(int((~same).sum()), 1)
        for c in self.columns:
            shared = self._agree_values(train, c)
            agree = np.array([bool(v) for v in shared])
            self.m[c] = (agree[same].sum() + 1) / (same.sum() + 2)
            self.u[c] = (agree[~same].sum() + 1) / (n_diff + 2)
            counts: dict = {}
            for values, is_same in zip(shared, same, strict=True):
                if not is_same:
                    for v in values:
                        counts[v] = counts.get(v, 0) + 1
            self.u_value[c] = {v: (k + 0.5) / (n_diff + 1) for v, k in counts.items()}
            self.u_value[c]["_unseen"] = 0.5 / (n_diff + 1)
        raw = self._raw(train)
        self.cal = LogisticRegression(class_weight="balanced").fit(raw.to_frame(), same)
        return self

    def _raw(self, pairs: pd.DataFrame) -> pd.Series:
        total = np.zeros(len(pairs))
        for c in self.columns:
            weights = []
            for shared in self._agree_values(pairs, c):
                if shared:
                    u_v = min(self.u_value[c].get(v, self.u_value[c]["_unseen"]) for v in shared)
                    weights.append(math.log(self.m[c] / min(u_v, 0.999)))
                else:
                    weights.append(math.log((1 - self.m[c]) / (1 - self.u[c])))
            total += np.array(weights)
        return pd.Series(total, index=pairs.index, name="llr")

    def predict(self, pairs: pd.DataFrame) -> pd.Series:
        proba = self.cal.predict_proba(self._raw(pairs).to_frame())[:, list(self.cal.classes_).index(True)]
        return pd.Series(proba, index=pairs.index)


def _as_set(cell):
    if isinstance(cell, (tuple, list, set, frozenset)):
        return set(cell) or {"∅"}
    return {"∅"} if cell is None or (isinstance(cell, float) and math.isnan(cell)) else {cell}


# ---- evaluation -----------------------------------------------------------------------------------
def evaluate_part(sessions, pairs, scores, mask, part, which, threshold) -> dict:
    sub = pairs.loc[mask]
    y = sub["same_user"].astype(bool)
    auc = roc_auc_score(y, scores.loc[sub.index]) if y.nunique() == 2 else float("nan")
    keys = part.index[part.eq(which)]
    own = sessions.loc[sessions["session_key"].isin(keys)]
    inner = pairs.loc[pairs["a"].isin(keys) & pairs["b"].isin(keys)]
    clusters = cluster(own, inner, scores.loc[inner.index], threshold)
    metrics = cluster_metrics(own, clusters)
    return {"auc": auc, "b3f1": metrics["bcubed_f1"], "ari": metrics["adjusted_rand"]}


def run(sessions, pairs, extra_pairs, seeds) -> pd.DataFrame:
    rows = []
    for seed in seeds:
        part = split_sessions(sessions, seed)
        # rarity from this split's training sessions only, so evaluation sessions never shape it
        train_keys = part.index[part.eq("train")]
        shares = value_shares(sessions.loc[sessions.session_key.isin(train_keys)])
        pairs = pairs.assign(**rarity_columns(pairs, sessions, shares))
        masks = pair_masks(pairs, part)
        train = pairs.loc[masks["train"]]
        round1 = ("logreg", "gboost", "extratrees")
        configs = [("ip rule", "-", None)] + [(f, m, None) for f in FEATURE_SETS for m in round1]
        configs += [(f, m, None) for f in ROUND2 for m in MODELS if m.startswith("extratrees-")]
        configs += [("fellegi-sunter", "fs", None), ("fellegi-sunter+org+ip", "fs", None)]
        if extra_pairs is not None:
            configs += [(f, m, "local") for f in ("trace", "trace+rarity") for m in round1]
        for features_name, model_name, extra in configs:
            if features_name == "ip rule":
                scores = pairs["same_ip"].astype(float)
            elif model_name == "fs":
                columns = FS_COLUMNS + (["ip", "ip_prefix"] if "ip" in features_name else [])
                fs_sessions = sessions.assign(ip=sessions["ip"].map(lambda x: (x,) if pd.notna(x) else ()))
                fs_sessions["ip_prefix"] = sessions["ip_prefix"].map(lambda x: (x,) if pd.notna(x) else ())
                scorer = FellegiSunter(fs_sessions, columns).fit(part.index[part.eq("train")], train)
                scores = scorer.predict(pairs)
            else:
                features = FEATURE_SETS[features_name]
                fit_on = train if extra is None else pd.concat([train, extra_pairs], ignore_index=True)
                scores = predict(fit_model(model_name, fit_on, features), pairs, features)
            for threshold in THRESHOLDS:
                for which in ("val", "test"):
                    result = evaluate_part(sessions, pairs, scores, masks[which], part, which, threshold)
                    rows.append(
                        {
                            "seed": seed,
                            "features": features_name + ("" if extra is None else " +local train"),
                            "model": model_name,
                            "threshold": threshold,
                            "split": which,
                            **result,
                        }
                    )
    return pd.DataFrame(rows)


def _threshold(best_per: pd.DataFrame, features: str, model: str) -> float:
    return best_per.set_index(["features", "model"]).loc[(features, model), "threshold"]


def _best(best_per: pd.DataFrame, features: str) -> tuple:
    row = best_per.loc[best_per.features.eq(features)].iloc[0]
    return row.features, row.model, row.threshold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs_dir")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--extra-train", help="local logs dir: their sessions only ever join training")
    parser.add_argument("--seeds", type=int, default=5)
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore")
    logs = load_logs(args.logs_dir, runs_dir=args.runs)
    t3 = logs.loc[logs["run_id"].astype(str).str.contains("-t3-")]
    sessions = build_sessions(t3).reset_index(drop=True)
    pairs = add_org(sessions, build_pairs(sessions))
    extra_pairs = None
    if args.extra_train:
        local = build_sessions(load_logs(args.extra_train, runs_dir=args.runs))
        local = local.loc[~local["run_id"].str.contains("-t3-")].reset_index(drop=True)
        extra_pairs = add_org(local, build_pairs(local))
    print(f"Sessions: {len(sessions)} ({sessions.label_user.nunique()} users); pairs: {len(pairs)}")
    results = run(sessions, pairs, extra_pairs, range(args.seeds))
    keys = ["features", "model", "threshold"]
    val = results.loc[results.split.eq("val")].groupby(keys)[["b3f1", "auc", "ari"]].mean()
    best_per = val.reset_index().sort_values("b3f1", ascending=False).drop_duplicates(["features", "model"])
    print("\nValidation (mean over seeds), best threshold per feature set and model:")
    print(best_per.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    eligible = best_per.loc[~best_per.features.str.contains("diagnostic")]
    winner = eligible.iloc[0]  # the schedule set is reported, never selected (it measures our timetable)
    print(f"\nSelected on validation: {winner.features} / {winner.model} / threshold {winner.threshold}")
    test = results.loc[results.split.eq("test")]
    chosen = [
        ("selected", winner.features, winner.model, winner.threshold),
        ("ip rule", "ip rule", "-", _threshold(best_per, "ip rule", "-")),
        ("schedule", *_best(best_per, "all+schedule (diagnostic)")),
    ]
    print("\nTest (each configuration's validation-chosen threshold; mean ± sd over seeds):")
    for label, f, m, t in chosen:
        rows = test.loc[test.features.eq(f) & test.model.eq(m) & test.threshold.eq(t)]
        print(
            f"  {label:9s} {f} / {m}: B-cubed F1 {rows.b3f1.mean():.3f} ± {rows.b3f1.std():.3f}, "
            f"AUC {rows.auc.mean():.3f} ± {rows.auc.std():.3f}, "
            f"ARI {rows.ari.mean():.3f} ± {rows.ari.std():.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
