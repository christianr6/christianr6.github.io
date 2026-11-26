import pandas as pd
from conftest import row, write

from mule_rings import data, split


def test_an_account_is_a_bank_plus_a_number(transactions):
    names = transactions.attrs["accounts"]
    first = transactions.iloc[0]
    assert names[first["src"]] == "001_A" and names[first["dst"]] == "001_B"


def test_the_same_account_number_at_two_banks_is_two_accounts(tmp_path):
    df = data.read_transactions(write(tmp_path, [
        row("2022/09/01 09:00", "A", "B", bank_a="001"),
        row("2022/09/01 09:01", "A", "B", bank_a="009"),
    ]))
    assert df["src"].nunique() == 2


def test_rows_are_sorted_by_time_and_minutes_count_from_the_first(tmp_path):
    df = data.read_transactions(write(tmp_path, [
        row("2022/09/01 10:00", "A", "B"), row("2022/09/01 09:00", "C", "D"),
    ]))
    assert list(df["minute"]) == [0, 60]
    assert list(df["from_account"]) == ["C", "A"]


def test_patterns_file_is_parsed_into_rings(patterns):
    assert [(p.kind, len(p.keys)) for p in patterns] == [("CYCLE", 3), ("FAN-OUT", 1)]


def test_pattern_transactions_match_rows_in_the_csv(transactions, patterns):
    cycle = patterns[0]
    matched = transactions[transactions["key"].isin(cycle.keys)]
    assert len(matched) == 3 and matched["is_laundering"].all()


def busy_days(tail_label=1):
    rows = []
    for day in range(1, 6):
        for minute in range(40):
            rows.append(row(f"2022/09/0{day} 10:{minute:02d}", f"S{minute}", f"R{minute}"))
    rows += [row("2022/09/06 10:00", "X", "Y", label=tail_label), row("2022/09/07 10:00", "Y", "Z", label=tail_label)]
    return rows


def test_the_thin_trailing_days_are_dropped_and_reported(tmp_path):
    df = data.read_transactions(write(tmp_path, busy_days()))
    kept, report = split.primary_period(df)
    assert kept["ts"].max() < pd.Timestamp("2022-09-06")
    assert report == {"last_day_kept": "2022-09-05", "dropped_transactions": 2,
                      "dropped_laundering": 2, "dropped_laundering_share": 1.0}


def test_whole_days_go_to_one_part_in_time_order(tmp_path):
    kept, _ = split.primary_period(data.read_transactions(write(tmp_path, busy_days())))
    parts = split.by_time(kept)
    assert list(parts.days.values()) == ["train", "train", "train", "valid", "test"]
    assert kept["ts"][parts.train].max() < kept["ts"][parts.valid].min() < kept["ts"][parts.test].min()
    assert parts.train.sum() + parts.valid.sum() + parts.test.sum() == len(kept)
