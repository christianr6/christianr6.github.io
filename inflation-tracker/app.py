"""Streamlit dashboard: streamlit run app.py"""

from __future__ import annotations

import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from inflation import basket, bls, items, ocr

HERE = Path(__file__).parent
HISTORY_START = 2023
GROUPS = {
    "Housing": ["rent", "fixed", "shelter", "utilities", "household"],
    "Food": ["groceries", "restaurants", "alcohol"],
    "Getting around": ["gasoline", "vehicles", "transport_services"],
    "Everything else": ["medical", "education", "communication", "recreation", "clothing", "other"],
}

st.set_page_config(page_title="Personal inflation tracker", page_icon="🧾", layout="wide")


def dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


YOU = "#338ced" if dark() else "#257de0"          # categorical slot 1
OFFICIAL = "#e76624" if dark() else "#f47230"     # categorical slot 2
MUTED = "#9c9c9c" if dark() else "#666666"


@st.cache_data(ttl=6 * 3600, show_spinner="Loading price data from BLS…")
def load(series: tuple[str, ...]) -> pd.DataFrame:
    return bls.Bls(cache_dir=HERE / "data" / "bls").fetch(list(series), HISTORY_START)


def rate_chart(mine: pd.Series, official: pd.Series) -> alt.Chart:
    # Keep the months with no figure as empty rows, so the line breaks there instead of bridging the gap.
    mine, official = mine.asfreq("MS"), official.asfreq("MS")
    frame = pd.concat([
        pd.DataFrame({"month": mine.index, "rate": mine.values, "who": "You"}),
        pd.DataFrame({"month": official.index, "rate": official.values, "who": "Official CPI"}),
    ])
    scale = alt.Scale(domain=["You", "Official CPI"], range=[YOU, OFFICIAL])
    base = alt.Chart(frame).encode(
        x=alt.X("month:T", title=None),
        y=alt.Y("rate:Q", title="12-month inflation", axis=alt.Axis(format="+.0%", tickCount=6)),
        color=alt.Color("who:N", scale=scale, legend=alt.Legend(title=None, orient="bottom")),
        tooltip=[alt.Tooltip("who:N", title=" "), alt.Tooltip("rate:Q", format="+.1%", title="12-month rate"),
                 alt.Tooltip("month:T", format="%B %Y", title="Month")],
    )
    line = base.mark_line(strokeWidth=2, strokeJoin="round", strokeCap="round")
    dots = base.transform_filter("isValid(datum.rate)").mark_point(size=60, filled=True, stroke="white", strokeWidth=1.5)
    return (line + dots).properties(height=320)


def contribution_chart(table: pd.DataFrame) -> alt.LayerChart:
    table = table.assign(points=table["points"] * 100)     # fractions -> percentage points
    base = alt.Chart(table).encode(
        y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False)),
        x=alt.X("points:Q", title="Percentage points added to your rate", axis=alt.Axis(format="+.1f", tickCount=6)),
        tooltip=[alt.Tooltip("label:N", title=" "), alt.Tooltip("share:Q", format=".1%", title="Share of spending"),
                 alt.Tooltip("change:Q", format="+.1%", title="Price change"),
                 alt.Tooltip("points:Q", format="+.2f", title="Points added")],
    )
    bars = base.mark_bar(color=YOU, size=16, cornerRadiusEnd=4)
    labels = base.mark_text(align="left", dx=5, color=MUTED).encode(text=alt.Text("points:Q", format="+.2f"))
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=MUTED, strokeWidth=1).encode(x="x:Q")
    return (zero + bars + labels).properties(height=alt.Step(30))


st.title("Personal inflation tracker")
st.caption("Official inflation is the average household's. Enter your own spending to see yours.")

try:
    prices = load(tuple(basket.SERIES))
except (bls.BlsError, Exception) as problem:   # noqa: BLE001 - show any data failure plainly
    st.error(f"Could not load price data. {problem}")
    st.markdown(
        "Without a key, BLS allows 25 requests a day per network address. A free key raises that to 500: "
        "register at https://data.bls.gov/registrationEngine/ and set `BLS_API_KEY`."
    )
    st.stop()

ratios = basket.price_ratios(prices)
official = basket.official_rate(ratios)
usable = {c.key for c in basket.CATEGORIES if c.key in ratios}

rate_tab, items_tab, method_tab = st.tabs(["Your rate", "Your prices", "Method"])

with rate_tab:
    sample = pd.read_csv(HERE / "sample" / "spending.csv").set_index("category")["amount"].to_dict()
    headline = st.container()      # filled in below, so the answer sits above the inputs on a phone
    spending: dict[str, float] = {}
    editor = st.expander("Monthly spending ($). The starting numbers are a made-up example; replace them with yours.",
                         expanded=True)
    for column, (group, keys) in zip(editor.columns(len(GROUPS)), GROUPS.items()):
        with column:
            st.caption(group)
            for key in keys:
                category = basket.BY_KEY[key]
                if key not in usable:
                    st.number_input(category.label, value=0, disabled=True, help="BLS returned no data for this line.", key=key)
                    continue
                spending[key] = float(st.number_input(
                    category.label, min_value=0, value=int(sample.get(key, 0)), step=10, help=category.hint or None, key=key))
    when = editor.radio(
        "These amounts describe my spending",
        ["then", "now"], horizontal=True,
        format_func={"then": "a year ago", "now": "today"}.get,
        help="It changes the formula. See the Method tab.",
    )

    if sum(spending.values()) <= 0:
        st.info("Enter spending in at least one category.")
    else:
        share = basket.shares(spending)
        mine = basket.personal_rate(share, ratios, when)
        month = basket.latest_common_month(mine, official)
        gap = (mine[month] - official[month]) * 100
        a, b, c = headline.columns(3)
        a.metric("Your inflation", f"{mine[month]:+.1%}")
        b.metric("Official CPI", f"{official[month]:+.1%}")
        c.metric("Difference", f"{gap:+.1f} points")
        latest_published = prices[basket.ALL_ITEMS].dropna().index.max()
        note = f"12 months to {month:%B %Y}."
        if latest_published > month:
            note += (f" BLS has published {latest_published:%B %Y}, but it has no figure for "
                     f"{latest_published - pd.DateOffset(years=1):%B %Y}, so that month has no 12-month comparison.")
        headline.caption(note)

        st.markdown("**Where your inflation comes from**")
        table = basket.contributions(share, ratios, month)
        st.altair_chart(contribution_chart(table), width="stretch")
        st.caption("Share of your spending × that category's price change. The bars add up to your rate when the amounts are from a year ago.")

        st.markdown("**You vs. official CPI over time**")
        st.altair_chart(rate_chart(mine, official), width="stretch")
        st.caption("Same spending mix applied to each month. A break in the line is a month BLS did not publish.")

        st.dataframe(
            table[["label", "share", "change", "points"]].assign(points=lambda t: t["points"] * 100),
            hide_index=True, width="stretch",
            column_config={"label": "Category",
                           "share": st.column_config.NumberColumn("Share of spending", format="percent"),
                           "change": st.column_config.NumberColumn("Price change", format="percent"),
                           "points": st.column_config.NumberColumn("Points added", format="%+.2f")},
        )

with items_tab:
    st.markdown(
        "BLS publishes a U.S. average price each month for a short list of exact items, like a dozen large eggs. "
        "Upload what you paid to compare. Columns: `date, item, price, quantity, unit`."
    )
    uploaded = st.file_uploader("Purchases (CSV)", type="csv")
    source = uploaded if uploaded is not None else HERE / "sample" / "purchases.csv"
    if uploaded is None:
        st.caption("Showing a made-up example file. The BLS prices beside it are real.")
    try:
        purchases = items.read_purchases(source)
        item_prices = load(tuple(items.SERIES))
        compared = items.compare(purchases, item_prices)
    except (ValueError, bls.BlsError) as problem:
        st.error(str(problem))
        compared = None
    if compared is not None:
        reasons = {"ok": "", "no_match": "Not on the BLS list", "bad_unit": "Unit does not convert",
                   "no_bls_price": "No BLS price that month"}
        st.dataframe(
            compared.assign(note=compared["status"].map(reasons)).drop(columns="status"),
            hide_index=True, width="stretch",
            column_config={"date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"), "item": "You bought",
                           "bls_item": "BLS item", "unit": "Per",
                           "you_paid": st.column_config.NumberColumn("You paid", format="$%.2f"),
                           "bls_average": st.column_config.NumberColumn("U.S. average", format="$%.2f"),
                           "gap": st.column_config.NumberColumn("Difference", format="percent"), "note": "Note"},
        )
        moved = items.changes(compared)
        if not moved.empty:
            st.markdown("**Price change between your first and last purchase**")
            st.dataframe(moved, hide_index=True, width="stretch", column_config={
                "bls_item": "Item", "first": "From", "last": "To",
                "your_change": st.column_config.NumberColumn("Your price", format="percent"),
                "bls_change": st.column_config.NumberColumn("U.S. average", format="percent")})

    st.divider()
    st.markdown("**Start from a receipt photo**")
    photo = st.file_uploader("Receipt photo", type=["png", "jpg", "jpeg"])
    if photo is not None:
        with tempfile.NamedTemporaryFile(suffix=Path(photo.name).suffix) as handle:
            handle.write(photo.getvalue())
            handle.flush()
            try:
                draft = ocr.read_receipt(handle.name)
            except ocr.OcrUnavailable as problem:
                draft = None
                st.warning(str(problem))
        if draft is not None:
            rows = pd.DataFrame(draft["lines"] or [{"item": "", "price": 0.0}])
            rows.insert(0, "date", draft["date"] or "")
            rows["quantity"], rows["unit"] = 1.0, ""
            st.caption("This is a draft. Fix any misread names and prices, add quantity and unit, then download it.")
            edited = st.data_editor(rows, num_rows="dynamic", hide_index=True, width="stretch")
            st.download_button("Download as purchases CSV", edited.to_csv(index=False).encode(),
                               file_name="purchases.csv", mime="text/csv")

with method_tab:
    st.markdown(
        """
**Category prices** are the official CPI-U indexes for the U.S. city average, not seasonally adjusted.
Your rate re-weights them by your spending.

| Your amounts describe | Formula | Name |
|---|---|---|
| A year ago | `sum(share × price_now / price_then) − 1` | Laspeyres |
| Today | `1 / sum(share × price_then / price_now) − 1` | Paasche |

A fixed payment, such as a fixed-rate mortgage, counts as a 0% price change.

**What this cannot see**

- **Your prices.** It uses national category averages. Your rent, your grocery store and your city differ.
- **Your substitutions.** If you switched to cheaper brands, your true cost rose less than this says.
- **Owning a home.** Official CPI prices owned homes at what they would rent for. If you own with a fixed
  mortgage, put the payment under "Mortgage or other fixed payment", not under shelter.

**Item prices** are BLS average prices: a national average for narrowly defined items. BLS notes they measure
price levels and are not designed to measure price change, so treat the comparison as a rough guide.
A different brand, size or store explains most gaps.

Data: U.S. Bureau of Labor Statistics. Category weights shown as defaults are from BLS's relative importance
table for December 2025.
"""
    )
