"""Run the whole study: python -m mule_rings [--data data] [--out results/summary.json]"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features, model, rings, split

RINGS_TO_SAVE = 40
MAX_RING_TRANSACTIONS_SAVED = 60


def run(data_dir: Path, log=print) -> dict:
    started = time.time()
    raw = data.read_transactions(data_dir / "HI-Small_Trans.csv")
    patterns = data.read_patterns(data_dir / "HI-Small_Patterns.txt")
    log(f"loaded {len(raw):,} transactions, {len(patterns)} labeled rings")

    df, leak = split.primary_period(raw)
    df.attrs["accounts"] = raw.attrs["accounts"]
    parts = split.by_time(df)
    labels = df["is_laundering"].to_numpy()
    log(f"kept {len(df):,} through {leak['last_day_kept']}; dropped {leak['dropped_transactions']:,} "
        f"trailing transactions ({leak['dropped_laundering_share']:.0%} laundering)")

    table = features.build(df)
    log(f"built {table.shape[1]} features in {time.time() - started:.0f}s")

    results = {}
    scores = {}
    for name, columns in (("raw", features.RAW), ("graph", features.RAW + features.GRAPH)):
        fitted = model.fit(table[columns], labels, parts.train, parts.valid)
        valid_scores = fitted.predict_proba(table.loc[parts.valid, columns])[:, 1]
        test_scores = fitted.predict_proba(table.loc[parts.test, columns])[:, 1]
        threshold = model.best_threshold(valid_scores, labels[parts.valid])
        results[name] = {
            "features": len(columns),
            "trees": int(fitted.best_iteration_ or fitted.n_estimators),
            "test": model.score(test_scores, labels[parts.test], threshold),
            "valid": model.score(valid_scores, labels[parts.valid], threshold),
            "curve": model.curve(test_scores, labels[parts.test]),
            "importance": model.importance(fitted),
        }
        scores[name] = (test_scores, threshold)
        t = results[name]["test"]
        log(f"{name:5s} test: AP {t['average_precision']:.3f}  precision {t['precision']:.2f}  "
            f"recall {t['recall']:.2f}  F1 {t['f1']:.2f}  ({t['flagged']:,} flagged)")

    # Rings from the graph model's flags on the test days.
    test_scores, threshold = scores["graph"]
    test = df[parts.test].copy()
    test["score"] = test_scores
    test["flagged"] = test_scores >= threshold
    with_rings = rings.find(test[test["flagged"]])
    ring_table = rings.summarize(with_rings)
    matched = rings.against_patterns(test, patterns)
    kinds = rings.by_kind(matched)
    log(f"{len(ring_table)} suspected rings; {int(matched['caught'].sum())} of {len(matched)} labeled rings caught")

    names = df.attrs["accounts"]
    kind_of_key = {key: p.kind for p in patterns for key in p.keys}
    saved = []
    pure_first = ring_table.sort_values(["laundering", "purity"], ascending=False).head(RINGS_TO_SAVE)
    for row in pure_first.itertuples(index=False):
        members = with_rings[with_rings["ring"] == row.ring].sort_values("ts").head(MAX_RING_TRANSACTIONS_SAVED)
        pattern_kinds = sorted({kind_of_key[k] for k in members["key"] if k in kind_of_key})
        saved.append({
            "ring": row.ring, "accounts": row.accounts, "transactions": row.transactions,
            "laundering": row.laundering, "purity": row.purity, "labeled_as": pattern_kinds,
            "edges": [
                {"from": str(names[s]), "to": str(names[d]), "time": str(ts), "amount": float(amount),
                 "currency": currency, "format": fmt, "laundering": int(label), "score": float(sc)}
                for s, d, ts, amount, currency, fmt, label, sc in zip(
                    members["src"], members["dst"], members["ts"], members["amount_paid"],
                    members["payment_currency"], members["payment_format"], members["is_laundering"], members["score"])
            ],
        })

    return {
        "dataset": {
            "name": "IBM AMLworld HI-Small (synthetic)",
            "transactions": int(len(raw)), "laundering": int(raw["is_laundering"].sum()),
            "accounts": int(len(names)), "labeled_rings": len(patterns),
        },
        "leak": leak,
        "split": {
            "days": parts.days,
            **{part: {"transactions": int(mask.sum()), "laundering": int(labels[mask].sum())}
               for part, mask in (("train", parts.train), ("valid", parts.valid), ("test", parts.test))},
        },
        "models": results,
        "rings": {
            "suspected": int(len(ring_table)),
            "mostly_laundering": int((ring_table["purity"] >= 0.5).sum()) if len(ring_table) else 0,
            "largest_accounts": int(ring_table["accounts"].max()) if len(ring_table) else 0,
            "labeled_in_test": int(len(matched)),
            "labeled_caught": int(matched["caught"].sum()),
            "by_kind": kinds.to_dict("records"),
            "examples": saved,
        },
        "seconds": round(time.time() - started),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mule_rings", description=__doc__)
    parser.add_argument("--data", default="data", help="folder with HI-Small_Trans.csv and HI-Small_Patterns.txt")
    parser.add_argument("--out", default="results/summary.json")
    args = parser.parse_args(argv)
    folder = Path(args.data)
    missing = [n for n in ("HI-Small_Trans.csv", "HI-Small_Patterns.txt") if not (folder / n).exists()]
    if missing:
        print(f"Missing in {folder}/: {', '.join(missing)}. See the README for the download.", file=sys.stderr)
        return 2
    summary = run(folder)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1))
    print(f"wrote {out} in {summary['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
