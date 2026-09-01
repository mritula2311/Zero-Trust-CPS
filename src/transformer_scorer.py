"""
Module 3, Phase 6 ablation candidate: Transformer denoising-autoencoder
anomaly scorer -- INFERENCE ONLY.

Same split as lstm_ae_scorer.py: training happens offline in
scripts/train_transformer.py, which imports `TransformerAutoencoder` from
this file (one architecture definition) and saves a trained state dict +
normalization/baseline-error stats to config.TRANSFORMER_MODEL_PATH /
TRANSFORMER_META_PATH. This file's `TransformerScorer` only ever loads
those artifacts and runs a forward pass.

NOT wired into fusion_engine.py -- this is an ablation candidate, scored
side-by-side with the other four signals in scripts/evaluate_ablation.py.
See docs/04_module3_trust_evaluation.md Section B.5's GNN keep/drop
precedent: prove it earns its place on held-out data before folding it
into the live fusion inputs.

Same task framing as the LSTM-AE (reconstruct a window of recent feature
vectors, score by reconstruction error), but self-attention over the
whole window instead of an LSTM's sequential bottleneck. Trained with
input noise (see train_transformer.py) specifically because a *clean*
reconstruction transformer can shortcut -- attend directly to neighboring
true values and copy them -- which an LSTM's recurrent bottleneck
prevents by construction but self-attention does not.
"""

import json
import os

import numpy as np
import torch
import torch.nn as nn

from config import (
    LSTM_SEQ_LEN,
    TRANSFORMER_D_MODEL,
    TRANSFORMER_NHEAD,
    TRANSFORMER_NUM_LAYERS,
    TRANSFORMER_DIM_FEEDFORWARD,
    TRANSFORMER_DROPOUT,
    TRANSFORMER_MODEL_PATH,
    TRANSFORMER_META_PATH,
    FEATURE_NAMES,
)

torch.manual_seed(0)

INPUT_DIM = len(FEATURE_NAMES)
SEQ_LEN = LSTM_SEQ_LEN  # deliberately shared with the LSTM-AE -- see config.py's comment

# Same "falls back to CPU automatically" pattern as lstm_ae_scorer.py.
_TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class TransformerAutoencoder(nn.Module):
    """Self-attention encoder over SEQ_LEN-length windows of INPUT_DIM-dim
    feature vectors, reconstructing the same window. Shared between
    scripts/train_transformer.py (which trains it) and this file (which
    only ever loads and runs it)."""

    def __init__(
        self,
        input_dim=INPUT_DIM,
        seq_len=SEQ_LEN,
        d_model=TRANSFORMER_D_MODEL,
        nhead=TRANSFORMER_NHEAD,
        num_layers=TRANSFORMER_NUM_LAYERS,
        dim_feedforward=TRANSFORMER_DIM_FEEDFORWARD,
        dropout=TRANSFORMER_DROPOUT,
    ):
        super().__init__()
        self.input_embedding = nn.Linear(input_dim, d_model)
        # Learned positional embedding, not sinusoidal -- SEQ_LEN is fixed
        # and small, so there's no variable-length-generalization need
        # sinusoidal encodings exist for; a learned table is simpler and
        # just as effective at this scale.
        self.positional_embedding = nn.Parameter(torch.zeros(1, seq_len, d_model))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.output_layer = nn.Linear(d_model, input_dim)

    def forward(self, x):
        # x: (batch, seq_len, input_dim)
        h = self.input_embedding(x) + self.positional_embedding
        h = self.encoder(h)
        return self.output_layer(h)


class TransformerScorer:
    """Loads a trained TransformerAutoencoder + normalization/baseline-
    error stats at construction; `score()` is a pure forward pass, no
    training. Interface deliberately matches LSTMAEScorer so it drops
    into scripts/evaluate_ablation.py as one more column."""

    def __init__(self):
        self.model: TransformerAutoencoder | None = None
        self.mean = np.zeros(INPUT_DIM)
        self.std = np.ones(INPUT_DIM)
        self.baseline_error_mean = 0.0
        self.baseline_error_std = 1.0
        self._history: dict[str, list] = {}
        self._load()

    def _load(self):
        if not (os.path.exists(TRANSFORMER_MODEL_PATH) and os.path.exists(TRANSFORMER_META_PATH)):
            return  # not trained yet -- score() will defer to the neutral fallback
        model = TransformerAutoencoder()
        model.load_state_dict(torch.load(TRANSFORMER_MODEL_PATH, map_location=_TORCH_DEVICE, weights_only=True))
        model.eval()
        self.model = model.to(_TORCH_DEVICE)
        with open(TRANSFORMER_META_PATH) as f:
            meta = json.load(f)
        self.mean = np.array(meta["mean"])
        self.std = np.array(meta["std"])
        self.baseline_error_mean = meta["baseline_error_mean"]
        self.baseline_error_std = meta["baseline_error_std"]

    def score(self, device_id: str, feature_vec: list[float]) -> float:
        """Feeds one new feature vector into this device's rolling window
        and scores the current window (CLEAN, no noise -- noise injection
        is a training-time-only technique). Returns [0,1] (1 = reconstructs
        like training-time normal windows, 0 = far worse)."""
        window = self._history.setdefault(device_id, [])
        window.append(feature_vec)
        if len(window) > SEQ_LEN:
            del window[0]

        if self.model is None or len(window) < SEQ_LEN:
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

    def _error_to_score(self, error: float) -> float:
        """Same rescaling score() uses -- see LSTMAEScorer._error_to_score()."""
        z = (error - self.baseline_error_mean) / self.baseline_error_std
        return float(np.clip(0.9 - 0.25 * max(z, 0.0), 0.0, 1.0))

    def level2_explain(self, device_id: str) -> tuple[str, float, float] | None:
        """Same perturbation-based method as LSTMAEScorer.level2_explain()
        (Module 3 Section C.3) -- deliberately identical logic, since both
        sub-signals answer the same question (reconstruction error over a
        window of feature vectors) and the design doc specifies the same
        perturbation approach for both. Kept as two copies rather than one
        shared helper: each scorer's `score()` is also independently
        duplicated (by design, see this file's own docstring), so a third,
        shared explain-only helper would break that established pattern
        without buying anything -- both are simple enough to stay
        readable side by side with train_lstm_ae.py's near-identical
        train_transformer.py, matching that existing choice. Returns
        (feature_name, error_drop, counterfactual_score) -- see
        LSTMAEScorer.level2_explain()'s docstring for what each means."""
        window = self._history.get(device_id)
        if self.model is None or not window or len(window) < SEQ_LEN:
            return None

        arr = (np.array(window, dtype=np.float32) - self.mean) / self.std
        x = torch.tensor(arr, dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)
        with torch.no_grad():
            base_error = float(((self.model(x) - x) ** 2).mean())

            best_name, best_drop, best_cf_error = None, -1.0, base_error
            for c, name in enumerate(FEATURE_NAMES):
                perturbed = x.clone()
                perturbed[:, :, c] = 0.0
                perturbed_error = float(((self.model(perturbed) - perturbed) ** 2).mean())
                drop = base_error - perturbed_error
                if drop > best_drop:
                    best_name, best_drop, best_cf_error = name, drop, perturbed_error
        return (best_name, best_drop, self._error_to_score(best_cf_error)) if best_name is not None else None
