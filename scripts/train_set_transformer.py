"""
Offline training for the M6 Set Transformer LIVE-RUNTIME candidate.

Run this AFTER train_isolation_forest.py, train_lstm_ae.py and (for
comparison) train_gnn.py. Unlike scripts/benchmark_crossdevice_models.py's
M6 sweeps (which validate the architecture's robustness across synthetic
node-count/provenance conditions and never save a checkpoint), this
replays the SAME training session GCN trains on, through the SAME trained
IF/LSTM-AE scorers, building the SAME [rule_score, if_score, lstm_score]
per-device node-feature history GCN uses -- so M6 becomes a fair,
comparable live candidate rather than only a standalone offline result.
See src/config.py's SET_TRANSFORMER_* constants and
docs/paper/17_CLAIM_EVIDENCE_MATRIX.md C05/C15 for why this training path
did not previously exist.

set_transformer_scorer.SetTransformerScorer only ever loads the resulting
artifact and runs inference -- mirrors gnn_scorer.py/train_gnn.py exactly.
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
    SET_TRANSFORMER_MODEL_PATH,
    SET_TRANSFORMER_EPOCHS,
    SET_TRANSFORMER_LEARNING_RATE,
    DEVICE_REGISTRY,
    is_feature_vector, TRAINING_SEED,
)
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from set_transformer_scorer import _SetTransformer, _TORCH_DEVICE
from generate_training_data import physical_label

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
DEVICE_IDS = list(DEVICE_REGISTRY.keys())
INDEX = {d: i for i, d in enumerate(DEVICE_IDS)}
EDGE_WINDOW_TICKS = 1  # matches train_gnn.py's EDGE_WINDOW_TICKS exactly


def build_snapshots(records):
    """Identical replay/labelling logic to train_gnn.py's build_snapshots
    (see that docstring for the full rationale of each choice -- true
    per-node labels tracked from last-seen record, physical_label as the
    target, rejected/replayed records skipped). The only difference is
    what's returned per snapshot: a boolean VALIDITY mask instead of a
    normalized adjacency matrix, since the Set Transformer has no graph at
    all -- attention validity is the live-candidate analogue of GCN's
    active-edge mask.

    Isolated-topology augmentation, adapted for masked attention (NOT a
    copy of GCN's): GCN's augmentation zeroes every active flag and still
    gets a well-defined per-node output, because its self-loop is
    unconditional (added before any active-pair edge, see
    gnn_scorer.normalized_adjacency). A Set Transformer's key_padding_mask
    has no such unconditional self-loop -- masking every key produces NaN
    (softmax over zero valid keys is undefined). So the isolated variant
    here marks ONLY the current record's own device as valid, not none of
    them: "this device, on its own last-known evidence, with no neighbour
    attesting" -- the same training intent as GCN's augmentation, expressed
    in terms this architecture can actually compute."""
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

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        last_features[i] = [rule_score, if_score, lstm_score]
        last_label[i] = float(physical_label(r["event_type"]))
        last_active_tick[device_id] = r["tick"]

        active = np.array([
            (r["tick"] - last_active_tick[d]) <= EDGE_WINDOW_TICKS for d in DEVICE_IDS
        ])
        snapshots.append((last_features.copy(), active.copy(), last_label.copy()))

        isolated = np.zeros(len(DEVICE_IDS), dtype=bool)
        isolated[i] = True
        snapshots.append((last_features.copy(), isolated, last_label.copy()))

    return snapshots


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    print("building device-set snapshots (replaying through trained IF/LSTM-AE scorers)...")
    snapshots = build_snapshots(records)
    print(f"built {len(snapshots)} snapshots")

    print(f"training device: {_TORCH_DEVICE}")
    xs = torch.tensor(np.stack([s[0] for s in snapshots]), dtype=torch.float32, device=_TORCH_DEVICE)
    valids = torch.tensor(np.stack([s[1] for s in snapshots]), dtype=torch.bool, device=_TORCH_DEVICE)
    ys = torch.tensor(np.stack([s[2] for s in snapshots]), dtype=torch.float32, device=_TORCH_DEVICE)

    # Same inverse-frequency class weighting as train_gnn.py, for the same
    # reason: node-targets are ~90% "normal" (1) / ~10% "suspicious" (0),
    # and an unweighted loss converges toward the majority class without
    # ever confidently crossing the 0.5 boundary.
    #
    # Counted over ys[valids], NOT the full ys tensor -- unlike train_gnn.py
    # (whose adjacency always gives every node a well-defined self-loop
    # contribution, so its unmasked loss legitimately sees every node-slot),
    # this script's loss below is masked to `valids` only (~8.9% of all
    # node-slots here; the rest are padded/inactive device-registry entries
    # carrying stale or default-filled labels). Counting the full tensor
    # previously computed weights from a distribution the loss never
    # actually trains on -- verified against training_session.json: it
    # inflated neg_weight (the suspicious class) to 45.18 vs. the correct
    # 6.27 for the valid-only distribution, a 7.2x overweight. See
    # docs/paper/18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md and
    # results/gcn_m6_corrected_comparison/summary.md for the fix's effect.
    num_pos = float((ys[valids] == 1).sum())
    num_neg = float((ys[valids] == 0).sum())
    pos_weight = num_pos and (num_pos + num_neg) / (2 * num_pos)
    neg_weight = num_neg and (num_pos + num_neg) / (2 * num_neg)
    print(f"class weights: pos(normal)={pos_weight:.3f} neg(suspicious)={neg_weight:.3f} "
          f"(from {int(num_pos)} normal / {int(num_neg)} suspicious node-targets)")

    torch.manual_seed(TRAINING_SEED)
    model = _SetTransformer().to(_TORCH_DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=SET_TRANSFORMER_LEARNING_RATE)
    model.train()

    # Batched over all snapshots per epoch, same rationale as train_gnn.py's
    # GPU-timing fix: one forward/backward per epoch rather than one per
    # snapshot. Loss masked to valid nodes only (an invalid node's target is
    # not a real observation the model was allowed to see).
    for epoch in range(SET_TRANSFORMER_EPOCHS):
        optimizer.zero_grad()
        pred = model(xs, valids)  # (num_snapshots, num_nodes)
        weight = torch.where(ys == 1, pos_weight, neg_weight)
        loss_per_node = nn.functional.binary_cross_entropy(pred, ys, weight=weight, reduction="none")
        total_loss = loss_per_node[valids].sum() / valids.sum()
        total_loss.backward()
        optimizer.step()
        if epoch % 20 == 0 or epoch == SET_TRANSFORMER_EPOCHS - 1:
            print(f"  epoch {epoch}: total_loss={total_loss.item():.3f}")

    # ZTCPS_SET_TRANSFORMER_OUTPUT lets a corrected/comparison retrain write
    # to a different file (e.g. config.SET_TRANSFORMER_MODEL_PATH_CORRECTED)
    # without touching the deployed checkpoint at SET_TRANSFORMER_MODEL_PATH.
    # Unset (the default) reproduces exactly the prior save behavior.
    output_path = os.environ.get("ZTCPS_SET_TRANSFORMER_OUTPUT", SET_TRANSFORMER_MODEL_PATH)
    os.makedirs(MODELS_DIR, exist_ok=True)
    torch.save(model.state_dict(), output_path)
    print(f"trained Set Transformer on {len(snapshots)} snapshots, saved to {output_path}")


if __name__ == "__main__":
    main()
