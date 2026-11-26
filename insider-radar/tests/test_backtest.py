import numpy as np
import pandas as pd
import pytest
from conftest import FakePrices, business_days

from insider_radar import backtest as bt


def cluster(trigger: str, ticker="TEST", name="Testco Inc") -> dict:
    day = pd.Timestamp(trigger)
    return {
        "issuer_cik": "1000", "issuer_name": name, "ticker": ticker, "trigger_date": day,
        "start_date": day, "end_date": day, "n_insiders": 3, "n_filings": 3,
        "total_value": 150_000.0, "insiders": "A; B; C",
    }


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# 300 business days from Mon 2024-01-01. Stock climbs 1 per day from 100; market is flat at 400.
STOCK = business_days("2024-01-01", 300, 100 + np.arange(300))
FLAT = business_days("2024-01-01", 300, [400.0] * 300)


def test_entry_is_the_first_trading_day_after_the_trigger():
    # Trigger Wed 2024-01-03 -> entry Thu 2024-01-04, never the trigger day itself.
    events = bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": STOCK, "SPY": FLAT}))
    assert events.iloc[0]["entry_date"] == pd.Timestamp("2024-01-04")


def test_a_friday_trigger_enters_on_monday():
    events = bt.event_returns(frame(cluster("2024-01-05")), FakePrices({"TEST": STOCK, "SPY": FLAT}))
    assert events.iloc[0]["entry_date"] == pd.Timestamp("2024-01-08")


def test_return_is_measured_in_trading_days_from_entry():
    events = bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": STOCK, "SPY": FLAT}))
    # Entry is index 3 (price 103); 21 trading days later the price is 124.
    assert events.iloc[0]["ret_21"] == pytest.approx(124 / 103 - 1)
    assert events.iloc[0]["ret_63"] == pytest.approx(166 / 103 - 1)


def test_abnormal_return_subtracts_the_benchmark():
    market = business_days("2024-01-01", 300, 400 * 1.001 ** np.arange(300))
    events = bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": STOCK, "SPY": market}))
    row = events.iloc[0]
    assert row["bench_21"] == pytest.approx(1.001**21 - 1)
    assert row["abn_21"] == pytest.approx(row["ret_21"] - row["bench_21"])


def test_stock_that_only_matches_the_market_has_zero_abnormal_return():
    same = business_days("2024-01-01", 300, 50 * 1.002 ** np.arange(300))
    events = bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": same, "SPY": same * 8}))
    assert events.iloc[0]["abn_126"] == pytest.approx(0.0, abs=1e-12)


def test_unfinished_holding_periods_are_left_blank():
    short = business_days("2024-01-01", 40, 100 + np.arange(40))
    events = bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": short, "SPY": FLAT}))
    row = events.iloc[0]
    assert row["status"] == "ok"
    assert not np.isnan(row["ret_21"])
    assert np.isnan(row["ret_63"]) and np.isnan(row["ret_126"])


def test_clusters_without_prices_are_reported_not_hidden():
    clusters = frame(cluster("2024-01-03"), cluster("2024-01-03", ticker="GONE"), cluster("2024-01-03", ticker=None))
    events = bt.event_returns(clusters, FakePrices({"TEST": STOCK, "SPY": FLAT}))
    assert list(events["status"]) == ["ok", "no_prices", "no_ticker"]


def test_a_stock_with_no_price_near_the_trigger_is_skipped():
    late = business_days("2024-03-01", 200, 100 + np.arange(200))  # first price two months after trigger
    events = bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": late, "SPY": FLAT}))
    assert events.iloc[0]["status"] == "no_prices"


def test_missing_benchmark_is_an_error():
    with pytest.raises(RuntimeError, match="benchmark"):
        bt.event_returns(frame(cluster("2024-01-03")), FakePrices({"TEST": STOCK}))


def test_summary_statistics():
    events = pd.DataFrame({"abn_21": [0.10, 0.20, -0.06], "ret_21": [0.12, 0.22, -0.04]})
    row = bt.summarize(events, horizons=(21,)).iloc[0]
    assert row["n"] == 3
    assert row["mean_abnormal"] == pytest.approx(0.08)
    assert row["median_abnormal"] == pytest.approx(0.10)
    assert row["hit_rate"] == pytest.approx(2 / 3)
    spread = np.std([0.10, 0.20, -0.06], ddof=1)
    assert row["t_stat"] == pytest.approx(0.08 / (spread / np.sqrt(3)))


def test_summary_of_nothing_is_empty_not_a_crash():
    row = bt.summarize(pd.DataFrame(columns=["abn_21", "ret_21"]), horizons=(21,)).iloc[0]
    assert row["n"] == 0 and np.isnan(row["mean_abnormal"])


def test_average_path_starts_at_zero_and_matches_the_horizon_return():
    prices = FakePrices({"TEST": STOCK, "SPY": FLAT})
    events = bt.event_returns(frame(cluster("2024-01-03")), prices)
    path = bt.average_path(events, prices, max_days=126)
    assert len(path) == 127
    assert path.iloc[0]["mean_abnormal"] == pytest.approx(0.0)
    assert path.iloc[126]["mean_abnormal"] == pytest.approx(events.iloc[0]["abn_126"])
    assert path.iloc[21]["mean_abnormal"] == pytest.approx(events.iloc[0]["abn_21"])
