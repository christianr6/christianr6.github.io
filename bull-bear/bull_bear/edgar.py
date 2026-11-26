"""Fetch a company's latest 10-K and reported financials from SEC EDGAR.

The SEC asks automated clients to identify themselves and to stay under
10 requests per second. Set SEC_USER_AGENT to something like
"Your Name your.email@example.com".
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
PAUSE_SECONDS = 0.25


class EdgarError(RuntimeError):
    pass


@dataclass(frozen=True)
class Filing:
    cik: int
    company: str
    ticker: str
    accession: str      # 0000320193-26-000026
    filed: str          # YYYY-MM-DD
    period: str         # fiscal year end, YYYY-MM-DD
    url: str


def user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if not value:
        raise EdgarError(
            "Set SEC_USER_AGENT to your name and contact email, for example:\n"
            '  export SEC_USER_AGENT="Jane Doe jane@example.com"\n'
            "The SEC rejects automated requests that do not identify themselves."
        )
    return value


class Edgar:
    """Small EDGAR client with an on-disk cache, so reruns cost no requests."""

    def __init__(self, cache_dir: str | Path = "data/cache", http: requests.Session | None = None):
        self.cache_dir = Path(cache_dir)
        self.http = http
        self._last_request = 0.0

    def _get(self, url: str) -> bytes:
        if self.http is None:
            self.http = requests.Session()
            self.http.headers.update({"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"})
        wait = PAUSE_SECONDS - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.http.get(url, timeout=120)
        self._last_request = time.monotonic()
        if response.status_code == 404:
            raise EdgarError(f"Not found on EDGAR: {url}")
        response.raise_for_status()
        return response.content

    def _cached(self, name: str, url: str, fresh: bool = False) -> bytes:
        path = self.cache_dir / name
        if path.exists() and not fresh:
            return path.read_bytes()
        content = self._get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return content

    def lookup(self, ticker: str) -> tuple[int, str]:
        """Ticker -> (CIK, company name)."""
        wanted = ticker.strip().upper().replace(".", "-")
        table = json.loads(self._cached("company_tickers.json", TICKERS_URL))
        for row in table.values():
            if row["ticker"].upper() == wanted:
                return int(row["cik_str"]), row["title"]
        raise EdgarError(f"No SEC registrant found for ticker {ticker!r}.")

    def latest_annual_report(self, ticker: str) -> Filing:
        """The most recent original 10-K (amendments are skipped)."""
        cik, company = self.lookup(ticker)
        recent = json.loads(self._get(SUBMISSIONS_URL.format(cik=cik)))["filings"]["recent"]
        for index, form in enumerate(recent["form"]):
            if form == "10-K":
                accession = recent["accessionNumber"][index]
                return Filing(
                    cik=cik,
                    company=company,
                    ticker=ticker.strip().upper(),
                    accession=accession,
                    filed=recent["filingDate"][index],
                    period=recent["reportDate"][index],
                    url=DOCUMENT_URL.format(
                        cik=cik, accession=accession.replace("-", ""), document=recent["primaryDocument"][index]
                    ),
                )
        raise EdgarError(
            f"{company} has no recent 10-K on EDGAR. Foreign companies file a 20-F instead, which is not supported."
        )

    def document(self, filing: Filing) -> str:
        raw = self._cached(f"{filing.cik}/{filing.accession}.htm", filing.url)
        return raw.decode("utf-8", errors="replace")

    def company_facts(self, filing: Filing) -> dict:
        # Keyed by accession so a new 10-K pulls fresh numbers.
        raw = self._cached(f"{filing.cik}/{filing.accession}.facts.json", FACTS_URL.format(cik=filing.cik))
        return json.loads(raw)
