"""Turn Form 4 purchases into cluster-buy events.

A cluster is: at least `min_insiders` different insiders at one company whose
purchase filings became public within `window_days` of each other.

Everything is keyed on the FILING date, the day the market could see the
trade. Using the trade date would let a backtest act on news before it was
public.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

_TICKER = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")
_NOT_TICKERS = {"NONE", "NA", "N/A", "NULL", "TBD"}

PURCHASE_COLUMNS = [
    "issuer_cik", "issuer_name", "ticker", "insider_cik", "insider_name",
    "role", "title", "filing_date", "first_trade", "shares", "value",
]
CLUSTER_COLUMNS = [
    "issuer_cik", "issuer_name", "ticker", "trigger_date", "start_date", "end_date",
    "n_insiders", "n_filings", "filing_days", "total_value", "insiders",
]


@dataclass(frozen=True)
class ClusterParams:
    min_insiders: int = 3
    window_days: int = 30
    min_value: float = 10_000.0          # dollars per insider per filing day
    roles: tuple[str, ...] = ("officer", "director")
    exclude_10b5_1: bool = True          # drop trades flagged as pre-scheduled plans


def normalize_ticker(raw: object) -> str | None:
    """Clean the symbol printed on a filing; None when it is not usable."""
    if not isinstance(raw, str):
        return None
    symbol = raw.strip().upper()
    if symbol in _NOT_TICKERS:
        return None
    # Filers write things like "NYSE: ABC", "ABC, ABC.WS" or "(ABC)".
    symbol = symbol.split(":")[-1].strip()
    symbol = re.split(r"[,;/\s]+", symbol)[0].strip("()[]\"'")
    if symbol in _NOT_TICKERS or not _TICKER.match(symbol):
        return None
    return symbol


def _roles(relationship: object) -> set[str]:
    if not isinstance(relationship, str):
        return set()
    return {part.strip().lower() for part in relationship.split(",") if part.strip()}


def load_purchases(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Raw open-market purchase lines and the owners of those filings.

    Kept: original Form 4s (amendments would double count), code P, acquired,
    positive shares and price, not an equity swap.
    """
    lines = pd.read_sql_query(
        """
        SELECT t.accession, s.filing_date, s.issuer_cik, s.issuer_name, s.ticker,
               s.aff10b5one, t.trans_date, t.shares, t.price
        FROM trans t
        JOIN submissions s ON s.accession = t.accession
        WHERE s.document_type = '4'
          AND t.trans_code = 'P'
          AND t.acq_disp = 'A'
          AND t.shares > 0
          AND t.price > 0
          AND COALESCE(t.equity_swap, 0) = 0
        """,
        conn,
    )
    owners = pd.read_sql_query(
        """
        SELECT o.accession, o.owner_cik, o.owner_name, o.relationship, o.title
        FROM owners o
        WHERE o.accession IN (
            SELECT DISTINCT t.accession FROM trans t WHERE t.trans_code = 'P'
        )
        """,
        conn,
    )
    return lines, owners


def qualifying_purchases(lines: pd.DataFrame, owners: pd.DataFrame, params: ClusterParams) -> pd.DataFrame:
    """One row per (company, insider, filing day) that passes the filters."""
    if lines.empty or owners.empty:
        return pd.DataFrame(columns=PURCHASE_COLUMNS)

    lines = lines.copy()
    if params.exclude_10b5_1:
        lines = lines[lines["aff10b5one"].fillna(0).astype(int) != 1]

    # One insider per filing. A joint filing (a director plus their trust,
    # say) reports one economic decision, so it counts once: the lowest CIK
    # among owners holding an allowed role stands for the filing.
    owners = owners.copy()
    owners["roles"] = owners["relationship"].map(_roles)
    wanted = set(params.roles)
    owners = owners[owners["roles"].map(lambda held: bool(held & wanted))]
    if owners.empty:
        return pd.DataFrame(columns=PURCHASE_COLUMNS)
    owners["cik_number"] = pd.to_numeric(owners["owner_cik"], errors="coerce")
    owners = owners.sort_values(["accession", "cik_number"]).drop_duplicates("accession")
    owners["role"] = owners["roles"].map(lambda held: "/".join(sorted(held & wanted)))

    merged = lines.merge(
        owners[["accession", "owner_cik", "owner_name", "role", "title"]], on="accession", how="inner"
    )
    if merged.empty:
        return pd.DataFrame(columns=PURCHASE_COLUMNS)
    merged["value"] = merged["shares"] * merged["price"]

    grouped = (
        merged.groupby(["issuer_cik", "owner_cik", "filing_date"], as_index=False)
        .agg(
            issuer_name=("issuer_name", "last"),
            ticker=("ticker", "last"),
            insider_name=("owner_name", "last"),
            role=("role", "last"),
            title=("title", "last"),
            first_trade=("trans_date", "min"),
            shares=("shares", "sum"),
            value=("value", "sum"),
        )
        .rename(columns={"owner_cik": "insider_cik"})
    )
    grouped = grouped[grouped["value"] >= params.min_value].copy()
    grouped["ticker"] = grouped["ticker"].map(normalize_ticker)
    grouped["filing_date"] = pd.to_datetime(grouped["filing_date"])
    grouped["first_trade"] = pd.to_datetime(grouped["first_trade"])
    return grouped[PURCHASE_COLUMNS].sort_values(["issuer_cik", "filing_date"]).reset_index(drop=True)


def _summarize(members: pd.DataFrame, trigger: pd.Timestamp) -> dict:
    latest = members.sort_values("filing_date").iloc[-1]
    tickers = members["ticker"].dropna()
    names = members.sort_values("filing_date")["insider_name"].fillna("Unknown").drop_duplicates()
    return {
        "issuer_cik": latest["issuer_cik"],
        "issuer_name": latest["issuer_name"],
        "ticker": tickers.iloc[-1] if len(tickers) else None,
        "trigger_date": trigger,
        "start_date": members["filing_date"].min(),
        "end_date": members["filing_date"].max(),
        "n_insiders": members["insider_cik"].nunique(),
        "n_filings": len(members),
        # 1 means everyone filed on the same day: often an offering or placement
        # the insiders took part in together, not separate decisions to buy.
        "filing_days": members["filing_date"].nunique(),
        "total_value": float(members["value"].sum()),
        "insiders": "; ".join(names),
    }


def _as_timestamp(day: int) -> pd.Timestamp:
    return pd.Timestamp(np.datetime64(int(day), "D"))


def find_clusters(purchases: pd.DataFrame, params: ClusterParams) -> pd.DataFrame:
    """Scan each company's purchase filings in date order.

    On each filing day, count the different insiders who filed in the trailing
    window. The first day that count reaches the threshold is the trigger: the
    earliest day an observer could have known. The cluster keeps absorbing
    filings while the count stays at or above the threshold, so one burst of
    buying gives one event, not one per extra filing.
    """
    if purchases.empty:
        return pd.DataFrame(columns=CLUSTER_COLUMNS)

    # Most companies never have enough different buyers; skip them up front.
    buyers = purchases.groupby("issuer_cik")["insider_cik"].transform("nunique")
    candidates = purchases[buyers >= params.min_insiders]
    found = []
    for _, company in candidates.groupby("issuer_cik", sort=False):
        company = company.sort_values("filing_date")
        days = company["filing_date"].to_numpy().astype("datetime64[D]").astype("int64")
        insiders = company["insider_cik"].to_numpy()
        # Rows are date-sorted, so a cluster's members are one contiguous slice.
        trigger, first_row, last_row = None, 0, 0
        for day in np.unique(days):
            low = int(np.searchsorted(days, day - params.window_days, side="right"))
            high = int(np.searchsorted(days, day, side="right"))
            crowded = len(set(insiders[low:high])) >= params.min_insiders
            if crowded:
                if trigger is None:
                    trigger, first_row = day, low
                last_row = high
            elif trigger is not None:
                found.append(_summarize(company.iloc[first_row:last_row], _as_timestamp(trigger)))
                trigger = None
        if trigger is not None:
            found.append(_summarize(company.iloc[first_row:last_row], _as_timestamp(trigger)))

    clusters = pd.DataFrame(found, columns=CLUSTER_COLUMNS)
    clusters["trigger_date"] = clusters["trigger_date"].astype(purchases["filing_date"].dtype)
    return clusters.sort_values("trigger_date", ascending=False).reset_index(drop=True)


def members_of(purchases: pd.DataFrame, cluster: pd.Series) -> pd.DataFrame:
    """The purchase rows that make up one cluster."""
    mask = (
        (purchases["issuer_cik"] == cluster["issuer_cik"])
        & (purchases["filing_date"] >= cluster["start_date"])
        & (purchases["filing_date"] <= cluster["end_date"])
    )
    return purchases[mask].sort_values("filing_date")


def run(conn: sqlite3.Connection, params: ClusterParams | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convenience: database -> (qualifying purchases, clusters)."""
    params = params or ClusterParams()
    lines, owners = load_purchases(conn)
    purchases = qualifying_purchases(lines, owners, params)
    return purchases, find_clusters(purchases, params)
