"""Personal inflation from spending by category.

Official CPI is one basket: the average urban household's. Yours differs, so
your inflation differs. This module re-weights the official category price
indexes by your own spending.

Two formulas, depending on WHEN your spending figures are from:

    spending from a year ago   rate = sum(share_i * I_now_i / I_then_i) - 1          (Laspeyres)
    spending from now          rate = 1 / sum(share_i * I_then_i / I_now_i) - 1      (Paasche)

share_i is category i's share of your total, I is its CPI index level.
A fixed payment (a fixed-rate mortgage, a loan) has I_now / I_then = 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ALL_ITEMS = "CUUR0000SA0"   # CPI-U, U.S. city average, all items, not seasonally adjusted


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    series: str | None        # None = a fixed payment; its price does not change
    official_weight: float    # percent of the CPI-U basket, December 2025; 0 = not a separate CPI line
    hint: str = ""


# Weights: BLS, "Relative importance of components in the Consumer Price Indexes:
# U.S. city average, December 2025", CPI-U column. They sum to 100.
# "Vehicles and parts" is transportation (16.316) less motor fuel (2.981) and
# transportation services (6.315); BLS does not print that row.
CATEGORIES = [
    Category("groceries", "Groceries", "CUUR0000SAF11", 8.325, "food at home"),
    Category("restaurants", "Restaurants and takeout", "CUUR0000SEFV", 5.373, "food away from home"),
    Category("alcohol", "Alcohol", "CUUR0000SAF116", 0.840),
    Category("rent", "Rent", "CUUR0000SEHA", 0.0, "rent of primary residence"),
    Category("fixed", "Mortgage or other fixed payment", None, 0.0, "the payment does not change, so 0%"),
    Category("shelter", "Housing at the CPI shelter rate", "CUUR0000SAH1", 35.625,
             "CPI shelter: rent plus what owners would pay to rent their own home"),
    Category("utilities", "Utilities", "CUUR0000SAH2", 4.546, "electricity, gas, water, trash"),
    Category("household", "Household goods and services", "CUUR0000SAH3", 4.298, "furniture, appliances, cleaning"),
    Category("clothing", "Clothing", "CUUR0000SAA", 2.368),
    Category("gasoline", "Gasoline", "CUUR0000SETB", 2.981, "motor fuel"),
    Category("vehicles", "Vehicles and parts", "CUUR0000SATCLTB", 7.020, "buying or leasing a car, tires, parts"),
    Category("transport_services", "Car insurance, repairs, fares", "CUUR0000SAS4", 6.315,
             "insurance, maintenance, airfare, transit"),
    Category("medical", "Medical care", "CUUR0000SAM", 8.423),
    Category("recreation", "Recreation", "CUUR0000SAR", 5.137, "streaming, pets, sports, hobbies"),
    Category("education", "Education", "CUUR0000SAE1", 2.602, "tuition, books, childcare"),
    Category("communication", "Phone and internet", "CUUR0000SAE2", 3.244),
    Category("other", "Personal care and other", "CUUR0000SAG", 2.902, "haircuts, toiletries, tobacco"),
]
BY_KEY = {category.key: category for category in CATEGORIES}
SERIES = [ALL_ITEMS] + [category.series for category in CATEGORIES if category.series]
OFFICIAL = {category.key: category.official_weight for category in CATEGORIES if category.official_weight > 0}


def shares(spending: dict[str, float]) -> dict[str, float]:
    """Dollar amounts -> shares of the total. Unknown keys and negatives are errors."""
    unknown = sorted(set(spending) - set(BY_KEY))
    if unknown:
        raise ValueError(f"Unknown categories: {', '.join(unknown)}")
    if any(amount < 0 for amount in spending.values()):
        raise ValueError("Spending cannot be negative.")
    total = sum(spending.values())
    if total <= 0:
        raise ValueError("Enter spending in at least one category.")
    return {key: amount / total for key, amount in spending.items() if amount > 0}


def price_ratios(prices: pd.DataFrame, months: int = 12) -> pd.DataFrame:
    """I_now / I_then for every category and month; missing when either month is missing."""
    ratios = {}
    for category in CATEGORIES:
        if category.series is None:
            ratios[category.key] = pd.Series(1.0, index=prices.index)
        elif category.series in prices:
            # prices has one row per month with no gaps, so shifting by rows shifts by months
            ratios[category.key] = prices[category.series] / prices[category.series].shift(months)
    ratios["all_items"] = prices[ALL_ITEMS] / prices[ALL_ITEMS].shift(months)
    return pd.DataFrame(ratios)


def personal_rate(share: dict[str, float], ratios: pd.DataFrame, spending_from: str = "then") -> pd.Series:
    """Your inflation rate for every month that has data for all your categories.

    spending_from: "then" if the spending figures describe a year ago (Laspeyres),
    "now" if they describe today (Paasche).
    """
    used = ratios[list(share)]
    weights = pd.Series(share)
    if spending_from == "then":
        rate = (used * weights).sum(axis=1, skipna=False) - 1
    elif spending_from == "now":
        rate = 1 / (weights / used).sum(axis=1, skipna=False) - 1
    else:
        raise ValueError("spending_from must be 'then' or 'now'")
    return rate.dropna()


def official_rate(ratios: pd.DataFrame) -> pd.Series:
    return (ratios["all_items"] - 1).dropna()


def latest_common_month(*series: pd.Series) -> pd.Timestamp:
    common = series[0].index
    for other in series[1:]:
        common = common.intersection(other.index)
    if len(common) == 0:
        raise ValueError("No month has data for every category.")
    return common.max()


def contributions(share: dict[str, float], ratios: pd.DataFrame, month: pd.Timestamp) -> pd.DataFrame:
    """Per category: share, price change, and percentage points added to your rate (base-period shares)."""
    rows = []
    for key, weight in share.items():
        change = float(ratios.loc[month, key] - 1)
        rows.append({"key": key, "label": BY_KEY[key].label, "share": weight, "change": change,
                     "points": weight * change})
    return pd.DataFrame(rows).sort_values("points", ascending=False).reset_index(drop=True)
