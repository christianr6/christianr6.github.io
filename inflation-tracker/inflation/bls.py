"""Read price series from the BLS Public Data API, with a disk cache.

Without a key the API allows 25 queries a day and 25 series per query, so
every answer is cached for a day. Set BLS_API_KEY (free registration at
https://data.bls.gov/registrationEngine/) for 500 queries a day.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

URL_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
URL_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
MAX_SERIES = {"v1": 25, "v2": 50}
CACHE_HOURS = 24


class BlsError(RuntimeError):
    pass


def parse(payload: dict) -> pd.DataFrame:
    """API answer -> table with one column per series, indexed by month.

    A month BLS did not publish arrives as "-" and becomes a missing value.
    Annual averages (period M13) are dropped.
    """
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise BlsError("BLS API: " + "; ".join(payload.get("message") or ["request failed"]))
    columns = {}
    for series in payload["Results"]["series"]:
        values = {}
        for point in series["data"]:
            period = point["period"]
            if not period.startswith("M") or period == "M13":
                continue
            month = pd.Timestamp(year=int(point["year"]), month=int(period[1:]), day=1)
            try:
                values[month] = float(point["value"])
            except ValueError:
                values[month] = float("nan")
        if values:      # an id BLS has no data for comes back empty; leave it out
            columns[series["seriesID"]] = pd.Series(values, dtype=float)
    if not columns:
        return pd.DataFrame(index=pd.DatetimeIndex([], freq="MS"))
    frame = pd.DataFrame(columns)
    frame.index = pd.DatetimeIndex(frame.index)
    # Every month from first to last, so "12 rows back" always means 12 months back.
    return frame.sort_index().asfreq("MS")


class Bls:
    def __init__(self, cache_dir: str | Path = "data/bls", http: requests.Session | None = None):
        self.cache_dir = Path(cache_dir)
        self.http = http or requests.Session()
        self.key = os.environ.get("BLS_API_KEY", "").strip()

    def _ask(self, series: list[str], start: int, end: int) -> dict:
        body = {"seriesid": series, "startyear": str(start), "endyear": str(end)}
        url = URL_V1
        if self.key:
            body["registrationkey"] = self.key
            url = URL_V2
        response = self.http.post(url, json=body, timeout=60)
        response.raise_for_status()
        return response.json()

    def fetch(self, series: list[str], start: int, end: int | None = None) -> pd.DataFrame:
        """Monthly values for the given series ids, from `start` year through `end`."""
        end = end or date.today().year
        limit = MAX_SERIES["v2" if self.key else "v1"]
        frames = []
        for offset in range(0, len(series), limit):
            chunk = sorted(series[offset : offset + limit])
            name = f"{abs(hash_ids(chunk))}_{start}_{end}.json"
            path = self.cache_dir / name
            fresh = path.exists() and time.time() - path.stat().st_mtime < CACHE_HOURS * 3600
            if fresh:
                payload = json.loads(path.read_text())
            else:
                payload = self._ask(chunk, start, end)
                frame = parse(payload)      # raises on a failed request, before anything is cached
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload))
            frames.append(parse(payload))
        return pd.concat(frames, axis=1).sort_index().asfreq("MS")


def hash_ids(ids: list[str]) -> int:
    """A stable number for a list of series ids (Python's own hash changes between runs)."""
    value = 0
    for character in ",".join(ids):
        value = (value * 131 + ord(character)) % (2**61 - 1)
    return value
