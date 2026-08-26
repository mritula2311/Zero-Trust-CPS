"""
Module 3, Phase 6b: LSTM-Autoencoder anomaly scorer -- INFERENCE ONLY.

CLAUDE.md Section 8: training happens offline in scripts/train_lstm_ae.py,
which imports `LSTMAutoencoder` from this file (one architecture
definition, not two copies) and saves a trained state dict + normalization
stats to config.LSTM_AE_MODEL_PATH / LSTM_AE_META_PATH. This file's
`LSTMAEScorer` only ever loads those artifacts and runs a forward pass --
it never calls `.fit()` or updates weights in the live gateway path.

Unlike Isolation Forest (scores one feature vector against a learned
distribution), this scores a short SEQUENCE of recent feature vectors
against a learned per-device *pattern over time* -- catching gradual
behavioural drift (e.g. a slowly worsening bearing fault) that a
single-message model can't see by construction (synopsis Section 5.4,
grounded in [37]).
"""

import json
import os

import numpy as np
import torch
import torch.nn as nn

from config import LSTM_SEQ_LEN, LSTM_HIDDEN_SIZE, LSTM_NUM_LAYERS, LSTM_AE_MODEL_PATH, LSTM_AE_META_PATH, FEATURE_NAMES

torch.manual_seed(0)

INPUT_DIM = len(FEATURE_NAMES)

# GPU support: falls back to CPU automatically if no CUDA GPU is present --
# same code path either way, nothing to keep in sync between a GPU and a
# CPU variant.
_TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class LSTMAutoencoder(nn.Module):
    """Encoder-decoder over LSTM_SEQ_LEN-length windows of INPUT_DIM-dim
    feature vectors. Shared between scripts/train_lstm_ae.py (which
    trains it) and this file (which only ever loads and runs it).

    GPU-scale-up (SESSION_LOG.md): num_layers stacks LSTM_NUM_LAYERS LSTM
    layers in both encoder and decoder (nn.LSTM's native num_layers
    support -- both must match so the encoder's final (h, c), shaped
    (num_layers, batch, hidden), is a valid initial state for the
    decoder)."""

    def __init__(self, input_dim=INPUT_DIM, hidden_size=LSTM_HIDDEN_SIZE, num_layers=LSTM_NUM_LAYERS):
        super().__init__()
        self.encoder = nn.LSTM(input_size=input_dim, hidden_size=hidden_size, num_layers=num_layers, batch_first=True)
        self.decoder = nn.LSTM(input_size=input_dim, hidden_size=hidden_size, num_layers=num_layers, batch_first=True)
        self.output_layer = nn.Linear(hidden_size, input_dim)

    def forward(self, x):
        # x: (batch, seq_len, input_dim). Encode the whole window, then let
        # the decoder reconstruct it from that context (zeros as decoder
        # input -- a standard seq2seq autoencoder, not teacher-forced with
        # the real values, which would let it trivially "cheat").
        _, (h, c) = self.encoder(x)
        decoder_input = torch.zeros_like(x)
        dec_out, _ = self.decoder(decoder_input, (h, c))
        return self.output_layer(dec_out)


class LSTMAEScorer:
    """Loads a trained LSTMAutoencoder + normalization/baseline-error stats
    at construction; `score()` is a pure forward pass, no training."""

    def __init__(self):
        self.model: LSTMAutoencoder | None = None
        self.mean = np.zeros(INPUT_DIM)
        self.std = np.ones(INPUT_DIM)
        self.baseline_error_mean = 0.0
        self.baseline_error_std = 1.0
        self._history: dict[str, list] = {}  # per-device rolling window of feature vectors
        self._load()

    def _load(self):
        if not (os.path.exists(LSTM_AE_MODEL_PATH) and os.path.exists(LSTM_AE_META_PATH)):
            return  # not trained yet -- score() will defer to the neutral fallback
        model = LSTMAutoencoder()
        model.load_state_dict(torch.load(LSTM_AE_MODEL_PATH, map_location=_TORCH_DEVICE, weights_only=True))
        model.eval()
        self.model = model.to(_TORCH_DEVICE)
        with open(LSTM_AE_META_PATH) as f:
            meta = json.load(f)
        self.mean = np.array(meta["mean"])
        self.std = np.array(meta["std"])
        self.baseline_error_mean = meta["baseline_error_mean"]
        self.baseline_error_std = meta["baseline_error_std"]

    def score(self, device_id: str, feature_vec: list[float]) -> float:
        """Feeds one new feature vector into this device's rolling window
        and scores the current window. Returns [0,1] (1 = reconstructs
        like training-time normal windows, 0 = far worse)."""
        window = self._history.setdefault(device_id, [])
        window.append(feature_vec)
        if len(window) > LSTM_SEQ_LEN:
            del window[0]

        if self.model is None or len(window) < LSTM_SEQ_LEN:
            return 0.9  # not trained yet, or not enough history for this device -- defer

        arr = (np.array(window, dtype=np.float32) - self.mean) / self.std
        x = torch.tensor(arr, dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)  # (1, seq_len, input_dim)
        with torch.no_grad():
            recon = self.model(x)
            error = float(((recon - x) ** 2).mean())

        z = (error - self.baseline_error_mean) / self.baseline_error_std
        return float(np.clip(0.9 - 0.25 * max(z, 0.0), 0.0, 1.0))

    def is_trained(self) -> bool:
        return self.model is not None
