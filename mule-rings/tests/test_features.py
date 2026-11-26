import numpy as np

from mule_rings import features


def feature_row(transactions, table, sender, receiver, nth=0):
    names = transactions.attrs["accounts"]
    mask = (names[transactions["src"]] == sender) & (names[transactions["dst"]] == receiver)
    return table[mask].iloc[nth]


def test_degree_counts_different_partners_and_txn_counts_every_payment(transactions):
    table = features.build(transactions)
    d_to_e = feature_row(transactions, table, "001_D", "001_E")
    assert d_to_e["src_out_txn"] == 3        # D pays E twice and F once
    assert d_to_e["src_out_degree"] == 2     # two different accounts
    assert d_to_e["src_in_txn"] == 1         # F pays D once
    assert d_to_e["pair_txn"] == 2


def test_reciprocal_marks_money_that_flows_both_ways(transactions):
    table = features.build(transactions)
    assert feature_row(transactions, table, "001_D", "001_F")["reciprocal"] == 1   # F later pays D
    assert feature_row(transactions, table, "001_D", "001_E")["reciprocal"] == 0


def test_pass_through_timing_in_the_ring(transactions):
    table = features.build(transactions)
    b_to_c = feature_row(transactions, table, "001_B", "001_C")
    assert b_to_c["src_gap_last_in"] == 30     # B received 30 minutes before paying on
    assert b_to_c["dst_gap_next_out"] == 30    # C pays on 30 minutes later
    assert b_to_c["src_in_24h"] == 1


def test_no_earlier_or_later_payment_is_a_large_sentinel_not_zero(transactions):
    table = features.build(transactions)
    a_to_b = feature_row(transactions, table, "001_A", "001_B")
    assert a_to_b["src_gap_prev_out"] == features._NEVER
    assert a_to_b["src_gap_last_in"] == features._NEVER   # A receives only later


def test_windows_cover_24_hours_and_no_more(transactions):
    table = features.build(transactions)
    second = feature_row(transactions, table, "001_D", "001_E", nth=1)   # next morning, 20h later
    assert second["src_out_24h"] == 3          # both of yesterday's payments plus this one
    late = feature_row(transactions, table, "001_F", "001_D")           # two days later
    assert late["src_in_24h"] == 0


def test_self_transfers_are_flagged_and_never_reciprocal(transactions):
    table = features.build(transactions)
    own = table[table["self_transfer"] == 1]
    assert len(own) == 1 and own.iloc[0]["reciprocal"] == 0


def test_features_never_read_the_label(transactions):
    flipped = transactions.copy()
    flipped["is_laundering"] = 1 - flipped["is_laundering"]
    flipped.attrs = transactions.attrs
    before, after = features.build(transactions), features.build(flipped)
    numeric = [c for c in before.columns if c not in features.CATEGORICAL]
    assert np.array_equal(before[numeric].to_numpy(), after[numeric].to_numpy())


def test_feature_table_lines_up_with_the_transactions(transactions):
    table = features.build(transactions)
    assert list(table.columns) == features.RAW + features.GRAPH
    assert len(table) == len(transactions) and table.index.equals(transactions.index)
