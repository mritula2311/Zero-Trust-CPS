"""
M6 Set Transformer -- live-runtime candidate scorer, INFERENCE ONLY.

Mirrors gnn_scorer.py's structure exactly: training happens offline in
scripts/train_set_transformer.py, which imports `_SetTransformer` from this
file (one architecture, not two copies) and saves a trained state dict to
config.SET_TRANSFORMER_MODEL_PATH. This file's `SetTransformerScorer` only
ever loads it and runs a forward pass over the current device set -- it
never trains in the live gateway path.

Unlike GCN, which uses a structural adjacency (a_hat) over an edge-window
graph, the Set Transformer has no declared graph at all -- every active
device attends to every other active device via self-attention, and an
inactive device is excluded from that attention entirely via a
key_padding_mask, not by giving it a zero-weight edge. This is the same
node-feature vector GCN's live path uses ([rule_score,
isolation_forest_score, lstm_ae_score]), so the two are a fair,
directly-comparable pair of live candidates -- not scored on different
inputs.
"""

import time

import numpy as np
import torch
import torch.nn as nn

from config import (
    DEVICE_REGISTRY, GNN_EDGE_WINDOW_SECONDS, GNN_NODE_FEATURE_DIM,
    SET_TRANSFORMER_MODEL_PATH, SET_TRANSFORMER_DIM, SET_TRANSFORMER_HEADS,
    SET_TRANSFORMER_BLOCKS, TRAINING_SEED,
)

torch.manual_seed(TRAINING_SEED)

_TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class _SetTransformer(nn.Module):
    """Stacked self-attention blocks over the device set. Permutation-
    equivariant by construction -- node ordering carries no information.
    Shared between scripts/train_set_transformer.py (trains it) and this
    file (only ever loads and runs it). Architecturally identical to
    scripts/benchmark_crossdevice_models.py's SetTransformer (M6); kept as
    a separate copy here for the same reason gnn_scorer.py's _GCN is not
    imported from a research script -- the live path must not depend on
    a file whose only job is an offline benchmark."""

    def __init__(self, in_dim=GNN_NODE_FEATURE_DIM, dim=SET_TRANSFORMER_DIM,
                 heads=SET_TRANSFORMER_HEADS, blocks=SET_TRANSFORMER_BLOCKS):
        super().__init__()
        self.embed = nn.Linear(in_dim, dim)
        self.blocks = nn.ModuleList(
            [nn.MultiheadAttention(dim, heads, batch_first=True) for _ in range(blocks)])
        self.norms = nn.ModuleList([nn.LayerNorm(dim) for _ in range(blocks)])
        self.head = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Linear(dim, 1))

    def forward(self, x, valid):
        """x: (batch, n_nodes, in_dim). valid: (batch, n_nodes) bool, True
        where the node is active -- passed as a key_padding_mask so an
        inactive node's raw feature values can never be attended to as a
        key/value, not merely down-weighted."""
        h = self.embed(x)
        key_padding_mask = ~valid
        for attn, norm in zip(self.blocks, self.norms):
            h = norm(h + attn(h, h, h, key_padding_mask=key_padding_mask,
                              need_weights=False)[0])
        return torch.sigmoid(self.head(h)).squeeze(-1)


class SetTransformerScorer:
    """Single shared instance across all devices, mirroring GNNScorer.
    Loads a trained model at construction; `score()` is a pure forward
    pass over the current device-set snapshot, no training."""

    def __init__(self, checkpoint_path: str | None = None, clock=None):
        """checkpoint_path: explicit override for which checkpoint to load,
        bypassing config.SET_TRANSFORMER_MODEL_PATH. None (default)
        preserves the ambient-config behavior every existing caller
        (gateway, tests, other scripts) relies on. An explicit path exists
        so a comparator script can pin exactly which checkpoint an arm uses
        instead of silently reading whatever the shared config constant
        currently means -- see src/relational_pin.py.

        clock: zero-arg callable returning the current time in seconds, used
        for the active-neighbour window (GNN_EDGE_WINDOW_SECONDS). None
        (default) uses time.time(), the correct choice live. Offline
        replay-based training/evaluation injects a deterministic clock
        derived from each replayed record's own `ts` field instead -- see
        gnn_scorer.GNNScorer's matching docstring for the full rationale."""
        self.device_ids = list(DEVICE_REGISTRY.keys())
        self._index = {d: i for i, d in enumerate(self.device_ids)}
        n = len(self.device_ids)
        self.last_seen = np.zeros(n)
        self.last_features = np.full((n, GNN_NODE_FEATURE_DIM), 0.9, dtype=np.float32)
        self.model: _SetTransformer | None = None
        self._checkpoint_path = checkpoint_path or SET_TRANSFORMER_MODEL_PATH
        self._clock = clock or time.time
        self._load()

    def _load(self):
        import os
        if not os.path.exists(self._checkpoint_path):
            return
        model = _SetTransformer()
        model.load_state_dict(torch.load(self._checkpoint_path, map_location=_TORCH_DEVICE, weights_only=True))
        model.eval()
        self.model = model.to(_TORCH_DEVICE)

    def score(self, device_id: str, rule_score: float, if_score: float, lstm_score: float) -> float:
        now = self._clock()
        i = self._index[device_id]
        self.last_seen[i] = now
        self.last_features[i] = [rule_score, if_score, lstm_score]

        if self.model is None:
            return 0.9  # not trained yet -- defer to the other scorers

        active = (now - self.last_seen) <= GNN_EDGE_WINDOW_SECONDS
        # Same canonicalization as gnn_scorer.py: an inactive row must not
        # carry stale feature values into the (masked-out, but still
        # matmul'd through nn.Linear's embed layer) attention computation.
        x = torch.tensor(np.where(active[:, None], self.last_features, 0.0),
                         dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)
        valid = torch.tensor(active, dtype=torch.bool, device=_TORCH_DEVICE).unsqueeze(0)
        with torch.no_grad():
            scores = self.model(x, valid)
        return float(scores[0, i].item())

    def is_trained(self) -> bool:
        return self.model is not None

    def level2_explain(self, device_id: str) -> tuple[str, float, float] | None:
        """Same Section C.3 perturbation methodology as gnn_scorer.GNNScorer's
        level2_explain (see that docstring for the full rationale), adapted
        to this architecture's actual mechanism: a Set Transformer has no
        adjacency for a masked node's signal to route through, so "masking a
        neighbor" here means removing it from the attention key set
        entirely (valid[j] = False), not replacing its feature values --
        that IS how this architecture excludes a node's influence. Returns
        (device_id, score_change, counterfactual_score) for the top
        contributor, or None if no active neighbor changes anything (device
        is currently isolated) -- never `device_id` itself, same reasoning
        as GNNScorer."""
        i = self._index[device_id]
        if self.model is None:
            return None

        now = self._clock()
        active = (now - self.last_seen) <= GNN_EDGE_WINDOW_SECONDS
        x = torch.tensor(np.where(active[:, None], self.last_features, 0.0),
                         dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)
        valid = torch.tensor(active, dtype=torch.bool, device=_TORCH_DEVICE).unsqueeze(0)
        with torch.no_grad():
            base_score = float(self.model(x, valid)[0, i].item())

            best_device, best_change, best_cf_score = None, -1.0, base_score
            for j, other_id in enumerate(self.device_ids):
                if j == i or not active[j]:
                    continue  # an inactive node is already excluded -- nothing to perturb
                perturbed_valid = valid.clone()
                perturbed_valid[0, j] = False
                perturbed_score = float(self.model(x, perturbed_valid)[0, i].item())
                change = abs(base_score - perturbed_score)
                if change > best_change:
                    best_device, best_change, best_cf_score = other_id, change, perturbed_score

        if best_device is None or best_change <= 1e-6:
            return None
        return (best_device, best_change, best_cf_score)
