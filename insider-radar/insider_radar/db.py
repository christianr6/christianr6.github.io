"""SQLite storage. One file holds filings, transactions and the price cache."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path("data") / "insider.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    accession     TEXT PRIMARY KEY,
    filing_date   TEXT NOT NULL,          -- YYYY-MM-DD, the day the filing became public
    period        TEXT,
    document_type TEXT NOT NULL,          -- 3, 4, 5, 3/A, 4/A, 5/A
    issuer_cik    TEXT NOT NULL,
    issuer_name   TEXT,
    ticker        TEXT,                   -- as printed on the filing, not cleaned
    aff10b5one    INTEGER                 -- 1 / 0, NULL when the data set predates the flag
);
CREATE INDEX IF NOT EXISTS submissions_issuer ON submissions (issuer_cik, filing_date);

CREATE TABLE IF NOT EXISTS owners (
    accession    TEXT NOT NULL,
    owner_cik    TEXT NOT NULL,
    owner_name   TEXT,
    relationship TEXT,                    -- e.g. "Director,Officer"
    title        TEXT,
    PRIMARY KEY (accession, owner_cik)
);

CREATE TABLE IF NOT EXISTS trans (
    accession      TEXT NOT NULL,
    sk             INTEGER NOT NULL,
    security_title TEXT,
    trans_date     TEXT,
    trans_code     TEXT,                  -- P = open market or private purchase
    equity_swap    INTEGER,
    shares         REAL,
    price          REAL,
    acq_disp       TEXT,                  -- A = acquired, D = disposed
    ownership      TEXT,                  -- D = direct, I = indirect
    PRIMARY KEY (accession, sk)
);
CREATE INDEX IF NOT EXISTS trans_code ON trans (trans_code);

CREATE TABLE IF NOT EXISTS loaded_files (
    name      TEXT PRIMARY KEY,
    loaded_at TEXT NOT NULL,
    filings   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    ticker    TEXT NOT NULL,
    date      TEXT NOT NULL,
    adj_close REAL NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS price_ranges (
    ticker     TEXT PRIMARY KEY,
    start_date TEXT NOT NULL,             -- range already requested from the source
    end_date   TEXT NOT NULL
);
"""


def connect(path: str | Path = DEFAULT_DB, *, same_thread: bool = True) -> sqlite3.Connection:
    """Open (and if needed create) the database.

    Pass same_thread=False when the connection is shared across threads, as
    Streamlit does between reruns.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=same_thread)
    conn.executescript(SCHEMA)
    return conn
