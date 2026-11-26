"""Command line: python -m insider_radar <command>.

    download  fetch quarterly SEC data sets (needs SEC_USER_AGENT)
    ingest    load downloaded zips into SQLite
    clusters  print the most recent cluster buys
    backtest  event study of every cluster, with prices from the cache
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import backtest as bt
from . import clusters as cl
from . import db, ingest, sec
from .prices import PriceCache, YahooChart


def _params(args) -> cl.ClusterParams:
    roles = ("officer", "director") + (("tenpercentowner",) if args.include_10pct else ())
    return cl.ClusterParams(
        min_insiders=args.min_insiders,
        window_days=args.window_days,
        min_value=args.min_value,
        roles=roles,
        exclude_10b5_1=not args.keep_10b5_1,
    )


def _add_rule_options(parser) -> None:
    defaults = cl.ClusterParams()
    parser.add_argument("--min-insiders", type=int, default=defaults.min_insiders)
    parser.add_argument("--window-days", type=int, default=defaults.window_days)
    parser.add_argument("--min-value", type=float, default=defaults.min_value,
                        help="minimum dollars per insider per filing day")
    parser.add_argument("--include-10pct", action="store_true", help="also count 10% owners")
    parser.add_argument("--keep-10b5-1", action="store_true", help="keep pre-scheduled plan trades")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insider_radar", description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=str(db.DEFAULT_DB), help="SQLite file (default: data/insider.db)")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("download", help="fetch SEC data sets")
    p.add_argument("first", help="first quarter, e.g. 2023q1")
    p.add_argument("last", help="last quarter, e.g. 2026q3")
    p.add_argument("--dest", default="data/raw")

    p = commands.add_parser("ingest", help="load zips into SQLite")
    p.add_argument("paths", nargs="*", help="zip files or folders (default: data/raw/*.zip)")

    p = commands.add_parser("clusters", help="list recent clusters")
    _add_rule_options(p)
    p.add_argument("--limit", type=int, default=25)

    p = commands.add_parser("backtest", help="event study")
    _add_rule_options(p)
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--out", help="write per-cluster returns to this CSV")

    args = parser.parse_args(argv)

    if args.command == "download":
        try:
            sec.download(sec.quarters_between(args.first, args.last), args.dest)
        except sec.MissingUserAgent as problem:
            print(problem, file=sys.stderr)
            return 2
        return 0

    conn = db.connect(args.db)

    if args.command == "ingest":
        paths = [Path(p) for p in args.paths] or sorted(Path("data/raw").glob("*.zip"))
        if not paths:
            print("Nothing to ingest. Run the download command first.", file=sys.stderr)
            return 2
        for path in paths:
            print(f"{path.name}: {ingest.load(conn, path):,} filings")
        return 0

    purchases, clusters = cl.run(conn, _params(args))

    if args.command == "clusters":
        print(f"{len(purchases):,} qualifying purchases, {len(clusters):,} clusters")
        if not clusters.empty:
            view = clusters.head(args.limit).copy()
            view["trigger_date"] = view["trigger_date"].dt.date
            view["total_value"] = view["total_value"].map("${:,.0f}".format)
            print(view[["trigger_date", "ticker", "issuer_name", "n_insiders", "total_value"]].to_string(index=False))
        return 0

    if args.command == "backtest":
        if clusters.empty:
            print("No clusters to test.", file=sys.stderr)
            return 2
        cache = PriceCache(conn, YahooChart())

        def progress(done: int, total: int) -> None:
            if done % 25 == 0 or done == total:
                print(f"  prices {done}/{total}", file=sys.stderr)

        events = bt.event_returns(clusters, cache, benchmark=args.benchmark, progress=progress)
        print(events["status"].value_counts().rename("clusters").to_string())
        summary = bt.summarize(events)
        with pd.option_context("display.float_format", "{:.4f}".format):
            print(summary.to_string(index=False))
        if args.out:
            events.to_csv(args.out, index=False)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
