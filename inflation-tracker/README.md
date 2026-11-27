# Personal inflation tracker

Official inflation describes the average household. This works out yours:
enter what you spend by category and it re-weights the official price
indexes by your own mix. It also compares what you paid for specific items
with U.S. average prices, starting from a spreadsheet or a receipt photo.

```
your spending by category ─→ shares ─┐
BLS category price indexes ──────────┴→ your rate vs. official CPI

your purchases (CSV or receipt photo) ─→ unit prices ─→ vs. BLS average price, same month
```

## Does the method work?

Checked on BLS data on 2026-11-27. If you give the tool the official CPI
weights (BLS relative importance, December 2025), it should give back
official CPI. It does: across the 20 months from January 2025 to September
2026 that have a 12-month comparison, the rebuilt rate is within 0.03
percentage points of the published one every month. For September 2026 it
gives 3.72% against the official 3.74%.

That check used 12 broad categories, with transportation as a single line.
One finer line the tool offers, "Vehicles and parts", could not be downloaded
in the build environment and is untested.

## Example

A made-up renter who drives (the numbers in `sample/spending.csv`), for the
12 months to September 2026:

| | Rate |
|---|---|
| This household | +4.6% |
| Official CPI | +3.7% |

Gasoline rose 34.9% and is 5.4% of this household's spending, which alone
adds 1.87 points. Rent rose 2.8% and adds 1.16.

## Two formulas

Which one applies depends on when your spending figures are from.

| Your amounts describe | Formula | Name |
|---|---|---|
| A year ago | `sum(share × price_now / price_then) − 1` | Laspeyres |
| Today | `1 / sum(share × price_then / price_now) − 1` | Paasche |

A fixed payment such as a fixed-rate mortgage counts as a 0% change.

## Receipt photos: a draft, not an answer

The original idea leaned on Tesseract OCR. I tested it on a receipt rendered
as an image:

| Image | Item lines read correctly |
|---|---|
| Clean, sharp | 3 of 3 |
| Faded, blurred, speckled (still easy for a person to read) | 0 of 3 |

On the worn copy it read "LG EGGS 12CT" as "LG £GG6S°.12CT". These were
generated images, not photos of real thermal receipts, which are usually
worse. So the photo path produces a draft table to correct by hand, and a
receipt never says "one dozen" in a way a program can trust: quantity and
unit are yours to fill in.

## Run it

```bash
pip install -r requirements.txt

streamlit run app.py                              # dashboard
python -m inflation spend sample/spending.csv     # your rate vs. official CPI
python -m inflation items sample/purchases.csv    # your prices vs. BLS averages
python -m inflation receipt photo.jpg             # draft from a photo (needs Tesseract)
python -m pytest                                  # tests; no network
```

Without a key, BLS allows 25 requests a day per network address, shared with
everyone behind it. Answers are cached for a day. A free key from
https://data.bls.gov/registrationEngine/ raises the limit to 500:

```bash
export BLS_API_KEY="..."
```

## Limits

- **National averages, not your prices.** Your rent, store and city differ
  from the U.S. city average.
- **No substitution.** If you switched to cheaper brands, your true cost rose
  less than this says.
- **Owning a home.** CPI prices owned homes at what they would rent for. With
  a fixed mortgage, enter the payment as a fixed payment instead.
- **October 2025 is missing.** BLS has no figure for that month, so neither
  it nor October 2026 has a 12-month rate. The tool reports the latest month that does.
- **Item prices are a rough guide.** BLS says its average prices measure
  levels and are not designed to measure change. Brand, size and store explain most gaps.
- **Short item list.** BLS prices only a few dozen exact items. Ten of the
  19 in this tool's catalog could not be downloaded in the build environment and are untested.

## Layout

| File | Job |
|---|---|
| `inflation/bls.py` | BLS API client with a one-day cache |
| `inflation/basket.py` | categories, official weights, the two formulas |
| `inflation/items.py` | item matching, unit conversion, price comparison |
| `inflation/ocr.py` | receipt photo to draft table |
| `app.py` | Streamlit dashboard |

Data: U.S. Bureau of Labor Statistics (CPI-U, U.S. city average, not
seasonally adjusted; CPI average price data).
