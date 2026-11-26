"""Load one quarterly SEC data set (zip or unzipped folder) into SQLite.

Only three of the eight tables are needed: SUBMISSION (one row per filing),
REPORTINGOWNER (who filed) and NONDERIV_TRANS (Table I stock transactions).
"""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_TRUE = {"1", "true", "y", "yes"}
_FALSE = {"0", "false", "n", "no"}


def read_table(source: Path, name: str) -> pd.DataFrame:
    """Read NAME.tsv as strings. A zip may nest the files inside a folder."""
    options = dict(sep="\t", dtype=str, keep_default_na=False, quoting=3, encoding="utf-8")
    if source.is_dir():
        return pd.read_csv(source / f"{name}.tsv", **options)
    with zipfile.ZipFile(source) as archive:
        matches = [n for n in archive.namelist() if n.rsplit("/", 1)[-1].upper() == f"{name}.TSV"]
        if not matches:
            raise FileNotFoundError(f"{name}.tsv not found in {source.name}")
        with archive.open(matches[0]) as handle:
            return pd.read_csv(handle, **options)


def sec_date(values: pd.Series) -> pd.Series:
    """DD-MON-YYYY (as published) -> YYYY-MM-DD, None when unparseable."""
    parsed = pd.to_datetime(values, format="%d-%b-%Y", errors="coerce")
    return parsed.dt.strftime("%Y-%m-%d").astype(object).where(parsed.notna(), None)


def flag(values: pd.Series) -> pd.Series:
    """Text flag -> 1 / 0 / None (None = not reported)."""
    lowered = values.str.strip().str.lower()
    out = pd.Series([None] * len(values), index=values.index, dtype=object)
    out[lowered.isin(_TRUE)] = 1
    out[lowered.isin(_FALSE)] = 0
    return out


def number(values: pd.Series) -> pd.Series:
    parsed = pd.to_numeric(values, errors="coerce")
    return parsed.astype(object).where(parsed.notna(), None)


def text(values: pd.Series) -> pd.Series:
    stripped = values.str.strip()
    return stripped.astype(object).where(stripped != "", None)


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """A column, or empty strings when an older data set does not have it."""
    if name in frame:
        return frame[name]
    return pd.Series([""] * len(frame), index=frame.index, dtype=str)


def _insert(conn: sqlite3.Connection, table: str, frame: pd.DataFrame) -> None:
    columns = ", ".join(frame.columns)
    marks = ", ".join("?" for _ in frame.columns)
    rows = frame.astype(object).where(frame.notna(), None).itertuples(index=False, name=None)
    conn.executemany(f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({marks})", rows)


def load(conn: sqlite3.Connection, source: str | Path) -> int:
    """Load one data set. Safe to run twice: rows are replaced, not duplicated.

    Returns the number of filings loaded.
    """
    source = Path(source)

    sub = read_table(source, "SUBMISSION")
    submissions = pd.DataFrame(
        {
            "accession": sub["ACCESSION_NUMBER"].str.strip(),
            "filing_date": sec_date(sub["FILING_DATE"]),
            "period": sec_date(_column(sub, "PERIOD_OF_REPORT")),
            "document_type": sub["DOCUMENT_TYPE"].str.strip().str.upper(),
            "issuer_cik": sub["ISSUERCIK"].str.strip().str.lstrip("0"),
            "issuer_name": text(_column(sub, "ISSUERNAME")),
            "ticker": text(_column(sub, "ISSUERTRADINGSYMBOL")),
            "aff10b5one": flag(_column(sub, "AFF10B5ONE")),
        }
    )
    submissions = submissions[submissions["filing_date"].notna()]

    own = read_table(source, "REPORTINGOWNER")
    owners = pd.DataFrame(
        {
            "accession": own["ACCESSION_NUMBER"].str.strip(),
            "owner_cik": own["RPTOWNERCIK"].str.strip().str.lstrip("0"),
            "owner_name": text(_column(own, "RPTOWNERNAME")),
            "relationship": text(_column(own, "RPTOWNER_RELATIONSHIP")),
            "title": text(_column(own, "RPTOWNER_TITLE")),
        }
    ).drop_duplicates(["accession", "owner_cik"])

    tr = read_table(source, "NONDERIV_TRANS")
    trans = pd.DataFrame(
        {
            "accession": tr["ACCESSION_NUMBER"].str.strip(),
            "sk": pd.to_numeric(tr["NONDERIV_TRANS_SK"], errors="coerce"),
            "security_title": text(_column(tr, "SECURITY_TITLE")),
            "trans_date": sec_date(_column(tr, "TRANS_DATE")),
            "trans_code": text(_column(tr, "TRANS_CODE")),
            "equity_swap": flag(_column(tr, "EQUITY_SWAP_INVOLVED")),
            "shares": number(_column(tr, "TRANS_SHARES")),
            "price": number(_column(tr, "TRANS_PRICEPERSHARE")),
            "acq_disp": text(_column(tr, "TRANS_ACQUIRED_DISP_CD")),
            "ownership": text(_column(tr, "DIRECT_INDIRECT_OWNERSHIP")),
        }
    )
    trans = trans[trans["sk"].notna()].astype({"sk": "int64"})

    with conn:
        _insert(conn, "submissions", submissions)
        _insert(conn, "owners", owners)
        _insert(conn, "trans", trans)
        conn.execute(
            "INSERT OR REPLACE INTO loaded_files (name, loaded_at, filings) VALUES (?, ?, ?)",
            (source.name, datetime.now(timezone.utc).isoformat(timespec="seconds"), len(submissions)),
        )
    return len(submissions)
