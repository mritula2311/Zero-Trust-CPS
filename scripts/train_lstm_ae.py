"""
Offline training for Module 3, Phase 6b (LSTM-Autoencoder).

CLAUDE.md Section 8: training happens here; lstm_ae_scorer.LSTMAEScorer
only ever loads the resulting artifacts and runs inference. Imports the
SAME LSTMAutoencoder class lstm_ae_scorer.py uses at inference time, so
there's exactly one architecture definition.

Trains on esp32-vib-001's NORMAL feature-vector time series only, using
overlapping sliding windows of length LSTM_SEQ_LEN as training sequences --
self-supervised (predict/reconstruct the window itself), same "only needs
normal data" property as Isolation Forest (synopsis Section 5.3).
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
    lstm_ae_path,
    lstm_ae_meta_path,
    LSTM_SEQ_LEN,
    LSTM_EPOCHS,
    LSTM_LEARNING_RATE,
    FEATURE_VECTOR_DEVICE_IDS,
    FEATURE_NAMES, TRAINING_SEED, feature_names_for,
)
import feature_engineering as fe
import datasets
from lstm_ae_scorer import LSTMAutoencoder, _TORCH_DEVICE

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")


def train_one(records, device_id) -> bool:
    """Trains ONE device's LSTM-AE + normalization/baseline stats on ITS OWN
    normal readings, saving both to that device's per-device paths. Returns
    True if trained, False if too few examples (skipped, not fatal)."""
    torch.manual_seed(TRAINING_SEED)
    normal = [
        r for r in records
        if r["device_id"] == device_id and r["label"] == 1 and r["auth_ok"]
    ]
    normal.sort(key=lambda r: r["tick"])
    if len(normal) < LSTM_SEQ_LEN + 10:
        print(f"[skip] {device_id}: only {len(normal)} normal examples -- no model trained")
        return False

    raw = np.array([fe.feature_vector(r["reading"]) for r in normal], dtype=np.float32)
    mean = raw.mean(axis=0)
    std = raw.std(axis=0)
    std[std < 1e-6] = 1.0
    normalized = (raw - mean) / std

    windows = np.stack([normalized[i:i + LSTM_SEQ_LEN] for i in range(len(normalized) - LSTM_SEQ_LEN + 1)])
    x = torch.tensor(windows, dtype=torch.float32, device=_TORCH_DEVICE)

    # input_dim from THIS device's own feature set, not the module-level
    # FEATURE_NAMES. The SW-420-type nodes publish four features, not five;
    # with a hardcoded 5 the trainer raised
    # "input.size(-1) must be equal to input_size. Expected 5, got 4"
    # on the first switch node it reached.
    model = LSTMAutoencoder(input_dim=raw.shape[1]).to(_TORCH_DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LSTM_LEARNING_RATE)
    loss_fn = nn.MSELoss()
    model.train()
    for epoch in range(LSTM_EPOCHS):
        optimizer.zero_grad()
        recon = model(x)
        loss = loss_fn(recon, x)
        loss.backward()
        optimizer.step()
        if epoch % 20 == 0 or epoch == LSTM_EPOCHS - 1:
            print(f"  [{device_id}] epoch {epoch}: loss={loss.item():.5f}")

    model.eval()
    with torch.no_grad():
        recon = model(x)
        per_window_error = ((recon - x) ** 2).mean(dim=(1, 2)).cpu().numpy()
    baseline_error_mean = float(per_window_error.mean())
    baseline_error_std = float(per_window_error.std()) or 1e-3

    os.makedirs(MODELS_DIR, exist_ok=True)
    torch.save(model.state_dict(), lstm_ae_path(device_id))
    with open(lstm_ae_meta_path(device_id), "w") as f:
        json.dump({
            "mean": mean.tolist(),
            "std": std.tolist(),
            "baseline_error_mean": baseline_error_mean,
            "baseline_error_std": baseline_error_std,
            "feature_names": feature_names_for(device_id),
        }, f, indent=1)

    print(f"[{device_id}] trained LSTM-AE on {len(windows)} windows ({len(normal)} normal readings) "
          f"-> {lstm_ae_path(device_id)} (baseline err mean={baseline_error_mean:.5f} std={baseline_error_std:.5f})")
    return True


def main():
    print(f"training device: {_TORCH_DEVICE}")
    # Per-device training corpus: esp32-vib-001 from training_session.json,
    # every other network node from the TRAIN split of the network scenarios.
    # See src/datasets.py for why the primary device's corpus is unchanged.
    records = datasets.training_records()
    trained = sum(train_one(records, d) for d in FEATURE_VECTOR_DEVICE_IDS)
    if trained == 0:
        raise SystemExit("no feature_vector device had enough normal examples -- re-run generate_training_data.py")
    print(f"trained {trained}/{len(FEATURE_VECTOR_DEVICE_IDS)} per-device LSTM-AE model(s)")


if __name__ == "__main__":
    main()
