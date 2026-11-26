"""Builders for small, clearly synthetic SEC data sets and price series."""

from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from insider_radar import db, ingest  # noqa: E402

SUBMISSION_COLUMNS = [
    "ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DATE_OF_ORIG_SUB",
    "NO_SECURITIES_OWNED", "NOT_SUBJECT_SEC16", "FORM3_HOLDING_REPORTED",
    "FORM4_TRANS_REPORTED", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
    "ISSUERTRADINGSYMBOL", "REMARKS", "AFF10B5ONE",
]
OWNER_COLUMNS = [
    "ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP",
    "RPTOWNER_TITLE", "RPTOWNER_TXT", "RPTOWNER_STREET1", "RPTOWNER_STREET2",
    "RPTOWNER_CITY", "RPTOWNER_STATE", "RPTOWNER_ZIPCODE", "RPTOWNER_STATE_DESC",
    "FILE_NUMBER",
]
TRANS_COLUMNS = [
    "ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "SECURITY_TITLE_FN",
    "TRANS_DATE", "TRANS_DATE_FN", "DEEMED_EXECUTION_DATE", "DEEMED_EXECUTION_DATE_FN",
    "TRANS_FORM_TYPE", "TRANS_CODE", "EQUITY_SWAP_INVOLVED", "EQUITY_SWAP_TRANS_CD_FN",
    "TRANS_TIMELINESS", "TRANS_TIMELINESS_FN", "TRANS_SHARES", "TRANS_SHARES_FN",
    "TRANS_PRICEPERSHARE", "TRANS_PRICEPERSHARE_FN", "TRANS_ACQUIRED_DISP_CD",
    "TRANS_ACQUIRED_DISP_CD_FN", "SHRS_OWND_FOLWNG_TRANS", "SHRS_OWND_FOLWNG_TRANS_FN",
    "VALU_OWND_FOLWNG_TRANS", "VALU_OWND_FOLWNG_TRANS_FN", "DIRECT_INDIRECT_OWNERSHIP",
    "DIRECT_INDIRECT_OWNERSHIP_FN", "NATURE_OF_OWNERSHIP", "NATURE_OF_OWNERSHIP_FN",
]


def sec_format(day: str) -> str:
    """2024-03-05 -> 05-MAR-2024, the format the SEC publishes."""
    return date.fromisoformat(day).strftime("%d-%b-%Y").upper()


def filing(
    filed: str,
    owner: int,
    *,
    issuer: int = 1000,
    ticker: str = "TEST",
    name: str = "Testco Inc",
    relationship: str = "Officer",
    code: str = "P",
    acq: str = "A",
    shares: float = 1000,
    price: float = 50.0,
    form: str = "4",
    plan: str = "0",
    extra_owners: tuple[tuple[int, str], ...] = (),
    swap: str = "0",
) -> dict:
    return dict(locals())


def write_dataset(path: Path, filings: list[dict], *, nested: bool = False, with_plan_flag: bool = True) -> Path:
    """Write filings as a quarterly zip with the three tables the loader reads."""
    subs, owners, trans = [], [], []
    for number, f in enumerate(filings, start=1):
        accession = f"0000000000-24-{number:06d}"
        row = dict.fromkeys(SUBMISSION_COLUMNS, "")
        row.update(
            ACCESSION_NUMBER=accession, FILING_DATE=sec_format(f["filed"]),
            PERIOD_OF_REPORT=sec_format(f["filed"]), DOCUMENT_TYPE=f["form"],
            ISSUERCIK=f"{f['issuer']:010d}", ISSUERNAME=f["name"],
            ISSUERTRADINGSYMBOL=f["ticker"], AFF10B5ONE=f["plan"],
        )
        subs.append(row)
        for cik, relationship in ((f["owner"], f["relationship"]),) + tuple(f["extra_owners"]):
            row = dict.fromkeys(OWNER_COLUMNS, "")
            row.update(
                ACCESSION_NUMBER=accession, RPTOWNERCIK=f"{cik:010d}",
                RPTOWNERNAME=f"Insider {cik}", RPTOWNER_RELATIONSHIP=relationship,
            )
            owners.append(row)
        row = dict.fromkeys(TRANS_COLUMNS, "")
        row.update(
            ACCESSION_NUMBER=accession, NONDERIV_TRANS_SK=str(number), SECURITY_TITLE="Common Stock",
            TRANS_DATE=sec_format(f["filed"]), TRANS_FORM_TYPE="4", TRANS_CODE=f["code"],
            EQUITY_SWAP_INVOLVED=f["swap"], TRANS_SHARES=str(f["shares"]),
            TRANS_PRICEPERSHARE=str(f["price"]), TRANS_ACQUIRED_DISP_CD=f["acq"],
            DIRECT_INDIRECT_OWNERSHIP="D",
        )
        trans.append(row)

    sub_columns = SUBMISSION_COLUMNS if with_plan_flag else SUBMISSION_COLUMNS[:-1]
    tables = {
        "SUBMISSION": pd.DataFrame(subs, columns=sub_columns),
        "REPORTINGOWNER": pd.DataFrame(owners, columns=OWNER_COLUMNS),
        "NONDERIV_TRANS": pd.DataFrame(trans, columns=TRANS_COLUMNS),
    }
    prefix = "2024q1_form345/" if nested else ""
    with zipfile.ZipFile(path, "w") as archive:
        for table, frame in tables.items():
            archive.writestr(f"{prefix}{table}.tsv", frame.to_csv(sep="\t", index=False))
    return path


class FakePrices:
    """In-memory price source that counts how often it is asked."""

    def __init__(self, series: dict[str, pd.Series]):
        self.series = series
        self.calls: list[str] = []

    def history(self, ticker, start, end):
        self.calls.append(ticker)
        data = self.series.get(ticker)
        if data is None:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]), name="adj_close")
        return data[(data.index >= pd.Timestamp(start)) & (data.index <= pd.Timestamp(end))]


def business_days(start: str, periods: int, values) -> pd.Series:
    index = pd.bdate_range(start, periods=periods)
    return pd.Series(list(values), index=index, dtype=float, name="adj_close")


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def load(conn, tmp_path):
    """Write filings to a zip and ingest them; returns the connection."""

    def _load(filings: list[dict], **options):
        ingest.load(conn, write_dataset(tmp_path / "2024q1_form345.zip", filings, **options))
        return conn

    return _load
