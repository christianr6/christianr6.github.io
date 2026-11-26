"""Turn a 10-K's HTML into plain text and cut out the sections worth arguing over."""

from __future__ import annotations

import re
import unicodedata
import warnings
from dataclasses import dataclass

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

_BLOCKS = ["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "br", "hr"]

# Item headings as they appear at the start of a line. The table of contents
# repeats them, so the longest candidate span is taken as the real section.
_ITEM = r"^[ \t]*item[ \t]*{number}[ \t]*[.:\-–—]?[ \t]*{title}"
RISK_FACTORS = (
    re.compile(_ITEM.format(number="1a", title="risk[ \t]+factors"), re.I | re.M),
    re.compile(_ITEM.format(number="(1b|1c|2)", title=""), re.I | re.M),
)
MDNA = (
    re.compile(_ITEM.format(number="7", title="management"), re.I | re.M),
    re.compile(_ITEM.format(number="(7a|8)", title=""), re.I | re.M),
)
MIN_SECTION_CHARS = 2_000


@dataclass(frozen=True)
class Section:
    key: str        # risk_factors | mdna | financials
    title: str
    text: str


def html_to_text(html: str) -> str:
    """Readable text: one line per block element, table cells separated by ' | '."""
    with warnings.catch_warnings():
        # Inline-XBRL filings declare themselves as XML but are laid out as HTML.
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    for cell in soup.find_all(["td", "th"]):
        cell.append(" | ")
    for tag in soup.find_all(_BLOCKS):
        tag.insert_before("\n")
        tag.append("\n")
    text = unicodedata.normalize("NFKC", soup.get_text())
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t ]+", " ", line)
        line = re.sub(r"(\| )+\|", "|", line)          # empty spacer cells
        line = re.sub(r"\$ \| (?=[\d(])", "$", line)      # "$ | 123" -> "$123"
        line = re.sub(r"(?<=[\d)]) \| (?=[%)])", "", line)  # "12 | %" -> "12%"
        line = line.strip(" |")
        if line:
            lines.append(line)
    return "\n".join(lines)


def extract(text: str, start: re.Pattern, end: re.Pattern) -> str:
    """The longest span from a start heading to the next end heading."""
    best = ""
    for opening in start.finditer(text):
        closing = end.search(text, opening.end())
        span = text[opening.start() : closing.start() if closing else len(text)]
        if len(span) > len(best):
            best = span
    return best.strip()


def filing_sections(html: str) -> tuple[list[Section], list[str]]:
    """Risk factors and MD&A, plus notes about anything that could not be found."""
    text = html_to_text(html)
    sections, notes = [], []
    for key, title, (start, end) in (
        ("risk_factors", "Item 1A. Risk Factors", RISK_FACTORS),
        ("mdna", "Item 7. Management's Discussion and Analysis", MDNA),
    ):
        body = extract(text, start, end)
        if len(body) < MIN_SECTION_CHARS:
            notes.append(
                f"{title} was not found in the main document "
                "(some companies incorporate it by reference to another exhibit)."
            )
        else:
            sections.append(Section(key, title, body))
    return sections, notes
