"""
Module 3, Phase 6c: GNN anomaly scorer -- INFERENCE ONLY.

CLAUDE.md Section 8: training happens offline in scripts/train_gnn.py,
which imports `_GCN` from this file (one architecture, not two copies)
and saves a trained state dict to config.GNN_MODEL_PATH. This file's
`GNNScorer` only ever loads it and runs a forward pass over the current
device graph -- it never trains in the live gateway path.

Graph choice (CLAUDE.md Section 2 offers two legitimate options -- this
build uses the HYBRID DEVICE-GRAPH, documented in config.py): nodes =
DEVICE_REGISTRY entries, edges = "communicated with the gateway in the
same time window" (config.GNN_EDGE_WINDOW_SECONDS), node feature vector =
[rule_score, isolation_forest_score, lstm_ae_score]. For the two scalar
devices (sensor-002, actuator-001), which have no independent IF/LSTM-AE
models of their own (those are specific to esp32-vib-001's feature
vector), the if/lstm slots mirror their rule_score -- documented
explicitly here and in gateway.py, not a silent placeholder.

Implementation note: plain PyTorch (hand-rolled GCN layer via matrix
multiply against a normalized adjacency), not `torch-geometric` --
`torch-geometric`'s compiled extensions are version-locked and a common
source of broken installs; not worth the risk for a 3-node graph, where a
hand-rolled GCN layer does the identical math. Swapping in real
torch-geometric later is a contained change if you need a larger graph.
"""

import time

import numpy as np
import torch
import torch.nn as nn

from config import DEVICE_REGISTRY, GNN_EDGE_WINDOW_SECONDS, GNN_HIDDEN_SIZE, GNN_NUM_LAYERS, GNN_NODE_FEATURE_DIM, GNN_MODEL_PATH, GNN_SELF_LOOP_WEIGHT, TRAINING_SEED

torch.manual_seed(TRAINING_SEED)

# GPU support: this file's own `device_id` parameter name already means
# "which CPS device" (esp32-vib-001 etc.), so the torch compute device is
# named _TORCH_DEVICE throughout to avoid colliding with that. Falls back
# to CPU automatically if no CUDA GPU is present -- same code runs
# correctly either way, no separate GPU/CPU code path to keep in sync.
_TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class _GCN(nn.Module):
    """N-layer Graph Convolutional Network: H' = sigma(A_hat @ H @ W) at
    each hop, N-1 hidden hops followed by one hidden->1 output hop.
    Shared between scripts/train_gnn.py (trains it) and this file (only
    ever loads and runs it).

    GPU-scale-up (SESSION_LOG.md): num_layers=2 reproduces the original
    architecture exactly (one in_dim->hidden layer, one hidden->1 output
    layer); num_layers=GNN_NUM_LAYERS (3, the new default) adds one
    hidden->hidden hop in between for real added depth."""

    def __init__(self, in_dim=GNN_NODE_FEATURE_DIM, hidden=GNN_HIDDEN_SIZE, num_layers=GNN_NUM_LAYERS):
        super().__init__()
        assert num_layers >= 2, "need at least an input hop and an output hop"
        hop_layers = [nn.Linear(in_dim, hidden)]
        hop_layers += [nn.Linear(hidden, hidden) for _ in range(num_layers - 2)]
        self.hidden_layers = nn.ModuleList(hop_layers)
        self.out_layer = nn.Linear(hidden, 1)

    def forward(self, x, a_hat):
        h = x
        for layer in self.hidden_layers:
            h = torch.relu(a_hat @ layer(h))
        out = torch.sigmoid(a_hat @ self.out_layer(h))
        return out.squeeze(-1)  # (num_nodes,) -- probability node is "normal"


def normalized_adjacency(active_mask: np.ndarray) -> torch.Tensor:
    """A_hat = D^-1/2 (A + wI) D^-1/2, edge between any two ACTIVE devices.
    w is config.GNN_SELF_LOOP_WEIGHT -- see there for why it is not 1."""
    n = len(active_mask)
    a = np.eye(n) * GNN_SELF_LOOP_WEIGHT
    for i in range(n):
        for j in range(n):
            if i != j and active_mask[i] and active_mask[j]:
                a[i, j] = 1.0
    deg = a.sum(axis=1)
    d_inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(deg, 1e-6)))
    return torch.tensor(d_inv_sqrt @ a @ d_inv_sqrt, dtype=torch.float32)


class GNNScorer:
    """Single shared instance across all devices -- a GNN's whole point is
    reasoning about the device graph jointly. Loads a trained model at
    construction; `score()` is a pure forward pass over the current graph
    snapshot, no training."""

    def __init__(self):
        self.device_ids = list(DEVICE_REGISTRY.keys())
        self._index = {d: i for i, d in enumerate(self.device_ids)}
        n = len(self.device_ids)
        self.last_seen = np.zeros(n)
        self.last_features = np.full((n, GNN_NODE_FEATURE_DIM), 0.9, dtype=np.float32)
        self.model: _GCN | None = None
        self._load()

    def _load(self):
        import os
        if not os.path.exists(GNN_MODEL_PATH):
            return
        model = _GCN()
        model.load_state_dict(torch.load(GNN_MODEL_PATH, map_location=_TORCH_DEVICE, weights_only=True))
        model.eval()
        self.model = model.to(_TORCH_DEVICE)

    def score(self, device_id: str, rule_score: float, if_score: float, lstm_score: float) -> float:
        now = time.time()
        i = self._index[device_id]
        self.last_seen[i] = now
        self.last_features[i] = [rule_score, if_score, lstm_score]

        if self.model is None:
            return 0.9  # not trained yet -- defer to the other scorers

        active = (now - self.last_seen) <= GNN_EDGE_WINDOW_SECONDS
        a_hat = normalized_adjacency(active).to(_TORCH_DEVICE)
        x = torch.tensor(self.last_features, dtype=torch.float32, device=_TORCH_DEVICE)
        with torch.no_grad():
            scores = self.model(x, a_hat)
        return float(scores[i].item())  # .item() implicitly syncs GPU->CPU for this one scalar

    def is_trained(self) -> bool:
        return self.model is not None

    def level2_explain(self, device_id: str) -> tuple[str, float, float] | None:
        """Module 3 Section C.3's perturbation-based Level-2 explanation
        for the GNN: mask one NODE's features at a time (replace with the
        neutral 0.9 fallback every scorer uses for "no evidence yet"), and
        measure the change in THIS device's own output score. The masked
        node causing the largest change is "responsible" -- i.e. which
        other device's current state is most driving this device's GNN
        score, the relational signal no single-device sub-signal can
        produce. Returns (device_id, score_change, counterfactual_score)
        for the top contributor -- counterfactual_score is what THIS
        device's own GNN score would have been with that neighbor masked,
        feeding Section C.4's validation procedure
        (scripts/evaluate_explainability_level2.py) -- never `device_id`
        itself (masking a node's own features and
        asking "how much did that change this same node's score" answers a
        different, less useful question than "which OTHER node matters
        most", the one this signal specifically exists for)."""
        i = self._index[device_id]
        if self.model is None:
            return None

        now = time.time()
        active = (now - self.last_seen) <= GNN_EDGE_WINDOW_SECONDS
        a_hat = normalized_adjacency(active).to(_TORCH_DEVICE)
        x = torch.tensor(self.last_features, dtype=torch.float32, device=_TORCH_DEVICE)
        with torch.no_grad():
            base_score = float(self.model(x, a_hat)[i].item())

            best_device, best_change, best_cf_score = None, -1.0, base_score
            for j, other_id in enumerate(self.device_ids):
                if j == i:
                    continue
                perturbed = x.clone()
                perturbed[j] = 0.9
                perturbed_score = float(self.model(perturbed, a_hat)[i].item())
                change = abs(base_score - perturbed_score)
                if change > best_change:
                    best_device, best_change, best_cf_score = other_id, change, perturbed_score

        # A masked node with no active edge to `i` cannot route any signal
        # through a_hat, so its perturbation changes nothing (change==0.0
        # exactly) -- with NO active neighbors at all, every candidate ties
        # at 0.0 and the loop above would otherwise "pick" the first one in
        # device_ids purely by iteration order, reporting a fake
        # attribution (e.g. always "sensor-002") even though nothing is
        # actually influencing this device's score. Treat that as no
        # attribution rather than a misleading one.
        if best_device is None or best_change <= 1e-6:
            return None
        return (best_device, best_change, best_cf_score)
