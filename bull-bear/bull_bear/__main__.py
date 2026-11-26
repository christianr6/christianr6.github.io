"""Command line: python -m bull_bear TICKER

    python -m bull_bear AAPL --dry-run   show what would be sent, call nothing paid
    python -m bull_bear AAPL             run the debate (uses the Claude API, costs money)
"""

from __future__ import annotations

import argparse
import sys

from . import pipeline
from .edgar import EdgarError
from .llm import ClaudeLlm, LlmError


def show(transcript: pipeline.Transcript) -> None:
    debate, sources = transcript.debate, transcript.sources
    print(f"\n{sources.company} ({sources.ticker}), 10-K filed {sources.filed}\n")
    for name, side in (("BULL", debate.bull), ("BEAR", debate.bear)):
        print(f"{name}: {side.thesis}")
        for claim in side.standing:
            print(f"  {claim.number}. {claim.point}\n     \"{claim.quote}\" [{claim.found_in}]")
        if side.dropped:
            print(f"  ({len(side.dropped)} of {len(side.claims)} claims dropped: quote not found in the filing)")
        for rebuttal in side.rebuttals:
            if rebuttal.verified:
                print(f"  vs. claim {rebuttal.target}: {rebuttal.response}")
        print()
    verdict = debate.verdict
    print(f"VERDICT: {verdict.winner.upper()}  (bull {verdict.bull_score}/10, bear {verdict.bear_score}/10)")
    print(verdict.reasoning)
    print(f"\nWhat the filing cannot tell you: {verdict.missing_evidence}")
    if transcript.usage:
        print(f"\nTokens: {transcript.usage}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bull_bear", description="Bull vs. bear debate from a company's 10-K.")
    parser.add_argument("ticker")
    parser.add_argument("--dry-run", action="store_true", help="fetch the filing and show sizes; do not call Claude")
    parser.add_argument("--again", action="store_true", help="rerun even if a saved debate exists for this filing")
    args = parser.parse_args(argv)

    try:
        sources = pipeline.gather(args.ticker)
    except EdgarError as problem:
        print(problem, file=sys.stderr)
        return 2

    print(f"{sources.company}: 10-K for the year ended {sources.period}, filed {sources.filed}")
    for section in sources.sections:
        print(f"  {section['title']}: {len(section['text']):,} characters")
    for note in sources.notes:
        print(f"  note: {note}")
    print(f"  about {sources.approx_tokens:,} tokens of source material per call (estimate)")
    if args.dry_run:
        return 0

    saved = None if args.again else pipeline.load_saved(sources)
    if saved:
        print("(showing the saved debate for this filing; use --again to rerun)")
        show(saved)
        return 0
    try:
        llm = ClaudeLlm(sources.as_sections())
        transcript = pipeline.hold(sources, llm, on_step=lambda step: print(f"  {step}…", file=sys.stderr))
    except LlmError as problem:
        print(problem, file=sys.stderr)
        return 1
    show(transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
