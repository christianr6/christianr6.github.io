"""Glue: ticker -> source documents -> debate -> saved transcript."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from . import debate
from .edgar import Edgar, EdgarError, Filing
from .facts import financials_section
from .sections import Section, filing_sections

SAVE_DIR = Path("data") / "debates"
CHARS_PER_TOKEN = 4          # rough rule of thumb, for the size estimate only
MAX_SOURCE_CHARS = 2_400_000  # about 600K tokens; beyond that the filing will not fit


class Sources(BaseModel):
    company: str
    ticker: str
    accession: str
    filed: str
    period: str
    url: str
    sections: list[dict]      # key, title, text
    notes: list[str]

    def as_sections(self) -> list[Section]:
        return [Section(**section) for section in self.sections]

    @property
    def chars(self) -> int:
        return sum(len(section["text"]) for section in self.sections)

    @property
    def approx_tokens(self) -> int:
        return self.chars // CHARS_PER_TOKEN


class Transcript(BaseModel):
    sources: Sources
    debate: debate.Debate
    model: str
    usage: dict
    created: str


def gather(ticker: str, edgar: Edgar | None = None) -> Sources:
    """Download (or read from cache) everything the debaters may quote."""
    edgar = edgar or Edgar()
    filing: Filing = edgar.latest_annual_report(ticker)
    sections, notes = filing_sections(edgar.document(filing))
    financials = financials_section(edgar.company_facts(filing))
    if financials:
        sections.append(financials)
    else:
        notes.append("No reported financials were found in the company's XBRL data.")
    if not any(section.key in ("risk_factors", "mdna") for section in sections):
        raise EdgarError(
            f"Could not find Risk Factors or MD&A in {filing.company}'s 10-K, so there is nothing to argue from."
        )
    sources = Sources(
        company=filing.company, ticker=filing.ticker, accession=filing.accession, filed=filing.filed,
        period=filing.period, url=filing.url, notes=notes,
        sections=[{"key": s.key, "title": s.title, "text": s.text} for s in sections],
    )
    if sources.chars > MAX_SOURCE_CHARS:
        # Refuse instead of silently cutting the filing: a quote checker that
        # only sees part of the document would wrongly drop honest claims.
        raise EdgarError(
            f"The extracted sections are too long to send in one request ({sources.chars:,} characters)."
        )
    return sources


def transcript_path(sources: Sources, directory: Path = SAVE_DIR) -> Path:
    return directory / f"{sources.ticker}_{sources.accession}.json"


def load_saved(sources: Sources, directory: Path = SAVE_DIR) -> Transcript | None:
    path = transcript_path(sources, directory)
    return Transcript.model_validate_json(path.read_text()) if path.exists() else None


def hold(sources: Sources, llm, on_step: Callable[[str], None] = lambda _: None,
         directory: Path = SAVE_DIR) -> Transcript:
    """Run the debate and save it, so the same filing is never paid for twice by accident."""
    result = debate.run(llm, sources.as_sections(), on_step)
    usage = llm.usage.model_dump() if hasattr(llm, "usage") else {}
    transcript = Transcript(
        sources=sources, debate=result, model=getattr(llm, "model", "unknown"), usage=usage,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    path = transcript_path(sources, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript.model_dump_json(indent=2))
    return transcript
