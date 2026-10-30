import argparse
import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import pearsonr, spearmanr
from sklearn.linear_model import LogisticRegression, RidgeCV
from sklearn.metrics import cohen_kappa_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = (
    "voiced_ms",
    "articulation_rate",
    "pause_count",
    "longest_pause_ms",
    "disfluency_density",
    "pvq",
    "loudness_dbfs",
)
MODELS = {
    "mean": (),
    "voiced_ms": ("voiced_ms",),
    "articulation_rate": ("articulation_rate",),
    "full": FEATURES,
}
ALPHAS = (0.1, 1.0, 10.0, 100.0)
FOLDS = 5


def load_table(
    path: Path, target: str, group: str, target_range: tuple[float, float] | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        columns = [x for x in FEATURES if x in (reader.fieldnames or ())]
        rows = list(reader)
    x_rows, y, groups = [], [], []
    for row in rows:
        try:
            value = float(row[target])
            features = [float(row[c]) if row[c] != "" else np.nan for c in columns]
        except (ValueError, KeyError):
            continue
        if np.isnan(value) or (target_range and not target_range[0] <= value <= target_range[1]):
            continue
        x_rows.append(features)
        y.append(value)
        groups.append(row[group])
    x = np.array(x_rows, dtype=float).reshape(len(y), len(columns))
    # Rows without a defined feature (e.g. no voiced frames) cannot be scored.
    keep = ~np.isnan(x).any(axis=1)
    return x[keep], np.array(y)[keep], np.array(groups)[keep], columns


def grouped_ridge(groups: np.ndarray) -> RidgeCV:
    """RidgeCV whose alpha is chosen by speaker-grouped inner CV, not leave-one-out."""
    splits = min(FOLDS, len(set(groups)))
    x_stub = np.zeros((len(groups), 1))
    return RidgeCV(alphas=ALPHAS, cv=list(GroupKFold(splits).split(x_stub, groups=groups)))


def out_of_fold(x: np.ndarray, y: np.ndarray, groups: np.ndarray, binary: np.ndarray | None):
    """Predictions from speaker-grouped CV. Binary returns probabilities instead."""
    predictions = np.zeros(len(y))
    for train, test in GroupKFold(FOLDS).split(x, y, groups):
        if x.shape[1] == 0:
            predictions[test] = binary[train].mean() if binary is not None else y[train].mean()
            continue
        if binary is not None:
            model = make_pipeline(StandardScaler(), LogisticRegression())
            model.fit(x[train], binary[train])
            predictions[test] = model.predict_proba(x[test])[:, 1]
        else:
            model = make_pipeline(StandardScaler(), grouped_ridge(groups[train]))
            model.fit(x[train], y[train])
            predictions[test] = model.predict(x[test])
    return predictions


def qwk(y: np.ndarray, pred: np.ndarray, low: float, high: float) -> float | None:
    labels = np.arange(round(low), round(high) + 1)
    a = np.clip(np.rint(y), labels[0], labels[-1]).astype(int)
    b = np.clip(np.rint(pred), labels[0], labels[-1]).astype(int)
    if len(set(a)) < 2 and len(set(b)) < 2:
        return None
    return float(cohen_kappa_score(a, b, weights="quadratic", labels=labels))


def metrics(y, pred, binary, proba, bounds) -> dict[str, float | None]:
    def safe(fn):
        try:
            value = float(fn())
        except ValueError:
            return None
        return None if np.isnan(value) else value

    pearson = safe(lambda: pearsonr(y, pred)[0]) if np.ptp(pred) > 0 else None
    spearman = safe(lambda: spearmanr(y, pred)[0]) if np.ptp(pred) > 0 else None
    result: dict[str, float | None] = {
        "pearson": pearson,
        "spearman": spearman,
        "rmse": float(np.sqrt(np.mean((y - pred) ** 2))),
        "qwk": qwk(y, pred, *bounds),
    }
    if binary is not None:
        result["auc"] = None if proba is None else safe(lambda: roc_auc_score(binary, proba))
    return result


def bootstrap_ci(y, pred, binary, proba, groups, bounds, draws, seed=0):
    rng = np.random.default_rng(seed)
    speakers = np.unique(groups)
    index = {s: np.flatnonzero(groups == s) for s in speakers}
    samples: dict[str, list[float]] = {}
    for _ in range(draws):
        pick = np.concatenate([index[s] for s in rng.choice(speakers, len(speakers))])
        sample = metrics(
            y[pick],
            pred[pick],
            None if binary is None else binary[pick],
            None if proba is None else proba[pick],
            bounds,
        )
        for key, value in sample.items():
            if value is not None:
                samples.setdefault(key, []).append(value)
    return {
        key: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
        for key, v in samples.items()
    }


def run_experiment(
    features: Path,
    *,
    target: str,
    group: str = "speaker_id",
    target_range: tuple[float, float] | None = None,
    binary_threshold: float | None = None,
    bootstrap: int = 1000,
) -> dict[str, Any]:
    x_all, y, groups, columns = load_table(features, target, group, target_range)
    found = len(set(groups))
    if found < FOLDS:
        raise ValueError(f"need at least {FOLDS} distinct '{group}' groups, found {found}")
    bounds = target_range or (float(np.floor(y.min())), float(np.ceil(y.max())))
    binary = (y >= binary_threshold).astype(int) if binary_threshold is not None else None
    if binary is not None:
        for train, _ in GroupKFold(FOLDS).split(x_all, y, groups):
            if len(set(binary[train])) < 2:
                raise ValueError(
                    "--binary-threshold leaves a training fold with one class; "
                    "every training fold needs both classes, choose another threshold"
                )
    models: dict[str, Any] = {}
    for name, wanted in MODELS.items():
        x = x_all[:, [columns.index(c) for c in wanted if c in columns]]
        pred = out_of_fold(x, y, groups, None)
        # The mean model has no ranking signal, so its AUC is reported as None.
        has_features = binary is not None and x.shape[1] > 0
        proba = out_of_fold(x, y, groups, binary) if has_features else None
        value = metrics(y, pred, binary, proba, bounds)
        ci = bootstrap_ci(y, pred, binary, proba, groups, bounds, bootstrap)
        models[name] = {key: {"value": v, "ci95": ci.get(key)} for key, v in value.items()}
    scaled = StandardScaler().fit_transform(x_all)
    ridge = grouped_ridge(groups).fit(scaled, y)
    return {
        "n_rows": int(len(y)),
        "n_speakers": int(len(set(groups))),
        "target": target,
        "target_range": list(bounds),
        "binary_threshold": binary_threshold,
        "models": models,
        "coefficients": dict(zip(columns, map(float, ridge.coef_), strict=True)),
        "hypotheses": {"pvq": "+", "disfluency_density": "-", "pause_count": "-"},
    }


def render(result: dict[str, Any]) -> str:
    def cell(item: dict[str, Any] | None) -> str:
        if not item or item["value"] is None:
            return "-"
        ci = item["ci95"]
        return f"{item['value']:.3f}" + (f" [{ci[0]:.3f},{ci[1]:.3f}]" if ci else "")

    keys = ["pearson", "spearman", "rmse", "qwk", "auc"]
    lines = [f"target={result['target']} n={result['n_rows']} speakers={result['n_speakers']}"]
    lines.append("model".ljust(20) + "".join(k.ljust(26) for k in keys))
    for name, values in result["models"].items():
        lines.append(name.ljust(20) + "".join(cell(values.get(k)).ljust(26) for k in keys))
    lines.append("standardized coefficients (full model)")
    for name, value in result["coefficients"].items():
        lines.append(f"  {name.ljust(20)}{value:+.3f}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="전달력 특징과 사람 평정의 관계를 확인합니다.")
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--group", default="speaker_id")
    parser.add_argument("--target-range", type=float, nargs=2, metavar=("LO", "HI"))
    parser.add_argument(
        "--binary-threshold",
        type=float,
        help="also fit logistic AUC for target >= threshold; exits with an error if any "
        "training fold has only one class",
    )
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--out-json", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_experiment(
            args.features,
            target=args.target,
            group=args.group,
            target_range=tuple(args.target_range) if args.target_range else None,
            binary_threshold=args.binary_threshold,
            bootstrap=args.bootstrap,
        )
    except ValueError as error:
        raise SystemExit(f"error: {error}") from error
    print(render(result))
    if args.out_json:
        args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
