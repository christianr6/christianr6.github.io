"""A tiny, hand-made set of transactions with one obvious ring."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mule_rings import data  # noqa: E402

HEADER = "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering"


def row(stamp, a, b, amount=100.0, fmt="ACH", label=0, bank_a="001", bank_b="001", currency="US Dollar", received=None):
    return (f"{stamp},{bank_a},{a},{bank_b},{b},{amount if received is None else received:.2f},{currency},"
            f"{amount:.2f},{currency},{fmt},{label}")


# A pays B, B pays C within the hour, C pays A back: a cycle. Then ordinary traffic.
ROWS = [
    row("2022/09/01 09:00", "A", "B", 5000, label=1),
    row("2022/09/01 09:30", "B", "C", 4900, label=1),
    row("2022/09/01 10:00", "C", "A", 4800, label=1),
    row("2022/09/01 12:00", "D", "E", 20, fmt="Cheque"),
    row("2022/09/01 12:05", "D", "F", 30, fmt="Cheque"),
    row("2022/09/02 08:00", "D", "E", 25, fmt="Cheque"),
    row("2022/09/02 09:00", "E", "E", 10, fmt="Reinvestment"),   # a self-transfer
    row("2022/09/03 15:00", "F", "D", 40, fmt="Credit Card"),
]
PATTERNS = """BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 3 hops
2022/09/01 09:00,001,A,001,B,5000.00,US Dollar,5000.00,US Dollar,ACH,1
2022/09/01 09:30,001,B,001,C,4900.00,US Dollar,4900.00,US Dollar,ACH,1
2022/09/01 10:00,001,C,001,A,4800.00,US Dollar,4800.00,US Dollar,ACH,1
END LAUNDERING ATTEMPT - CYCLE

BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 2-degree Fan-Out
2022/09/05 09:00,001,X,001,Y,1.00,US Dollar,1.00,US Dollar,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT
"""


def write(tmp_path, rows=ROWS):
    path = tmp_path / "HI-Small_Trans.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n")
    return path


@pytest.fixture
def transactions(tmp_path) -> pd.DataFrame:
    return data.read_transactions(write(tmp_path))


@pytest.fixture
def patterns(tmp_path):
    path = tmp_path / "HI-Small_Patterns.txt"
    path.write_text(PATTERNS)
    return data.read_patterns(path)
