"""
Offline training for Module 3, Phase 6c (GNN).

CLAUDE.md Section 8: training happens here; gnn_scorer.GNNScorer only
ever loads the resulting artifact and runs inference. Run this AFTER
train_isolation_forest.py and train_lstm_ae.py -- it replays the training
session through both of those (now-trained, inference-mode) scorers to
build each device's [rule_score, if_score, lstm_score] node-feature
history, exactly the graph-snapshot construction gateway.py does live.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import torch
import torch.nn as nn

from config import (
    DATA_COLLECTED_DIR,
    MODELS_DIR,
    GNN_MODEL_PATH,
    GNN_EPOCHS,
    GNN_LEARNING_RATE,
    DEVICE_REGISTRY,
)
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import _GCN, normalized_adjacency, _TORCH_DEVICE
from generate_training_data import physical_label

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
DEVICE_IDS = list(DEVICE_REGISTRY.keys())
INDEX = {d: i for i, d in enumerate(DEVICE_IDS)}
EDGE_WINDOW_TICKS = 1  # replaying tick-by-tick, all 3 devices in a tick count as "same time window"


def build_snapshots(records):
    """Replays the session tick-by-tick through the trained IF/LSTM-AE
    scorers, producing one graph snapshot (features + adjacency + joint
    label vector) per incoming record -- features and the TRUE label for
    every node reflect the most-recently-seen record for that device,
    mirroring gateway.py's live "snapshot of latest known state per
    device" approach for BOTH features and ground truth.

    Correctness note (fixed after the fact -- see SESSION_LOG.md): this
    used to force every node OTHER than the record's own device to
    y=1 ("assume normal"), which actively taught the GNN to ignore
    simultaneous anomalies on other nodes -- exactly backwards for a
    model whose entire purpose is relational/coordinated-anomaly
    detection (synopsis Section 4.2 Stage 6's "coordinated multi-device
    attack" scenario, gnn_scorer.py's docstring). Tracking each device's
    own last-known TRUE label instead means a "coordinated" tick, where
    all 3 devices go suspicious in the same tick, produces at least one
    snapshot (the last record processed that tick) with the full true
    joint target [0, 0, 0] -- the training signal the GCN actually needs
    to learn "simultaneously-mild-across-neighbors is worse than any one
    alone" instead of being told the opposite.

    TWO-SCORE REARCHITECTURE: records with auth_ok=False or
    event_type=="replay" are SKIPPED entirely -- no feature/label/
    active-tick update, no snapshot produced for that row -- because
    Module 2 rejects both before they ever reach Module 3 in the live
    architecture, so there is no live analogue of "what would the graph
    snapshot look like right after a rejected message" to train against.
    The label target is physical_label(event_type), not the old blended
    `label` -- a `high_rate` record's features are genuinely normal, and
    pairing them with label=0 (the bug this replaced) taught the GNN that
    ordinary-looking feature vectors sometimes mean "suspicious" with
    nothing in the features to justify it."""
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()

    last_features = np.full((len(DEVICE_IDS), 3), 0.9, dtype=np.float32)
    last_label = np.ones(len(DEVICE_IDS), dtype=np.float32)
    last_active_tick = {d: -999 for d in DEVICE_IDS}
    snapshots = []

    records = sorted(records, key=lambda r: r["tick"])
    for r in records:
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue  # rejected at Module 2 -- never reaches Module 3 live
        device_id = r["device_id"]
        i = INDEX[device_id]
        rule_score, _ = rule_range_score(device_id, r["reading"])

        if device_id == "esp32-vib-001":
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            # scalar devices have no independent IF/LSTM-AE model -- mirror
            # rule_score into those slots (documented in gnn_scorer.py)
            if_score = lstm_score = rule_score

        last_features[i] = [rule_score, if_score, lstm_score]
        last_label[i] = float(physical_label(r["event_type"]))
        last_active_tick[device_id] = r["tick"]

        active = np.array([
            (r["tick"] - last_active_tick[d]) <= EDGE_WINDOW_TICKS for d in DEVICE_IDS
        ])
        a_hat = normalized_adjacency(active)

        snapshots.append((last_features.copy(), a_hat.numpy(), last_label.copy()))

    return snapshots


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    print("building graph snapshots (replaying through trained IF/LSTM-AE scorers)...")
    snapshots = build_snapshots(records)
    print(f"built {len(snapshots)} snapshots")

    print(f"training device: {_TORCH_DEVICE}")
    xs = torch.tensor(np.stack([s[0] for s in snapshots]), dtype=torch.float32, device=_TORCH_DEVICE)
    as_ = torch.tensor(np.stack([s[1] for s in snapshots]), dtype=torch.float32, device=_TORCH_DEVICE)
    ys = torch.tensor(np.stack([s[2] for s in snapshots]), dtype=torch.float32, device=_TORCH_DEVICE)

    # Per-node training targets are ~90% "normal" (1) / ~10% "suspicious"
    # (0) -- the same imbalance an unweighted BCELoss always converges
    # toward the majority class under, producing a model that's
    # DIRECTIONALLY right (a worse neighborhood scores lower) but never
    # confident enough to cross the 0.5 decision boundary even on the
    # worst input (verified: an all-three-nodes-bad snapshot only reached
    # ~0.66 pre-fix). Standard inverse-frequency class weighting fixes
    # this without changing the (deliberately small, demo-scale)
    # architecture.
    num_pos = float((ys == 1).sum())
    num_neg = float((ys == 0).sum())
    pos_weight = num_pos and (num_pos + num_neg) / (2 * num_pos)
    neg_weight = num_neg and (num_pos + num_neg) / (2 * num_neg)
    print(f"class weights: pos(normal)={pos_weight:.3f} neg(suspicious)={neg_weight:.3f} "
          f"(from {int(num_pos)} normal / {int(num_neg)} suspicious node-targets)")

    torch.manual_seed(0)
    model = _GCN().to(_TORCH_DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=GNN_LEARNING_RATE)
    model.train()

    # Batched training (see SESSION_LOG.md's GPU timing entry for why): the
    # ORIGINAL loop called model() once per snapshot (97,600 tiny CUDA
    # kernel launches across 1220 snapshots x 80 epochs), which measured
    # ~6.5x SLOWER on GPU than CPU purely from per-launch overhead, since
    # each individual (3-node, hidden=8) forward pass is far too small to
    # amortize a kernel launch. _GCN.forward() already uses `@` (matmul)
    # and nn.Linear, both of which handle an extra leading batch dimension
    # transparently -- no model/architecture change needed, just feeding
    # the whole (1220, 3, 3) batch in one call per epoch instead of 1220
    # separate (3, 3) calls. gnn_scorer.py's live inference path is
    # untouched -- it still calls model() with a single unbatched (3, 3)
    # snapshot, which forward() still handles correctly (no batch dim).
    #
    # Loss normalization -- chosen to reproduce the OLD loop's gradient
    # EXACTLY, not just approximately, so this is a pure performance
    # refactor rather than an accidental change in training dynamics:
    # the old loop called .backward() once per snapshot with a MEAN-over-3-
    # nodes loss, accumulating gradients across all 1220 snapshots before
    # one optimizer.step() -- equivalent to differentiating
    # sum_i(mean_j(loss_ij)) = sum(all losses) / num_nodes. A single
    # `reduction="sum"` call over the whole batch, divided by num_nodes,
    # is algebraically identical. Verified after training: loss trajectory
    # and downstream evaluate_ablation.py numbers matched the un-batched
    # run exactly.
    num_nodes = xs.shape[1]
    for epoch in range(GNN_EPOCHS):
        optimizer.zero_grad()
        pred = model(xs, as_)  # batched: (num_snapshots, num_nodes)
        weight = torch.where(ys == 1, pos_weight, neg_weight)
        total_loss = nn.functional.binary_cross_entropy(pred, ys, weight=weight, reduction="sum") / num_nodes
        total_loss.backward()
        optimizer.step()
        if epoch % 20 == 0 or epoch == GNN_EPOCHS - 1:
            print(f"  epoch {epoch}: total_loss={total_loss.item():.3f}")

    os.makedirs(MODELS_DIR, exist_ok=True)
    torch.save(model.state_dict(), GNN_MODEL_PATH)
    print(f"trained GNN on {len(snapshots)} snapshots, saved to {GNN_MODEL_PATH}")


if __name__ == "__main__":
    main()
