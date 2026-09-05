"""
Offline training for the Transformer ablation candidate (Module 3,
Phase 6 -- see transformer_scorer.py's docstring for why this is not
wired into the live fusion inputs).

CLAUDE.md Section 8: training happens here; transformer_scorer.py's
TransformerScorer only ever loads the resulting artifacts and runs
inference. Imports the SAME TransformerAutoencoder class
transformer_scorer.py uses at inference time, so there's exactly one
architecture definition -- same pattern as train_lstm_ae.py.

Trains on esp32-vib-001's NORMAL feature-vector time series only, using
overlapping sliding windows of length SEQ_LEN (== LSTM_SEQ_LEN) as
training sequences. Denoising objective: Gaussian noise is added to the
NORMALIZED input window; the loss is reconstruction error against the
CLEAN window. This is what actually prevents the self-attention shortcut
described in transformer_scorer.py's docstring -- without it, the model
can partially learn to just copy neighboring positions instead of
learning the underlying normal pattern.
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
    transformer_path,
    transformer_meta_path,
    TRANSFORMER_EPOCHS,
    TRANSFORMER_LEARNING_RATE,
    TRANSFORMER_NOISE_STD,
    LSTM_SEQ_LEN,
    FEATURE_VECTOR_DEVICE_IDS,
    FEATURE_NAMES, TRAINING_SEED, feature_names_for,
)
import feature_engineering as fe
import datasets
from transformer_scorer import TransformerAutoencoder, _TORCH_DEVICE

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
SEQ_LEN = LSTM_SEQ_LEN


def train_one(records, device_id) -> bool:
    """Trains ONE device's Transformer-AE + stats on ITS OWN normal readings,
    saved to that device's per-device paths. Returns True if trained, False
    if too few examples (skipped, not fatal)."""
    torch.manual_seed(TRAINING_SEED)
    runs = datasets.normal_sequences(records, device_id)
    normal = [r for run in runs for r in run]
    if len(normal) < SEQ_LEN + 10:
        print(f"[skip] {device_id}: only {len(normal)} normal examples -- no model trained")
        return False

    raw = np.array([fe.feature_vector(r["reading"]) for r in normal], dtype=np.float32)
    mean = raw.mean(axis=0)
    std = raw.std(axis=0)
    std[std < 1e-6] = 1.0
    windows = []
    for run in runs:
        normalized = (np.array([fe.feature_vector(r["reading"]) for r in run],
                               dtype=np.float32) - mean) / std
        windows.extend(normalized[i:i + SEQ_LEN]
                       for i in range(len(run) - SEQ_LEN + 1))
    if not windows:
        print(f"[skip] {device_id}: no contiguous normal training windows")
        return False
    windows = np.stack(windows)
    clean = torch.tensor(windows, dtype=torch.float32, device=_TORCH_DEVICE)

    # input_dim from THIS device's own feature set, not the module-level
    # FEATURE_NAMES -- SW-420-type nodes publish four features, not five,
    # same fix as train_lstm_ae.py's.
    model = TransformerAutoencoder(input_dim=raw.shape[1]).to(_TORCH_DEVICE)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[{device_id}] {len(windows)} training windows, {n_params} model parameters")

    optimizer = torch.optim.Adam(model.parameters(), lr=TRANSFORMER_LEARNING_RATE)
    loss_fn = nn.MSELoss()
    model.train()
    for epoch in range(TRANSFORMER_EPOCHS):
        optimizer.zero_grad()
        noisy = clean + torch.randn_like(clean) * TRANSFORMER_NOISE_STD
        recon = model(noisy)
        loss = loss_fn(recon, clean)  # denoise: reconstruct the CLEAN window from the noisy one
        loss.backward()
        optimizer.step()
        if epoch % 20 == 0 or epoch == TRANSFORMER_EPOCHS - 1:
            print(f"  [{device_id}] epoch {epoch}: loss={loss.item():.5f}")

    # Baseline error stats computed on the CLEAN windows (no noise) -- this
    # must match what score() does at inference time (transformer_scorer.py
    # never adds noise), or the z-score rescaling below would be calibrated
    # against the wrong distribution.
    model.eval()
    with torch.no_grad():
        recon = model(clean)
        per_window_error = ((recon - clean) ** 2).mean(dim=(1, 2)).cpu().numpy()
    baseline_error_mean = float(per_window_error.mean())
    baseline_error_std = float(per_window_error.std()) or 1e-3

    os.makedirs(MODELS_DIR, exist_ok=True)
    torch.save(model.state_dict(), transformer_path(device_id))
    with open(transformer_meta_path(device_id), "w") as f:
        json.dump({
            "mean": mean.tolist(),
            "std": std.tolist(),
            "baseline_error_mean": baseline_error_mean,
            "baseline_error_std": baseline_error_std,
            "feature_names": feature_names_for(device_id),
        }, f, indent=1)

    print(f"[{device_id}] trained Transformer-AE on {len(windows)} windows -> {transformer_path(device_id)} "
          f"(baseline clean err mean={baseline_error_mean:.5f} std={baseline_error_std:.5f})")
    return True


def main():
    print(f"training device: {_TORCH_DEVICE}")
    with open(SESSION_PATH) as f:
        records = json.load(f)
    trained = sum(train_one(records, d) for d in FEATURE_VECTOR_DEVICE_IDS)
    if trained == 0:
        raise SystemExit("no feature_vector device had enough normal examples -- re-run generate_training_data.py")
    print(f"trained {trained}/{len(FEATURE_VECTOR_DEVICE_IDS)} per-device Transformer-AE model(s)")


if __name__ == "__main__":
    main()
