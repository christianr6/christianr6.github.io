from datetime import date

import numpy as np
import pandas as pd
from conftest import FakePrices, business_days

from insider_radar import sec
from insider_radar.prices import PriceCache, parse_yahoo_chart

SERIES = business_days("2024-01-01", 60, 100 + np.arange(60))


def test_cache_asks_the_source_once_for_a_covered_range(conn):
    source = FakePrices({"TEST": SERIES})
    cache = PriceCache(conn, source)
    first = cache.history("TEST", date(2024, 1, 1), date(2024, 2, 1))
    second = cache.history("TEST", date(2024, 1, 10), date(2024, 1, 20))
    assert source.calls == ["TEST"]
    assert first.iloc[0] == 100.0
    assert second.index.min() == pd.Timestamp("2024-01-10")


def test_cache_refetches_when_the_range_grows(conn):
    source = FakePrices({"TEST": SERIES})
    cache = PriceCache(conn, source)
    cache.history("TEST", date(2024, 1, 1), date(2024, 1, 15))
    wider = cache.history("TEST", date(2024, 1, 1), date(2024, 3, 1))
    assert source.calls == ["TEST", "TEST"]
    assert wider.index.max() > pd.Timestamp("2024-02-01")


def test_unknown_tickers_are_remembered_so_they_are_not_requested_again(conn):
    source = FakePrices({})
    cache = PriceCache(conn, source)
    assert cache.history("GONE", date(2024, 1, 1), date(2024, 2, 1)).empty
    assert cache.history("GONE", date(2024, 1, 1), date(2024, 2, 1)).empty
    assert source.calls == ["GONE"]


def test_parse_yahoo_chart_prefers_adjusted_close_and_skips_gaps():
    # 14:30 UTC opens on 2024-01-02 and 2024-01-03, New York offset -18000 s.
    payload = {"chart": {"result": [{
        "meta": {"gmtoffset": -18000},
        "timestamp": [1704205800, 1704292200],
        "indicators": {
            "quote": [{"close": [10.0, 11.0]}],
            "adjclose": [{"adjclose": [9.5, None]}],
        },
    }]}}
    series = parse_yahoo_chart(payload)
    assert list(series.index) == [pd.Timestamp("2024-01-02")]
    assert series.iloc[0] == 9.5


def test_parse_yahoo_chart_handles_an_empty_answer():
    assert parse_yahoo_chart({"chart": {"result": None, "error": {"code": "Not Found"}}}).empty


def test_index_links_are_found_in_both_download_folders():
    html = """
      <a href="https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/2026q3_form345.zip">2026 Q3</a>
      <a href="/files/structureddata/data/insider-transactions-data-sets/2024q1_form345.zip">2024 Q1</a>
    """
    found = sec.parse_index(html)
    assert found["2026q3"].endswith("/datastandardsinnovation/data/insider-transactions-data-sets/2026q3_form345.zip")
    assert found["2024q1"] == "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2024q1_form345.zip"


def test_quarters_between_crosses_year_ends():
    assert sec.quarters_between("2023q4", "2024q2") == ["2023q4", "2024q1", "2024q2"]


def test_downloads_refuse_to_run_without_a_declared_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    try:
        sec.user_agent()
    except sec.MissingUserAgent as problem:
        assert "SEC_USER_AGENT" in str(problem)
    else:
        raise AssertionError("expected MissingUserAgent")
