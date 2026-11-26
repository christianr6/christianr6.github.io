"""Run the debate: openings, rebuttals, verdict.

Order of play
    1. Bull and bear each open with claims, one verbatim quote per claim.
    2. Code checks every quote against the filing. Unverified claims are dropped.
    3. Each side rebuts the other's surviving claims. Rebuttal quotes are checked too.
    4. A judge reads only what survived and says which case the filing supports better.
"""

from __future__ import annotations

from typing import Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from .quotes import QuoteChecker
from .sections import Section

Source = Literal["risk_factors", "mdna", "financials"]
SideName = Literal["bull", "bear"]
CLAIMS_PER_SIDE = 5
REBUTTALS_PER_SIDE = 3

T = TypeVar("T", bound=BaseModel)


# ---------- what the model returns ----------

class Claim(BaseModel):
    point: str = Field(description="The argument, in one or two plain sentences.")
    quote: str = Field(description="One contiguous passage copied exactly from the material.")
    source: Source


class Opening(BaseModel):
    thesis: str = Field(description="The case in two or three sentences.")
    claims: list[Claim]


class Rebuttal(BaseModel):
    target: int = Field(description="Number of the opposing claim being answered.")
    response: str = Field(description="Why that claim is weaker than it looks, in one or two sentences.")
    quote: str = Field(description="One contiguous passage copied exactly from the material.")
    source: Source


class Rebuttals(BaseModel):
    rebuttals: list[Rebuttal]


class Verdict(BaseModel):
    winner: Literal["bull", "bear", "draw"]
    bull_score: int = Field(description="0 to 10: how well the filing supports the bull case.")
    bear_score: int = Field(description="0 to 10: how well the filing supports the bear case.")
    reasoning: str = Field(description="Three to five sentences on why.")
    strongest_bull_point: str
    strongest_bear_point: str
    missing_evidence: str = Field(description="What this filing cannot tell an investor and would settle the question.")


# ---------- what the program keeps ----------

class CheckedClaim(Claim):
    number: int
    verified: bool
    reason: str                    # verified | not_found | too_short | has_ellipsis
    found_in: str | None = None


class CheckedRebuttal(Rebuttal):
    verified: bool
    reason: str
    found_in: str | None = None


class Side(BaseModel):
    thesis: str = ""
    claims: list[CheckedClaim] = []
    rebuttals: list[CheckedRebuttal] = []

    @property
    def standing(self) -> list[CheckedClaim]:
        return [claim for claim in self.claims if claim.verified]

    @property
    def dropped(self) -> list[CheckedClaim]:
        return [claim for claim in self.claims if not claim.verified]


class Debate(BaseModel):
    bull: Side
    bear: Side
    verdict: Verdict


class Llm(Protocol):
    def ask(self, prompt: str, schema: type[T]) -> T: ...


# ---------- prompts ----------

RULES = """\
You are taking part in a structured debate about a company's stock, staged for an individual \
investor who wants to see the strongest honest case on each side before deciding anything.

The only evidence allowed is the material in the documents below: sections of the company's \
most recent annual report (Form 10-K) and a table of its reported financials. You know nothing \
about the share price, the valuation, or anything that happened after the filing, so do not \
argue from them.

Evidence rule. Every claim and every rebuttal carries exactly one quote, and a program checks \
each quote against the documents before anyone reads the argument. A quote that is not found \
word for word is deleted together with its argument, so an inexact quote wastes the point. \
To pass the check:
- Copy one contiguous passage exactly as written. No paraphrase, no ellipses, no bracketed edits, \
and do not join passages from different places.
- Keep it between 6 and 60 words.
- To cite a number from the financial table, quote one whole line of the table.
- Prose from the annual report is safer to quote than its tables, whose layout was flattened."""

OPENING = {
    "bull": (
        f"You argue the bull case: why this business is in good shape and likely to do well. "
        f"Give a short thesis and your {CLAIMS_PER_SIDE} strongest claims, strongest first. "
        "Results and trends the company reports are better evidence than its optimism about itself."
    ),
    "bear": (
        f"You argue the bear case: what could go wrong and where the business is weak. "
        f"Give a short thesis and your {CLAIMS_PER_SIDE} strongest claims, strongest first. "
        "Risk factors are partly legal boilerplate that every company prints, so risks specific to "
        "this company, and weaknesses visible in its own numbers, are better evidence than generic ones."
    ),
}

REBUT = (
    "You argue the {side} case. Below are the opposing side's claims that passed the quote check. "
    "Answer the {count} you can weaken most, using evidence from the documents. A rebuttal that "
    "only restates your own case does not weaken theirs.\n\n{claims}"
)

JUDGE = (
    "You are the judge. Below is everything that passed the quote check: each side's thesis, "
    "claims and rebuttals. Decide which case the filing supports better. Judge the arguments on "
    "the evidence, including whether each quote really supports the point made from it and "
    "whether a rebuttal landed. A draw is a fair result when the evidence is balanced.\n\n"
    "Keep in mind what this record is: the company's own account of itself, with risk factors "
    "written defensively by lawyers, and nothing about price or valuation. Your verdict says "
    "which case the filing supports, not whether to buy the stock.\n\n{record}"
)


def documents_block(sections: list[Section]) -> str:
    parts = [f'<document key="{s.key}" title="{s.title}">\n{s.text}\n</document>' for s in sections]
    return "<documents>\n" + "\n".join(parts) + "\n</documents>"


def _numbered(claims: list[CheckedClaim]) -> str:
    if not claims:
        return "(none)"
    return "\n".join(f'{c.number}. {c.point}\n   Quote ({c.found_in}): "{c.quote}"' for c in claims)


def _record(bull: Side, bear: Side) -> str:
    def block(name: str, side: Side, other: Side) -> str:
        rebuttals = [r for r in other.rebuttals if r.verified]
        answered = "\n".join(
            f'- Against claim {r.target}: {r.response}\n   Quote ({r.found_in}): "{r.quote}"' for r in rebuttals
        )
        return (
            f"## {name} case\nThesis: {side.thesis or '(none)'}\n\nClaims:\n{_numbered(side.standing)}\n\n"
            f"Rebuttals from the other side:\n{answered or '(none)'}"
        )

    return block("Bull", bull, bear) + "\n\n" + block("Bear", bear, bull)


# ---------- the debate ----------

def _open(llm: Llm, checker: QuoteChecker, side: SideName) -> Side:
    opening = llm.ask(OPENING[side], Opening)
    claims = []
    for number, claim in enumerate(opening.claims, start=1):
        result = checker.check(claim.quote)
        claims.append(
            CheckedClaim(**claim.model_dump(), number=number, verified=result.ok,
                         reason=result.reason, found_in=result.section)
        )
    return Side(thesis=opening.thesis, claims=claims)


def _rebut(llm: Llm, checker: QuoteChecker, side: SideName, opponent: Side) -> list[CheckedRebuttal]:
    targets = opponent.standing
    if not targets:
        return []
    count = min(REBUTTALS_PER_SIDE, len(targets))
    answer = llm.ask(REBUT.format(side=side, count=count, claims=_numbered(targets)), Rebuttals)
    valid = {claim.number for claim in targets}
    checked = []
    for rebuttal in answer.rebuttals:
        if rebuttal.target not in valid:
            continue  # answers a claim that does not exist or was dropped
        result = checker.check(rebuttal.quote)
        checked.append(
            CheckedRebuttal(**rebuttal.model_dump(), verified=result.ok,
                            reason=result.reason, found_in=result.section)
        )
    return checked


def run(llm: Llm, sections: list[Section], on_step: Callable[[str], None] = lambda _: None) -> Debate:
    checker = QuoteChecker(sections)
    on_step("Bull is building its case")
    bull = _open(llm, checker, "bull")
    on_step("Bear is building its case")
    bear = _open(llm, checker, "bear")
    on_step("Bull is answering the bear")
    bull.rebuttals = _rebut(llm, checker, "bull", bear)
    on_step("Bear is answering the bull")
    bear.rebuttals = _rebut(llm, checker, "bear", bull)
    on_step("Judge is deciding")
    verdict = llm.ask(JUDGE.format(record=_record(bull, bear)), Verdict)
    return Debate(bull=bull, bear=bear, verdict=verdict)
