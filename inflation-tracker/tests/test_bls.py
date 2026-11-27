import math

import pandas as pd
import pytest
from conftest import payload

from inflation import bls


def test_values_become_numbers_indexed_by_month():
    frame = bls.parse(payload({"A": {"2026-08": "101.5", "2026-09": "102.0"}}))
    assert frame.loc[pd.Timestamp("2026-09-01"), "A"] == 102.0
    assert list(frame.index) == [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")]


def test_a_month_bls_did_not_publish_is_missing_not_zero():
    frame = bls.parse(payload({"A": {"2025-09": "100", "2025-10": "-", "2025-11": "101"}}))
    assert math.isnan(frame.loc[pd.Timestamp("2025-10-01"), "A"])


def test_a_skipped_month_still_gets_a_row_so_lags_line_up():
    frame = bls.parse(payload({"A": {"2025-09": "100", "2025-11": "101"}}))
    assert len(frame) == 3 and math.isnan(frame["A"].iloc[1])


def test_annual_averages_are_dropped():
    answer = payload({"A": {"2025-12": "100"}})
    answer["Results"]["series"][0]["data"].append({"year": "2025", "period": "M13", "value": "99"})
    assert len(bls.parse(answer)) == 1


def test_an_id_with_no_data_is_left_out():
    assert list(bls.parse(payload({"A": {"2026-09": "1"}, "GONE": {}})).columns) == ["A"]


def test_a_refused_request_raises_with_the_reason():
    with pytest.raises(bls.BlsError, match="daily threshold"):
        bls.parse(payload({}, status="REQUEST_NOT_PROCESSED", message=["daily threshold reached"]))


class Http:
    def __init__(self, answers):
        self.answers, self.requests = list(answers), []

    def post(self, url, json, timeout):
        self.requests.append((url, json))
        answer = self.answers.pop(0)

        class Response:
            def raise_for_status(self): pass
            def json(self): return answer
        return Response()


def test_answers_are_cached_so_the_daily_quota_is_not_spent_twice(tmp_path, monkeypatch):
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    http = Http([payload({"A": {"2026-09": "1"}})])
    client = bls.Bls(cache_dir=tmp_path, http=http)
    first = client.fetch(["A"], 2026, 2026)
    second = client.fetch(["A"], 2026, 2026)
    assert len(http.requests) == 1 and first.equals(second)


def test_a_refused_answer_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    refused = payload({}, status="REQUEST_NOT_PROCESSED", message=["daily threshold reached"])
    http = Http([refused, payload({"A": {"2026-09": "1"}})])
    client = bls.Bls(cache_dir=tmp_path, http=http)
    with pytest.raises(bls.BlsError):
        client.fetch(["A"], 2026, 2026)
    assert client.fetch(["A"], 2026, 2026).loc[pd.Timestamp("2026-09-01"), "A"] == 1.0


def test_long_lists_are_split_to_fit_the_keyless_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    ids = [f"S{i:02d}" for i in range(30)]
    http = Http([payload({i: {"2026-09": "1"} for i in ids[:25]}), payload({i: {"2026-09": "1"} for i in ids[25:]})])
    frame = bls.Bls(cache_dir=tmp_path, http=http).fetch(ids, 2026, 2026)
    assert [len(body["seriesid"]) for _, body in http.requests] == [25, 5]
    assert frame.shape == (1, 30)


def test_a_key_switches_to_the_registered_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("BLS_API_KEY", "abc")
    http = Http([payload({"A": {"2026-09": "1"}})])
    bls.Bls(cache_dir=tmp_path, http=http).fetch(["A"], 2026, 2026)
    url, body = http.requests[0]
    assert url == bls.URL_V2 and body["registrationkey"] == "abc"
