"""Find and download the SEC's quarterly Insider Transactions Data Sets.

The SEC asks automated clients to identify themselves and to stay under
10 requests per second. Set SEC_USER_AGENT to something like
"Your Name your.email@example.com" before downloading.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
# The folder in the download path has changed over time, so links are read
# from the index page instead of being built from a pattern.
_LINK = re.compile(r'href="([^"]*?/(\d{4}q[1-4])_form345\.zip)"', re.IGNORECASE)
_QUARTER = re.compile(r"^\d{4}q[1-4]$")
PAUSE_SECONDS = 0.25  # 4 requests per second, well under the SEC's limit of 10


class MissingUserAgent(RuntimeError):
    pass


def user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if not value:
        raise MissingUserAgent(
            "Set SEC_USER_AGENT to your name and contact email, for example:\n"
            '  export SEC_USER_AGENT="Jane Doe jane@example.com"\n'
            "The SEC rejects automated requests that do not identify themselves."
        )
    return value


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"})
    return s


def parse_index(html: str) -> dict[str, str]:
    """Map quarter ("2024q1") to its absolute download URL."""
    found: dict[str, str] = {}
    for href, quarter in _LINK.findall(html):
        url = href if href.startswith("http") else "https://www.sec.gov" + href
        found[quarter.lower()] = url
    return found


def list_datasets(http: requests.Session) -> dict[str, str]:
    response = http.get(INDEX_URL, timeout=60)
    response.raise_for_status()
    datasets = parse_index(response.text)
    if not datasets:
        raise RuntimeError(f"No data set links found on {INDEX_URL}; the page layout may have changed.")
    return datasets


def quarters_between(first: str, last: str) -> list[str]:
    """Inclusive list of quarters, e.g. ("2023q4", "2024q2") -> 2023q4, 2024q1, 2024q2."""
    for q in (first, last):
        if not _QUARTER.match(q):
            raise ValueError(f"Bad quarter {q!r}; expected a form like 2024q1")
    year, quarter = int(first[:4]), int(first[5])
    end = (int(last[:4]), int(last[5]))
    out = []
    while (year, quarter) <= end:
        out.append(f"{year}q{quarter}")
        year, quarter = (year, quarter + 1) if quarter < 4 else (year + 1, 1)
    return out


def download(quarters: list[str], dest: str | Path, http: requests.Session | None = None) -> list[Path]:
    """Download the given quarters into dest, skipping files already there."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    http = http or session()
    available = list_datasets(http)
    paths = []
    for quarter in quarters:
        if quarter not in available:
            print(f"{quarter}: not published yet, skipped")
            continue
        path = dest / f"{quarter}_form345.zip"
        if not path.exists():
            time.sleep(PAUSE_SECONDS)
            response = http.get(available[quarter], timeout=300)
            response.raise_for_status()
            partial = path.with_suffix(".part")
            partial.write_bytes(response.content)
            partial.rename(path)
            print(f"{quarter}: downloaded {len(response.content) / 1e6:.1f} MB")
        paths.append(path)
    return paths
