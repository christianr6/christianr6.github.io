import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inflation import basket  # noqa: E402


def payload(series: dict[str, dict[str, str]], status="REQUEST_SUCCEEDED", message=()):
    """A BLS-shaped answer from {series id: {"2026-09": "123.4"}}."""
    blocks = []
    for sid, points in series.items():
        data = [{"year": month[:4], "period": "M" + month[5:7], "value": value} for month, value in points.items()]
        blocks.append({"seriesID": sid, "data": data})
    return {"status": status, "message": list(message), "Results": {"series": blocks}}


@pytest.fixture
def prices() -> pd.DataFrame:
    """Two years of made-up index levels: all items +4%, groceries +10%, rent flat, gasoline -20%."""
    months = pd.date_range("2025-01-01", "2026-12-01", freq="MS")
    year_two = months >= pd.Timestamp("2026-01-01")
    frame = pd.DataFrame(index=months)
    frame[basket.ALL_ITEMS] = 100.0
    frame.loc[year_two, basket.ALL_ITEMS] = 104.0
    for key, later in (("groceries", 110.0), ("rent", 100.0), ("gasoline", 80.0)):
        series = basket.BY_KEY[key].series
        frame[series] = 100.0
        frame.loc[year_two, series] = later
    return frame
