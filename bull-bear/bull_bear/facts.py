"""Build a small, quotable table of reported financials from XBRL company facts.

Every line is computed by code from numbers the company filed, so the debaters
can cite figures the same way they cite text: by quoting a line exactly.
"""

from __future__ import annotations

from datetime import date

from .sections import Section

# Label -> XBRL concepts to try, in order. Companies tag the same idea differently.
CONCEPTS: dict[str, list[str]] = {
    "Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "Gross profit": ["GrossProfit"],
    "Operating income": ["OperatingIncomeLoss"],
    "Net income": ["NetIncomeLoss", "ProfitLoss"],
    "Diluted EPS": ["EarningsPerShareDiluted"],
    "Operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Capital expenditures": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "Share repurchases": ["PaymentsForRepurchaseOfCommonStock"],
    "Cash and equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "Total assets": ["Assets"],
    "Total liabilities": ["Liabilities"],
    "Shareholders' equity": ["StockholdersEquity"],
}
YEARS = 3


def _annual_values(concept: dict) -> dict[str, float]:
    """Fiscal-year-end date -> value, from 10-K facts only.

    Flow items (revenue, cash flow) must span about a year; 10-Ks also carry
    quarterly figures under the same tag. Balance-sheet items have no start.
    When a number is restated, the most recently filed value wins.
    """
    best: dict[str, tuple[str, float]] = {}
    for unit, entries in concept.get("units", {}).items():
        if unit not in ("USD", "USD/shares"):
            continue
        for entry in entries:
            if entry.get("form") != "10-K" or "end" not in entry or "val" not in entry:
                continue
            if "start" in entry:
                days = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
                if not 350 <= days <= 380:
                    continue
            filed = entry.get("filed", "")
            if entry["end"] not in best or filed >= best[entry["end"]][0]:
                best[entry["end"]] = (filed, float(entry["val"]))
    return {end: value for end, (_, value) in best.items()}


def _pick(facts: dict, names: list[str], year_ends: list[str] | None = None) -> dict[str, float]:
    """The first concept that has data for the latest year (or any data at all)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    fallback: dict[str, float] = {}
    for name in names:
        values = _annual_values(gaap.get(name, {}))
        if not values:
            continue
        if year_ends is None or year_ends[0] in values:
            return values
        fallback = fallback or values
    return fallback


def money(value: float) -> str:
    millions = value / 1e6
    return f"-${abs(millions):,.0f} million" if millions < 0 else f"${millions:,.0f} million"


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def financial_lines(facts: dict) -> list[str]:
    """Lines such as 'FY ended 2026-09-26 | Revenue | $478,834 million'."""
    revenue = _pick(facts, CONCEPTS["Revenue"])
    anchor = revenue or _pick(facts, CONCEPTS["Net income"]) or _pick(facts, CONCEPTS["Total assets"])
    if not anchor:
        return []
    year_ends = sorted(anchor, reverse=True)[:YEARS]
    table = {label: _pick(facts, names, year_ends) for label, names in CONCEPTS.items()}

    lines = []
    for end in year_ends:
        for label, values in table.items():
            if end in values:
                shown = f"${values[end]:,.2f}" if label == "Diluted EPS" else money(values[end])
                lines.append(f"FY ended {end} | {label} | {shown}")
        get = lambda label: table[label].get(end)  # noqa: E731
        if get("Revenue") and get("Gross profit") is not None:
            lines.append(f"FY ended {end} | Gross margin | {percent(get('Gross profit') / get('Revenue'))}")
        if get("Revenue") and get("Net income") is not None:
            lines.append(f"FY ended {end} | Net margin | {percent(get('Net income') / get('Revenue'))}")
        if get("Operating cash flow") is not None and get("Capital expenditures") is not None:
            free = get("Operating cash flow") - get("Capital expenditures")
            lines.append(f"FY ended {end} | Free cash flow (operating cash flow minus capex) | {money(free)}")

    for newer, older in zip(year_ends, year_ends[1:]):
        for label in ("Revenue", "Net income"):
            now, before = table[label].get(newer), table[label].get(older)
            if now is not None and before:
                change = (now - before) / abs(before)
                lines.append(f"FY ended {newer} vs. {older} | {label} change | {change * 100:+.1f}%")
    return lines


def financials_section(facts: dict) -> Section | None:
    lines = financial_lines(facts)
    if not lines:
        return None
    return Section("financials", "Reported financials (from XBRL filings, computed by code)", "\n".join(lines))
