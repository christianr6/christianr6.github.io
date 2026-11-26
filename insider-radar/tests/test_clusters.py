import pandas as pd
import pytest
from conftest import filing

from insider_radar import clusters as cl

PARAMS = cl.ClusterParams()


def find(conn, params=PARAMS):
    return cl.run(conn, params)[1]


def test_three_insiders_in_the_window_make_one_cluster(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-10", 12), filing("2024-03-20", 13)])
    found = find(conn)
    assert len(found) == 1
    row = found.iloc[0]
    assert row["n_insiders"] == 3
    assert row["ticker"] == "TEST"
    assert row["total_value"] == pytest.approx(3 * 1000 * 50.0)


def test_trigger_is_the_day_the_third_insider_filed(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-10", 12), filing("2024-03-20", 13)])
    row = find(conn).iloc[0]
    assert row["trigger_date"] == pd.Timestamp("2024-03-20")
    assert row["start_date"] == pd.Timestamp("2024-03-01")


def test_two_insiders_are_not_enough(load):
    assert find(load([filing("2024-03-01", 11), filing("2024-03-10", 12)])).empty


def test_one_insider_buying_three_times_is_not_a_cluster(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-10", 11), filing("2024-03-20", 11)])
    assert find(conn).empty


def test_filings_spread_wider_than_the_window_do_not_cluster(load):
    # 30-day window: Mar 1 and Mar 31 are exactly 30 days apart, so Mar 1 has aged out.
    conn = load([filing("2024-03-01", 11), filing("2024-03-15", 12), filing("2024-03-31", 13)])
    assert find(conn).empty


def test_filings_just_inside_the_window_cluster(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-15", 12), filing("2024-03-30", 13)])
    assert len(find(conn)) == 1


def test_different_companies_are_never_mixed(load):
    conn = load([
        filing("2024-03-01", 11, issuer=1000),
        filing("2024-03-02", 12, issuer=1000),
        filing("2024-03-03", 13, issuer=2000, ticker="OTHR"),
    ])
    assert find(conn).empty


def test_sales_are_ignored(load):
    conn = load([
        filing("2024-03-01", 11), filing("2024-03-02", 12),
        filing("2024-03-03", 13, code="S", acq="D"),
    ])
    assert find(conn).empty


def test_grants_and_other_codes_are_ignored(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-02", 12), filing("2024-03-03", 13, code="A")])
    assert find(conn).empty


def test_amendments_are_ignored(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-02", 12), filing("2024-03-03", 13, form="4/A")])
    assert find(conn).empty


def test_prescheduled_plan_trades_are_dropped_by_default(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-02", 12), filing("2024-03-03", 13, plan="1")])
    assert find(conn).empty
    assert len(find(conn, cl.ClusterParams(exclude_10b5_1=False))) == 1


def test_missing_plan_flag_counts_as_not_a_plan(load):
    filings = [filing("2022-03-01", 11), filing("2022-03-02", 12), filing("2022-03-03", 13)]
    assert len(find(load(filings, with_plan_flag=False))) == 1


def test_ten_percent_owners_are_excluded_unless_asked_for(load):
    conn = load([
        filing("2024-03-01", 11), filing("2024-03-02", 12),
        filing("2024-03-03", 13, relationship="TenPercentOwner"),
    ])
    assert find(conn).empty
    wider = cl.ClusterParams(roles=("officer", "director", "tenpercentowner"))
    assert len(find(conn, wider)) == 1


def test_a_director_who_is_also_a_ten_percent_owner_counts(load):
    conn = load([
        filing("2024-03-01", 11), filing("2024-03-02", 12),
        filing("2024-03-03", 13, relationship="Director,TenPercentOwner"),
    ])
    assert len(find(conn)) == 1


def test_small_purchases_are_dropped(load):
    conn = load([
        filing("2024-03-01", 11), filing("2024-03-02", 12),
        filing("2024-03-03", 13, shares=10, price=5.0),  # $50
    ])
    assert find(conn).empty


def test_equity_swaps_are_dropped(load):
    conn = load([filing("2024-03-01", 11), filing("2024-03-02", 12), filing("2024-03-03", 13, swap="1")])
    assert find(conn).empty


def test_a_joint_filing_counts_as_one_insider(load):
    conn = load([
        filing("2024-03-01", 11),
        filing("2024-03-02", 12, extra_owners=((13, "Director"), (14, "Officer"))),
    ])
    assert find(conn).empty


def test_a_long_burst_is_one_cluster_not_several(load):
    conn = load([
        filing("2024-03-01", 11), filing("2024-03-05", 12), filing("2024-03-10", 13),
        filing("2024-03-20", 14), filing("2024-03-28", 15),
    ])
    found = find(conn)
    assert len(found) == 1
    assert found.iloc[0]["n_insiders"] == 5
    assert found.iloc[0]["trigger_date"] == pd.Timestamp("2024-03-10")
    assert found.iloc[0]["end_date"] == pd.Timestamp("2024-03-28")


def test_two_bursts_far_apart_are_two_clusters(load):
    conn = load([
        filing("2024-01-02", 11), filing("2024-01-03", 12), filing("2024-01-04", 13),
        filing("2024-06-03", 11), filing("2024-06-04", 12), filing("2024-06-05", 13),
    ])
    found = find(conn)
    assert list(found["trigger_date"]) == [pd.Timestamp("2024-06-05"), pd.Timestamp("2024-01-04")]


def test_filing_days_separates_same_day_bursts_from_spread_out_buying(load):
    conn = load([
        filing("2024-03-05", 11), filing("2024-03-05", 12), filing("2024-03-05", 13),
        filing("2024-03-01", 21, issuer=2000, ticker="OTHR"),
        filing("2024-03-08", 22, issuer=2000, ticker="OTHR"),
        filing("2024-03-15", 23, issuer=2000, ticker="OTHR"),
    ])
    days = find(conn).set_index("ticker")["filing_days"]
    assert days["TEST"] == 1 and days["OTHR"] == 3


def test_members_of_returns_the_purchases_behind_a_cluster(load):
    conn = load([
        filing("2024-03-01", 11), filing("2024-03-10", 12), filing("2024-03-20", 13),
        filing("2024-09-01", 14),
    ])
    purchases, found = cl.run(conn, PARAMS)
    members = cl.members_of(purchases, found.iloc[0])
    assert sorted(members["insider_cik"]) == ["11", "12", "13"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("aapl", "AAPL"), (" BRK.B ", "BRK.B"), ("NYSE: ABC", "ABC"), ("ABC, ABC.WS", "ABC"),
        ("(XYZ)", "XYZ"), ("NONE", None), ("N/A", None), ("", None), (None, None),
        ("TOOLONGSYMBOL", None), ("1234", None),
    ],
)
def test_normalize_ticker(raw, expected):
    assert cl.normalize_ticker(raw) == expected
