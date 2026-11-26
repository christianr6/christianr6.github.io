import numpy as np
import pandas as pd
import pytest

from mule_rings import model, rings
from mule_rings.data import Pattern


def test_threshold_is_the_cut_with_the_best_f1():
    scores = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    labels = np.array([0, 0, 1, 1, 1])
    assert model.best_threshold(scores, labels) == pytest.approx(0.3)


def test_score_counts_precision_recall_and_f1():
    scores = np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05])
    labels = np.array([1, 0, 1, 1, 0, 0])
    result = model.score(scores, labels, threshold=0.5)
    assert (result["flagged"], result["caught"], result["laundering"]) == (3, 2, 3)
    assert result["precision"] == pytest.approx(2 / 3) and result["recall"] == pytest.approx(2 / 3)
    assert result["f1"] == pytest.approx(2 / 3)
    assert result["base_rate"] == pytest.approx(0.5)


def test_flagging_nothing_scores_zero_not_an_error():
    result = model.score(np.array([0.1, 0.2]), np.array([1, 0]), threshold=0.9)
    assert result["flagged"] == 0 and result["f1"] == 0.0


def flagged(*arrows):
    return pd.DataFrame(
        [{"src": s, "dst": d, "is_laundering": label, "amount_paid": 100.0} for s, d, label in arrows],
        columns=["src", "dst", "is_laundering", "amount_paid"],
    )


def test_linked_accounts_form_one_ring_and_separate_groups_stay_separate():
    found = rings.find(flagged((1, 2, 1), (2, 3, 1), (3, 1, 1), (7, 8, 1), (8, 9, 0), (20, 21, 0)))
    assert found["ring"].tolist() == [0, 0, 0, 1, 1, -1]     # a pair alone is not a ring


def test_direction_does_not_matter_for_grouping():
    found = rings.find(flagged((1, 2, 1), (3, 2, 1)))        # two payers into one account: fan-in
    assert (found["ring"] == 0).all()


def test_self_transfers_join_nothing():
    found = rings.find(flagged((1, 1, 0), (1, 2, 1), (2, 3, 1)))
    assert found["ring"].tolist() == [-1, 0, 0]


def test_ring_summary_reports_size_and_purity():
    summary = rings.summarize(rings.find(flagged((1, 2, 1), (2, 3, 1), (3, 4, 0))))
    only = summary.iloc[0]
    assert (only["accounts"], only["transactions"], only["laundering"]) == (4, 3, 2)
    assert only["purity"] == pytest.approx(2 / 3)


def test_no_flags_means_no_rings():
    assert rings.summarize(rings.find(flagged())).empty


def test_a_labeled_ring_is_caught_when_half_its_transactions_are_flagged():
    scored = pd.DataFrame({"key": list("abcdef"), "flagged": [True, True, False, False, False, True]})
    patterns = [Pattern(1, "CYCLE", frozenset("abc")), Pattern(2, "FAN-IN", frozenset("def")),
                Pattern(3, "STACK", frozenset(["a", "zz", "yy"]))]   # mostly outside the scored period
    matched = rings.against_patterns(scored, patterns)
    assert matched[["pattern", "flagged", "caught"]].values.tolist() == [[1, 2, True], [2, 1, False]]


def test_results_by_kind():
    matched = pd.DataFrame({
        "pattern": [1, 2, 3], "kind": ["CYCLE", "CYCLE", "STACK"], "transactions": [4, 4, 3],
        "flagged": [4, 1, 3], "share_flagged": [1.0, 0.25, 1.0], "caught": [True, False, True],
    })
    table = rings.by_kind(matched).set_index("kind")
    assert table.loc["CYCLE", "caught_share"] == 0.5 and table.loc["STACK", "caught_share"] == 1.0
