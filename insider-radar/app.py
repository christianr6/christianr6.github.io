"""Streamlit dashboard: streamlit run app.py"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from insider_radar import backtest as bt
from insider_radar import clusters as cl
from insider_radar import db
from insider_radar.prices import PriceCache, YahooChart

DB_PATH = Path(os.environ.get("INSIDER_RADAR_DB", db.DEFAULT_DB))
HORIZON_NAMES = {21: "1 month", 63: "3 months", 126: "6 months"}

st.set_page_config(page_title="Insider cluster-buy radar", page_icon="📡", layout="wide")


# ---------- data ----------

@st.cache_resource
def connection(path: str):
    return db.connect(path, same_thread=False)


def data_version(path: str) -> str:
    """Changes when filings are loaded, but not when the price cache grows."""
    count, latest = connection(path).execute("SELECT COUNT(*), MAX(loaded_at) FROM loaded_files").fetchone()
    return f"{count}:{latest}"


@st.cache_data(show_spinner="Scanning filings…")
def scan(path: str, version: str, params: cl.ClusterParams):
    """Purchases and clusters for one rule setting. `version` busts the cache on new data."""
    return cl.run(connection(path), params)


@st.cache_data
def coverage(path: str, version: str):
    row = connection(path).execute(
        "SELECT COUNT(*), MIN(filing_date), MAX(filing_date) FROM submissions WHERE document_type = '4'"
    ).fetchone()
    return {"form4s": row[0], "first": row[1], "last": row[2]}


def price_cache() -> PriceCache:
    return PriceCache(connection(str(DB_PATH)), YahooChart())


# ---------- charts ----------

def series_color() -> str:
    """One series per chart, so one hue: the blue slot, stepped for the active theme."""
    try:
        return "#338ced" if st.context.theme.type == "dark" else "#257de0"
    except Exception:
        return "#257de0"


def _hover(base: alt.Chart, x: str, y: str, tooltip: list) -> alt.LayerChart:
    """Crosshair that snaps to the nearest x, a ringed dot on the line, and a tooltip."""
    nearest = alt.selection_point(nearest=True, on="pointerover", fields=[x], empty=False)
    rule = (
        base.mark_rule(strokeWidth=1, color="#9c9c9c")
        .encode(x=x, opacity=alt.condition(nearest, alt.value(1), alt.value(0)), tooltip=tooltip)
        .add_params(nearest)
    )
    dot = (
        base.mark_point(size=90, filled=True, color=series_color(), stroke="white", strokeWidth=2)
        .encode(x=x, y=y, opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
    )
    return rule + dot


def price_chart(prices: pd.Series, trigger: pd.Timestamp) -> alt.LayerChart:
    frame = prices.rename("close").rename_axis("date").reset_index()
    base = alt.Chart(frame)
    line = base.mark_line(strokeWidth=2, color=series_color(), strokeJoin="round", strokeCap="round").encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("close:Q", title="Adjusted close ($)", scale=alt.Scale(zero=False)),
    )
    marker = pd.DataFrame({"date": [trigger], "label": ["Cluster public"]})
    trigger_rule = alt.Chart(marker).mark_rule(strokeWidth=1.5, color="#666666").encode(x="date:T")
    trigger_text = (
        alt.Chart(marker)
        .mark_text(align="left", dx=6, dy=-4, baseline="top", color="#666666", fontSize=12)
        .encode(x="date:T", y=alt.value(0), text="label")
    )
    tooltip = [alt.Tooltip("close:Q", title="Adj. close", format="$,.2f"), alt.Tooltip("date:T", title="Date")]
    return (line + trigger_rule + trigger_text + _hover(base, "date", "close", tooltip)).properties(height=320)


def path_chart(path: pd.DataFrame) -> alt.LayerChart:
    base = alt.Chart(path)
    zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(strokeWidth=1, color="#9c9c9c").encode(y="y:Q")
    line = base.mark_line(strokeWidth=2, color=series_color(), strokeJoin="round", strokeCap="round").encode(
        x=alt.X("day:Q", title="Trading days since entry"),
        y=alt.Y("mean_abnormal:Q", title="Mean return vs. benchmark", axis=alt.Axis(format="+.1%")),
    )
    tooltip = [
        alt.Tooltip("mean_abnormal:Q", title="Vs. benchmark", format="+.2%"),
        alt.Tooltip("day:Q", title="Trading day"),
    ]
    return (zero + line + _hover(base, "day", "mean_abnormal", tooltip)).properties(height=320)


# ---------- page ----------

st.title("Insider cluster-buy radar")
st.caption("Flags companies where several officers or directors bought their own stock in a short span.")

if not DB_PATH.exists():
    st.warning("No data loaded yet.")
    st.markdown(
        "Load SEC filings first, then refresh this page:\n"
        "```bash\n"
        'export SEC_USER_AGENT="Your Name you@example.com"\n'
        "python -m insider_radar download 2023q1 2026q3\n"
        "python -m insider_radar ingest\n"
        "```"
    )
    st.stop()

version = data_version(str(DB_PATH))
covered = coverage(str(DB_PATH), version)
if not covered["form4s"]:
    st.warning("The database has no Form 4 filings yet. Run the ingest command.")
    st.stop()

with st.sidebar:
    st.header("Cluster rule")
    defaults = cl.ClusterParams()
    min_insiders = st.slider("Insiders required", 2, 8, defaults.min_insiders)
    window_days = st.slider("Within this many days", 7, 90, defaults.window_days)
    min_value = st.number_input("Minimum purchase per insider ($)", 0, 10_000_000, int(defaults.min_value), step=5_000)
    include_10pct = st.checkbox("Count 10% owners too", value=False, help="Funds and other large holders. Off by default.")
    drop_plans = st.checkbox(
        "Drop pre-scheduled plan trades",
        value=True,
        help="Rule 10b5-1 trades are set up in advance, so they say little about what the insider thinks today.",
    )
    spread_only = st.checkbox(
        "Skip same-day bursts",
        value=False,
        help="Drop clusters where every insider filed on one day. Those are often a shared offering, not separate decisions.",
    )
    st.caption(
        f"{covered['form4s']:,} Form 4 filings, {covered['first']} to {covered['last']}. "
        "Dates are filing dates: the day each trade became public."
    )

params = cl.ClusterParams(
    min_insiders=min_insiders,
    window_days=window_days,
    min_value=float(min_value),
    roles=("officer", "director") + (("tenpercentowner",) if include_10pct else ()),
    exclude_10b5_1=drop_plans,
)
purchases, clusters = scan(str(DB_PATH), version, params)
if spread_only:
    clusters = clusters[clusters["filing_days"] > 1].reset_index(drop=True)

radar_tab, backtest_tab, method_tab = st.tabs(["Radar", "Backtest", "Method"])

with radar_tab:
    last_day = pd.Timestamp(covered["last"])
    recent = clusters[clusters["trigger_date"] > last_day - timedelta(days=90)] if not clusters.empty else clusters
    a, b, c = st.columns(3)
    a.metric("Clusters found", f"{len(clusters):,}")
    b.metric("In the latest 90 days of data", f"{len(recent):,}")
    c.metric("Qualifying purchases", f"{len(purchases):,}")

    if clusters.empty:
        st.info("No clusters match this rule. Loosen it in the sidebar.")
    else:
        st.subheader("Clusters, newest first")
        st.caption("Select a row to see who bought and what the stock did.")
        table = clusters[["trigger_date", "ticker", "issuer_name", "n_insiders", "filing_days", "total_value", "insiders"]].copy()
        table["total_value"] = table["total_value"].round()
        picked = st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "trigger_date": st.column_config.DateColumn("Became a cluster", format="YYYY-MM-DD"),
                "ticker": "Ticker",
                "issuer_name": "Company",
                "n_insiders": st.column_config.NumberColumn("Insiders"),
                "filing_days": st.column_config.NumberColumn("Filing days", help="1 = everyone filed on the same day"),
                "total_value": st.column_config.NumberColumn("Bought ($)", format="localized"),
                "insiders": "Who",
            },
        )
        rows = picked.selection.rows if picked and picked.selection else []
        chosen = clusters.iloc[rows[0] if rows else 0]

        st.subheader(f"{chosen['issuer_name']}" + (f" ({chosen['ticker']})" if chosen["ticker"] else ""))
        members = cl.members_of(purchases, chosen).assign(
            title=lambda rows: rows["title"].fillna(""), value=lambda rows: rows["value"].round()
        )
        st.dataframe(
            members[["filing_date", "insider_name", "role", "title", "shares", "value"]],
            hide_index=True,
            width="stretch",
            column_config={
                "filing_date": st.column_config.DateColumn("Filed", format="YYYY-MM-DD"),
                "insider_name": "Insider",
                "role": "Role",
                "title": "Title",
                "shares": st.column_config.NumberColumn("Shares", format="localized"),
                "value": st.column_config.NumberColumn("Value ($)", format="localized"),
            },
        )
        if not chosen["ticker"]:
            st.info("No usable ticker on these filings, so there is no price chart.")
        else:
            start = (chosen["start_date"] - timedelta(days=90)).date()
            end = (chosen["trigger_date"] + timedelta(days=200)).date()
            try:
                history = price_cache().history(chosen["ticker"], start, end)
            except Exception as problem:  # network trouble should not take the page down
                history = pd.Series(dtype=float)
                st.warning(f"Could not load prices: {problem}")
            if history.empty:
                st.info(f"No prices found for {chosen['ticker']}. It may be delisted or use a different symbol.")
            else:
                st.markdown(f"**{chosen['ticker']} adjusted close**")
                st.altair_chart(price_chart(history, chosen["trigger_date"]), width="stretch")

with backtest_tab:
    st.markdown(
        "For every cluster: buy at the close of the first trading day **after** it became public, "
        "hold, and compare with the S&P 500 (SPY) over the same dates."
    )
    key = ("backtest", params, version, spread_only)
    if clusters.empty:
        st.info("No clusters to test.")
    else:
        tickers = clusters["ticker"].nunique()
        if st.button(f"Run backtest on {len(clusters):,} clusters", type="primary"):
            bar = st.progress(0.0, text=f"Loading prices for {tickers:,} tickers (cached after the first run)…")
            cache = price_cache()
            events = bt.event_returns(clusters, cache, progress=lambda done, total: bar.progress(done / total))
            bar.empty()
            st.session_state[key] = (events, bt.average_path(events, cache))

        if key in st.session_state:
            events, path = st.session_state[key]
            summary = bt.summarize(events)
            priced = int((events["status"] == "ok").sum())
            st.caption(
                f"{priced:,} of {len(events):,} clusters had prices. The rest are left out, "
                "which makes the averages look better than reality (see Method)."
            )
            for column, row in zip(st.columns(len(summary)), summary.itertuples(index=False)):
                name = HORIZON_NAMES.get(row.horizon_days, f"{row.horizon_days} days")
                if row.n:
                    column.metric(
                        f"{name}: mean vs. SPY",
                        f"{row.mean_abnormal:+.1%}",
                        help=f"{row.n:,} clusters. {row.hit_rate:.0%} beat SPY. Median {row.median_abnormal:+.1%}.",
                    )
                    column.caption(f"n = {row.n:,} · {row.hit_rate:.0%} beat SPY")
                else:
                    column.metric(f"{name}: mean vs. SPY", "n/a")
                    column.caption("No finished holding periods yet")

            if not path.empty:
                st.markdown(f"**Average return vs. SPY after a cluster** ({int(path['n'].iloc[0]):,} clusters with a full 6 months of prices)")
                st.altair_chart(path_chart(path), width="stretch")

            st.dataframe(
                summary,
                hide_index=True,
                width="stretch",
                column_config={
                    "horizon_days": "Trading days held",
                    "n": "Clusters",
                    "mean_return": st.column_config.NumberColumn("Mean return", format="percent"),
                    "mean_abnormal": st.column_config.NumberColumn("Mean vs. SPY", format="percent"),
                    "median_abnormal": st.column_config.NumberColumn("Median vs. SPY", format="percent"),
                    "hit_rate": st.column_config.NumberColumn("Beat SPY", format="percent"),
                    "t_stat": st.column_config.NumberColumn("t-stat", format="%.2f"),
                },
            )
            st.download_button(
                "Download per-cluster returns (CSV)",
                events.to_csv(index=False).encode(),
                file_name="cluster_returns.csv",
                mime="text/csv",
            )

with method_tab:
    st.markdown(
        f"""
**What counts as a purchase**

- An original Form 4 (amendments are skipped so nothing is counted twice).
- Transaction code P, an open-market or private purchase. Grants, option exercises and gifts are ignored.
- Filed by an officer or director. A joint filing counts as one insider.
- At least ${params.min_value:,.0f} per insider per filing day.

**What counts as a cluster**

- {params.min_insiders} or more different insiders at one company filing within {params.window_days} days.
- The cluster date is the day the last required filing became public, not the trade date.

**Why the backtest flatters the strategy**

- **Survivorship:** delisted stocks have no prices and drop out. Those are often the losers.
- **Risk:** returns are compared with SPY only. Small, cheap stocks are riskier than SPY.
- **Overlap:** clusters bunch up in sell-offs, so the t-stat overstates confidence.
- **Costs:** none are charged, and many of these stocks trade thinly.

Data: SEC Insider Transactions Data Sets (Forms 3, 4, 5). Prices: Yahoo Finance, unofficial.
This is a research tool, not investment advice.
"""
    )
