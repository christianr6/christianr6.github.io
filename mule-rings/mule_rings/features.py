"""Features for each transaction, in two groups.

RAW      what a rule engine sees looking at one transaction alone.
GRAPH    what you only see by looking at who else each account deals with,
         and how fast money that arrives moves on.

Graph features read the structure of every transaction in the period, the
way a bank reviewing a batch after the fact would. They never read a label.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RAW = [
    "log_amount", "payment_format", "payment_currency", "receiving_currency",
    "hour", "cross_currency", "self_transfer", "same_bank",
]
GRAPH = [
    "src_out_txn", "src_out_degree", "src_in_txn", "src_in_degree",
    "dst_out_txn", "dst_out_degree", "dst_in_txn", "dst_in_degree",
    "pair_txn", "reciprocal",
    "src_gap_prev_out", "src_gap_last_in", "dst_gap_next_out",
    "src_in_24h", "src_out_24h", "dst_in_24h", "dst_out_24h",
    "src_relay_ratio", "dst_relay_ratio",
]
CATEGORICAL = ["payment_format", "payment_currency", "receiving_currency"]
DAY = 24 * 60
_NEVER = 10**7        # minutes; stands for "no such earlier/later transaction"
_BIG = 10**8          # larger than any minute value, to pack (account, minute) into one integer


def _count_in_window(event_accounts, event_minutes, accounts, start, end) -> np.ndarray:
    """For each (account, start, end], how many events that account has in the window."""
    keys = np.sort(event_accounts.astype(np.int64) * _BIG + event_minutes.astype(np.int64))
    base = accounts.astype(np.int64) * _BIG
    return np.searchsorted(keys, base + end, side="right") - np.searchsorted(keys, base + start, side="right")


def _nearest(event_accounts, event_minutes, accounts, minutes, direction: str) -> np.ndarray:
    """Minutes to the account's closest event strictly before ('prev') or after ('next')."""
    keys = np.sort(event_accounts.astype(np.int64) * _BIG + event_minutes.astype(np.int64))
    wanted = accounts.astype(np.int64) * _BIG + minutes.astype(np.int64)
    if direction == "prev":
        position = np.searchsorted(keys, wanted, side="left") - 1
        found = position >= 0
        hit = keys[np.clip(position, 0, len(keys) - 1)]
        same = found & (hit // _BIG == accounts)
        return np.where(same, minutes - hit % _BIG, _NEVER)
    position = np.searchsorted(keys, wanted, side="right")
    found = position < len(keys)
    hit = keys[np.clip(position, 0, len(keys) - 1)]
    same = found & (hit // _BIG == accounts)
    return np.where(same, hit % _BIG - minutes, _NEVER)


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Feature table aligned row for row with df."""
    src, dst, minute = df["src"].to_numpy(), df["dst"].to_numpy(), df["minute"].to_numpy()
    out = pd.DataFrame(index=df.index)

    # ----- raw -----
    out["log_amount"] = np.log1p(df["amount_paid"].to_numpy())
    for column in CATEGORICAL:
        out[column] = df[column].astype("category")
    out["hour"] = df["ts"].dt.hour.to_numpy()
    out["cross_currency"] = (df["payment_currency"] != df["receiving_currency"]).astype("int8").to_numpy()
    out["self_transfer"] = (src == dst).astype("int8")
    out["same_bank"] = (df["from_bank"] == df["to_bank"]).astype("int8").to_numpy()

    # ----- graph: how connected is each end -----
    n = int(max(src.max(), dst.max())) + 1
    pairs = pd.DataFrame({"src": src, "dst": dst})
    distinct = pairs.drop_duplicates()
    out_txn = np.bincount(src, minlength=n)
    in_txn = np.bincount(dst, minlength=n)
    out_degree = np.bincount(distinct["src"], minlength=n)   # different accounts paid
    in_degree = np.bincount(distinct["dst"], minlength=n)    # different accounts paid by
    for side, ids in (("src", src), ("dst", dst)):
        out[f"{side}_out_txn"] = out_txn[ids]
        out[f"{side}_out_degree"] = out_degree[ids]
        out[f"{side}_in_txn"] = in_txn[ids]
        out[f"{side}_in_degree"] = in_degree[ids]

    pair_code = src.astype(np.int64) * n + dst
    reverse_code = dst.astype(np.int64) * n + src
    codes, counts = np.unique(pair_code, return_counts=True)
    out["pair_txn"] = counts[np.searchsorted(codes, pair_code)]
    out["reciprocal"] = (np.isin(reverse_code, codes) & (src != dst)).astype("int8")

    # ----- graph: timing. Mules pass money on quickly. -----
    out["src_gap_prev_out"] = _nearest(src, minute, src, minute, "prev")   # sender's previous payment
    out["src_gap_last_in"] = _nearest(dst, minute, src, minute, "prev")    # sender last received money
    out["dst_gap_next_out"] = _nearest(src, minute, dst, minute, "next")   # receiver next pays someone
    out["src_in_24h"] = _count_in_window(dst, minute, src, minute - DAY, minute)
    out["src_out_24h"] = _count_in_window(src, minute, src, minute - DAY, minute)
    out["dst_in_24h"] = _count_in_window(dst, minute, dst, minute, minute + DAY)
    out["dst_out_24h"] = _count_in_window(src, minute, dst, minute, minute + DAY)
    # Share of an account's activity that is outgoing: near 0.5 means money in, money out.
    for side, ids in (("src", src), ("dst", dst)):
        total = out_txn[ids] + in_txn[ids]
        out[f"{side}_relay_ratio"] = out_txn[ids] / np.maximum(total, 1)
    return out[RAW + GRAPH]
