"""Event study: what did the stock do after a cluster became public?

For each cluster:
    entry  = close of the first trading day AFTER the trigger filing date
             (Form 4s often arrive after the bell, so the same-day close
             may not have been tradable)
    return = close[entry + h trading days] / close[entry] - 1
    abnormal return = stock return - benchmark return over the same dates

Known limits, stated so the numbers are not over-read:
  * Delisted tickers have no prices at the source and drop out, which
    flatters the average (survivorship bias).
  * "Abnormal" is market-adjusted only. Small, cheap stocks carry more risk
    than the benchmark and that is not corrected for.
  * Clusters overlap in time, so the t-statistic overstates confidence.
  * No trading costs. Many of these stocks are thinly traded.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from .prices import PriceSource, span_for

HORIZONS = (21, 63, 126)  # trading days: about 1, 3 and 6 months
MAX_ENTRY_DELAY_DAYS = 7  # skip when no price exists within a week of the trigger


def _entry_position(prices: pd.Series, trigger: pd.Timestamp) -> int | None:
    position = int(prices.index.searchsorted(trigger, side="right"))
    if position >= len(prices):
        return None
    if (prices.index[position] - trigger).days > MAX_ENTRY_DELAY_DAYS:
        return None
    return position


def event_returns(
    clusters: pd.DataFrame,
    prices: PriceSource,
    horizons: tuple[int, ...] = HORIZONS,
    benchmark: str = "SPY",
    progress=None,
) -> pd.DataFrame:
    """One row per cluster with stock, benchmark and abnormal return per horizon.

    `status` says why a cluster has no returns: no_ticker, no_prices or ok.
    """
    columns = ["issuer_name", "ticker", "trigger_date", "entry_date", "status"]
    for h in horizons:
        columns += [f"ret_{h}", f"bench_{h}", f"abn_{h}"]
    if clusters.empty:
        return pd.DataFrame(columns=columns)

    start, end = span_for(clusters["trigger_date"], max(horizons))
    market = prices.history(benchmark, start, end)
    if market.empty:
        raise RuntimeError(f"No prices for benchmark {benchmark}; cannot compute abnormal returns.")

    rows = []
    total = len(clusters)
    for count, cluster in enumerate(clusters.itertuples(index=False), start=1):
        if progress:
            progress(count, total)
        trigger = pd.Timestamp(cluster.trigger_date)
        row = {
            "issuer_name": cluster.issuer_name,
            "ticker": cluster.ticker,
            "trigger_date": trigger,
            "entry_date": pd.NaT,
            "status": "ok",
        }
        if not isinstance(cluster.ticker, str) or not cluster.ticker:
            row["status"] = "no_ticker"
            rows.append(row)
            continue
        one_start, one_end = span_for(pd.Series([trigger]), max(horizons))
        stock = prices.history(cluster.ticker, one_start, one_end)
        entry = _entry_position(stock, trigger) if not stock.empty else None
        if entry is None:
            row["status"] = "no_prices"
            rows.append(row)
            continue
        entry_day = stock.index[entry]
        row["entry_date"] = entry_day
        for h in horizons:
            if entry + h >= len(stock):
                continue  # the holding period has not finished yet (or data ends)
            exit_day = stock.index[entry + h]
            market_in = market.asof(entry_day)
            market_out = market.asof(exit_day)
            if not (np.isfinite(market_in) and np.isfinite(market_out)):
                continue
            stock_return = stock.iloc[entry + h] / stock.iloc[entry] - 1
            market_return = market_out / market_in - 1
            row[f"ret_{h}"] = stock_return
            row[f"bench_{h}"] = market_return
            row[f"abn_{h}"] = stock_return - market_return
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def summarize(events: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Per horizon: sample size, mean and median abnormal return, hit rate, t-stat."""
    rows = []
    for h in horizons:
        abnormal = events.get(f"abn_{h}", pd.Series(dtype=float)).dropna().astype(float)
        raw = events.get(f"ret_{h}", pd.Series(dtype=float)).dropna().astype(float)
        n = len(abnormal)
        spread = abnormal.std(ddof=1) if n > 1 else float("nan")
        rows.append(
            {
                "horizon_days": h,
                "n": n,
                "mean_return": raw.mean() if n else float("nan"),
                "mean_abnormal": abnormal.mean() if n else float("nan"),
                "median_abnormal": abnormal.median() if n else float("nan"),
                "hit_rate": (abnormal > 0).mean() if n else float("nan"),
                # t = mean / (sd / sqrt(n)); treats events as independent, which they are not
                "t_stat": abnormal.mean() / (spread / math.sqrt(n)) if n > 1 and spread > 0 else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def average_path(
    events: pd.DataFrame,
    prices: PriceSource,
    max_days: int = max(HORIZONS),
    benchmark: str = "SPY",
) -> pd.DataFrame:
    """Mean cumulative abnormal return by trading day since entry.

    Only clusters with a full `max_days` of prices are used, so every point on
    the line averages the same set of events.
    """
    usable = events[(events["status"] == "ok") & events["entry_date"].notna()]
    if usable.empty:
        return pd.DataFrame(columns=["day", "mean_abnormal", "n"])
    start, end = span_for(usable["trigger_date"], max_days)
    market = prices.history(benchmark, start, end)
    paths = []
    for event in usable.itertuples(index=False):
        one_start, one_end = span_for(pd.Series([event.trigger_date]), max_days)
        stock = prices.history(event.ticker, one_start, one_end)
        entry = int(stock.index.searchsorted(event.entry_date))
        window = stock.iloc[entry : entry + max_days + 1]
        if len(window) < max_days + 1:
            continue
        market_window = market.reindex(window.index, method="ffill")
        if market_window.isna().any():
            continue
        relative = window.to_numpy() / window.iloc[0] - market_window.to_numpy() / market_window.iloc[0]
        paths.append(relative)
    if not paths:
        return pd.DataFrame(columns=["day", "mean_abnormal", "n"])
    stacked = np.vstack(paths)
    return pd.DataFrame(
        {"day": np.arange(max_days + 1), "mean_abnormal": stacked.mean(axis=0), "n": len(paths)}
    )


def data_through(clusters: pd.DataFrame) -> date | None:
    return None if clusters.empty else pd.Timestamp(clusters["end_date"].max()).date()
