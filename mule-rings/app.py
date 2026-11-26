"""Streamlit dashboard over the saved study results: streamlit run app.py

Reads results/summary.json (and results/gnn.json if present), so it runs
without the 475 MB transaction file.
"""

from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RESULTS = Path(__file__).parent / "results"
FEATURE_NAMES = {
    "src_out_degree": "Sender: different accounts paid", "src_out_txn": "Sender: payments made",
    "src_in_txn": "Sender: payments received", "src_in_degree": "Sender: different payers",
    "dst_out_txn": "Receiver: payments made", "dst_out_degree": "Receiver: different accounts paid",
    "dst_in_txn": "Receiver: payments received", "dst_in_degree": "Receiver: different payers",
    "pair_txn": "Payments between this pair", "reciprocal": "Money also flows back",
    "src_gap_prev_out": "Sender: minutes since last payment", "src_gap_last_in": "Sender: minutes since money arrived",
    "dst_gap_next_out": "Receiver: minutes until it pays on", "src_in_24h": "Sender: received in prior 24h",
    "src_out_24h": "Sender: paid in prior 24h", "dst_in_24h": "Receiver: receives in next 24h",
    "dst_out_24h": "Receiver: pays in next 24h", "src_relay_ratio": "Sender: share of activity outgoing",
    "dst_relay_ratio": "Receiver: share of activity outgoing", "log_amount": "Amount",
    "payment_format": "Payment format", "payment_currency": "Payment currency",
    "receiving_currency": "Receiving currency", "hour": "Hour of day", "cross_currency": "Currency conversion",
    "self_transfer": "Transfer to self", "same_bank": "Same bank",
}
MODEL_NAMES = {"raw": "Single-transaction features", "graph": "Plus graph features", "gnn": "Graph neural network"}

st.set_page_config(page_title="Money mule ring detector", page_icon="🕸️", layout="wide")


def dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


# Categorical slots 1-3 of the palette, stepped for each theme. Fixed per model, never by rank.
SERIES = {
    "raw": "#e76624" if dark() else "#f47230",
    "graph": "#338ced" if dark() else "#257de0",
    "gnn": "#00a888" if dark() else "#00b894",
}
BLUE = SERIES["graph"]
MUTED = "#9c9c9c" if dark() else "#666666"


@st.cache_data
def load() -> tuple[dict, dict | None]:
    summary = json.loads((RESULTS / "summary.json").read_text())
    gnn_path = RESULTS / "gnn.json"
    return summary, json.loads(gnn_path.read_text()) if gnn_path.exists() else None


def precision_recall_chart(curves: dict[str, list[dict]]) -> alt.LayerChart:
    rows = [{"model": MODEL_NAMES[key], **point} for key, points in curves.items() for point in points]
    frame = pd.DataFrame(rows)
    order = [MODEL_NAMES[key] for key in curves]
    colors = alt.Scale(domain=order, range=[SERIES[key] for key in curves])
    lines = alt.Chart(frame).mark_line(strokeWidth=2, strokeJoin="round", strokeCap="round").encode(
        x=alt.X("recall:Q", title="Recall: share of laundering caught", axis=alt.Axis(format="%", tickCount=6)),
        y=alt.Y("precision:Q", title="Precision: share of flags that are right", axis=alt.Axis(format="%", tickCount=6)),
        color=alt.Color("model:N", scale=colors, legend=alt.Legend(title=None, orient="bottom")),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("precision:Q", format=".0%", title="Precision"),
                 alt.Tooltip("recall:Q", format=".0%", title="Recall")],
    )
    points = lines.mark_point(size=120, opacity=0).encode()   # generous hover targets along each line
    return (lines + points).properties(height=340)


def bars(frame: pd.DataFrame, value: str, label: str, title: str, fmt: str) -> alt.LayerChart:
    base = alt.Chart(frame).encode(
        y=alt.Y(f"{label}:N", sort=None, title=None, axis=alt.Axis(labelLimit=280, labelOverlap=False)),
        x=alt.X(f"{value}:Q", title=title, axis=alt.Axis(format=fmt, tickCount=5)),
        tooltip=[alt.Tooltip(f"{label}:N", title=" "), alt.Tooltip(f"{value}:Q", format=fmt, title=title)],
    )
    bar = base.mark_bar(color=BLUE, size=16, cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
    text = base.mark_text(align="left", dx=5, color=MUTED).encode(text=alt.Text(f"{value}:Q", format=fmt))
    return (bar + text).properties(height=alt.Step(30))


def ring_picture(ring: dict) -> str:
    """Graphviz picture of one suspected ring. Solid = really laundering, dashed = false alarm."""
    short = {}

    def name(account: str) -> str:
        return short.setdefault(account, f"{chr(65 + len(short) % 26)}{len(short) // 26 or ''}")

    lines = ["digraph ring {", "  rankdir=LR; bgcolor=transparent;",
             f'  node [shape=circle, color="{MUTED}", fontcolor="{MUTED}", fontname="Helvetica", fontsize=11];',
             f'  edge [fontname="Helvetica", fontsize=9, fontcolor="{MUTED}"];']
    for edge in ring["edges"]:
        style = f'color="{BLUE}", penwidth=2' if edge["laundering"] else f'color="{MUTED}", style=dashed'
        amount = f"{edge['amount']:,.0f} {edge['currency']}"
        lines.append(f'  "{name(edge["from"])}" -> "{name(edge["to"])}" [label="{amount}", {style}];')
    lines.append("}")
    return "\n".join(lines)


if not (RESULTS / "summary.json").exists():
    st.title("Money mule ring detector")
    st.warning("No results yet. Run `python -m mule_rings` first (see the README for the data download).")
    st.stop()

summary, gnn = load()
models = dict(summary["models"])
if gnn:
    models["gnn"] = gnn
dataset, leak, test = summary["dataset"], summary["leak"], summary["split"]["test"]
graph, raw = models["graph"]["test"], models["raw"]["test"]
ring_stats = summary["rings"]

st.title("Money mule ring detector")
st.caption(
    f"Finds laundering in {dataset['transactions']:,} synthetic bank transactions (IBM AMLworld, HI-Small) "
    "by looking at who pays whom, then groups what it flags into rings."
)

a, b, c, d = st.columns(4)
a.metric("Flags that are right", f"{graph['precision']:.0%}", help=f"{graph['caught']:,} of {graph['flagged']:,} flagged test transactions are laundering.")
b.metric("Laundering caught", f"{graph['recall']:.0%}", help=f"{graph['caught']:,} of {graph['laundering']:,} laundering transactions in the test days.")
c.metric("F1 with graph features", f"{graph['f1']:.2f}", delta=f"{graph['f1'] - raw['f1']:+.2f} vs. without", delta_color="off")
d.metric("Labeled rings caught", f"{ring_stats['labeled_caught']} of {ring_stats['labeled_in_test']}", help="A ring counts as caught when at least half of its test-day transactions are flagged.")
st.caption(
    f"Scored on the last two days ({test['transactions']:,} transactions, {test['laundering']:,} laundering) "
    "that the model never trained on. Guessing would be right about 0.1% of the time."
)

models_tab, rings_tab, method_tab = st.tabs(["Models", "Rings", "Method"])

with models_tab:
    st.markdown("**Precision vs. recall on the test days**")
    st.altair_chart(precision_recall_chart({key: value["curve"] for key, value in models.items()}), width="stretch")
    table = pd.DataFrame([
        {"Model": MODEL_NAMES[key], "Average precision": value["test"]["average_precision"],
         "Precision": value["test"]["precision"], "Recall": value["test"]["recall"], "F1": value["test"]["f1"],
         "Flagged": value["test"]["flagged"]}
        for key, value in models.items()
    ])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Average precision": st.column_config.NumberColumn(format="%.3f"),
        "Precision": st.column_config.NumberColumn(format="percent"),
        "Recall": st.column_config.NumberColumn(format="percent"),
        "F1": st.column_config.NumberColumn(format="%.2f"),
        "Flagged": st.column_config.NumberColumn(format="localized"),
    })
    st.caption("The threshold for each model was chosen on the validation days, then applied unchanged to the test days.")

    st.markdown("**What the graph model relies on** (share of total gain, top 12)")
    importance = pd.DataFrame(models["graph"]["importance"][:12])
    importance["feature"] = importance["feature"].map(lambda f: FEATURE_NAMES.get(f, f))
    st.altair_chart(bars(importance, "share_of_gain", "feature", "Share of gain", ".0%"), width="stretch")

with rings_tab:
    x, y, z = st.columns(3)
    x.metric("Suspected rings", f"{ring_stats['suspected']}")
    y.metric("Mostly real laundering", f"{ring_stats['mostly_laundering']}")
    z.metric("Largest ring", f"{ring_stats['largest_accounts']} accounts")

    st.markdown("**Labeled rings caught, by pattern type**")
    kinds = pd.DataFrame(ring_stats["by_kind"])
    kinds["label"] = kinds["kind"].str.title() + " (" + kinds["caught"].astype(str) + " of " + kinds["rings"].astype(str) + ")"
    st.altair_chart(bars(kinds, "caught_share", "label", "Share caught", ".0%"), width="stretch")

    st.markdown("**Look at one ring**")
    examples = ring_stats["examples"]
    labels = {
        i: f"Ring {e['ring'] + 1}: {e['accounts']} accounts, {e['transactions']} flagged transfers, "
           f"{e['laundering']} laundering" + (f" ({', '.join(k.title() for k in e['labeled_as'])})" if e["labeled_as"] else "")
        for i, e in enumerate(examples)
    }
    choice = st.selectbox("Ring", list(labels), format_func=labels.get, label_visibility="collapsed")
    ring = examples[choice]
    st.graphviz_chart(ring_picture(ring), width="stretch")
    st.caption("Solid blue arrow: labeled laundering. Dashed gray arrow: flagged, but not laundering. Letters stand in for account numbers.")
    st.dataframe(
        pd.DataFrame(ring["edges"]).assign(laundering=lambda t: t["laundering"].map({1: "Yes", 0: "No"})),
        hide_index=True, width="stretch",
        column_config={"from": "From", "to": "To", "time": "Time", "currency": "Currency", "format": "Format",
                       "laundering": "Laundering", "amount": st.column_config.NumberColumn("Amount", format="localized"),
                       "score": st.column_config.NumberColumn("Model score", format="%.2f")},
    )

with method_tab:
    st.markdown(
        f"""
**The data is synthetic.** IBM's AMLworld simulator generated every transaction, so the labels are complete,
which real bank data never is. Results here say how well the method finds the simulator's laundering,
not how it would do at a real bank.

**The leak that had to be removed.** After {leak['last_day_kept']} only {leak['dropped_transactions']:,} transactions remain,
and {leak['dropped_laundering_share']:.0%} of them are laundering (the normal rate is about 0.1%).
A model could score well just by learning that late means guilty. Those days are dropped.

**Split by time.** Train on the first six days, pick the threshold on the next two, test on the last two.

**Why not accuracy.** Flagging nothing would be 99.9% accurate. Everything is scored on the laundering class.

**What the graph features know.** They read the structure of every transaction in the ten days, including
later ones, the way an analyst reviewing a batch would. They never read a label. A live system scoring each
payment as it arrives would know less, and would score lower.

**Rings.** Flagged transfers that share accounts are grouped; a group of three or more accounts is a ring.
The simulator's pattern file is the answer key.
"""
    )
