"""Compare what you paid for specific items with BLS average prices.

BLS publishes a U.S. city average price each month for a short list of
narrowly defined items (a dozen large grade A eggs, a gallon of whole milk).
Purchases are matched to that list by keyword, converted to the same unit,
and compared with the BLS price for the same month.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

PREFIX = "APU0000"   # average price, U.S. city average


@dataclass(frozen=True)
class Item:
    code: str                       # BLS item code; series id is APU0000 + code
    label: str
    unit: str                       # the unit BLS prices it in: lb, gal, doz, kwh, therm
    any_of: tuple[tuple[str, ...], ...]     # a purchase matches if all words of one tuple appear
    none_of: tuple[str, ...] = ()

    @property
    def series(self) -> str:
        return PREFIX + self.code


# Codes and definitions: BLS, "CPI: Average Price Data" fact sheet. Order matters:
# the first match wins, so specific items come before general ones.
CATALOG = [
    Item("FF1101", "Chicken breast, boneless", "lb", (("chicken", "breast"),)),
    Item("706111", "Chicken, fresh, whole", "lb", (("whole", "chicken"),)),
    Item("703112", "Ground beef, 100% beef", "lb", (("ground", "beef"), ("hamburger",)), ("turkey",)),
    Item("704111", "Bacon, sliced", "lb", (("bacon",),), ("turkey", "bits")),
    Item("708111", "Eggs, grade A, large", "doz", (("egg",), ("eggs",)), ("noodle", "roll", "plant")),
    Item("709112", "Milk, fresh, whole", "gal", (("milk",),),
         ("almond", "oat", "soy", "coconut", "chocolate", "condensed", "evaporated", "powder", "skim", "2%", "1%")),
    Item("702111", "Bread, white, pan", "lb", (("bread",),), ("crumb", "banana", "wheat", "rye", "sourdough")),
    Item("710211", "American processed cheese", "lb", (("american", "cheese"),)),
    Item("711211", "Bananas", "lb", (("banana",), ("bananas",)), ("bread", "chip")),
    Item("711311", "Oranges, navel", "lb", (("navel",), ("orange",), ("oranges",)), ("juice", "soda", "chicken")),
    Item("712311", "Tomatoes, field grown", "lb", (("tomato",), ("tomatoes",)),
         ("sauce", "paste", "canned", "soup", "ketchup", "cherry", "grape")),
    Item("712112", "Potatoes, white", "lb", (("potato",), ("potatoes",)), ("chip", "sweet", "fries", "salad", "mashed")),
    Item("701312", "Rice, white, long grain", "lb", (("rice",),), ("brown", "cake", "krispies", "pudding", "cauliflower")),
    Item("717311", "Coffee, ground roast", "lb", (("coffee",),), ("creamer", "filter", "instant", "pod", "latte")),
    Item("715211", "Sugar, white", "lb", (("sugar",),), ("brown", "powdered", "free", "cookie", "snap")),
    Item("701111", "Flour, white, all purpose", "lb", (("flour",),), ("tortilla", "almond", "wheat")),
    Item("72620", "Utility (piped) gas", "therm", (("natural", "gas"), ("therm",), ("therms",))),
    Item("72610", "Electricity", "kwh", (("electric",), ("electricity",), ("kwh",))),
    Item("74714", "Gasoline, unleaded regular", "gal", (("gasoline",), ("unleaded",), ("gas",), ("fuel",)), ("premium", "diesel")),
]
SERIES = [item.series for item in CATALOG]

# Everything is converted to the first unit of its group.
_FACTORS = {
    "lb": {"lb": 1, "lbs": 1, "pound": 1, "pounds": 1, "oz": 1 / 16, "ounce": 1 / 16, "ounces": 1 / 16,
           "kg": 2.20462, "g": 0.00220462},
    "gal": {"gal": 1, "gallon": 1, "gallons": 1, "qt": 0.25, "quart": 0.25, "pt": 0.125, "pint": 0.125,
            "fl oz": 1 / 128, "floz": 1 / 128, "l": 0.264172, "liter": 0.264172, "litre": 0.264172},
    "doz": {"doz": 1, "dozen": 1, "ct": 1 / 12, "count": 1 / 12, "each": 1 / 12, "ea": 1 / 12, "egg": 1 / 12, "eggs": 1 / 12},
    "kwh": {"kwh": 1},
    "therm": {"therm": 1, "therms": 1},
}


def match(description: str) -> Item | None:
    words = set(re.findall(r"[a-z0-9%]+", str(description).lower()))
    text = str(description).lower()
    for item in CATALOG:
        if any(blocked in text for blocked in item.none_of):
            continue
        if any(all(word in words for word in group) for group in item.any_of):
            return item
    return None


def to_unit(quantity: float, unit: str, target: str) -> float | None:
    """Quantity expressed in the target unit, or None if the units do not convert."""
    factor = _FACTORS[target].get(str(unit).strip().lower().rstrip("."))
    return None if factor is None else float(quantity) * factor


def read_purchases(source) -> pd.DataFrame:
    """A CSV with columns date, item, price, quantity, unit. price is the total paid."""
    frame = pd.read_csv(source)
    frame.columns = [column.strip().lower() for column in frame.columns]
    missing = [column for column in ("date", "item", "price", "quantity", "unit") if column not in frame]
    if missing:
        raise ValueError(f"The file needs these columns: date, item, price, quantity, unit. Missing: {', '.join(missing)}")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def compare(purchases: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per purchase: your unit price, the BLS average that month, and the gap.

    `status` says why a row has no comparison: ok, no_match (not on the BLS
    list), bad_unit (cannot convert), no_bls_price (BLS has no figure that month).
    """
    rows = []
    for purchase in purchases.itertuples(index=False):
        row = {"date": purchase.date, "item": purchase.item, "bls_item": None, "unit": None,
               "you_paid": None, "bls_average": None, "gap": None, "status": "no_match"}
        item = match(purchase.item)
        if item is not None:
            row.update(bls_item=item.label, unit=item.unit, status="bad_unit")
            amount = to_unit(purchase.quantity, purchase.unit, item.unit)
            if amount:
                row["you_paid"] = float(purchase.price) / amount
                month = pd.Timestamp(purchase.date).to_period("M").to_timestamp()
                average = prices[item.series].get(month) if item.series in prices else None
                if average is None or pd.isna(average):
                    row["status"] = "no_bls_price"
                else:
                    row.update(bls_average=float(average), gap=row["you_paid"] / float(average) - 1, status="ok")
        rows.append(row)
    return pd.DataFrame(rows)


def changes(compared: pd.DataFrame, min_months: int = 6) -> pd.DataFrame:
    """For items bought in two months far enough apart: your price change vs. the BLS change."""
    ok = compared[compared["status"] == "ok"].copy()
    if ok.empty:
        return pd.DataFrame(columns=["bls_item", "first", "last", "your_change", "bls_change"])
    ok["month"] = ok["date"].dt.to_period("M")
    monthly = ok.groupby(["bls_item", "month"]).agg(you_paid=("you_paid", "mean"), bls_average=("bls_average", "first"))
    rows = []
    for label, group in monthly.groupby(level=0):
        group = group.droplevel(0).sort_index()
        first, last = group.index[0], group.index[-1]
        if (last - first).n < min_months:
            continue
        rows.append({
            "bls_item": label, "first": str(first), "last": str(last),
            "your_change": group["you_paid"].iloc[-1] / group["you_paid"].iloc[0] - 1,
            "bls_change": group["bls_average"].iloc[-1] / group["bls_average"].iloc[0] - 1,
        })
    return pd.DataFrame(rows, columns=["bls_item", "first", "last", "your_change", "bls_change"])
