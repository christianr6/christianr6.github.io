"""Streamlit dashboard: streamlit run app.py"""

from __future__ import annotations

import streamlit as st

from bull_bear import pipeline
from bull_bear.debate import CheckedClaim, Side
from bull_bear.edgar import EdgarError
from bull_bear.llm import ClaudeLlm, LlmError

SECTION_NAMES = {"risk_factors": "Risk Factors", "mdna": "MD&A", "financials": "Reported financials"}
REASONS = {
    "not_found": "quote not found in the filing",
    "too_short": "quote too short to check",
    "has_ellipsis": "quote was stitched or edited",
}

st.set_page_config(page_title="Bull vs. bear", page_icon="⚖️", layout="wide")


@st.cache_data(show_spinner="Fetching the 10-K from the SEC…")
def gather(ticker: str) -> pipeline.Sources:
    return pipeline.gather(ticker)


def claim_card(claim: CheckedClaim, rebuttals) -> None:
    with st.container(border=True):
        st.markdown(f"**{claim.number}. {claim.point}**")
        st.markdown(f"> {claim.quote}")
        st.caption(f"✓ Found word for word in {SECTION_NAMES.get(claim.found_in, claim.found_in)}")
        for rebuttal in rebuttals:
            st.markdown(f"↩︎ **Other side:** {rebuttal.response}")
            st.markdown(f"> {rebuttal.quote}")


def side_column(title: str, side: Side, opponent: Side) -> None:
    st.subheader(title)
    st.write(side.thesis)
    answers = [r for r in opponent.rebuttals if r.verified]
    for claim in side.standing:
        claim_card(claim, [r for r in answers if r.target == claim.number])
    if side.dropped:
        with st.expander(f"{len(side.dropped)} of {len(side.claims)} claims thrown out by the quote check"):
            for claim in side.dropped:
                st.markdown(f"~~{claim.point}~~")
                st.markdown(f"> {claim.quote}")
                st.caption(f"✗ {REASONS.get(claim.reason, claim.reason)}")


def show(transcript: pipeline.Transcript) -> None:
    debate, verdict = transcript.debate, transcript.debate.verdict
    names = {"bull": "Bull wins", "bear": "Bear wins", "draw": "Draw"}
    a, b, c = st.columns(3)
    a.metric("Verdict", names[verdict.winner])
    b.metric("Bull case", f"{verdict.bull_score} / 10")
    c.metric("Bear case", f"{verdict.bear_score} / 10")
    st.write(verdict.reasoning)
    st.info(f"**What this filing cannot tell you:** {verdict.missing_evidence}")

    left, right = st.columns(2)
    with left:
        side_column("🐂 Bull", debate.bull, debate.bear)
    with right:
        side_column("🐻 Bear", debate.bear, debate.bull)

    total = len(debate.bull.claims) + len(debate.bear.claims)
    kept = len(debate.bull.standing) + len(debate.bear.standing)
    usage = transcript.usage
    st.caption(
        f"{kept} of {total} claims passed the quote check. Model: {transcript.model}. Run {transcript.created}. "
        + (f"Tokens: {usage.get('cache_write_tokens', 0) + usage.get('input_tokens', 0):,} in, "
           f"{usage.get('cache_read_tokens', 0):,} read from cache, {usage.get('output_tokens', 0):,} out."
           if usage else "")
    )
    st.download_button("Download transcript (JSON)", transcript.model_dump_json(indent=2),
                       file_name=f"{transcript.sources.ticker}_debate.json", mime="application/json")


st.title("Bull vs. bear")
st.caption("Two AI agents argue a stock from its latest annual report. A program checks every quote. A third agent judges.")

ticker = st.text_input("Ticker", placeholder="AAPL", max_chars=8).strip().upper()
if not ticker:
    st.stop()

try:
    sources = gather(ticker)
except EdgarError as problem:
    st.error(str(problem))
    st.stop()

st.markdown(
    f"**{sources.company}** · 10-K for the year ended {sources.period}, filed {sources.filed} · "
    f"[read it on SEC.gov]({sources.url})"
)
for note in sources.notes:
    st.warning(note)

saved = pipeline.load_saved(sources)
label = "Run the debate again" if saved else "Run the debate"
st.caption(
    f"A debate makes 5 calls to the Claude API with about {sources.approx_tokens:,} tokens of filing text, "
    "billed to your API key. Finished debates are saved, so reopening one is free."
)
if st.button(label, type="primary" if not saved else "secondary"):
    try:
        with st.status("Debating…", expanded=True) as status:
            llm = ClaudeLlm(sources.as_sections())
            saved = pipeline.hold(sources, llm, on_step=lambda step: st.write(step + "…"))
            status.update(label="Debate finished", state="complete", expanded=False)
    except LlmError as problem:
        st.error(str(problem))
        st.stop()

if saved:
    show(saved)

st.divider()
st.caption(
    "The verdict says which case the filing supports, not whether to buy. A 10-K is the company's own account, "
    "and nothing here looks at price or valuation. This is a research tool, not investment advice."
)
