"""Command line.

    python -m inflation spend sample/spending.csv          your rate vs. official CPI
    python -m inflation items sample/purchases.csv         your prices vs. BLS averages
    python -m inflation receipt photo.jpg                  draft item list from a receipt photo
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import basket, bls, items, ocr

HISTORY_START = 2023


def load_prices(client: bls.Bls) -> pd.DataFrame:
    return client.fetch(basket.SERIES, HISTORY_START)


def read_spending(path: str) -> dict[str, float]:
    """A CSV with columns category, amount. Categories are the keys in basket.CATEGORIES."""
    frame = pd.read_csv(path)
    frame.columns = [column.strip().lower() for column in frame.columns]
    return {str(row.category).strip(): float(row.amount) for row in frame.itertuples(index=False)}


def cmd_spend(args) -> int:
    spending = read_spending(args.file)
    share = basket.shares(spending)
    ratios = basket.price_ratios(load_prices(bls.Bls()))
    missing = [basket.BY_KEY[key].label for key in share if key not in ratios]
    if missing:
        print(f"No price data for: {', '.join(missing)}", file=sys.stderr)
        return 1
    mine = basket.personal_rate(share, ratios, args.spending_from)
    official = basket.official_rate(ratios)
    month = basket.latest_common_month(mine, official)
    print(f"12 months to {month:%B %Y}")
    print(f"  your rate      {mine[month]:+.1%}")
    print(f"  official CPI   {official[month]:+.1%}")
    print(f"  gap            {(mine[month] - official[month]) * 100:+.1f} points\n")
    table = basket.contributions(share, ratios, month)
    for row in table.itertuples(index=False):
        print(f"  {row.label:34s} {row.share:6.1%} of spending  {row.change:+6.1%}  adds {row.points * 100:+.2f} pts")
    return 0


def cmd_items(args) -> int:
    purchases = items.read_purchases(args.file)
    first_year = min(int(purchases["date"].dt.year.min()), HISTORY_START)
    prices = bls.Bls().fetch(items.SERIES, first_year)
    compared = items.compare(purchases, prices)
    with pd.option_context("display.width", 200, "display.float_format", "{:.2f}".format):
        print(compared.assign(date=compared["date"].dt.date).to_string(index=False))
        moved = items.changes(compared)
        if not moved.empty:
            print("\nPrice change between your first and last purchase:")
            print(moved.to_string(index=False))
    return 0


def cmd_receipt(args) -> int:
    try:
        draft = ocr.read_receipt(args.file)
    except ocr.OcrUnavailable as problem:
        print(problem, file=sys.stderr)
        return 2
    print(f"date: {draft['date'] or 'not found'}")
    for line in draft["lines"]:
        print(f"  {line['price']:8.2f}  {line['item']}")
    print("\nCheck these against the receipt, then add quantity and unit to compare with BLS prices.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inflation", description="Your inflation rate against official CPI.")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("spend", help="personal rate from spending by category")
    p.add_argument("file")
    p.add_argument("--spending-from", choices=["then", "now"], default="then",
                   help="'then' if the amounts describe a year ago (default), 'now' if they describe today")
    p.set_defaults(run=cmd_spend)
    p = commands.add_parser("items", help="your item prices vs. BLS average prices")
    p.add_argument("file")
    p.set_defaults(run=cmd_items)
    p = commands.add_parser("receipt", help="draft item list from a receipt photo")
    p.add_argument("file")
    p.set_defaults(run=cmd_receipt)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (bls.BlsError, ValueError) as problem:
        print(problem, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
