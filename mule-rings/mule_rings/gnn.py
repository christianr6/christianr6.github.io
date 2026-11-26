"""A graph neural network on the same task, for comparison with the trees.

    python -m mule_rings.gnn --data data --out results/gnn.json

Accounts are nodes. Each pair of accounts with at least one payment between
them is an arrow, described by how many payments it carries, their typical
size and their payment formats. Each layer lets an account collect
information from the accounts it pays and from the accounts that pay it (two
separate passes, since direction matters in laundering). A transaction is
then scored from its two accounts and its own features.

Messages travel over account pairs (about 1 million) and not over single
transactions (about 5 million) so that training fits in 16 GB of memory.

Same information as the tree model: the structure of all transactions in the
period is visible, labels only for the training days. Needs torch and
torch_geometric, which the rest of the project does not.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch_geometric.nn import GINEConv

from . import data, model, split

HIDDEN = 64
LAYERS = 2
EPOCHS = 120
LEARNING_RATE = 0.01
POSITIVE_WEIGHT = 8.0     # laundering is 1 in 1,000; weigh its errors more


def edge_features(df: pd.DataFrame) -> np.ndarray:
    """Per-transaction inputs. No timestamps: position in time would reveal the split."""
    amount = np.log1p(df["amount_paid"].to_numpy())
    columns = [
        (amount - amount.mean()) / amount.std(),
        (df["payment_currency"] != df["receiving_currency"]).to_numpy(float),
        (df["src"] == df["dst"]).to_numpy(float),
        (df["from_bank"] == df["to_bank"]).to_numpy(float),
        np.sin(2 * np.pi * df["ts"].dt.hour.to_numpy() / 24),
        np.cos(2 * np.pi * df["ts"].dt.hour.to_numpy() / 24),
    ]
    one_hot = [pd.get_dummies(df[name]).to_numpy(float) for name in ("payment_format", "payment_currency")]
    return np.column_stack(columns + one_hot).astype(np.float32)


def node_features(df: pd.DataFrame, n: int) -> np.ndarray:
    """How busy each account is, on a log scale."""
    src, dst = df["src"].to_numpy(), df["dst"].to_numpy()
    distinct = pd.DataFrame({"s": src, "d": dst}).drop_duplicates()
    counts = [
        np.bincount(src, minlength=n), np.bincount(dst, minlength=n),
        np.bincount(distinct["s"], minlength=n), np.bincount(distinct["d"], minlength=n),
    ]
    return np.column_stack([np.log1p(c) for c in counts]).astype(np.float32)


def pair_graph(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Collapse parallel payments: one arrow per (payer, payee), with summary features.

    Returns (edge_index of shape 2 x pairs, features of shape pairs x k).
    Self-transfers connect nothing and are left out.
    """
    links = df[df["src"] != df["dst"]]
    frame = pd.DataFrame({
        "src": links["src"].to_numpy(), "dst": links["dst"].to_numpy(),
        "log_amount": np.log1p(links["amount_paid"].to_numpy()),
    })
    formats = pd.get_dummies(links["payment_format"]).astype(np.float32)
    formats.index = frame.index
    frame = pd.concat([frame, formats], axis=1)
    grouped = frame.groupby(["src", "dst"], sort=True)
    summary = grouped.mean()                       # mean log amount, share of each payment format
    summary.insert(0, "log_count", np.log1p(grouped.size().to_numpy()))
    index = np.array(summary.index.to_list(), dtype=np.int64).T
    n = int(max(df["src"].max(), df["dst"].max())) + 1
    codes = index[0] * n + index[1]
    summary["reciprocal"] = np.isin(index[1] * n + index[0], codes).astype(np.float32)
    values = summary.to_numpy(np.float32)
    values[:, 1] = (values[:, 1] - values[:, 1].mean()) / values[:, 1].std()
    return index, values


class EdgeClassifier(nn.Module):
    def __init__(self, node_dim: int, pair_dim: int, edge_dim: int, hidden: int = HIDDEN, layers: int = LAYERS):
        super().__init__()
        self.node_in = nn.Linear(node_dim, hidden)
        self.pair_in = nn.Linear(pair_dim, hidden)
        self.edge_in = nn.Linear(edge_dim, hidden)

        def conv() -> GINEConv:
            return GINEConv(nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, hidden)),
                            edge_dim=hidden)

        self.forward_convs = nn.ModuleList(conv() for _ in range(layers))    # along the money
        self.backward_convs = nn.ModuleList(conv() for _ in range(layers))   # against it
        self.norms = nn.ModuleList(nn.BatchNorm1d(hidden) for _ in range(layers))
        self.readout = nn.Sequential(nn.Linear(3 * hidden, hidden), nn.ReLU(), nn.Dropout(0.1), nn.Linear(hidden, 1))

    def accounts(self, x, pair_index, pair_attr):
        """One vector per account, after looking at its neighbourhood."""
        h, p = self.node_in(x), self.pair_in(pair_attr)
        reverse = pair_index.flip(0)
        for along, against, norm in zip(self.forward_convs, self.backward_convs, self.norms):
            update = along(h, pair_index, p) + against(h, reverse, p)
            h = h + torch.relu(norm(update))
        return h

    def score(self, h, source, target, edge_attr):
        """One number per transaction: higher means more likely laundering."""
        return self.readout(torch.cat([h[source], h[target], self.edge_in(edge_attr)], dim=1)).squeeze(1)


def _score_all(net, h, source, target, edge_attr, chunk: int = 500_000) -> np.ndarray:
    parts = [torch.sigmoid(net.score(h, source[i:i + chunk], target[i:i + chunk], edge_attr[i:i + chunk]))
             for i in range(0, len(source), chunk)]
    return torch.cat(parts).numpy()


def run(data_dir: Path, epochs: int = EPOCHS, log=print) -> dict:
    started = time.time()
    torch.manual_seed(7)
    raw = data.read_transactions(data_dir / "HI-Small_Trans.csv")
    df, _ = split.primary_period(raw)
    parts = split.by_time(df)
    labels = df["is_laundering"].to_numpy()
    n = int(max(df["src"].max(), df["dst"].max())) + 1

    x = torch.from_numpy(node_features(df, n))
    index, pair_values = pair_graph(df)
    pair_index, pair_attr = torch.from_numpy(index), torch.from_numpy(pair_values)
    edge_attr = torch.from_numpy(edge_features(df))
    source = torch.from_numpy(df["src"].to_numpy().astype(np.int64))
    target = torch.from_numpy(df["dst"].to_numpy().astype(np.int64))
    y = torch.from_numpy(labels.astype(np.float32))
    train = torch.from_numpy(np.flatnonzero(parts.train))
    log(f"{n:,} accounts, {pair_index.shape[1]:,} account pairs, {len(df):,} transactions")

    net = EdgeClassifier(x.shape[1], pair_attr.shape[1], edge_attr.shape[1])
    optimizer = torch.optim.Adam(net.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(POSITIVE_WEIGHT))
    best = {"valid_ap": -1.0}
    history = []
    for epoch in range(1, epochs + 1):
        net.train()
        optimizer.zero_grad()
        h = net.accounts(x, pair_index, pair_attr)
        logits = net.score(h, source[train], target[train], edge_attr[train])
        loss = loss_fn(logits, y[train])            # labels from the training days only
        loss.backward()
        optimizer.step()

        net.eval()
        with torch.no_grad():
            scores = _score_all(net, net.accounts(x, pair_index, pair_attr), source, target, edge_attr)
        valid_ap = model.score(scores[parts.valid], labels[parts.valid], 0.5)["average_precision"]
        history.append({"epoch": epoch, "loss": float(loss), "valid_average_precision": valid_ap})
        if valid_ap > best["valid_ap"]:      # keep the epoch that did best on validation
            best = {"valid_ap": valid_ap, "epoch": epoch, "scores": scores.copy()}
        if epoch % 5 == 0 or epoch == 1:
            log(f"epoch {epoch:3d}  loss {float(loss):.4f}  valid AP {valid_ap:.3f}  ({time.time() - started:.0f}s)")

    scores = best["scores"]
    threshold = model.best_threshold(scores[parts.valid], labels[parts.valid])
    return {
        "model": f"GINE on account pairs, {LAYERS} layers, hidden {HIDDEN}, messages in both directions",
        "epochs": epochs, "best_epoch": best["epoch"],
        "parameters": int(sum(p.numel() for p in net.parameters())),
        "test": model.score(scores[parts.test], labels[parts.test], threshold),
        "valid": model.score(scores[parts.valid], labels[parts.valid], threshold),
        "curve": model.curve(scores[parts.test], labels[parts.test]),
        "history": history,
        "seconds": round(time.time() - started),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mule_rings.gnn", description="Train the graph neural network.")
    parser.add_argument("--data", default="data")
    parser.add_argument("--out", default="results/gnn.json")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    args = parser.parse_args(argv)
    summary = run(Path(args.data), epochs=args.epochs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1))
    t = summary["test"]
    print(f"test: AP {t['average_precision']:.3f}  precision {t['precision']:.2f}  recall {t['recall']:.2f}  "
          f"F1 {t['f1']:.2f}  (best epoch {summary['best_epoch']}, {summary['seconds']}s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
