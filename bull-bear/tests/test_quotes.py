import pytest

from bull_bear.quotes import QuoteChecker
from bull_bear.sections import Section

SECTIONS = [
    Section("risk_factors", "Risk", "The Company’s business depends on a single supplier\nlocated outside the United States — a disruption there would halt production."),
    Section("financials", "Numbers", "FY ended 2026-09-30 | Revenue | $1,200 million\nFY ended 2026-09-30 | Net income | -$60 million"),
]
checker = QuoteChecker(SECTIONS)


def test_an_exact_quote_is_verified_and_located():
    result = checker.check("business depends on a single supplier located outside the United States")
    assert result.ok and result.section == "risk_factors"


def test_quote_style_dashes_case_and_line_breaks_do_not_matter():
    result = checker.check("the company's business depends on a single supplier located outside the united states - a disruption there")
    assert result.ok


def test_wrapping_quotation_marks_and_a_final_period_are_forgiven():
    assert checker.check('"depends on a single supplier located outside the United States."').ok


def test_a_changed_word_fails():
    result = checker.check("business depends on a single customer located outside the United States")
    assert not result.ok and result.reason == "not_found"


def test_a_paraphrase_fails():
    assert not checker.check("the firm relies on one overseas supplier and that is quite risky indeed").ok


def test_stitched_quotes_are_refused():
    result = checker.check("business depends on a single supplier ... would halt production")
    assert not result.ok and result.reason == "has_ellipsis"


def test_bracketed_edits_are_refused():
    assert checker.check("[Apple]'s business depends on a single supplier located outside").reason == "has_ellipsis"


def test_tiny_quotes_are_refused():
    assert checker.check("a single supplier").reason == "too_short"


def test_a_financial_table_line_can_be_quoted():
    result = checker.check("FY ended 2026-09-30 | Revenue | $1,200 million")
    assert result.ok and result.section == "financials"


@pytest.mark.parametrize("wrong", ["FY ended 2026-09-30 | Revenue | $1,300 million", "FY ended 2026-09-30 | Net income | $60 million"])
def test_a_wrong_number_fails(wrong):
    assert not checker.check(wrong).ok
