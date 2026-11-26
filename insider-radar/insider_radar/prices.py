"""Daily adjusted closes, with a SQLite cache in front of the source.

The source is pluggable: anything with a `history(ticker, start, end)` method
that returns a Series of adjusted closes indexed by date works. The default
reads Yahoo's chart endpoint, which is unofficial and can change or
disappear; the cache means a ticker is only requested once per date range.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import pandas as pd
import requests


class PriceSource(Protocol):
    def history(self, ticker: str, start: date, end: date) -> pd.Series:
        """Adjusted closes indexed by pandas Timestamps; empty when unknown."""
        ...


def _empty() -> pd.Series:
    return pd.Series(dtype=float, index=pd.DatetimeIndex([]), name="adj_close")


def parse_yahoo_chart(payload: dict) -> pd.Series:
    """Extract adjusted closes from a v8 chart response."""
    results = (payload.get("chart") or {}).get("result") or []
    if not results or not results[0].get("timestamp"):
        return _empty()
    result = results[0]
    offset = (result.get("meta") or {}).get("gmtoffset", 0) or 0
    indicators = result.get("indicators") or {}
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    closes = adjusted or (indicators.get("quote") or [{}])[0].get("close") or []
    # Timestamps mark the session open in UTC; shift to exchange time for the date.
    days = pd.to_datetime([t + offset for t in result["timestamp"]], unit="s").normalize()
    series = pd.Series(closes, index=days, dtype=float, name="adj_close").dropna()
    return series[~series.index.duplicated(keep="last")].sort_index()


class YahooChart:
    """Unofficial Yahoo Finance chart endpoint. No key needed."""

    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def __init__(self, pause: float = 0.3, http: requests.Session | None = None):
        self.pause = pause
        self.http = http or requests.Session()
        self.http.headers.update({"User-Agent": "insider-radar/0.1"})

    def history(self, ticker: str, start: date, end: date) -> pd.Series:
        symbol = ticker.replace(".", "-")  # BRK.B is BRK-B on Yahoo
        params = {
            "period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
            "period2": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86_400,
            "interval": "1d",
            "events": "div,splits",
        }
        for attempt in range(4):
            time.sleep(self.pause)
            response = self.http.get(self.URL.format(symbol=symbol), params=params, timeout=30)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2**attempt)
                continue
            if response.status_code >= 400:
                # 404 = unknown symbol; 400 = no data in this range (for
                # example the stock was delisted before it). Either way
                # there are no prices, which the backtest reports.
                return _empty()
            return parse_yahoo_chart(response.json())
        raise RuntimeError(f"Price source kept failing for {ticker} (last status {response.status_code})")


class PriceCache:
    """Serve prices from SQLite, calling the source only for uncovered ranges."""

    def __init__(self, conn: sqlite3.Connection, source: PriceSource):
        self.conn = conn
        self.source = source

    def _covered(self, ticker: str) -> tuple[date, date] | None:
        row = self.conn.execute(
            "SELECT start_date, end_date FROM price_ranges WHERE ticker = ?", (ticker,)
        ).fetchone()
        return (date.fromisoformat(row[0]), date.fromisoformat(row[1])) if row else None

    def history(self, ticker: str, start: date, end: date) -> pd.Series:
        # Stop at yesterday: today's bar may still be an intraday price.
        end = min(end, date.today() - timedelta(days=1))
        covered = self._covered(ticker)
        if covered is None or start < covered[0] or end > covered[1]:
            want_start = min(start, covered[0]) if covered else start
            want_end = max(end, covered[1]) if covered else end
            fetched = self.source.history(ticker, want_start, want_end)
            with self.conn:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO prices (ticker, date, adj_close) VALUES (?, ?, ?)",
                    [(ticker, day.strftime("%Y-%m-%d"), float(value)) for day, value in fetched.items()],
                )
                # Record the range even when nothing came back, so an unknown
                # or delisted ticker is not requested again on every run.
                self.conn.execute(
                    "INSERT OR REPLACE INTO price_ranges (ticker, start_date, end_date) VALUES (?, ?, ?)",
                    (ticker, want_start.isoformat(), want_end.isoformat()),
                )
        rows = self.conn.execute(
            "SELECT date, adj_close FROM prices WHERE ticker = ? AND date BETWEEN ? AND ? ORDER BY date",
            (ticker, start.isoformat(), end.isoformat()),
        ).fetchall()
        if not rows:
            return _empty()
        return pd.Series(
            [value for _, value in rows],
            index=pd.to_datetime([day for day, _ in rows]),
            dtype=float,
            name="adj_close",
        )


def span_for(dates: pd.Series, horizon_days: int) -> tuple[date, date]:
    """Calendar range that covers every event plus the longest holding period."""
    first = pd.Timestamp(dates.min()).date() - timedelta(days=10)
    last = pd.Timestamp(dates.max()).date() + timedelta(days=int(horizon_days * 1.6) + 15)
    return first, min(last, date.today())
