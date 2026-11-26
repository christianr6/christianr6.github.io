# Insider cluster-buy radar

Flags companies where several officers or directors bought their own stock
within a short span, then tests whether the stock beat the market afterwards.

```
SEC bulk Form 4 files -> SQLite -> open-market buys -> cluster rule -> dashboard
                                   (code P, no plans)  (3+ insiders,    + backtest
                                                        30 days)
```

## Result on real data

Run on 2026-11-26 over 669,110 Form 4 filings from 2023-01-03 to 2026-09-30
(prices through 2026-11-25), default rule: 1,778 clusters, 1,535 with prices.

| Held | Clusters | Mean vs. SPY | Median vs. SPY | Beat SPY | t-stat |
|---|---|---|---|---|---|
| 1 month | 1,535 | +0.6% | -1.0% | 46% | 1.14 |
| 3 months | 1,492 | -0.3% | -3.3% | 43% | -0.30 |
| 6 months | 1,394 | -1.6% | -7.4% | 40% | -1.25 |

**No edge.** The average cluster did not beat the S&P 500, the typical one
lagged it, and nothing is statistically distinguishable from zero. Against a
small-cap benchmark (IWM) the means are +0.8%, +0.4% and +0.1%, still with
fewer than half the clusters ahead. The biases listed below all push these
numbers up, so the true picture is no better.

Two things the real data showed:

- **Same-day bursts are a different animal.** In 324 clusters every insider
  filed on one day, often a shared offering. Those lagged SPY by 6.7% on
  average over 6 months. The `filing_days` column marks them.
- **A few rockets carry the mean.** Returns ranged from -100% to +380% over
  6 months, so the median and the share that beat SPY say more than the mean.

## Run it

```bash
pip install -r requirements.txt

# The SEC rejects automated requests that do not identify themselves.
export SEC_USER_AGENT="Your Name you@example.com"

python -m insider_radar download 2023q1 2026q3   # about 10 MB per quarter
python -m insider_radar ingest                   # loads data/raw/*.zip into data/insider.db
python -m insider_radar clusters                 # newest clusters in the terminal
python -m insider_radar backtest                 # event study (fetches prices once, then cached)

streamlit run app.py                             # dashboard
python -m pytest                                 # tests
```

## The rule

A **purchase** counts when all of these hold:

- It is on an original Form 4. Amendments are skipped so nothing counts twice.
- Transaction code is P (open-market or private purchase) and shares were acquired.
- The filer is an officer or director. Ten-percent owners are off by default.
- It is not flagged as a Rule 10b5-1 plan trade, which is scheduled in advance.
- It is worth at least $10,000 per insider per filing day.

A **cluster** is 3 or more different insiders at one company whose purchase
filings became public within 30 days of each other. A joint filing counts as
one insider. One burst of buying is one cluster, however long it runs.

Every threshold is a slider in the dashboard and a flag on the command line.

## The backtest

Everything is keyed on the **filing date**, the day the trade became public.
Using the trade date would let the test act on news nobody could see yet.

- **Entry:** close of the first trading day after the cluster's trigger date.
- **Return:** `close[entry + h] / close[entry] - 1` for h = 21, 63 and 126 trading days.
- **Abnormal return:** stock return minus SPY's return over the same dates.
- **Reported:** sample size, mean, median, share that beat SPY, and a t-statistic.

## Why the numbers will flatter the strategy

- **Survivorship:** delisted stocks have no prices at the source and drop out.
  Those are often the losers. The backtest prints how many clusters it lost.
- **Risk:** small, cheap stocks are riskier than SPY, and that is not adjusted for.
- **Overlap:** clusters bunch up during sell-offs, so the t-statistic overstates confidence.
- **Costs:** none are charged, and many of these stocks trade thinly.

## Data sources

- **Filings:** SEC [Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets),
  quarterly flat files extracted from Forms 3, 4 and 5, January 2006 onward.
  The 10b5-1 flag is present from the 2023 files on.
- **Prices:** Yahoo Finance's chart endpoint. It is unofficial and can change.
  Prices sit behind a small interface in `insider_radar/prices.py`, so another
  source can be swapped in. Cached prices are not refreshed after later splits
  or dividends; delete the `prices` and `price_ranges` tables to refetch.

## Layout

| File | Job |
|---|---|
| `insider_radar/sec.py` | find and download the quarterly files |
| `insider_radar/ingest.py` | load them into SQLite |
| `insider_radar/clusters.py` | filters and the cluster rule |
| `insider_radar/prices.py` | price source and cache |
| `insider_radar/backtest.py` | event study |
| `app.py` | Streamlit dashboard |

This is a research project, not investment advice.
