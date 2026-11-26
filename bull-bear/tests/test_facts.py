from bull_bear.facts import financial_lines, financials_section


def fact(end, value, start=None, filed="2026-11-01", form="10-K"):
    entry = {"end": end, "val": value, "form": form, "filed": filed}
    if start:
        entry["start"] = start
    return entry


def company(**concepts):
    return {"facts": {"us-gaap": {name: {"units": {unit: entries}} for name, (unit, entries) in concepts.items()}}}


FACTS = company(
    Revenues=("USD", [
        fact("2026-09-30", 1_200_000_000, start="2025-10-01"),
        fact("2025-09-30", 1_000_000_000, start="2024-10-01"),
        fact("2026-09-30", 330_000_000, start="2026-07-01"),          # a quarter, same tag
        fact("2026-06-30", 900_000_000, start="2025-10-01", form="10-Q"),
    ]),
    NetIncomeLoss=("USD", [
        fact("2026-09-30", -60_000_000, start="2025-10-01"),
        fact("2025-09-30", 100_000_000, start="2024-10-01", filed="2025-11-01"),
        fact("2025-09-30", 90_000_000, start="2024-10-01", filed="2026-11-01"),   # restated
    ]),
    GrossProfit=("USD", [fact("2026-09-30", 480_000_000, start="2025-10-01")]),
    NetCashProvidedByUsedInOperatingActivities=("USD", [fact("2026-09-30", 150_000_000, start="2025-10-01")]),
    PaymentsToAcquirePropertyPlantAndEquipment=("USD", [fact("2026-09-30", 50_000_000, start="2025-10-01")]),
    Assets=("USD", [fact("2026-09-30", 2_000_000_000)]),
    EarningsPerShareDiluted=("USD/shares", [fact("2026-09-30", -0.6, start="2025-10-01")]),
)


def lines():
    return financial_lines(FACTS)


def test_annual_revenue_is_used_not_the_quarter_or_the_10q():
    assert "FY ended 2026-09-30 | Revenue | $1,200 million" in lines()
    assert not any("$330 million" in line or "$900 million" in line for line in lines())


def test_the_most_recently_filed_value_wins_after_a_restatement():
    assert "FY ended 2025-09-30 | Net income | $90 million" in lines()


def test_losses_are_shown_as_negative():
    assert "FY ended 2026-09-30 | Net income | -$60 million" in lines()
    assert "FY ended 2026-09-30 | Diluted EPS | $-0.60" in lines()


def test_balance_sheet_items_without_a_start_date_are_included():
    assert "FY ended 2026-09-30 | Total assets | $2,000 million" in lines()


def test_derived_lines_are_computed_from_the_reported_numbers():
    assert "FY ended 2026-09-30 | Gross margin | 40.0%" in lines()
    assert "FY ended 2026-09-30 | Net margin | -5.0%" in lines()
    assert "FY ended 2026-09-30 | Free cash flow (operating cash flow minus capex) | $100 million" in lines()
    assert "FY ended 2026-09-30 vs. 2025-09-30 | Revenue change | +20.0%" in lines()


def test_an_older_revenue_tag_is_used_when_the_newer_one_is_absent():
    old = company(SalesRevenueNet=("USD", [fact("2026-09-30", 5_000_000, start="2025-10-01")]))
    assert financial_lines(old) == ["FY ended 2026-09-30 | Revenue | $5 million"]


def test_no_facts_means_no_section():
    assert financials_section({"facts": {}}) is None
