"""
Module 3, Phase 6b: LSTM-Autoencoder anomaly scorer -- INFERENCE ONLY.

CLAUDE.md Section 8: training happens offline in scripts/train_lstm_ae.py,
which imports `LSTMAutoencoder` from this file (one architecture
definition, not two copies) and saves a trained state dict + normalization
stats per feature_vector device to config.lstm_ae_path(device_id) /
lstm_ae_meta_path(device_id). This file's
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

from config import LSTM_SEQ_LEN, LSTM_HIDDEN_SIZE, LSTM_NUM_LAYERS, lstm_ae_path, lstm_ae_meta_path, FEATURE_VECTOR_DEVICE_IDS, FEATURE_NAMES, TRAINING_SEED

torch.manual_seed(TRAINING_SEED)

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
        # Per-device registry: one trained model + one set of normalization/
        # baseline-error stats PER feature_vector device (keyed by device_id).
        # A device's raw feature scale and its normal reconstruction-error
        # distribution are both device-specific, so BOTH the model and its
        # stats must be per device -- sharing either would misjudge a second
        # board. `_history` was already per-device.
        self.models: dict[str, LSTMAutoencoder] = {}
        self.stats: dict[str, dict] = {}     # device_id -> {mean, std, baseline_error_mean, baseline_error_std}
        self._history: dict[str, list] = {}  # per-device rolling window of feature vectors
        self._load()

    def _load(self):
        for device_id in FEATURE_VECTOR_DEVICE_IDS:
            model_path, meta_path = lstm_ae_path(device_id), lstm_ae_meta_path(device_id)
            if not (os.path.exists(model_path) and os.path.exists(meta_path)):
                continue  # no model for this device yet -- score() defers to the neutral fallback
            model = LSTMAutoencoder()
            model.load_state_dict(torch.load(model_path, map_location=_TORCH_DEVICE, weights_only=True))
            model.eval()
            self.models[device_id] = model.to(_TORCH_DEVICE)
            with open(meta_path) as f:
                meta = json.load(f)
            self.stats[device_id] = {
                "mean": np.array(meta["mean"]),
                "std": np.array(meta["std"]),
                "baseline_error_mean": meta["baseline_error_mean"],
                "baseline_error_std": meta["baseline_error_std"],
            }

    def score(self, device_id: str, feature_vec: list[float]) -> float:
        """Feeds one new feature vector into this device's rolling window
        and scores the current window. Returns [0,1] (1 = reconstructs
        like training-time normal windows, 0 = far worse)."""
        window = self._history.setdefault(device_id, [])
        window.append(feature_vec)
        if len(window) > LSTM_SEQ_LEN:
            del window[0]

        model = self.models.get(device_id)
        if model is None or len(window) < LSTM_SEQ_LEN:
            return 0.9  # no model for this device, or not enough history yet -- defer

        st = self.stats[device_id]
        arr = (np.array(window, dtype=np.float32) - st["mean"]) / st["std"]
        x = torch.tensor(arr, dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)  # (1, seq_len, input_dim)
        with torch.no_grad():
            recon = model(x)
            error = float(((recon - x) ** 2).mean())

        return self._error_to_score(device_id, error)

    def is_trained(self, device_id: str | None = None) -> bool:
        return bool(self.models) if device_id is None else device_id in self.models

    def _error_to_score(self, device_id: str, error: float) -> float:
        """Same rescaling score() uses -- factored out so level2_explain()'s
        counterfactual error can be turned into a counterfactual SCORE on
        the same (per-device) scale, for the C.4 validation procedure
        (scripts/evaluate_explainability_level2.py)."""
        st = self.stats[device_id]
        z = (error - st["baseline_error_mean"]) / st["baseline_error_std"]
        return float(np.clip(0.9 - 0.25 * max(z, 0.0), 0.0, 1.0))

    def level2_explain(self, device_id: str) -> tuple[str, float, float] | None:
        """Module 3 Section C.3's perturbation-based Level-2 explanation
        for this sub-signal: replace one input channel at a time (across
        every timestep in the current window) with its training-mean
        ("normal") value, re-run the autoencoder, and measure how much
        reconstruction error DROPS. The channel whose replacement drops
        the error the most is "responsible" for this window's anomaly
        score -- exactly the method the design doc specifies, applied to
        the actual live window this scorer already maintains (no new
        plumbing needed: `self._history` is the same state `score()` uses).
        Returns (feature_name, error_drop, counterfactual_score) for the
        top channel -- counterfactual_score is what this sub-signal WOULD
        have scored with that one channel replaced, feeding Section C.4's
        validation procedure -- or None if there isn't a full window yet."""
        window = self._history.get(device_id)
        model = self.models.get(device_id)
        if model is None or not window or len(window) < LSTM_SEQ_LEN:
            return None

        st = self.stats[device_id]
        arr = (np.array(window, dtype=np.float32) - st["mean"]) / st["std"]
        x = torch.tensor(arr, dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)
        with torch.no_grad():
            base_error = float(((model(x) - x) ** 2).mean())

            best_name, best_drop, best_cf_error = None, -1.0, base_error
            for c, name in enumerate(FEATURE_NAMES):
                perturbed = x.clone()
                perturbed[:, :, c] = 0.0  # 0.0 in NORMALIZED space == this channel's own training mean
                perturbed_error = float(((model(perturbed) - perturbed) ** 2).mean())
                drop = base_error - perturbed_error
                if drop > best_drop:
                    best_name, best_drop, best_cf_error = name, drop, perturbed_error
        return (best_name, best_drop, self._error_to_score(device_id, best_cf_error)) if best_name is not None else None
