"""Check that a quoted passage really appears in the source documents.

This is the part of the project that does not trust the model. A claim whose
quote cannot be found word for word is dropped before anyone judges it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .sections import Section

MIN_WORDS = 6  # short enough for one table line, long enough to mean something

_SWAPS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    " ": " ", "​": "", "­": "",
})


@dataclass(frozen=True)
class Check:
    ok: bool
    reason: str               # verified | not_found | too_short | has_ellipsis
    section: str | None = None


def normalize(text: str) -> str:
    """Same words, one spelling: straight quotes, plain dashes, single spaces, lower case."""
    text = unicodedata.normalize("NFKC", text).translate(_SWAPS)
    return re.sub(r"\s+", " ", text).strip().casefold()


class QuoteChecker:
    def __init__(self, sections: list[Section]):
        self._haystacks = [(section.key, normalize(section.text)) for section in sections]

    def check(self, quote: str) -> Check:
        needle = normalize(quote).strip("\"' ")
        # A quote stitched together with "..." hides what was cut, so it is refused.
        if "..." in needle or "…" in needle or "[" in needle:
            return Check(False, "has_ellipsis")
        if len(needle.split()) < MIN_WORDS:
            return Check(False, "too_short")
        # Trailing punctuation is often added or dropped when quoting.
        for candidate in (needle, needle.rstrip(".,;:")):
            for key, haystack in self._haystacks:
                if candidate in haystack:
                    return Check(True, "verified", key)
        return Check(False, "not_found")
