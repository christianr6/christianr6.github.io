"""Split by time, and remove the days that give the answer away.

The simulator keeps finishing laundering chains after normal activity stops,
so the trailing days are mostly laundering. A model that learned "late
transaction = laundering" would score well and know nothing. Those days are
dropped before anything is trained or scored.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TAIL_VOLUME_SHARE = 0.05   # a day with under 5% of the median day's volume is "after the period"


@dataclass(frozen=True)
class Split:
    train: np.ndarray      # boolean masks over the kept rows
    valid: np.ndarray
    test: np.ndarray
    days: dict             # day -> part, for reporting


def primary_period(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Keep the days with normal volume; report what the dropped tail looked like."""
    day = df["ts"].dt.normalize()
    volume = day.value_counts().sort_index()
    busy = volume[volume >= TAIL_VOLUME_SHARE * volume.median()]
    last_day = busy.index.max()
    keep = day <= last_day
    dropped = df[~keep]
    report = {
        "last_day_kept": str(last_day.date()),
        "dropped_transactions": int(len(dropped)),
        "dropped_laundering": int(dropped["is_laundering"].sum()),
        "dropped_laundering_share": float(dropped["is_laundering"].mean()) if len(dropped) else 0.0,
    }
    return df[keep].reset_index(drop=True), report


def by_time(df: pd.DataFrame, train_share: float = 0.6, valid_share: float = 0.2) -> Split:
    """Whole days go to one part: earliest to train, then validation, latest to test."""
    day = df["ts"].dt.normalize()
    counts = day.value_counts().sort_index()
    cumulative = counts.cumsum() / counts.sum()
    parts = {}
    for one_day, share in cumulative.items():
        before = share - counts[one_day] / counts.sum()
        parts[one_day] = "train" if before < train_share else "valid" if before < train_share + valid_share else "test"
    part = day.map(parts).to_numpy()
    return Split(
        train=part == "train", valid=part == "valid", test=part == "test",
        days={str(k.date()): v for k, v in parts.items()},
    )
