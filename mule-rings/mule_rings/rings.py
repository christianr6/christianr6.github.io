"""From flagged transactions to rings, and a check against the answer key.

A flagged transaction is an arrow between two accounts. Accounts joined by
flagged arrows form a group; each group of three or more accounts is reported
as one suspected ring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .data import Pattern

MIN_ACCOUNTS = 3
CAUGHT_SHARE = 0.5      # a labeled ring counts as caught when half its transactions are flagged


def find(flagged: pd.DataFrame) -> pd.DataFrame:
    """Add a `ring` column: a ring number, or -1 for arrows not in any ring.

    `flagged` needs src and dst. Self-transfers join nothing and are left out.
    """
    out = flagged.copy()
    out["ring"] = -1
    links = out[out["src"] != out["dst"]]
    if links.empty:
        return out
    accounts, codes = np.unique(np.concatenate([links["src"], links["dst"]]), return_inverse=True)
    a, b = codes[: len(links)], codes[len(links):]
    graph = coo_matrix((np.ones(len(links)), (a, b)), shape=(len(accounts), len(accounts)))
    _, component = connected_components(graph, directed=True, connection="weak")
    sizes = np.bincount(component)
    big = sizes[component[a]] >= MIN_ACCOUNTS
    # Renumber so ring 0 is the largest.
    order = {old: new for new, old in enumerate(np.argsort(-sizes)) if sizes[old] >= MIN_ACCOUNTS}
    out.loc[links.index[big], "ring"] = [order[c] for c in component[a][big]]
    return out


def summarize(with_rings: pd.DataFrame) -> pd.DataFrame:
    """One row per suspected ring: size, and how much of it is really laundering."""
    inside = with_rings[with_rings["ring"] >= 0]
    if inside.empty:
        return pd.DataFrame(columns=["ring", "accounts", "transactions", "laundering", "purity", "amount"])
    rows = []
    for ring, group in inside.groupby("ring"):
        rows.append({
            "ring": int(ring),
            "accounts": int(pd.unique(np.concatenate([group["src"], group["dst"]])).size),
            "transactions": int(len(group)),
            "laundering": int(group["is_laundering"].sum()),
            "purity": float(group["is_laundering"].mean()),
            "amount": float(group["amount_paid"].sum()),
        })
    return pd.DataFrame(rows).sort_values("ring").reset_index(drop=True)


def against_patterns(scored: pd.DataFrame, patterns: list[Pattern], min_size: int = 3) -> pd.DataFrame:
    """For each labeled ring with enough transactions in `scored`: how much was flagged.

    `scored` needs key and flagged (bool). Rings cut by the time split are
    judged only on the transactions that fall inside the scored period.
    """
    flagged_by_key = dict(zip(scored["key"], scored["flagged"]))
    rows = []
    for pattern in patterns:
        present = [key for key in pattern.keys if key in flagged_by_key]
        if len(present) < min_size:
            continue
        found = sum(bool(flagged_by_key[key]) for key in present)
        rows.append({
            "pattern": pattern.number, "kind": pattern.kind, "transactions": len(present),
            "flagged": found, "share_flagged": found / len(present),
            "caught": found / len(present) >= CAUGHT_SHARE,
        })
    return pd.DataFrame(rows, columns=["pattern", "kind", "transactions", "flagged", "share_flagged", "caught"])


def by_kind(matched: pd.DataFrame) -> pd.DataFrame:
    if matched.empty:
        return pd.DataFrame(columns=["kind", "rings", "caught", "caught_share", "mean_share_flagged"])
    table = matched.groupby("kind").agg(
        rings=("pattern", "size"), caught=("caught", "sum"), mean_share_flagged=("share_flagged", "mean")
    ).reset_index()
    table["caught_share"] = table["caught"] / table["rings"]
    return table.sort_values("caught_share", ascending=False).reset_index(drop=True)
