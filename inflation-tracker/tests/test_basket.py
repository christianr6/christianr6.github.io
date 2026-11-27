import pandas as pd
import pytest

from inflation import basket

SEPT = pd.Timestamp("2026-09-01")


def test_official_weights_cover_the_whole_basket():
    assert sum(basket.OFFICIAL.values()) == pytest.approx(100.0, abs=0.01)
    assert "rent" not in basket.OFFICIAL and "fixed" not in basket.OFFICIAL   # inside shelter / not a CPI line


def test_dollars_become_shares_and_zero_lines_drop_out():
    assert basket.shares({"groceries": 300, "rent": 900, "gasoline": 0}) == {"groceries": 0.25, "rent": 0.75}


@pytest.mark.parametrize("bad", [{"snacks": 10}, {"groceries": -5}, {"groceries": 0}])
def test_bad_spending_is_rejected(bad):
    with pytest.raises(ValueError):
        basket.shares(bad)


def test_rate_with_spending_from_a_year_ago(prices):
    ratios = basket.price_ratios(prices)
    rate = basket.personal_rate({"groceries": 0.5, "rent": 0.5}, ratios, "then")
    assert rate[SEPT] == pytest.approx(0.5 * 1.10 + 0.5 * 1.00 - 1)        # +5.0%


def test_rate_with_spending_from_now_is_lower_when_prices_diverge(prices):
    ratios = basket.price_ratios(prices)
    rate = basket.personal_rate({"groceries": 0.5, "rent": 0.5}, ratios, "now")
    assert rate[SEPT] == pytest.approx(1 / (0.5 / 1.10 + 0.5 / 1.00) - 1)  # +4.76%


def test_a_fixed_payment_pulls_the_rate_toward_zero(prices):
    ratios = basket.price_ratios(prices)
    assert basket.personal_rate({"groceries": 0.5, "fixed": 0.5}, ratios)[SEPT] == pytest.approx(0.05)
    assert basket.personal_rate({"fixed": 1.0}, ratios)[SEPT] == pytest.approx(0.0)


def test_falling_prices_give_a_negative_rate(prices):
    ratios = basket.price_ratios(prices)
    assert basket.personal_rate({"gasoline": 1.0}, ratios)[SEPT] == pytest.approx(-0.20)


def test_official_rate_is_the_all_items_change(prices):
    assert basket.official_rate(basket.price_ratios(prices))[SEPT] == pytest.approx(0.04)


def test_no_rate_for_a_month_whose_year_ago_value_is_missing(prices):
    prices.loc[pd.Timestamp("2025-10-01"), :] = float("nan")       # as with October 2025 in the real data
    ratios = basket.price_ratios(prices)
    rate = basket.personal_rate({"groceries": 1.0}, ratios)
    assert pd.Timestamp("2026-10-01") not in rate.index
    assert pd.Timestamp("2026-09-01") in rate.index and pd.Timestamp("2026-11-01") in rate.index


def test_one_missing_category_blanks_the_month_instead_of_shrinking_the_basket(prices):
    prices.loc[SEPT, basket.BY_KEY["rent"].series] = float("nan")
    rate = basket.personal_rate({"groceries": 0.5, "rent": 0.5}, basket.price_ratios(prices))
    assert SEPT not in rate.index


def test_contributions_add_up_to_the_rate(prices):
    ratios = basket.price_ratios(prices)
    share = {"groceries": 0.3, "rent": 0.5, "gasoline": 0.2}
    table = basket.contributions(share, ratios, SEPT)
    assert table["points"].sum() == pytest.approx(basket.personal_rate(share, ratios)[SEPT])
    assert table.iloc[0]["key"] == "groceries" and table.iloc[-1]["key"] == "gasoline"


def test_latest_common_month_skips_months_only_one_series_has(prices):
    ratios = basket.price_ratios(prices)
    mine = basket.personal_rate({"groceries": 1.0}, ratios).drop(pd.Timestamp("2026-12-01"))
    assert basket.latest_common_month(mine, basket.official_rate(ratios)) == pd.Timestamp("2026-11-01")
