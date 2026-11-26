from bull_bear.sections import filing_sections, html_to_text

FILLER = "The company depends on a small number of suppliers for key components. " * 60
REVIEW = "Net sales rose because customers bought more units at higher prices. " * 60
TEN_K = f"""
<html><head><title>10-K</title><style>p {{ color: red }}</style></head><body>
<div style="display:none">hidden inline-XBRL header that must not leak into the text</div>
<p>Table of Contents</p>
<p>Item 1A. Risk Factors 5</p>
<p>Item 1B. Unresolved Staff Comments 20</p>
<p>Item 7. Management&#8217;s Discussion and Analysis of Financial Condition 25</p>
<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk 30</p>
<p>Item 1. Business</p><p>We make things.</p>
<p><b>Item 1A.</b> <b>Risk Factors</b></p><p>{FILLER}</p>
<p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
<p>ITEM 7. MANAGEMENT&#8217;S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</p>
<p>{REVIEW}</p>
<table><tr><td>Total net sales</td><td>$</td><td>478,834</td><td></td><td>15</td><td>%</td></tr></table>
<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p><p>Rates move.</p>
</body></html>
"""


def test_sections_come_from_the_body_not_the_table_of_contents():
    sections, notes = filing_sections(TEN_K)
    found = {section.key: section.text for section in sections}
    assert notes == []
    assert "small number of suppliers" in found["risk_factors"]
    assert "customers bought more units" in found["mdna"]


def test_a_section_stops_at_the_next_item():
    sections, _ = filing_sections(TEN_K)
    found = {section.key: section.text for section in sections}
    assert "Unresolved Staff Comments" not in found["risk_factors"]
    assert "Rates move" not in found["mdna"]


def test_headings_split_across_tags_and_in_capitals_are_recognized():
    sections, _ = filing_sections(TEN_K)
    assert {section.key for section in sections} == {"risk_factors", "mdna"}


def test_a_missing_section_is_reported_not_invented():
    html = f"<html><body><p>Item 1A. Risk Factors</p><p>{FILLER}</p><p>Item 1B. None</p></body></html>"
    sections, notes = filing_sections(html)
    assert [section.key for section in sections] == ["risk_factors"]
    assert len(notes) == 1 and "Item 7" in notes[0]


def test_hidden_content_styles_and_scripts_are_removed():
    text = html_to_text(TEN_K)
    assert "hidden inline-XBRL header" not in text
    assert "color: red" not in text


def test_table_rows_become_one_readable_line():
    assert "Total net sales | $478,834 | 15%" in html_to_text(TEN_K)


def test_curly_apostrophes_survive_as_written():
    assert "Management’s Discussion" in html_to_text(TEN_K)
