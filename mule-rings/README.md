# Money mule ring detector

Finds money laundering in bank transactions by looking at who pays whom, not
at one transaction at a time, then groups what it flags into rings.

```
5M transactions → drop leaky days → graph features → boosted trees → flagged transfers → rings
                                     (who pays whom,                   (checked against the
                                      how fast money moves on)          simulator's answer key)
```

## Result

Data: IBM's synthetic AMLworld set, HI-Small: 5,078,345 transactions between
515,088 accounts, of which 5,177 are laundering (1 in 981). Trained on the
first six days, threshold picked on the next two, scored on the last two
(862,792 transactions, 956 laundering).

| Model | Flags that are right | Laundering caught | F1 |
|---|---|---|---|
| Single-transaction features | 13% | 16% | 0.14 |
| Plus graph features | 88% | 45% | 0.59 |

- **Graph features carry the result.** Amount, currency and payment format
  alone find little. Adding how connected each account is and how quickly
  money moves on lifts F1 from 0.14 to 0.59.
- **Flags are mostly right.** 428 of the 488 transactions it flagged in the
  test days are laundering. Guessing would be right 0.1% of the time.
- **It misses more than half.** 45% recall means 528 laundering transactions
  went unflagged.
- **Rings:** the flags form 82 groups of three or more accounts, and 81 of
  them are mostly real laundering. Of the 86 labeled rings with at least three
  transactions in the test days, 75 had half or more of those transactions flagged.

## The leak

The simulator keeps finishing laundering chains after normal activity stops.
After 2022-09-10 only 1,108 transactions remain and 59% of them are
laundering, against 0.1% before. A model can score well by learning "late
means guilty". Those days are dropped before training, and the split is by
time so the model is always tested on days after the ones it learned from.

## Run it

```bash
pip install -r requirements.txt

# Download HI-Small_Trans.csv (475 MB) and HI-Small_Patterns.txt into data/ from
# https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml

python -m mule_rings          # about 5 minutes on 4 CPU cores; writes results/summary.json
streamlit run app.py          # dashboard; reads results/, not the raw data
python -m pytest              # tests on a tiny hand-made ledger
```

The dashboard works straight from the committed `results/summary.json`.

## Limits

- **The data is synthetic.** Labels are complete because a simulator wrote
  them. Real bank data has unlabeled laundering and messier behaviour, so these
  numbers do not transfer to a real bank.
- **The features use hindsight.** They read the structure of all ten days,
  including later transactions, as an analyst reviewing a batch would. They
  never read a label. A system scoring each payment as it arrives would know
  less and score lower.
- **Counting rings flatters the model.** The labeled patterns are the tidy
  ones. Laundering outside the pattern file is harder, which is why 87% of
  labeled rings are caught but only 45% of laundering transactions.
- **One dataset, one split.** Nothing here was repeated across seeds or the
  larger IBM sets.

## Layout

| File | Job |
|---|---|
| `mule_rings/data.py` | load transactions and the labeled patterns |
| `mule_rings/split.py` | drop the leaky days; split by time |
| `mule_rings/features.py` | single-transaction and graph features |
| `mule_rings/model.py` | boosted trees and scoring |
| `mule_rings/rings.py` | group flags into rings; compare with labels |
| `mule_rings/gnn.py` | graph neural network, for comparison |
| `app.py` | Streamlit dashboard |

Data: E. Altman et al., "Realistic Synthetic Financial Transactions for
Anti-Money Laundering Models", NeurIPS 2023 (arXiv 2306.16424).
