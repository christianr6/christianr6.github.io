import io

import pandas as pd
import pytest

from inflation import items, ocr


@pytest.mark.parametrize("text, label", [
    ("Large eggs grade A", "Eggs, grade A, large"),
    ("WHOLE MILK GAL", "Milk, fresh, whole"),
    ("Boneless chicken breast", "Chicken breast, boneless"),
    ("Whole chicken fryer", "Chicken, fresh, whole"),
    ("80/20 ground beef", "Ground beef, 100% beef"),
    ("Regular unleaded", "Gasoline, unleaded regular"),
    ("Natural gas bill", "Utility (piped) gas"),
    ("Electric bill", "Electricity"),
])
def test_purchases_match_the_right_bls_item(text, label):
    assert items.match(text).label == label


@pytest.mark.parametrize("text", ["Oat milk", "Banana bread", "Egg noodles", "Ground turkey", "Potato chips",
                                  "Orange juice", "Premium gasoline", "Dish soap"])
def test_lookalikes_are_not_matched(text):
    assert items.match(text) is None


@pytest.mark.parametrize("quantity, unit, target, expected", [
    (20, "oz", "lb", 1.25), (1, "kg", "lb", 2.20462), (0.5, "gal", "gal", 0.5), (2, "qt", "gal", 0.5),
    (18, "ct", "doz", 1.5), (1, "dozen", "doz", 1.0), (640, "kWh", "kwh", 640.0),
])
def test_unit_conversion(quantity, unit, target, expected):
    assert items.to_unit(quantity, unit, target) == pytest.approx(expected)


def test_units_from_another_dimension_do_not_convert():
    assert items.to_unit(1, "gal", "lb") is None


PURCHASES = """date,item,price,quantity,unit
2025-11-08,Large eggs,3.60,18,ct
2026-10-10,Large eggs,3.00,1,doz
2026-10-10,Oat milk,4.99,0.5,gal
2026-10-10,Whole milk,4.00,1,box
2025-10-10,Whole milk,4.00,1,gal
"""


@pytest.fixture
def bls_prices():
    months = pd.date_range("2025-09-01", "2026-10-01", freq="MS")
    frame = pd.DataFrame({"APU0000708111": 3.00, "APU0000709112": 4.00}, index=months)
    frame.loc[pd.Timestamp("2026-10-01"), "APU0000708111"] = 2.40
    frame.loc[pd.Timestamp("2025-10-01"), :] = float("nan")
    return frame


def test_compare_converts_to_the_bls_unit_and_reports_the_gap(bls_prices):
    compared = items.compare(items.read_purchases(io.StringIO(PURCHASES)), bls_prices)
    first = compared.iloc[0]
    assert first["you_paid"] == pytest.approx(2.40)          # $3.60 for 18 eggs is $2.40 a dozen
    assert first["bls_average"] == 3.00 and first["gap"] == pytest.approx(-0.20)


def test_every_row_that_cannot_be_compared_says_why(bls_prices):
    compared = items.compare(items.read_purchases(io.StringIO(PURCHASES)), bls_prices)
    assert list(compared["status"]) == ["ok", "ok", "no_match", "bad_unit", "no_bls_price"]


def test_price_change_is_compared_with_the_bls_change_over_the_same_months(bls_prices):
    compared = items.compare(items.read_purchases(io.StringIO(PURCHASES)), bls_prices)
    moved = items.changes(compared).iloc[0]
    assert moved["your_change"] == pytest.approx(3.00 / 2.40 - 1)     # +25%
    assert moved["bls_change"] == pytest.approx(2.40 / 3.00 - 1)      # -20%


def test_a_file_without_the_needed_columns_is_rejected():
    with pytest.raises(ValueError, match="quantity"):
        items.read_purchases(io.StringIO("date,item,price\n2026-01-01,eggs,3\n"))


RECEIPT = """
   FRESH MARKET #204
   10/17/2026  14:32
LG EGGS 12CT              2.89 F
WHOLE MILK GAL            4.49 F
BANANAS 2.31 LB @ 0.59    1.36
SUBTOTAL                  8.74
TAX                       0.00
TOTAL                     8.74
VISA ************1234     8.74
"""


def test_receipt_text_becomes_item_lines_without_totals_or_payment_lines():
    draft = ocr.parse(RECEIPT)
    assert draft["date"] == "2026-10-17"
    assert draft["lines"] == [
        {"item": "LG EGGS 12CT", "price": 2.89},
        {"item": "WHOLE MILK GAL", "price": 4.49},
        {"item": "BANANAS 2.31 LB @ 0.59", "price": 1.36},
    ]


def test_receipt_with_no_date_or_prices_gives_an_empty_draft():
    assert ocr.parse("THANK YOU FOR SHOPPING") == {"date": None, "lines": []}
