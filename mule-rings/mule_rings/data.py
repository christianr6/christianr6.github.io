"""Load IBM's synthetic AML transactions and the labeled laundering patterns.

Data: "IBM Transactions for Anti Money Laundering (AML)" on Kaggle, generated
by IBM's AMLworld simulator. Every transaction is synthetic. Download
HI-Small_Trans.csv and HI-Small_Patterns.txt into data/.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CSV_COLUMNS = [
    "timestamp", "from_bank", "from_account", "to_bank", "to_account",
    "amount_received", "receiving_currency", "amount_paid", "payment_currency",
    "payment_format", "is_laundering",
]
TIME_FORMAT = "%Y/%m/%d %H:%M"


@dataclass(frozen=True)
class Pattern:
    """One labeled laundering attempt: a ring of transactions."""
    number: int
    kind: str                 # FAN-OUT, CYCLE, SCATTER-GATHER, ...
    keys: frozenset[str]      # transaction keys, see transaction_key()


def read_transactions(path: str | Path) -> pd.DataFrame:
    """One row per transaction, sorted by time, with integer account ids.

    Adds: ts (Timestamp), minute (int, minutes since the first transaction),
    src / dst (int codes for bank+account), key (to match the patterns file).
    """
    text = {name: str for name in ("from_bank", "from_account", "to_bank", "to_account")}
    df = pd.read_csv(path, header=0, names=CSV_COLUMNS, dtype=text)
    df["ts"] = pd.to_datetime(df["timestamp"], format=TIME_FORMAT)
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    df["minute"] = ((df["ts"] - df["ts"].iloc[0]).dt.total_seconds() // 60).astype("int64")

    # The same account number can exist at two banks, so an account is bank + number.
    sender = df["from_bank"] + "_" + df["from_account"]
    receiver = df["to_bank"] + "_" + df["to_account"]
    codes, names = pd.factorize(pd.concat([sender, receiver], ignore_index=True))
    df["src"] = codes[: len(df)]
    df["dst"] = codes[len(df):]
    df.attrs["accounts"] = np.asarray(names, dtype=object)
    df["key"] = transaction_key(df["timestamp"], sender, receiver, df["amount_paid"])
    df["is_laundering"] = df["is_laundering"].astype("int8")
    return df


def transaction_key(timestamp, sender, receiver, amount_paid) -> pd.Series:
    """A string that identifies a transaction in both files (they share no id column)."""
    amount = pd.Series(amount_paid).astype(float).map("{:.2f}".format)
    return pd.Series(timestamp).astype(str) + "|" + pd.Series(sender).astype(str) + "|" + \
        pd.Series(receiver).astype(str) + "|" + amount


def read_patterns(path: str | Path) -> list[Pattern]:
    """Parse the BEGIN/END blocks of the patterns file."""
    patterns, kind, keys = [], None, []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith("BEGIN LAUNDERING ATTEMPT"):
            kind = line.split("-", 1)[1].split(":")[0].strip()
            keys = []
        elif line.startswith("END LAUNDERING ATTEMPT"):
            if kind and keys:
                patterns.append(Pattern(len(patterns) + 1, kind, frozenset(keys)))
            kind = None
        elif kind and line:
            parts = line.split(",")
            if len(parts) >= 8:
                stamp, from_bank, from_account, to_bank, to_account = parts[:5]
                amount_paid = parts[7]
                keys.append(
                    f"{stamp}|{from_bank}_{from_account}|{to_bank}_{to_account}|{float(amount_paid):.2f}"
                )
    return patterns
