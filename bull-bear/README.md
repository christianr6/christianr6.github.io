# Bull vs. bear

Two AI agents argue for and against a stock using its latest annual report.
A program checks every quote against the filing. A third agent judges what
is left.

```
10-K (Risk Factors, MD&A) ─┐
reported financials (XBRL) ─┴→ bull opens ─┐
                               bear opens ─┴→ quote check → rebuttals → quote check → judge
```

**Status:** the filing pipeline and quote checker run on real SEC data and
are covered by 36 tests. The debate itself has only been run with a scripted
stand-in for the model. It has not been run against the Claude API yet, so
there is no real debate to show here.

## Why the quote check matters

A language model asked to argue from a 200-page filing will sometimes cite
things the filing does not say. Here every claim and rebuttal must carry one
quote, and code looks for that quote word for word in the source text.

- **Found:** the claim stands and the judge sees it.
- **Not found, stitched with "...", or too short:** the claim is thrown out
  before the other side or the judge reads it. The dashboard lists what was dropped.
- **Numbers:** the debaters cite figures by quoting a line of a financial
  table that code builds from the company's XBRL filings, so a wrong number fails the same check.

The check proves the words are in the filing. It does not prove the quote
supports the point made from it; judging that is the third agent's job.

## Run it

```bash
pip install -r requirements.txt

export SEC_USER_AGENT="Your Name you@example.com"   # the SEC requires a contact
export ANTHROPIC_API_KEY="..."                      # from console.anthropic.com

python -m bull_bear AAPL --dry-run   # fetch the filing and show sizes; free
python -m bull_bear AAPL             # run the debate; billed to your API key
streamlit run app.py                 # dashboard
python -m pytest                     # tests; no network, no API key
```

A debate is five calls to Claude Opus 5.5 (`BULL_BEAR_MODEL` changes the
model). The filing text is cached after the first call. For Apple's 10-K,
about 27,000 tokens of source text, that should come to roughly $0.50; this is
an estimate, not a measured cost. Finished debates are saved under
`data/debates/`, so reopening one costs nothing.

## What it reads

- **Item 1A, Risk Factors** and **Item 7, MD&A** from the most recent 10-K,
  found by ticker through SEC EDGAR.
- **Reported financials** for the last three fiscal years from EDGAR's XBRL
  company facts: revenue, profit, cash flow, balance-sheet totals, plus margins,
  free cash flow and growth rates computed in code.

## Limits

- **It is not a stock tip.** The verdict says which case the filing supports.
  Nothing here looks at price or valuation.
- **A 10-K is the company's own account.** Risk factors are written
  defensively by lawyers, and management describes its own results.
- **It cannot be backtested honestly.** The model may already know what
  happened to a company after an old filing.
- **U.S. filers only.** Foreign companies file a 20-F, which is not supported.
- **Some filings do not parse.** A few companies (large banks, for example)
  place MD&A outside the standard heading. The tool says so and argues from what it found.

## Layout

| File | Job |
|---|---|
| `bull_bear/edgar.py` | find and download the 10-K and financial facts |
| `bull_bear/sections.py` | HTML to text; cut out Risk Factors and MD&A |
| `bull_bear/facts.py` | build the quotable financial table |
| `bull_bear/quotes.py` | the quote checker |
| `bull_bear/debate.py` | prompts, order of play, what the judge sees |
| `bull_bear/llm.py` | the Claude API calls |
| `app.py` | Streamlit dashboard |
