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
    LSTM_AE_MODEL_PATH,
    LSTM_AE_META_PATH,
    LSTM_SEQ_LEN,
    LSTM_EPOCHS,
    LSTM_LEARNING_RATE,
    FEATURE_NAMES,
)
import feature_engineering as fe
from lstm_ae_scorer import LSTMAutoencoder, _TORCH_DEVICE

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")


def main():
    torch.manual_seed(0)
    with open(SESSION_PATH) as f:
        records = json.load(f)

    normal = [
        r for r in records
        if r["device_id"] == "esp32-vib-001" and r["label"] == 1 and r["auth_ok"]
    ]
    normal.sort(key=lambda r: r["tick"])
    if len(normal) < LSTM_SEQ_LEN + 10:
        raise SystemExit(f"only {len(normal)} normal examples -- need more, re-run generate_training_data.py")

    raw = np.array([fe.feature_vector(r["reading"]) for r in normal], dtype=np.float32)
    mean = raw.mean(axis=0)
    std = raw.std(axis=0)
    std[std < 1e-6] = 1.0
    normalized = (raw - mean) / std

    windows = np.stack([normalized[i:i + LSTM_SEQ_LEN] for i in range(len(normalized) - LSTM_SEQ_LEN + 1)])
    print(f"training device: {_TORCH_DEVICE}")
    x = torch.tensor(windows, dtype=torch.float32, device=_TORCH_DEVICE)

    model = LSTMAutoencoder().to(_TORCH_DEVICE)
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
            print(f"  epoch {epoch}: loss={loss.item():.5f}")

    model.eval()
    with torch.no_grad():
        recon = model(x)
        per_window_error = ((recon - x) ** 2).mean(dim=(1, 2)).cpu().numpy()
    baseline_error_mean = float(per_window_error.mean())
    baseline_error_std = float(per_window_error.std()) or 1e-3

    os.makedirs(MODELS_DIR, exist_ok=True)
    torch.save(model.state_dict(), LSTM_AE_MODEL_PATH)
    with open(LSTM_AE_META_PATH, "w") as f:
        json.dump({
            "mean": mean.tolist(),
            "std": std.tolist(),
            "baseline_error_mean": baseline_error_mean,
            "baseline_error_std": baseline_error_std,
            "feature_names": FEATURE_NAMES,
        }, f, indent=1)

    print(f"trained LSTM-AE on {len(windows)} windows ({len(normal)} normal readings), saved to {LSTM_AE_MODEL_PATH}")
    print(f"baseline reconstruction error: mean={baseline_error_mean:.5f} std={baseline_error_std:.5f}")


if __name__ == "__main__":
    main()
