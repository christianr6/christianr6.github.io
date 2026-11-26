"""Gradient-boosted trees on the feature table, and honest scoring.

With one laundering transaction per thousand, accuracy is useless: flagging
nothing is 99.9% accurate. Everything here is scored on the laundering class:
average precision (area under the precision-recall curve), and precision,
recall and F1 at a threshold chosen on validation data only.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

PARAMS = dict(
    objective="binary", learning_rate=0.05, num_leaves=63, min_child_samples=40,
    colsample_bytree=0.8, subsample=0.8, subsample_freq=1, reg_lambda=1.0,
    n_estimators=3000, verbose=-1, n_jobs=4, random_state=7,
)
EARLY_STOP_ROUNDS = 150


def fit(features: pd.DataFrame, labels: np.ndarray, train: np.ndarray, valid: np.ndarray) -> lgb.LGBMClassifier:
    model = lgb.LGBMClassifier(**PARAMS)
    model.fit(
        features[train], labels[train],
        eval_X=(features[valid],), eval_y=(labels[valid],),
        eval_metric="average_precision",
        callbacks=[lgb.early_stopping(EARLY_STOP_ROUNDS, verbose=False)],
    )
    return model


def best_threshold(scores: np.ndarray, labels: np.ndarray) -> float:
    """The score cut-off with the highest F1. Call this on validation data, never on test."""
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    return float(thresholds[int(np.argmax(f1[:-1]))])


def score(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    flagged = scores >= threshold
    hits = int((flagged & (labels == 1)).sum())
    precision = hits / max(int(flagged.sum()), 1)
    recall = hits / max(int(labels.sum()), 1)
    return {
        "average_precision": float(average_precision_score(labels, scores)),
        "base_rate": float(labels.mean()),      # what random guessing scores on average precision
        "threshold": threshold,
        "flagged": int(flagged.sum()),
        "caught": hits,
        "laundering": int(labels.sum()),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / max(precision + recall, 1e-12),
    }


def curve(scores: np.ndarray, labels: np.ndarray, points: int = 101) -> list[dict]:
    """Precision at evenly spaced recall levels, for plotting.

    Each point is the best precision reachable at that recall or higher, the
    usual way to draw the curve without its sawtooth.
    """
    precision, recall, _ = precision_recall_curve(labels, scores)   # recall runs from 1 down to 0
    best_so_far = np.maximum.accumulate(precision)                   # best precision at this recall or more
    out = []
    for level in np.linspace(0, 1, points):
        reachable = recall >= level
        out.append({"recall": float(level), "precision": float(best_so_far[reachable][-1])})
    return out


def importance(model: lgb.LGBMClassifier, top: int = 15) -> list[dict]:
    gain = model.booster_.feature_importance(importance_type="gain")
    total = gain.sum() or 1.0
    order = np.argsort(gain)[::-1][:top]
    names = model.booster_.feature_name()
    return [{"feature": names[i], "share_of_gain": float(gain[i] / total)} for i in order]
