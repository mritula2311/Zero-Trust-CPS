"""
Model selection for the cross-device Process Anomaly channel.

evaluate_gnn_baselines.py answered "does the GRAPH earn its place" and found it
does not: a concatenated MLP beat the GCN on identical information. That
settles a claim but not a choice -- concat-MLP won a field of two learned
models, which is not evidence it is the right architecture.

This script widens the field to four families that treat the ten-node input
differently, and adds the axis a deployment decision actually turns on
(inference latency), which the baselines script never measured:

    M1 concat_mlp     order-dependent dense net over all 30 sub-scores
    M2 grad_boosting  histogram gradient boosting on the same flat matrix
    M3 deep_sets      per-device encoder -> permutation-invariant pool -> head
    M4 gcn            2-layer GCN over config/graph_topology.json
    M5 gatv2          GATv2 attention over the same declared topology
    M6 set_transformer  multi-head self-attention over the device SET, no graph
    M7 np_st          set transformer + a PROTECTED local path (the proposal)

WHAT M5-M7 ARE TESTING. M4's failure is specific: 0.0067 recall on isolated
anomalies against 0.977 on coordinated ones. The hypothesis is that neighbourhood
aggregation averages a lone anomalous node toward its healthy neighbours. Three
architectures separate the candidate causes:

    M5 keeps the graph, replaces fixed averaging with LEARNED attention.
       If attention alone fixes it, the cause was the fixed weights.
    M6 drops the graph, keeps learned attention over the set.
       If M6 beats M5, the declared topology was the problem, not aggregation.
    M7 adds an explicit local residual the context cannot overwrite.
       If M7 beats M6, preservation is doing work that attention alone does not.

READ M3 BEFORE CLAIMING M7 IS NOVEL. Deep Sets already concatenates each node's
OWN un-aggregated embedding with the pooled context before the head, which is a
protected local path by another name, and it already scores 1.000 isolated
recall. M7's delta over M3 is attention-instead-of-pooling plus an explicit
gate, not the idea of preserving local evidence.


WHY NO xgboost/lightgbm. Neither is installed, and sklearn's
HistGradientBoostingClassifier is the same algorithm family (histogram-binned
GBM, the LightGBM design) already in this project's dependency set. Adding a
dependency to get a second implementation of an algorithm we already have is
the kind of convenience docs/11 records this project deciding against. Stated
here so the absence reads as a decision, not an oversight.

WHY DEEP SETS IS THE INTERESTING ENTRY. Concat is order-dependent: swap two
nodes' feature blocks and the model sees a different input, so it must spend
capacity learning that node 4's block means node 4. Deep Sets is
permutation-invariant by construction -- it gets cross-device context, which
the baselines script showed is what helps, without the graph structure that the
same script showed does not. If the finding is "context yes, structure no",
Deep Sets is the architecture that hypothesis predicts should win.

PROTOCOL -- identical to evaluate_gnn_baselines.py, and fixed before any
number here was looked at:
    TRAIN split      -> fit
    VALIDATION split -> choose every decision threshold (objective: max F1),
                        and the GCN self-loop weight
    TEST split       -> read ONCE, report

Models receive the same per-node [rule, isolation_forest, lstm_ae] sub-scores.
Architecture, optimisation and class weighting differ; in particular the concat
MLP loss is unweighted (RESULTS.md §0.13.17 for the comparison's limits).

OPERATING POINT. Two are reported per model, because "which model" and "where
to set the alarm" are different questions and answering them with one number
hides the trade. The max-F1 point is kept for continuity with
evaluate_gnn_baselines.py. The second is the deployment-relevant one: the most
sensitive threshold whose FALSE POSITIVE RATE stays inside a declared budget
(1% and 3%), read off the ROC rather than a coarse grid, on scores that have
first been isotonically calibrated. A gateway that pages an operator has an
alarm budget; 0.5 is not it, and neither is whatever maximises F1.

WHY NO FOCAL LOSS. The brief allows "focal loss OR class-weighted
cross-entropy". Both torch models here already train under inverse-frequency
class weighting, shared verbatim with train_network_gnn so the comparison stays
like-for-like. Swapping in focal loss would change two models and not the two
sklearn ones, which is the sort of asymmetry this file exists to avoid.

PENDING_REAL_HARDWARE_DATA rows (esp32-vib-002, no capture exists) are excluded
from target loss and metrics, but a neutral 0.9 placeholder remains in model
context. A masked input benchmark is still required; no physical observation
exists for that column.

Writes results/crossdevice_benchmark/.
"""

import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from scipy.stats import t as student_t
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import f1_score, roc_curve, brier_score_loss, roc_auc_score, average_precision_score

from config import (
    NETWORK_NODES, REAL_NODES, GNN_NODE_FEATURE_DIM, GNN_EPOCHS,
    TRAINING_SEED, PROCESS_THRESHOLD, network_edges,
)
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
import virtual_device_generator as vgen
import generate_virtual_network_data as gvnd

# Reuse, do not re-implement. Building a second copy of the snapshot builder is
# exactly how two "identical" comparisons quietly stop being identical.
from evaluate_gnn_baselines import (
    build_snapshots, flatten_for_concat, metrics, choose_threshold,
    event_metrics, train_network_gnn, gnn_scores, SELF_LOOP_SWEEP,
    N_NODES, _TORCH_DEVICE, _NODE_INDEX, normalized_adjacency,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "crossdevice_benchmark")

# Deep Sets sizes chosen to sit between the concat MLP's (32,16) and the GCN's
# hidden width, so no model wins on parameter count alone. Not swept -- a sweep
# on this much data fits noise, and only the concat MLP would have a matching
# sweep to be compared against.
DEEPSETS_ENC_HIDDEN = 24
DEEPSETS_EMBED_DIM = 16
DEEPSETS_HEAD_HIDDEN = 32
DEEPSETS_EPOCHS = 300
DEEPSETS_LR = 1e-2

# Attention models. Widths chosen to land the parameter counts in the same order
# as Deep Sets, so no model wins on capacity alone. Not swept, for the reason
# given above the Deep Sets constants.
ATTN_DIM = 16
ATTN_HEADS = 4
ATTN_BLOCKS = 2
GAT_HIDDEN = 16
GAT_HEADS = 4

LATENCY_SAMPLES = 200   # single-sample forward passes timed per model

# Alarm budgets, declared before any threshold was fitted. 1% of the ~9300
# normal test rows is ~93 false alarms; at one tick per 2 s per node that is the
# order of what an operator will tolerate before muting the channel.
FPR_CAPS = (0.01, 0.03)
PRIMARY_CAP = 0.01      # the cap the summary table is printed at


# --------------------------------------------------------------------------
# M3: Deep Sets
# --------------------------------------------------------------------------
class DeepSets(nn.Module):
    """phi() encodes each device independently; the pool is over devices, so
    the network output is unchanged by permuting node order.

    Both sum AND max are pooled. Sum carries "how much anomaly is present in
    total", max carries "how bad is the worst node" -- a coordinated pattern
    and a single severe fault differ in exactly that pair, and pooling only one
    would make the two indistinguishable to the head.

    The head sees [own_embedding, pooled_context], so it can answer "is node i
    anomalous" while the context stays permutation-invariant. That is the
    set-based equivalent of the one-hot the concat baselines get.
    """

    def __init__(self, in_dim=GNN_NODE_FEATURE_DIM):
        super().__init__()
        self.phi = nn.Sequential(
            nn.Linear(in_dim, DEEPSETS_ENC_HIDDEN), nn.ReLU(),
            nn.Linear(DEEPSETS_ENC_HIDDEN, DEEPSETS_EMBED_DIM), nn.ReLU())
        self.rho = nn.Sequential(
            nn.Linear(DEEPSETS_EMBED_DIM * 3, DEEPSETS_HEAD_HIDDEN), nn.ReLU(),
            nn.Linear(DEEPSETS_HEAD_HIDDEN, 1), nn.Sigmoid())

    def forward(self, x):
        """x: (batch, n_nodes, in_dim) -> (batch, n_nodes) probability-of-NORMAL."""
        h = self.phi(x)                                                  # (b, n, e)
        pooled = torch.cat([h.sum(dim=1), h.max(dim=1).values], dim=1)   # (b, 2e)
        ctx = pooled.unsqueeze(1).expand(-1, x.shape[1], -1)             # (b, n, 2e)
        return self.rho(torch.cat([h, ctx], dim=2)).squeeze(-1)


# --------------------------------------------------------------------------
# M5: GATv2  (Brody et al. 2021)
# --------------------------------------------------------------------------
class GATv2(nn.Module):
    """Graph attention where the scoring MLP is applied AFTER the nonlinearity.

    That ordering is the whole point of GATv2 over GAT: in GAT the attention
    ranking of neighbours is the same for every query node (static attention),
    so it cannot express "node i cares about j but node k does not". Putting the
    linear `a` after the LeakyReLU makes the ranking depend on the query.

    Runs over the SAME declared topology as M4, as a dense mask rather than an
    edge list -- ten nodes is far below the size where sparsity pays, and a
    dense mask keeps this comparable to the GCN's shared-A_hat batching."""

    def __init__(self, in_dim=GNN_NODE_FEATURE_DIM, hidden=GAT_HIDDEN, heads=GAT_HEADS):
        super().__init__()
        self.h, self.d = heads, hidden
        self.proj = nn.Linear(in_dim, heads * hidden)
        self.wl = nn.Linear(hidden, hidden)
        self.wr = nn.Linear(hidden, hidden)
        self.att = nn.Linear(hidden, 1, bias=False)
        self.out = nn.Linear(heads * hidden, 1)

    def _attend(self, h, mask):
        # h: (b, heads, n, d).  e_ij = a^T LeakyReLU(Wl h_i + Wr h_j)
        e = self.att(nn.functional.leaky_relu(
            self.wl(h).unsqueeze(3) + self.wr(h).unsqueeze(2), 0.2)).squeeze(-1)
        e = e.masked_fill(~mask, float("-inf"))
        return torch.softmax(e, dim=-1) @ h

    def forward(self, x, mask):
        b, n, _ = x.shape
        h = self.proj(x).view(b, n, self.h, self.d).transpose(1, 2)   # (b,H,n,d)
        h = torch.relu(self._attend(h, mask))
        h = self._attend(h, mask)
        h = h.transpose(1, 2).reshape(b, n, self.h * self.d)
        return torch.sigmoid(self.out(h)).squeeze(-1)


def topology_mask(n_nodes=None):
    """Boolean (1,1,n,n) adjacency INCLUDING self-loops, broadcast over batch and
    heads. Self-loops are not optional here: a masked softmax row with no true
    entries produces NaN, and an isolated node is exactly the case this
    benchmark exists to measure."""
    n = n_nodes or N_NODES
    m = np.eye(n, dtype=bool)
    if n_nodes is None:
        for edge in network_edges():
            i, j = (_NODE_INDEX[d] for d in edge)
            m[i, j] = m[j, i] = True
    else:
        m[:, :] = True          # dilution/scaling probes use a complete graph
    return torch.tensor(m, device=_TORCH_DEVICE).view(1, 1, n, n)


# --------------------------------------------------------------------------
# M6: Set Transformer     M7: Node-Preserving Set Transformer
# --------------------------------------------------------------------------
class SetTransformer(nn.Module):
    """Stacked self-attention blocks over the device set. No graph at all: every
    device may attend to every other, and what matters is learned rather than
    declared. Permutation-equivariant by construction, so the node ordering
    carries no information -- which is the property the concat models lack."""

    def __init__(self, in_dim=GNN_NODE_FEATURE_DIM, dim=ATTN_DIM,
                 heads=ATTN_HEADS, blocks=ATTN_BLOCKS):
        super().__init__()
        self.embed = nn.Linear(in_dim, dim)
        self.blocks = nn.ModuleList(
            [nn.MultiheadAttention(dim, heads, batch_first=True) for _ in range(blocks)])
        self.norms = nn.ModuleList([nn.LayerNorm(dim) for _ in range(blocks)])
        self.head = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Linear(dim, 1))

    def context(self, x):
        h = self.embed(x)
        for attn, norm in zip(self.blocks, self.norms):
            h = norm(h + attn(h, h, h, need_weights=False)[0])
        return h

    def forward(self, x):
        return torch.sigmoid(self.head(self.context(x))).squeeze(-1)


class NodePreservingSetTransformer(nn.Module):
    """The proposal: a local path the cross-device context is added TO, never
    substituted for.

        L_i = phi(x_i)                      local evidence, sees node i only
        C_i = SetTransformer(x)_i           context, sees every device
        g_i = sigmoid(W [L_i ; C_i])        learned gate
        h_i = L_i + g_i * C_i               context modulates, does not replace

    HONEST LIMIT OF THE MECHANISM, because the paper will be read by someone who
    checks: this is a SOFT preservation, not a guarantee. Nothing stops the
    network learning a large negative C_i that cancels L_i through the sum. The
    residual biases the optimisation toward keeping local evidence and removes
    the architectural *necessity* of destroying it, which is what separates it
    from a GCN whose node state IS the aggregate. A hard guarantee would need a
    non-negative or monotone modulation, and is not what is implemented here."""

    def __init__(self, in_dim=GNN_NODE_FEATURE_DIM, dim=ATTN_DIM):
        super().__init__()
        self.local = nn.Sequential(nn.Linear(in_dim, dim), nn.ReLU(),
                                   nn.Linear(dim, dim), nn.ReLU())
        self.ctx = SetTransformer(in_dim=in_dim, dim=dim)
        self.gate = nn.Linear(dim * 2, dim)
        self.head = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Linear(dim, 1))

    def forward(self, x):
        local = self.local(x)
        ctx = self.ctx.context(x)
        gate = torch.sigmoid(self.gate(torch.cat([local, ctx], dim=-1)))
        return torch.sigmoid(self.head(local + gate * ctx)).squeeze(-1)


def train_deep_sets(X, y, meta, factory=DeepSets, adjacency=None, seed=None):
    """Same optimiser, same class weighting and same masking of PENDING nodes as
    train_network_gnn -- the models differ in architecture and nothing else.

    Shared by M3, M5, M6 and M7 deliberately. Four separate training loops that
    were meant to be identical is how a comparison quietly stops being one."""
    torch.manual_seed(TRAINING_SEED if seed is None else seed)
    model = factory().to(_TORCH_DEVICE)
    x = torch.tensor(X, dtype=torch.float32, device=_TORCH_DEVICE)
    t = torch.tensor(y, dtype=torch.float32, device=_TORCH_DEVICE)
    mask = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool,
                        device=_TORCH_DEVICE)

    n_pos = float(t[mask].sum().item())
    n_neg = float(mask.sum().item() - n_pos)
    w_pos = (n_pos + n_neg) / (2 * max(n_pos, 1.0))
    w_neg = (n_pos + n_neg) / (2 * max(n_neg, 1.0))

    opt = torch.optim.Adam(model.parameters(), lr=DEEPSETS_LR)
    model.train()
    t0 = time.perf_counter_ns()
    for _ in range(DEEPSETS_EPOCHS):
        opt.zero_grad()
        out = model(x) if adjacency is None else model(x, adjacency)
        w = torch.where(t > 0.5, w_pos, w_neg)
        loss = (nn.functional.binary_cross_entropy(out, t, reduction="none") * w)[mask].mean()
        loss.backward()
        opt.step()
    elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
    model.eval()
    return model, elapsed_ms, DEEPSETS_EPOCHS


def train_mixed_cardinality(X, y, meta, factory=SetTransformer,
                            sizes=(2, 3, 5, 10)):
    """Train one set model across MIXED device counts instead of only at n=10.

    Every other model in this file is fitted at n=10 and evaluated elsewhere by
    extrapolation, which is the largest stated limitation of the dilution
    results. Here each epoch draws a cardinality and a random subset of node
    slots, so the same weights see 2-, 3-, 5- and 10-device networks during
    training. Only set models can be trained this way at all; the graph models
    need an adjacency per size and the concat models have a fixed input width.

    THE SUBSETS ARE REAL. A size-k network is k of the ten real scored nodes at
    a real tick, never a synthesised or duplicated device, so nothing here is
    generated data. The ceiling is therefore n=10: this project has ten node
    streams and going above that needs the virtual-device generator, not a
    resampling trick that would quietly reuse one device as several.

    Same optimiser, learning rate, epoch count and class weighting as
    train_deep_sets -- only the cardinality schedule differs."""
    torch.manual_seed(TRAINING_SEED)
    rng = np.random.default_rng(TRAINING_SEED)
    model = factory().to(_TORCH_DEVICE)
    x_all = torch.tensor(X, dtype=torch.float32, device=_TORCH_DEVICE)
    t_all = torch.tensor(y, dtype=torch.float32, device=_TORCH_DEVICE)
    m_all = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool,
                         device=_TORCH_DEVICE)

    n_pos = float(t_all[m_all].sum().item())
    n_neg = float(m_all.sum().item() - n_pos)
    w_pos = (n_pos + n_neg) / (2 * max(n_pos, 1.0))
    w_neg = (n_pos + n_neg) / (2 * max(n_neg, 1.0))

    opt = torch.optim.Adam(model.parameters(), lr=DEEPSETS_LR)
    model.train()
    t0 = time.perf_counter_ns()
    for ep in range(DEEPSETS_EPOCHS):
        k = sizes[ep % len(sizes)]
        cols = torch.tensor(np.sort(rng.choice(N_NODES, size=k, replace=False)),
                            device=_TORCH_DEVICE)
        x, t, mask = x_all[:, cols], t_all[:, cols], m_all[:, cols]
        opt.zero_grad()
        out = model(x)
        w = torch.where(t > 0.5, w_pos, w_neg)
        loss = (nn.functional.binary_cross_entropy(out, t, reduction="none") * w)[mask].mean()
        loss.backward()
        opt.step()
    elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
    model.eval()
    return model, elapsed_ms, DEEPSETS_EPOCHS



# ---------------------------------------------------------------------------
# M9 -- validated LOW-heterogeneity virtual nodes mixed in at every cardinality
# ---------------------------------------------------------------------------

VIRTUAL_NETWORK_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "collected", "virtual_network")
N_VIRTUAL_NODES = 5
_VIRTUAL_NODE_INDEX = {vid: i for i, vid in enumerate(vgen.node_ids(N_VIRTUAL_NODES))}


_VIRTUAL_SCENARIO_NAMES = sorted(gvnd.VIRTUAL_SCENARIOS)


def build_virtual_snapshots(split: str, preset_name: str = "LOW"):
    """(X, y, meta) for the 5-node virtual network
    (scripts/generate_virtual_network_data.py), in EXACTLY build_snapshots()'s
    shape and per-tick scoring convention, so its columns can be pooled with
    the real network's without any special-casing downstream.

    `preset_name`: "LOW" (the only validated, trainable regime) reads the
    unsuffixed files build_virtual_snapshots always has; "MEDIUM"/"HIGH" read
    the OOD-stress-test-only files (test split only -- see
    generate_virtual_network_data.output_path()).

    Virtual nodes are esp32-vib-001-DERIVED telemetry (virtual_device_generator.py's
    own design), so they are scored through esp32-vib-001's trained rule/IF/
    LSTM-AE models -- but each virtual node needs its OWN rolling LSTM-AE
    window. Done by aliasing each virtual node id onto the SAME model/stats
    objects after construction, so LSTMAEScorer's per-device-id `_history`
    dict still gives each one an independent window without any change to
    lstm_ae_scorer.py itself."""
    BASE = vgen.BASE_REAL_NODE
    X, y, meta = [], [], []
    for scenario in _VIRTUAL_SCENARIO_NAMES:
        path = gvnd.output_path(scenario, split, preset_name)
        with open(path) as f:
            rows = json.load(f)
        by_tick = collections.defaultdict(dict)
        for r in rows:
            by_tick[r["tick"]][r["device_id"]] = r

        if_s, lstm_s = IsolationForestScorer(), LSTMAEScorer()   # fresh state per scenario
        for vid in _VIRTUAL_NODE_INDEX:
            lstm_s.models[vid] = lstm_s.models[BASE]
            lstm_s.stats[vid] = lstm_s.stats[BASE]

        for tick in sorted(by_tick):
            node_rows = by_tick[tick]
            feats = np.zeros((N_VIRTUAL_NODES, GNN_NODE_FEATURE_DIM), dtype=np.float32)
            labels = np.ones(N_VIRTUAL_NODES, dtype=np.int64)
            valid = np.ones(N_VIRTUAL_NODES, dtype=bool)
            for device_id, r in node_rows.items():
                i = _VIRTUAL_NODE_INDEX[device_id]
                labels[i] = r["label"]
                fv = fe.feature_vector(r["reading"])
                rule, _ = rule_range_score(BASE, r["reading"])
                iso = if_s.score(BASE, fv)
                lstm = lstm_s.score(device_id, fv)
                feats[i] = [rule, iso, lstm]
            X.append(feats)
            y.append(labels)
            meta.append({"scenario": scenario, "tick": tick, "valid": valid,
                         "event_id": next((r.get("event_id") for r in node_rows.values()), None)})
    return np.array(X), np.array(y), meta


def _train_pooled_sets(sources, sizes, factory=SetTransformer, seed=None):
    """Shared core: pool N (X, y, meta) column-sources along the node axis and
    train one Set Transformer with per-epoch cardinality cycling across
    `sizes`, drawing columns uniformly from the FULL pool at every size (not
    only at the largest) -- see train_mixed_provenance's own docstring for why
    that matters. All sources must have matching row counts."""
    Xs, ys, valids = [], [], []
    n0 = len(sources[0][0])
    for X, y, meta in sources:
        assert len(X) == n0, (
            f"column-pooling requires matching row counts, got {[len(s[0]) for s in sources]}")
        Xs.append(X)
        ys.append(y)
        valids.append(np.array([m["valid"] for m in meta]))

    X_all = np.concatenate(Xs, axis=1)
    y_all = np.concatenate(ys, axis=1)
    valid_all = np.concatenate(valids, axis=1)
    n_cols = X_all.shape[1]

    torch.manual_seed(TRAINING_SEED if seed is None else seed)
    rng = np.random.default_rng(TRAINING_SEED if seed is None else seed)
    model = factory().to(_TORCH_DEVICE)
    x_all_t = torch.tensor(X_all, dtype=torch.float32, device=_TORCH_DEVICE)
    t_all_t = torch.tensor(y_all, dtype=torch.float32, device=_TORCH_DEVICE)
    m_all_t = torch.tensor(valid_all, dtype=torch.bool, device=_TORCH_DEVICE)

    n_pos = float(t_all_t[m_all_t].sum().item())
    n_neg = float(m_all_t.sum().item() - n_pos)
    w_pos = (n_pos + n_neg) / (2 * max(n_pos, 1.0))
    w_neg = (n_pos + n_neg) / (2 * max(n_neg, 1.0))

    opt = torch.optim.Adam(model.parameters(), lr=DEEPSETS_LR)
    model.train()
    t0 = time.perf_counter_ns()
    for ep in range(DEEPSETS_EPOCHS):
        k = sizes[ep % len(sizes)]
        cols = torch.tensor(np.sort(rng.choice(n_cols, size=k, replace=False)),
                            device=_TORCH_DEVICE)
        x, t, mask = x_all_t[:, cols], t_all_t[:, cols], m_all_t[:, cols]
        opt.zero_grad()
        out = model(x)
        w = torch.where(t > 0.5, w_pos, w_neg)
        loss = (nn.functional.binary_cross_entropy(out, t, reduction="none") * w)[mask].mean()
        loss.backward()
        opt.step()
    elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
    model.eval()
    return model, elapsed_ms, DEEPSETS_EPOCHS


def train_mixed_provenance(real, virtual, factory=SetTransformer,
                           sizes=(2, 3, 5, 10, 15), seed=None):
    """M9: same architecture/optimiser/lr/epochs/class-weighting as M8's
    train_mixed_cardinality, but the per-epoch column pool is the FULL 15
    columns (10 existing hybrid + 5 LOW-heterogeneity virtual), not just the
    10 real ones -- every cardinality, not only n=15, can draw a virtual
    column. Confounding "virtual provenance" with "large n" would let the
    model shortcut on which population a column came from instead of learning
    genuine cardinality robustness; sampling uniformly across the full pool at
    every size is what avoids that.

    `real` and `virtual` are (X, y, meta) triples from build_snapshots("train")
    and build_virtual_snapshots("train") respectively. Their row counts must
    match (both are scenario-count x ticks-per-split, deliberately mirrored --
    see generate_virtual_network_data.py's docstring)."""
    return _train_pooled_sets([real, virtual], sizes, factory, seed)


def train_virtual_only(virtual, factory=SetTransformer, sizes=(2, 3, 5), seed=None):
    """Methodology ablation, not a training-regime candidate: the SAME
    architecture trained on ONLY the 5 virtual columns (no real hybrid
    columns at all), to measure whether the real+virtual pooling in
    train_mixed_provenance is earning its keep -- if real+virtual beats
    virtual-only on the REAL test set, that is direct evidence real telemetry
    still matters even after adding virtual scale, not an assumption."""
    return _train_pooled_sets([virtual], sizes, factory, seed)


_VIRTUAL_SCENARIO_KIND = {   # diagnostic labelling only, not stored in the data
    "V_NETWORK_NORMAL": "normal",
    "V_SCENARIO_A": "isolated",
    "V_SCENARIO_B": "coordinated",
    "V_SCENARIO_C": "coordinated",
}


def m9_sanity_check():
    """One-seed sanity check: does the M9 pipeline produce plausible,
    NON-LEAKED scores/labels before committing to the full 10-seed run?

    Same score function (deep_sets_scores) and the same probability-of-NORMAL
    convention feed both regimes below -- there is only one model and one
    scoring path, so Test A/B cannot differ in semantics by construction.
    What CAN differ, and is checked explicitly:
      - threshold is fit on VALIDATION only and frozen before TEST is touched
      - class balance per regime/split
      - threshold-free ROC-AUC / PR-AUC on TEST (calibration-insensitive)
      - per-scenario anomalous-score spread on VALIDATION, to catch a
        memorised/too-clean synthetic anomaly template rather than infer one
    """
    print("Building real snapshots (train/validation/test)...")
    real_tr = build_snapshots("train")[:3]
    real_va = build_snapshots("validation")[:3]
    real_te = build_snapshots("test")[:3]
    print(f"  train={len(real_tr[0])} validation={len(real_va[0])} test={len(real_te[0])} rows")

    print("Building virtual snapshots (train/validation/test)...")
    virt_tr = build_virtual_snapshots("train")
    virt_va = build_virtual_snapshots("validation")
    virt_te = build_virtual_snapshots("test")
    print(f"  train={len(virt_tr[0])} validation={len(virt_va[0])} test={len(virt_te[0])} rows")

    print("Training M9 (1 seed)...")
    model, elapsed_ms, epochs = train_mixed_provenance(real_tr, virt_tr, seed=TRAINING_SEED)
    print(f"  trained in {elapsed_ms:.0f} ms ({epochs} epochs)")

    def _scores_labels(X, y, meta, k):
        cols = np.arange(k)
        scores = deep_sets_scores(model, X[:, cols])
        valid = np.array([m["valid"][:k] for m in meta])
        return scores, y[:, cols], valid, scores[valid], y[:, cols][valid]

    def _regime(name, va, te, k):
        print(f"\n=== {name} (n={k}) ===")
        _, _, _, s_va, lab_va = _scores_labels(*va, k)
        scores_te, y_te_cols, valid_te, s_te, lab_te = _scores_labels(*te, k)

        n_pos_va, n_neg_va = int((lab_va == 0).sum()), int((lab_va == 1).sum())
        n_pos_te, n_neg_te = int((lab_te == 0).sum()), int((lab_te == 1).sum())
        print(f"  class balance  validation: anomalous={n_pos_va:5d} normal={n_neg_va:5d} "
              f"({n_pos_va / (n_pos_va + n_neg_va):.1%} anomalous)")
        print(f"  class balance  test:       anomalous={n_pos_te:5d} normal={n_neg_te:5d} "
              f"({n_pos_te / (n_pos_te + n_neg_te):.1%} anomalous)")

        # Threshold fit on VALIDATION ONLY, then frozen -- TEST labels never
        # participate in choosing it.
        thr = choose_threshold(s_va, lab_va)
        m = metrics(s_te, lab_te, thr)
        true_anom_te = (lab_te == 0).astype(int)
        if len(set(true_anom_te)) > 1:
            roc = roc_auc_score(true_anom_te, -s_te)
            pr = average_precision_score(true_anom_te, -s_te)
        else:
            roc = pr = float("nan")
        print(f"  threshold (fit on VALIDATION only) = {thr:.3f}")
        print(f"  TEST at that threshold: f1={m['f1']:.3f} precision={m['precision']:.3f} "
              f"recall={m['recall']:.3f} fpr={m['false_positive_rate']:.3f} "
              f"detection={m['detection_rate']:.3f}")
        print(f"  TEST threshold-free: ROC-AUC={roc:.4f}  PR-AUC={pr:.4f}")

        for lbl, lname in ((0, "anomalous"), (1, "normal")):
            sub = s_va[lab_va == lbl]
            if len(sub):
                pct = np.percentile(sub, [0, 10, 25, 50, 75, 90, 100])
                print(f"  VALIDATION {lname:10s} n={len(sub):5d}  "
                      f"p0/10/25/50/75/90/100 = " + " ".join(f"{v:.3f}" for v in pct))

        return scores_te, y_te_cols, valid_te

    _regime("Test A -- real-only regression check (same protocol as M8's own test)",
            real_va, real_te, k=N_NODES)

    v_scores_te, v_y_te_cols, v_valid_te = _regime(
        "Test B -- LOW virtual cardinality check", virt_va, virt_te, k=N_VIRTUAL_NODES)

    # Per-scenario anomalous-score spread: the fixed-fault-displacement-per-split
    # simplification (generate_virtual_network_data.py's own docstring) predicts
    # a specific, checkable symptom -- near-zero variance among a scenario's
    # anomalous scores, i.e. the model separating on a repeated template rather
    # than the real CPS problem. Demonstrated here, not inferred.
    print("\n=== per-scenario anomalous-score spread on virtual TEST (template check) ===")
    for sc in sorted(_VIRTUAL_SCENARIO_KIND):
        idx = [i for i, m in enumerate(virt_te[2]) if m["scenario"] == sc]
        if not idx:
            continue
        s_sc, lab_sc, val_sc = v_scores_te[idx], v_y_te_cols[idx], v_valid_te[idx]
        anom = s_sc[val_sc & (lab_sc == 0)]
        norm = s_sc[val_sc & (lab_sc == 1)]
        kind = _VIRTUAL_SCENARIO_KIND[sc]
        if len(anom):
            print(f"  {sc:18s} {kind:11s} anomalous: n={len(anom):5d} mean={anom.mean():.4f} "
                  f"std={anom.std():.4f} min={anom.min():.4f} max={anom.max():.4f}")
        if len(norm):
            print(f"  {'':18s} {'':11s} normal:    n={len(norm):5d} mean={norm.mean():.4f} "
                  f"std={norm.std():.4f}")


def deep_sets_scores(model, X, adjacency=None):
    x = torch.tensor(X, dtype=torch.float32, device=_TORCH_DEVICE)
    with torch.no_grad():
        return (model(x) if adjacency is None else model(x, adjacency)).cpu().numpy()


def n_params(model):
    return int(sum(p.numel() for p in model.parameters()))


def _eval_at_threshold(model, X, y, meta, k, thr):
    cols = np.arange(k)
    scores = deep_sets_scores(model, X[:, cols])
    valid = np.array([m["valid"][:k] for m in meta])
    s, lab = scores[valid], y[:, cols][valid]
    m = metrics(s, lab, thr)
    true_anom = (lab == 0).astype(int)
    if len(set(true_anom)) > 1:
        roc = roc_auc_score(true_anom, -s)
        pr = average_precision_score(true_anom, -s)
    else:
        roc = pr = float("nan")
    return {**m, "roc_auc": roc, "pr_auc": pr}


def _fit_and_eval(model, va, te, k):
    """Threshold fit on VALIDATION only (choose_threshold), frozen before
    scoring TEST -- returns (threshold, test metrics dict)."""
    X_va, y_va, meta_va = va
    cols = np.arange(k)
    s_va = deep_sets_scores(model, X_va[:, cols])
    valid_va = np.array([m["valid"][:k] for m in meta_va])
    thr = choose_threshold(s_va[valid_va], y_va[:, cols][valid_va])
    return thr, _eval_at_threshold(model, *te, k, thr)


def m9_seed_study(n_seeds=10):
    """The full M9 study: 10-seed training with per-seed threshold reporting
    across four regimes, plus a real+virtual vs. virtual-only ablation.

    - Real Test A / LOW virtual: threshold fit fresh each seed on that
      regime's OWN validation split (choose_threshold), then frozen for test
      -- the same protocol evaluate_gnn_baselines.py's docstring locks in.
    - MEDIUM/HIGH stress: NOT re-fit. These have no validation split by
      design (generate_virtual_network_data.py only builds their TEST split)
      -- they reuse the SAME seed's LOW-fitted threshold, frozen, because the
      question is "how does the already-calibrated model degrade under
      distribution shift", not "what threshold would look best here". Fitting
      a threshold on stress-test data would answer a different, less useful
      question and make MEDIUM/HIGH look better than they should.
    - Ablation: the SAME per-seed architecture trained on virtual columns
      ONLY (no real hybrid columns), evaluated on REAL test with its own
      real-validation-fit threshold -- tests whether real+virtual pooling
      (train_mixed_provenance) is actually earning its keep over virtual data
      alone.

    Snapshots don't depend on the training seed and are built ONCE.
    """
    print("Building snapshots (once; reused across all seeds)...")
    real_tr, real_va, real_te = build_snapshots("train")[:3], build_snapshots("validation")[:3], build_snapshots("test")[:3]
    virt_tr = build_virtual_snapshots("train", "LOW")
    virt_va = build_virtual_snapshots("validation", "LOW")
    virt_te = build_virtual_snapshots("test", "LOW")
    medium_te = build_virtual_snapshots("test", "MEDIUM")
    high_te = build_virtual_snapshots("test", "HIGH")
    print(f"  real train={len(real_tr[0])} virtual train={len(virt_tr[0])}")

    rows = {k: [] for k in ("real", "low", "medium", "high", "ablation_real")}

    for seed in range(n_seeds):
        t0 = time.perf_counter_ns()
        model, _elapsed_ms, _epochs = train_mixed_provenance(real_tr, virt_tr, seed=seed)
        abl_model, _, _ = train_virtual_only(virt_tr, seed=seed)

        thr_real, m_real = _fit_and_eval(model, real_va, real_te, N_NODES)
        thr_low, m_low = _fit_and_eval(model, virt_va, virt_te, N_VIRTUAL_NODES)
        m_medium = _eval_at_threshold(model, *medium_te, N_VIRTUAL_NODES, thr_low)
        m_high = _eval_at_threshold(model, *high_te, N_VIRTUAL_NODES, thr_low)
        thr_abl, m_abl = _fit_and_eval(abl_model, real_va, real_te, N_NODES)

        rows["real"].append({"threshold": thr_real, **m_real})
        rows["low"].append({"threshold": thr_low, **m_low})
        rows["medium"].append({"threshold": thr_low, **m_medium})   # frozen, not re-fit
        rows["high"].append({"threshold": thr_low, **m_high})       # frozen, not re-fit
        rows["ablation_real"].append({"threshold": thr_abl, **m_abl})

        dt_s = (time.perf_counter_ns() - t0) / 1e9
        print(f"  seed {seed}: real f1={m_real['f1']:.3f}  low f1={m_low['f1']:.3f}  "
              f"medium f1={m_medium['f1']:.3f}  high f1={m_high['f1']:.3f}  "
              f"ablation(virtual-only on real) f1={m_abl['f1']:.3f}  ({dt_s:.1f}s)")

    metric_keys = ["threshold", "f1", "precision", "recall",
                   "false_positive_rate", "detection_rate", "roc_auc", "pr_auc"]
    summary = {}
    for regime, recs in rows.items():
        summary[regime] = {mk: mean_ci([r[mk] for r in recs]) for mk in metric_keys}

    print(f"\n{'=' * 100}")
    print(f"M9 -- {n_seeds}-SEED STUDY SUMMARY (mean +/- 95% CI over training seeds)")
    print(f"{'=' * 100}")
    labels = {"real": "Real Test A (n=10)", "low": "LOW virtual (n=5)",
              "medium": "MEDIUM stress (frozen thr)", "high": "HIGH stress (frozen thr)",
              "ablation_real": "Ablation: virtual-only-trained, on real test"}
    for regime, label in labels.items():
        print(f"\n{label}:")
        for mk in metric_keys:
            s = summary[regime][mk]
            ci = f"+/-{s['ci95']:.4f}" if s.get("ci95") is not None else "(n<2)"
            print(f"    {mk:22s} {s['mean']:.4f} {ci}")

    path = os.path.join(RESULTS_DIR, "m9_seed_study.json")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"n_seeds": n_seeds, "summary": summary, "per_seed": rows}, f, indent=2, default=float)
    print(f"\nwritten to {path}")
    return summary


_REAL_COL_IDX = np.array([_NODE_INDEX[d] for d in REAL_NODES])          # esp32-vib-001, -002
_SIM_COL_IDX = np.array([i for i in range(N_NODES) if i not in _REAL_COL_IDX])


def _eval_slice(model, X, y, meta, thr, col_idx=None, scenario=None):
    """Metrics at a FROZEN threshold (the model's own full-network,
    validation-fit threshold -- never re-fit per slice, since the question is
    'how does the already-deployed decision behave on this slice', not 'what
    threshold would look best here'), restricted to a column subset and/or a
    single scenario."""
    k = X.shape[1]
    scores = deep_sets_scores(model, X[:, np.arange(k)])
    valid = np.array([m["valid"] for m in meta])
    if scenario is not None:
        row_idx = np.array([i for i, m in enumerate(meta) if m["scenario"] == scenario])
        if len(row_idx) == 0:
            return None
        scores, y, valid = scores[row_idx], y[row_idx], valid[row_idx]
    if col_idx is not None:
        scores, y, valid = scores[:, col_idx], y[:, col_idx], valid[:, col_idx]
    s, lab = scores[valid], y[valid]
    result = metrics(s, lab, thr)
    if not np.any(lab == 0):
        result.update(f1=None, recall=None, detection_rate=None,
                      undefined_reason="no anomalous observations")
    if not np.any(lab == 1):
        result["false_positive_rate"] = None
    return result


def m9_ablation_investigation(n_seeds=10):
    """Why did the virtual-only ablation (F1=0.977) beat M9's real+virtual
    hybrid (F1=0.967) on REAL test, the opposite of the expected direction?
    Two concrete hypotheses, checked directly rather than assumed:

    H1 -- provenance artifact: the real test network's 10 columns are 8
    parametrically-simulated (device_simulator.py, not real-derived) + 2
    genuinely real physical devices (config.REAL_NODES). If the ablation's
    apparent win is confined to the 8 simulated columns and reverses (or
    disappears) on the 2 real physical columns, its "wins on real data" claim
    does not actually hold on real HARDWARE, only on this project's older
    parametric simulator.
    H2 -- easy-scenario artifact: if the win is concentrated in
    NETWORK_NORMAL / easy scenarios rather than holding on SCENARIO_C
    (coordinated, the hard case this whole network exists to test), the
    aggregate F1 difference is not evidence of a genuinely better detector.

    Both models' thresholds are fit ONCE on the full 10-node validation split
    (matching m9_seed_study exactly) and then frozen across every slice below
    -- slicing must not re-fit, or it answers a different question."""
    print("Building snapshots (once; reused across all seeds)...")
    real_tr, real_va, real_te = build_snapshots("train")[:3], build_snapshots("validation")[:3], build_snapshots("test")[:3]
    virt_tr = build_virtual_snapshots("train", "LOW")

    slices = {"real_physical_cols": _REAL_COL_IDX, "simulated_cols": _SIM_COL_IDX}
    scenarios = sorted(set(m["scenario"] for m in real_te[2]))

    per_seed = {"hybrid": collections.defaultdict(list), "ablation": collections.defaultdict(list)}
    for seed in range(n_seeds):
        hybrid, _, _ = train_mixed_provenance(real_tr, virt_tr, seed=seed)
        ablation, _, _ = train_virtual_only(virt_tr, seed=seed)
        thr_hybrid, _ = _fit_and_eval(hybrid, real_va, real_te, N_NODES)
        thr_ablation, _ = _fit_and_eval(ablation, real_va, real_te, N_NODES)

        for name, model, thr in (("hybrid", hybrid, thr_hybrid), ("ablation", ablation, thr_ablation)):
            for slice_name, col_idx in slices.items():
                r = _eval_slice(model, *real_te, thr, col_idx=col_idx)
                per_seed[name][f"col:{slice_name}"].append(r["f1"])
                per_seed[name][f"col:{slice_name}:false_positive_rate"].append(r["false_positive_rate"])
            for sc in scenarios:
                r = _eval_slice(model, *real_te, thr, scenario=sc)
                if r is not None:
                    per_seed[name][f"scenario:{sc}"].append(r["f1"])
                    per_seed[name][f"scenario:{sc}:false_positive_rate"].append(r["false_positive_rate"])
        print(f"  seed {seed} done")

    print(f"\n{'=' * 90}")
    print("M9 ABLATION INVESTIGATION -- per-slice F1 and FPR, mean +/- 95% CI over seeds")
    print(f"{'=' * 90}")
    all_keys = sorted(per_seed["hybrid"])
    print(f"{'slice':28s} {'hybrid (real+virtual)':26s} {'ablation (virtual-only)':26s}")
    summary = {"hybrid": {}, "ablation": {}}
    for key in all_keys:
        row = {}
        for name in ("hybrid", "ablation"):
            vals = [v for v in per_seed[name][key] if v is not None]
            row[name] = mean_ci(vals) if vals else {"mean": None, "ci95": None,
                                                   "undefined_reason": "no observations for this metric"}
            summary[name][key] = row[name]
        h, a = row["hybrid"], row["ablation"]
        h_str = "n/a" if h["mean"] is None else f"{h['mean']:.4f}" + (f" +/-{h['ci95']:.4f}" if h.get("ci95") is not None else " (CI n/a)")
        a_str = "n/a" if a["mean"] is None else f"{a['mean']:.4f}" + (f" +/-{a['ci95']:.4f}" if a.get("ci95") is not None else " (CI n/a)")
        print(f"{key:28s} {h_str:26s} {a_str:26s}")

    path = os.path.join(RESULTS_DIR, "m9_ablation_investigation.json")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"n_seeds": n_seeds, "summary": summary,
                   "per_seed": {k: dict(v) for k, v in per_seed.items()}}, f, indent=2, default=float, allow_nan=False)
    print(f"\nwritten to {path}")
    return summary


# --------------------------------------------------------------------------
# timing
# --------------------------------------------------------------------------
def time_inference_per_sample(predict_one, n=LATENCY_SAMPLES):
    """Latency of ONE sample, not a batch divided by its size.

    A batched throughput number divided by batch size is not latency: the
    deployed gateway scores one tick as it arrives and never gets to amortise a
    batch. Measuring the batch and calling it per-sample would understate every
    model here and would flatter the two torch models most, because they batch
    best."""
    predict_one(0)                      # warm up: first call pays alloc/dispatch cost
    samples = []
    for i in range(n):
        t0 = time.perf_counter_ns()
        predict_one(i)
        samples.append((time.perf_counter_ns() - t0) / 1e6)
    samples.sort()
    return {"mean_ms": round(float(np.mean(samples)), 4),
            "p50_ms": round(samples[len(samples) // 2], 4),
            "p95_ms": round(samples[int(len(samples) * 0.95)], 4),
            "n": n}


# --------------------------------------------------------------------------
# calibration and FPR-capped thresholding
# --------------------------------------------------------------------------
def validation_halves(meta, keep):
    """Split validation rows into a CALIBRATION half and a SELECTION half.

    A calibrator is a fit, not a selection. Fitting it on the same rows the
    threshold is then read from would make the reported FPR the calibrator's
    training error -- the exact shape of leak this project has already had to
    withdraw a published number over. The two halves are disjoint.

    The cut is CONTIGUOUS within each scenario, not random: neighbouring ticks
    share LSTM-AE windows and belong to the same event, so a random row split
    would put two views of one disturbance on both sides of the wall."""
    ticks = {}
    for t, _i in keep:
        ticks.setdefault(meta[t]["scenario"], []).append(meta[t]["tick"])
    cut = {sc: sorted(v)[len(v) // 2] for sc, v in ticks.items()}
    calib = np.array([meta[t]["tick"] < cut[meta[t]["scenario"]] for t, _i in keep])
    return calib, ~calib


def fit_calibrator(scores, labels):
    """Map a model's raw score onto a probability that the node is NORMAL.

    Isotonic rather than Platt: three of these four models emit near-saturated
    scores (M1 and M2 sit at 0.97+ thresholds), and a sigmoid cannot reshape a
    distribution already piled against its own asymptote. Isotonic only assumes
    the score is monotone in the probability, which is the one property all four
    architectures actually share."""
    return IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
        scores, (labels == 1).astype(float))


def threshold_at_fpr_cap(scores, labels, cap):
    """Most SENSITIVE threshold whose false positive rate stays within `cap`.

    Read off the ROC, not off the 1/40 grid choose_threshold() uses: a budget is
    only honoured if the search can land on its boundary, and a coarse grid
    lands wherever it happens to land. `scores` are probability-of-NORMAL, so
    the ROC is built on their negation and the threshold flipped back.

    nextafter widens the returned threshold by one float so that the deployed
    `score < threshold` test includes the boundary ties the ROC counted with
    `>=`. Without it the achieved FPR silently undershoots the point selected,
    which reads as a safety margin and is actually a reporting error."""
    fpr, tpr, thr = roc_curve((labels == 0).astype(int), -scores)
    feasible = np.where(fpr <= cap, tpr, -1.0)
    return float(np.nextafter(-thr[int(np.argmax(feasible))], np.inf))


def brier(scores, labels):
    """Brier score against the NORMAL class -- lower is better calibrated.
    Reported raw and calibrated so the calibration step has to show its work
    rather than being asserted."""
    return round(float(brier_score_loss((labels == 1).astype(int),
                                        np.clip(scores, 0.0, 1.0))), 5)


# --------------------------------------------------------------------------
# structural probes: dilution, scaling, coordination, permutation
# --------------------------------------------------------------------------
def complete_adjacency(n, self_loop_weight):
    """A_hat for a complete graph of n active devices -- the same construction
    src/gnn_scorer.py uses live (edge between any two ACTIVE devices), just at a
    size other than ten. Needed because the probes below vary the device count
    and the declared ten-node topology cannot be evaluated at n != 10."""
    a = np.eye(n) * self_loop_weight + (1.0 - np.eye(n))
    deg = a.sum(axis=1)
    d_inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(deg, 1e-6)))
    return torch.tensor(d_inv_sqrt @ a @ d_inv_sqrt, dtype=torch.float32,
                        device=_TORCH_DEVICE)


def _pools(X, y, meta):
    """Feature vectors of genuinely anomalous and genuinely normal nodes, taken
    from real scored data rather than synthesised. A probe built from invented
    feature values would measure the invention."""
    anom, norm = [], []
    for t in range(len(X)):
        for i in range(X.shape[1]):
            if not meta[t]["valid"][i]:
                continue
            (norm if y[t][i] == 1 else anom).append(X[t][i])
    return np.array(anom), np.array(norm)


def probe_scores(name, model, batch, n, self_loop_weight, force_complete=False):
    """Score a (b, n, 3) probe batch through whichever calling convention the
    model uses, and return probability-of-NORMAL for every node.

    At n == N_NODES the graph models get the DECLARED topology they were trained
    on; at any other size that topology does not exist and a complete graph is
    used, matching src/gnn_scorer.py's live rule (edge between any two active
    devices). Feeding a complete graph at n=10 would have made the permutation
    probe trivially pass -- with all 45 edges present, relabelling changes
    nothing, and the declared graph has 15."""
    x = torch.tensor(batch, dtype=torch.float32, device=_TORCH_DEVICE)
    declared = (n == N_NODES) and not force_complete
    with torch.no_grad():
        if name == "M4_gcn":
            a = normalized_adjacency(self_loop_weight) if declared                 else complete_adjacency(n, self_loop_weight)
            out = model(x, a)
        elif name == "M5_gatv2":
            out = model(x, topology_mask() if declared else topology_mask(n))
        else:
            out = model(x)
    return out.cpu().numpy()


def dilution_probe(models, anom, norm, thresholds, self_loop_weight,
                   sizes=(2, 3, 5, 10, 20), trials=400, rng_seed=TRAINING_SEED):
    """ONE anomalous device among n-1 healthy ones, as n grows.

    force_complete: the graph models get a COMPLETE graph at every n, INCLUDING
    n=10. Without it the row crosses a regime boundary -- the declared 15-edge
    topology exists only at ten nodes, so n=10 would be the one cell drawn from a
    different graph than its neighbours, and any kink there reads as an effect of
    device count when it is an effect of the adjacency changing. The declared
    topology is reported separately instead of being smuggled into the curve.

    This is the experiment the isolated-recall collapse actually predicts. If
    neighbourhood aggregation is what destroys isolated anomalies, the anomalous
    node's own score must degrade as healthy context is added, and the effect
    must be monotone in n. If it does not degrade, the aggregation explanation
    is wrong and the collapse has some other cause -- which is worth knowing
    before building an architecture to fix it.

    Node 0 is always the anomalous one. Every other slot is a real normal
    feature vector drawn from test data. Reported as mean P(anomaly) on node 0
    and as recall at each model's own validation-selected threshold, because a
    score that drifts without crossing the threshold is a different finding from
    one that stops detecting.

    M1/M2 are absent by construction: their input is a fixed 10*3+10 vector, so
    they cannot be evaluated at any other device count. That is itself the
    scaling result.

    EVERY model here was TRAINED at n=10 only. The n != 10 columns are therefore
    extrapolation for all of them, not just the graph ones, and a model that
    behaves oddly at n=2 may be reporting the edge of its training distribution
    rather than a property of its architecture. Stated because the n=10 column
    is the only one that is strictly in-distribution."""
    rng = np.random.default_rng(rng_seed)
    out = {}
    for name, model in models.items():
        rows = {}
        for n in sizes:
            batch = np.empty((trials, n, GNN_NODE_FEATURE_DIM), dtype=np.float32)
            batch[:, 0] = anom[rng.integers(0, len(anom), trials)]
            for j in range(1, n):
                batch[:, j] = norm[rng.integers(0, len(norm), trials)]
            s = probe_scores(name, model, batch, n, self_loop_weight,
                             force_complete=True)[:, 0]
            rows[n] = {"mean_p_anomaly": round(float(1.0 - s.mean()), 4),
                       "recall_at_threshold": round(float((s < thresholds[name]).mean()), 4)}
        out[name] = rows
    return out


def declared_topology_point(models, anom, norm, thresholds, self_loop_weight,
                            trials=400, rng_seed=TRAINING_SEED):
    """The n=10 dilution cell computed on the DECLARED topology the graph models
    were actually trained on -- the only in-distribution point in the whole
    probe. Reported beside the complete-graph curve rather than inside it, so
    the curve stays one experiment and this stays the reality check on it."""
    rng = np.random.default_rng(rng_seed)
    batch = np.empty((trials, N_NODES, GNN_NODE_FEATURE_DIM), dtype=np.float32)
    batch[:, 0] = anom[rng.integers(0, len(anom), trials)]
    for j in range(1, N_NODES):
        batch[:, j] = norm[rng.integers(0, len(norm), trials)]
    out = {}
    for name, model in models.items():
        s = probe_scores(name, model, batch, N_NODES, self_loop_weight)[:, 0]
        out[name] = {"mean_p_anomaly": round(float(1.0 - s.mean()), 4),
                     "recall_at_threshold": round(float((s < thresholds[name]).mean()), 4)}
    return out


def degree_adjacency(n, d, self_loop_weight):
    """The healthy population 1..n-1 is COMPLETE among itself in every condition;
    node 0 connects to exactly d of them. Device count is held at n, the healthy
    nodes' own context is held constant, and the only thing that varies is how
    many healthy neighbours aggregate into the anomalous node.

    An earlier version left nodes 1..n-1 isolated, which broke the intervention:
    with nothing else to attend to, node 0's neighbours absorbed its anomaly and
    reflected it straight back, so GATv2 read a flat 0.99 across every degree
    while reading 0.2225 on a complete graph at the same n. The probe was
    measuring the neighbours' isolation, not node 0's degree."""
    a = np.eye(n) * self_loop_weight
    a[1:, 1:] = 1.0
    np.fill_diagonal(a[1:, 1:], self_loop_weight)
    for j in range(1, d + 1):
        a[0, j] = a[j, 0] = 1.0
    deg = a.sum(axis=1)
    d_inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(deg, 1e-6)))
    return torch.tensor(d_inv_sqrt @ a @ d_inv_sqrt, dtype=torch.float32,
                        device=_TORCH_DEVICE)


def degree_mask(n, d):
    m = np.eye(n, dtype=bool)
    m[1:, 1:] = True                      # healthy population complete among itself
    m[0, 1:d + 1] = True
    m[1:d + 1, 0] = True
    return torch.tensor(m, device=_TORCH_DEVICE).view(1, 1, n, n)


def degree_probe(models, anom, norm, thresholds, self_loop_weight,
                 n=10, degrees=(1, 2, 3, 5, 9), trials=400, rng_seed=TRAINING_SEED):
    """Isolated-anomaly recall against HEALTHY-NEIGHBOUR DEGREE, device count fixed.

    The dilution curve confounds two variables: as n grows, so does the number of
    neighbours aggregating into node 0. This separates them. If recall falls with
    d at constant n, the mechanism is aggregation degree and not set size.

    The set models have no neighbourhood, so d does not exist for them -- they see
    all n devices at every d. Their row is therefore FLAT BY CONSTRUCTION and is
    printed as a reference line, not as a result. Saying so here because a flat
    row that looks like a finding is worse than no row."""
    rng = np.random.default_rng(rng_seed)
    batch = np.empty((trials, n, GNN_NODE_FEATURE_DIM), dtype=np.float32)
    batch[:, 0] = anom[rng.integers(0, len(anom), trials)]
    for j in range(1, n):
        batch[:, j] = norm[rng.integers(0, len(norm), trials)]
    x = torch.tensor(batch, dtype=torch.float32, device=_TORCH_DEVICE)

    out = {}
    for name, model in models.items():
        rows = {}
        for d in degrees:
            with torch.no_grad():
                if name == "M4_gcn":
                    sc = model(x, degree_adjacency(n, d, self_loop_weight))
                elif name == "M5_gatv2":
                    sc = model(x, degree_mask(n, d))
                else:
                    sc = model(x)          # no neighbourhood; d is inapplicable
            sc = sc.cpu().numpy()[:, 0]
            rows[d] = {"mean_p_anomaly": round(float(1.0 - sc.mean()), 4),
                       "recall_at_threshold": round(float((sc < thresholds[name]).mean()), 4)}
        out[name] = rows
    return out


def _peer_edges(n):
    """All pairs among the healthy population 1..n-1, in a fixed order so a
    density level always selects the same edges."""
    return [(i, j) for i in range(1, n) for j in range(i + 1, n)]


def neighbour_density_probe(models, anom, norm, thresholds, self_loop_weight,
                            n=10, d0=3, densities=(0, 4, 9, 18, 36),
                            trials=400, rng_seed=TRAINING_SEED):
    """Node 0's OWN degree is held at d0; what varies is how densely the healthy
    population is wired among ITSELF.

    Motivated by a result the degree probe produced and could not explain: with
    the healthy nodes fully connected, GATv2 sat at ~0.21 recall at EVERY degree
    of node 0, including d=1 -- yet reached 0.8725 on the sparse declared
    topology at the same device count. Node 0's own degree cannot account for
    that, so the candidate mechanism is second-hop: how much healthy context its
    neighbours have absorbed before node 0 attends to them.

    If recall falls with peer density while node 0's degree is constant, the
    dilution is PROPAGATED rather than direct, and 'reduce the target's degree'
    is not a mitigation."""
    rng = np.random.default_rng(rng_seed)
    batch = np.empty((trials, n, GNN_NODE_FEATURE_DIM), dtype=np.float32)
    batch[:, 0] = anom[rng.integers(0, len(anom), trials)]
    for j in range(1, n):
        batch[:, j] = norm[rng.integers(0, len(norm), trials)]
    x = torch.tensor(batch, dtype=torch.float32, device=_TORCH_DEVICE)
    edges = _peer_edges(n)

    out = {}
    for name, model in models.items():
        rows = {}
        for m_edges in densities:
            adj = np.eye(n)
            for (i, j) in edges[:m_edges]:
                adj[i, j] = adj[j, i] = 1.0
            for j in range(1, d0 + 1):
                adj[0, j] = adj[j, 0] = 1.0
            with torch.no_grad():
                if name == "M4_gcn":
                    a = adj * 1.0
                    np.fill_diagonal(a, self_loop_weight)
                    deg = a.sum(axis=1)
                    dh = np.diag(1.0 / np.sqrt(np.maximum(deg, 1e-6)))
                    sc = model(x, torch.tensor(dh @ a @ dh, dtype=torch.float32,
                                               device=_TORCH_DEVICE))
                elif name == "M5_gatv2":
                    msk = torch.tensor(adj.astype(bool), device=_TORCH_DEVICE).view(1, 1, n, n)
                    sc = model(x, msk)
                else:
                    sc = model(x)
            sc = sc.cpu().numpy()[:, 0]
            rows[m_edges] = {"mean_p_anomaly": round(float(1.0 - sc.mean()), 4),
                             "recall_at_threshold": round(float((sc < thresholds[name]).mean()), 4)}
        out[name] = rows
    return out


def coordination_probe(models, anom, norm, thresholds, self_loop_weight,
                       n=10, counts=(1, 2, 3, 5, 10), trials=400,
                       rng_seed=TRAINING_SEED):
    """The mirror of the dilution probe: hold the device count at ten and grow
    the number of SIMULTANEOUSLY anomalous devices. Node 0 is anomalous in every
    condition, so the only thing changing is how much company it has.

    Run because a fix that raises isolated recall can silently cost coordinated
    recall, and reporting only the case that motivated the change is how a
    number goes up while the model gets worse."""
    rng = np.random.default_rng(rng_seed)
    out = {}
    for name, model in models.items():
        rows = {}
        for k in counts:
            batch = np.empty((trials, n, GNN_NODE_FEATURE_DIM), dtype=np.float32)
            for j in range(n):
                pool = anom if j < k else norm
                batch[:, j] = pool[rng.integers(0, len(pool), trials)]
            s = probe_scores(name, model, batch, n, self_loop_weight)[:, 0]
            rows[k] = {"mean_p_anomaly": round(float(1.0 - s.mean()), 4),
                       "recall_at_threshold": round(float((s < thresholds[name]).mean()), 4)}
        out[name] = rows
    return out


def permutation_probe(models, X, self_loop_weight, rng_seed=TRAINING_SEED):
    """Relabel the devices and check whether the verdict follows the device or
    the slot.

    The adjacency is deliberately NOT permuted with the nodes. That is the real
    deployment question -- if device identities are reassigned to slots, does the
    model's answer move? A set model must be exactly invariant; a graph model
    must not be, because its structure is bound to slot indices; the concat
    models cannot be, because a one-hot names the slot. Reported as the max
    absolute score difference, so 'invariant' is a measurement rather than a
    claim about the architecture diagram."""
    rng = np.random.default_rng(rng_seed)
    perm = rng.permutation(X.shape[1])
    inv = np.argsort(perm)
    out = {}
    for name, model in models.items():
        base = probe_scores(name, model, X[:200], X.shape[1], self_loop_weight)
        shuf = probe_scores(name, model, X[:200][:, perm], X.shape[1], self_loop_weight)
        out[name] = round(float(np.abs(base - shuf[:, inv]).max()), 6)
    return out


# --------------------------------------------------------------------------
# coordinated vs isolated recall
# --------------------------------------------------------------------------
def coordination_split(labels, keep_idx):
    """Partition anomalous rows by how many nodes are anomalous AT THAT TICK.

    The scenarios in this dataset are all multi-node by design, so the
    single/coordinated distinction cannot be taken from the scenario name. It is
    taken from the ground-truth labels instead: a tick with exactly one
    anomalous node is an ISOLATED anomaly, two or more is COORDINATED. That is
    the definition the question is actually about, and it is computed from
    labels only -- never from any model's output.
    """
    per_tick = collections.Counter()
    for idx, (t, _i) in enumerate(keep_idx):
        if labels[idx] == 0:
            per_tick[t] += 1
    isolated, coordinated = [], []
    for idx, (t, _i) in enumerate(keep_idx):
        if labels[idx] != 0:
            continue
        (isolated if per_tick[t] == 1 else coordinated).append(idx)
    return np.array(isolated, dtype=int), np.array(coordinated, dtype=int)


def recall_on(scores, idx, threshold):
    if len(idx) == 0:
        return None
    return round(float((scores[idx] < threshold).mean()), 4)


def macro_f1(scores, labels, threshold):
    return round(float(f1_score((labels == 0).astype(int),
                                (scores < threshold).astype(int),
                                average="macro", zero_division=0)), 4)


# --------------------------------------------------------------------------
def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=" * 96)
    print("CROSS-DEVICE PROCESS ANOMALY -- ARCHITECTURE BENCHMARK (10-node hybrid network)")
    print("=" * 96)

    data = {}
    for split in ("train", "validation", "test"):
        X, y, meta, pending = build_snapshots(split)
        flat_X, flat_y, keep = flatten_for_concat(X, y, meta)
        data[split] = dict(X=X, y=y, meta=meta, flat_X=flat_X, flat_y=flat_y, keep=keep)
        print(f"{split:11s} {len(X):5d} snapshots  {len(flat_X):6d} scoreable (tick,node) rows  "
              f"{pending} PENDING rows excluded")
    tr, va, te = data["train"], data["validation"], data["test"]
    print(f"\nPENDING rows are {REAL_NODES[1]} -- no capture exists. Excluded, never imputed.")

    va_calib, va_select = validation_halves(va["meta"], va["keep"])
    print(f"validation split for the capped operating point: {int(va_calib.sum())} rows "
          f"calibrate, {int(va_select.sum())} rows choose the threshold (disjoint)")

    iso_idx, coord_idx = coordination_split(te["flat_y"], te["keep"])
    print(f"TEST anomalous rows: {len(iso_idx)} isolated (1 node bad at that tick), "
          f"{len(coord_idx)} coordinated (>=2)\n")

    results = {}

    def record(name, s_va, s_te, train_ms, epochs, latency, params=None):
        thr = choose_threshold(s_va, va["flat_y"])

        # Calibrate on one half of validation, pick the capped threshold on the
        # other, apply both to test. Test is still read once.
        cal = fit_calibrator(s_va[va_calib], va["flat_y"][va_calib])
        c_va, c_te = cal.predict(s_va), cal.predict(s_te)
        capped = {}
        for cap in FPR_CAPS:
            ct = threshold_at_fpr_cap(c_va[va_select], va["flat_y"][va_select], cap)
            m = metrics(c_te, te["flat_y"], ct)
            capped[str(cap)] = {
                "threshold_selected_on_validation": round(ct, 6),
                "test": m,
                "precision_at_cap": m["precision"],
                "achieved_test_fpr": m["false_positive_rate"],
                "cap_held_on_test": m["false_positive_rate"] <= cap,
                "test_macro_f1": macro_f1(c_te, te["flat_y"], ct),
                "test_event": event_metrics(c_te, te["flat_y"], te["meta"],
                                            te["keep"], ct),
                "recall_isolated_anomaly": recall_on(c_te, iso_idx, ct),
                "recall_coordinated_anomaly": recall_on(c_te, coord_idx, ct)}

        results[name] = {
            "calibration": {
                "method": "isotonic, fitted on the validation calibration half",
                "test_brier_raw": brier(s_te, te["flat_y"]),
                "test_brier_calibrated": brier(c_te, te["flat_y"])},
            "fpr_capped": capped,
            "threshold_selected_on_validation": round(float(thr), 4),
            "validation": metrics(s_va, va["flat_y"], thr),
            "test": metrics(s_te, te["flat_y"], thr),
            "test_macro_f1": macro_f1(s_te, te["flat_y"], thr),
            "test_event": event_metrics(s_te, te["flat_y"], te["meta"], te["keep"], thr),
            "recall_isolated_anomaly": recall_on(s_te, iso_idx, thr),
            "recall_coordinated_anomaly": recall_on(s_te, coord_idx, thr),
            "train_time_ms_total": round(train_ms, 2),
            "train_epochs": epochs,
            "train_ms_per_epoch": round(train_ms / epochs, 3) if epochs else None,
            "inference_latency": latency,
            "parameters": params,
        }

    # ---- M1 concat MLP ----------------------------------------------------
    t0 = time.perf_counter_ns()
    m1 = MLPClassifier(hidden_layer_sizes=(32, 16), activation="relu", solver="adam",
                       learning_rate_init=1e-3, max_iter=400,
                       random_state=TRAINING_SEED).fit(tr["flat_X"], tr["flat_y"])
    m1_ms = (time.perf_counter_ns() - t0) / 1e6
    record("M1_concat_mlp",
           m1.predict_proba(va["flat_X"])[:, 1], m1.predict_proba(te["flat_X"])[:, 1],
           m1_ms, int(m1.n_iter_),
           time_inference_per_sample(
               lambda i: m1.predict_proba(te["flat_X"][i % len(te["flat_X"]):
                                                       i % len(te["flat_X"]) + 1])),
           params=int(sum(c.size for c in m1.coefs_) + sum(b.size for b in m1.intercepts_)))

    # ---- M2 gradient boosting --------------------------------------------
    # class_weight="balanced" matches every other model here; without it the
    # numerous normal rows dominate and the comparison stops being like-for-like.
    t0 = time.perf_counter_ns()
    m2 = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1,
                                        class_weight="balanced",
                                        random_state=TRAINING_SEED).fit(tr["flat_X"], tr["flat_y"])
    m2_ms = (time.perf_counter_ns() - t0) / 1e6
    record("M2_grad_boosting",
           m2.predict_proba(va["flat_X"])[:, 1], m2.predict_proba(te["flat_X"])[:, 1],
           m2_ms, int(m2.n_iter_),
           time_inference_per_sample(
               lambda i: m2.predict_proba(te["flat_X"][i % len(te["flat_X"]):
                                                       i % len(te["flat_X"]) + 1])),
           params=None)   # tree ensemble: parameter count is not comparable

    # ---- M3 Deep Sets -----------------------------------------------------
    ds, ds_ms, ds_epochs = train_deep_sets(tr["X"], tr["y"], tr["meta"])
    ds_va_all = deep_sets_scores(ds, va["X"])
    ds_te_all = deep_sets_scores(ds, te["X"])
    record("M3_deep_sets",
           np.array([ds_va_all[t][i] for t, i in va["keep"]]),
           np.array([ds_te_all[t][i] for t, i in te["keep"]]),
           ds_ms, ds_epochs,
           time_inference_per_sample(
               lambda i: deep_sets_scores(ds, te["X"][i % len(te["X"]):
                                                      i % len(te["X"]) + 1])),
           params=n_params(ds))

    # ---- M4 GCN -----------------------------------------------------------
    # Self-loop weight selected on VALIDATION, same sweep as the baselines script.
    sweep = {}
    for w in SELF_LOOP_SWEEP:
        m = train_network_gnn(tr["X"], tr["y"], tr["meta"], w)
        s = gnn_scores(m, va["X"], w, va["meta"])
        flat = np.array([s[t][i] for t, i in va["keep"]])
        thr = choose_threshold(flat, va["flat_y"])
        sweep[w] = {"threshold": thr, **metrics(flat, va["flat_y"], thr)}
    best_w = max(sweep, key=lambda w: sweep[w]["f1"])
    print(f"GCN self-loop weight {best_w} selected on validation "
          f"(F1 {sweep[best_w]['f1']:.4f})\n")

    t0 = time.perf_counter_ns()
    gnn = train_network_gnn(tr["X"], tr["y"], tr["meta"], best_w)
    gnn_ms = (time.perf_counter_ns() - t0) / 1e6
    gva = gnn_scores(gnn, va["X"], best_w, va["meta"])
    gte = gnn_scores(gnn, te["X"], best_w, te["meta"])
    record("M4_gcn",
           np.array([gva[t][i] for t, i in va["keep"]]),
           np.array([gte[t][i] for t, i in te["keep"]]),
           gnn_ms, GNN_EPOCHS,
           time_inference_per_sample(
               lambda i: gnn_scores(gnn, te["X"][i % len(te["X"]):
                                                 i % len(te["X"]) + 1], best_w)),
           params=n_params(gnn))

    # ---- M5 GATv2, M6 Set Transformer, M7 NP-ST ---------------------------
    # Identical training loop to M3; only the architecture differs.
    mask = topology_mask()
    attn_models = {}
    for name, factory, adj in (("M5_gatv2", GATv2, mask),
                               ("M6_set_transformer", SetTransformer, None),
                               ("M7_np_st", NodePreservingSetTransformer, None)):
        mdl, ms, eps = train_deep_sets(tr["X"], tr["y"], tr["meta"], factory, adj)
        attn_models[name] = mdl
        s_va_all = deep_sets_scores(mdl, va["X"], adj)
        s_te_all = deep_sets_scores(mdl, te["X"], adj)
        record(name,
               np.array([s_va_all[t][i] for t, i in va["keep"]]),
               np.array([s_te_all[t][i] for t, i in te["keep"]]),
               ms, eps,
               time_inference_per_sample(
                   lambda i, m=mdl, a=adj: deep_sets_scores(
                       m, te["X"][i % len(te["X"]):i % len(te["X"]) + 1], a)),
               params=n_params(mdl))

    # ---- M8: the same Set Transformer, trained across mixed cardinalities --
    mx, mx_ms, mx_eps = train_mixed_cardinality(tr["X"], tr["y"], tr["meta"])
    mx_va = deep_sets_scores(mx, va["X"])
    mx_te = deep_sets_scores(mx, te["X"])
    record("M8_set_transformer_mixed_n",
           np.array([mx_va[t][i] for t, i in va["keep"]]),
           np.array([mx_te[t][i] for t, i in te["keep"]]),
           mx_ms, mx_eps,
           time_inference_per_sample(
               lambda i: deep_sets_scores(mx, te["X"][i % len(te["X"]):
                                                      i % len(te["X"]) + 1])),
           params=n_params(mx))

    # ---- report -----------------------------------------------------------
    order = ["M1_concat_mlp", "M2_grad_boosting", "M3_deep_sets", "M4_gcn",
             "M5_gatv2", "M6_set_transformer", "M7_np_st",
             "M8_set_transformer_mixed_n"]
    hdr = (f"{'model':18s} {'macroF1':>8s} {'F1':>7s} {'detect':>7s} {'FPR':>7s} "
           f"{'evtRec':>7s} {'isoRec':>7s} {'coordRec':>9s} {'ms/epoch':>9s} {'infer ms':>9s} "
           f"{'params':>7s}")
    print("TEST-SET RESULTS  (threshold chosen on validation, test read once)")
    print("-" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for name in order:
        r = results[name]
        t = r["test"]
        iso = "n/a" if r["recall_isolated_anomaly"] is None else f"{r['recall_isolated_anomaly']:.4f}"
        crd = "n/a" if r["recall_coordinated_anomaly"] is None else f"{r['recall_coordinated_anomaly']:.4f}"
        print(f"{name:18s} {r['test_macro_f1']:>8.4f} {t['f1']:>7.4f} "
              f"{t['detection_rate']:>7.4f} {t['false_positive_rate']:>7.4f} "
              f"{r['test_event']['event_recall']:>7.4f} {iso:>7s} {crd:>9s} "
              f"{(r['train_ms_per_epoch'] or 0):>9.3f} "
              f"{r['inference_latency']['mean_ms']:>9.4f} "
              f"{('n/a' if r['parameters'] is None else str(r['parameters'])):>7s}")
    print("-" * len(hdr))
    print("isoRec   = recall on ticks where exactly ONE node is anomalous")
    print("coordRec = recall on ticks where TWO OR MORE nodes are anomalous")
    print("infer ms = mean single-sample latency, not batch throughput / batch size")
    print("params   = n/a for M2: a tree ensemble has no comparable parameter count")

    # ---- second operating point: calibrated, inside the alarm budget -------
    print()
    print(f"SAME MODELS AT A DECLARED ALARM BUDGET  (isotonic-calibrated, "
          f"FPR <= {PRIMARY_CAP:.0%} chosen on validation)")
    hdr2 = (f"{'model':18s} {'thresh':>8s} {'precis':>7s} {'detect':>7s} {'FPR':>7s} "
            f"{'macroF1':>8s} {'isoRec':>7s} {'coordRec':>9s} {'brier':>8s} {'brierCal':>9s}")
    print("-" * len(hdr2))
    print(hdr2)
    print("-" * len(hdr2))
    for name in order:
        r = results[name]
        c = r["fpr_capped"][str(PRIMARY_CAP)]
        iso = "n/a" if c["recall_isolated_anomaly"] is None else f"{c['recall_isolated_anomaly']:.4f}"
        crd = "n/a" if c["recall_coordinated_anomaly"] is None else f"{c['recall_coordinated_anomaly']:.4f}"
        flag = "" if c["cap_held_on_test"] else "  <-- CAP BREACHED ON TEST"
        print(f"{name:18s} {c['threshold_selected_on_validation']:>8.4f} "
              f"{c['precision_at_cap']:>7.4f} {c['test']['detection_rate']:>7.4f} "
              f"{c['achieved_test_fpr']:>7.4f} {c['test_macro_f1']:>8.4f} "
              f"{iso:>7s} {crd:>9s} "
              f"{r['calibration']['test_brier_raw']:>8.5f} "
              f"{r['calibration']['test_brier_calibrated']:>9.5f}{flag}")
    print("-" * len(hdr2))
    print("A cap chosen on validation is not a guarantee on test. Where the achieved")
    print("test FPR exceeds the budget it is printed and flagged, not re-tuned.")
    print(f"FPR <= {FPR_CAPS[1]:.0%} is recorded in metrics.json alongside this one.")

    # ---- structural probes ------------------------------------------------
    # Every model that can accept a variable device count. M1/M2 cannot.
    probe_models = {"M3_deep_sets": ds, "M4_gcn": gnn, **attn_models,
                    "M8_set_transformer_mixed_n": mx}
    probe_thr = {k: results[k]["threshold_selected_on_validation"] for k in probe_models}
    anom_pool, norm_pool = _pools(te["X"], te["y"], te["meta"])
    dil = dilution_probe(probe_models, anom_pool, norm_pool, probe_thr, best_w)
    coo = coordination_probe(probe_models, anom_pool, norm_pool, probe_thr, best_w)
    perm = permutation_probe(probe_models, te["X"], best_w)
    declared_pt = declared_topology_point(probe_models, anom_pool, norm_pool,
                                          probe_thr, best_w)
    deg = degree_probe(probe_models, anom_pool, norm_pool, probe_thr, best_w)
    dens = neighbour_density_probe(probe_models, anom_pool, norm_pool, probe_thr, best_w)

    def probe_table(title, table, sizes, col, legend):
        print()
        print(title)
        h = f"{'model':20s}" + "".join(f"{('n=' + str(n)):>10s}" for n in sizes)
        print("-" * len(h)); print(h); print("-" * len(h))
        for name in [k for k in order if k in table]:
            print(f"{name:20s}" + "".join(f"{table[name][n][col]:>10.4f}" for n in sizes))
        print("-" * len(h))
        print(legend)

    print()
    print("=" * 96)
    print("STRUCTURAL PROBES -- what the architectures do, not how they score")
    print("=" * 96)
    print(f"drawn from real test feature vectors: {len(anom_pool)} anomalous, "
          f"{len(norm_pool)} normal; 400 trials per cell")
    print("M1/M2 are absent: a fixed 10*3+10 input cannot be evaluated at any other")
    print("device count. That inability IS the scaling result, not a missing row.")

    probe_table("A. DILUTION -- one anomalous device among n-1 healthy ones",
                dil, (2, 3, 5, 10, 20), "mean_p_anomaly",
                "mean P(anomaly) on the anomalous node. Falling with n means healthy "
                "context is suppressing local evidence -- the hypothesis the "
                "GCN's 0.0067 predicts.")
    probe_table("   dilution, recall at each model's own threshold",
                dil, (2, 3, 5, 10, 20), "recall_at_threshold",
                "a score that drifts without crossing the threshold is a different "
                "finding from one that stops detecting; both are reported.")
    probe_table("B. COORDINATION -- k of 10 devices anomalous at once",
                coo, (1, 2, 3, 5, 10), "mean_p_anomaly",
                "the opposite case, run because a fix that raises isolated recall can "
                "silently cost coordinated recall.")

    probe_table("D. NEIGHBOUR DEGREE -- n fixed at 10, only node 0's degree varies",
                deg, (1, 2, 3, 5, 9), "recall_at_threshold",
                "the causal version of A: device count is constant, so any fall is "
                "caused by aggregation degree alone. Set-model rows are FLAT BY "
                "CONSTRUCTION and are a reference line, not a result.")

    probe_table("E. PEER DENSITY -- n=10, node 0 degree fixed at 3, peers wired to "
                "each other",
                dens, (0, 4, 9, 18, 36), "recall_at_threshold",
                "columns are EDGES among the 9 healthy peers (36 = complete). "
                "Node 0's own degree never changes, so a fall here is dilution "
                "arriving through its neighbours rather than directly.")

    print()
    print("   n=10 on the DECLARED 15-edge topology (the only in-distribution cell)")
    print("-" * 60)
    for name in [k for k in order if k in declared_pt]:
        d = declared_pt[name]
        print(f"{name:20s} P(anomaly) {d['mean_p_anomaly']:.4f}   "
              f"recall {d['recall_at_threshold']:.4f}")
    print("-" * 60)
    print("differs from the n=10 column above only in the adjacency; the set")
    print("models are identical there because they never see a graph.")

    print()
    print("C. PERMUTATION -- devices relabelled, adjacency NOT permuted with them")
    print("-" * 60)
    for name in [k for k in order if k in perm]:
        verdict = "invariant" if perm[name] < 1e-5 else "order-dependent"
        print(f"{name:20s} max |delta| = {perm[name]:.6f}   {verdict}")
    print("-" * 60)
    print("M1/M2 are order-dependent by construction -- a one-hot names the slot.")

    # ---- recommendation ---------------------------------------------------
    best_f1 = max(order, key=lambda k: results[k]["test_macro_f1"])
    fastest = min(order, key=lambda k: results[k]["inference_latency"]["mean_ms"])
    best_capped = max(order, key=lambda k: results[k]["fpr_capped"][str(PRIMARY_CAP)]
                      ["test"]["detection_rate"])

    # A ranking is only a finding if the gap is bigger than the noise. One test
    # split, one seed, and no confidence intervals cannot separate two models a
    # few thousandths of macro-F1 apart -- announcing a winner there would be
    # reading rank order out of sampling noise. MARGIN is declared here rather
    # than derived, because deriving it would need repeated seeds this script
    # does not run.
    MARGIN = 0.01
    tied = [k for k in order
            if results[best_f1]["test_macro_f1"] - results[k]["test_macro_f1"] < MARGIN]

    print()
    print("RECOMMENDATION")
    print("-" * len(hdr))
    print(f"  highest test macro-F1 : {best_f1} ({results[best_f1]['test_macro_f1']:.4f})")
    print(f"  best inside the budget: {best_capped} "
          f"({results[best_capped]['fpr_capped'][str(PRIMARY_CAP)]['test']['detection_rate']:.4f} "
          f"detection at FPR <= {PRIMARY_CAP:.0%}, precision "
          f"{results[best_capped]['fpr_capped'][str(PRIMARY_CAP)]['precision_at_cap']:.4f})")
    print(f"  lowest inference cost : {fastest} "
          f"({results[fastest]['inference_latency']['mean_ms']:.4f} ms/sample)")
    if len(tied) > 1:
        print(f"  within {MARGIN} macro-F1 of the best, i.e. NOT separated by this")
        print(f"  experiment: {', '.join(tied)}")
        cheapest_tied = min(tied, key=lambda k: results[k]["inference_latency"]["mean_ms"])
        print(f"  -> accuracy does not decide between them. Taking the cheapest of the")
        print(f"     tied set: {cheapest_tied} "
              f"({results[cheapest_tied]['test_macro_f1']:.4f} macro-F1, "
              f"{results[cheapest_tied]['inference_latency']['mean_ms']:.4f} ms/sample).")
        print(f"     Separating them properly needs repeated seeds and a second test")
        print(f"     session, neither of which exists yet.")
    elif best_f1 == fastest:
        print(f"  -> {best_f1} wins on both axes. No trade-off to argue about.")
    else:
        d_f1 = results[best_f1]["test_macro_f1"] - results[fastest]["test_macro_f1"]
        d_ms = (results[best_f1]["inference_latency"]["mean_ms"]
                - results[fastest]["inference_latency"]["mean_ms"])
        print(f"  -> {best_f1} buys {d_f1:+.4f} macro-F1 for {d_ms:+.4f} ms/sample "
              f"against {fastest}.")
        print(f"     Telemetry arrives every 2.0 s per node, so a {abs(d_ms):.4f} ms "
              f"difference is not")
        print(f"     a binding constraint at this network size; accuracy is the "
              f"deciding axis.")
    print()
    print("  CAVEAT, not optional: these differences are measured on ONE test split")
    print("  of a network with TWO physical devices and eight simulated ones. Model")
    print("  ranking on simulated nodes is evidence about the simulator as much as")
    print("  about the models. This is architecture SELECTION, not a published")
    print("  claim of superiority.")

    out = {"protocol": {"fit": "train", "selected_on": "validation",
                        "reported_on": "test",
                        "threshold_objective": "max F1 on validation",
                        "gcn_self_loop_weight": best_w, "seed": TRAINING_SEED},
           "network": {"size": N_NODES, "real": len(REAL_NODES),
                       "simulated": N_NODES - len(REAL_NODES), "nodes": NETWORK_NODES},
           "coordination_definition":
               ">=2 anomalous nodes at the same tick, taken from ground-truth labels only",
           "test_anomalous_rows": {"isolated": int(len(iso_idx)),
                                   "coordinated": int(len(coord_idx))},
           "operating_points": {
               "max_f1": "threshold maximising F1 on the full validation split",
               "fpr_capped": ("isotonic calibration fitted on the validation "
                              "calibration half; threshold read off the ROC of the "
                              "disjoint validation selection half at each cap"),
               "caps": list(FPR_CAPS)},
           "structural_probes": {
               "dilution_one_anomaly_among_n_minus_1_healthy": dil,
               "coordination_k_of_10_anomalous": coo,
               "permutation_max_abs_score_delta": perm,
               "dilution_n10_declared_topology": declared_pt,
               "neighbour_degree_at_n10": deg,
               "peer_density_at_n10_degree3": dens,
               "dilution_graph_regime": "complete graph at every n, so the curve "
                                        "is one experiment; declared topology "
                                        "reported separately",
               "excluded": "M1/M2 accept a fixed 10*3+10 vector only"},
           "gcn_self_loop_sweep_validation": {str(k): v for k, v in sweep.items()},
           "results": results,
           "recommendation": {"highest_macro_f1": best_f1, "lowest_latency": fastest,
                              f"highest_detection_at_fpr_{PRIMARY_CAP}": best_capped},
           "limitations": [
               "single test split; no repeated-seed confidence intervals",
               "eight of ten nodes are SIMULATED -- ranking partly reflects the simulator",
               "xgboost/lightgbm not installed; sklearn HistGradientBoosting used instead",
               "an FPR cap is honoured on validation; the achieved test FPR is "
               "reported as measured and flagged when it exceeds the cap"]}
    with open(os.path.join(RESULTS_DIR, "metrics.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nwritten to {RESULTS_DIR}")


# --------------------------------------------------------------------------
# multi-seed validation of the two dilution mechanisms
# --------------------------------------------------------------------------
def mean_ci(values):
    """Mean and half-width of a two-sided 95% interval over SEEDS.

    The spread here is training-seed variance at a fixed dataset, which is the
    question -- 'does this mechanism reproduce when the model is refitted' -- and
    NOT sampling variance over test rows. A single split is still a single split;
    this interval does not widen to cover that and must not be described as if it
    does."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < 2:
        return {"mean": round(float(v.mean()), 4) if n else None,
                "ci95": None, "n_seeds": n}
    t = float(student_t.ppf(0.975, n - 1))
    half = t * float(v.std(ddof=1)) / np.sqrt(n)
    return {"mean": round(float(v.mean()), 4), "ci95": round(float(half), 4),
            "sd": round(float(v.std(ddof=1)), 4), "n_seeds": n,
            "multiplier": "t",
            # Raw per-seed values kept, not just the summary. A +-0.36 interval
            # on a bounded [0,1] metric is a warning that the distribution may be
            # bimodal, and a mean +- CI reported over a bimodal outcome describes
            # a value no seed actually produced.
            "per_seed": [round(float(x), 4) for x in v]}


def seed_study(data, seeds, best_w):
    """Refit M3/M4/M5/M6 under each seed and re-run probes D and E.

    Everything is refitted per seed, INCLUDING the decision threshold, because a
    threshold carried over from seed 0 would make later seeds be evaluated at an
    operating point chosen for a model that no longer exists. Probes D and E only
    -- they are the two that carry the mechanism claim, and running the full
    benchmark per seed would multiply runtime for numbers no claim rests on."""
    import evaluate_gnn_baselines as egb

    tr, va, te = data["train"], data["validation"], data["test"]
    anom, norm = _pools(te["X"], te["y"], te["meta"])
    acc = {}
    for seed in seeds:
        models, thr = {}, {}
        models["M3_deep_sets"], _, _ = train_deep_sets(
            tr["X"], tr["y"], tr["meta"], DeepSets, None, seed)
        models["M5_gatv2"], _, _ = train_deep_sets(
            tr["X"], tr["y"], tr["meta"], GATv2, topology_mask(), seed)
        models["M6_set_transformer"], _, _ = train_deep_sets(
            tr["X"], tr["y"], tr["meta"], SetTransformer, None, seed)
        # train_network_gnn seeds itself from the module-level constant, so the
        # constant is what has to move. Restored below; noted because a leaked
        # global would silently reseed every later call in the process.
        prev, egb.TRAINING_SEED = egb.TRAINING_SEED, seed
        try:
            models["M4_gcn"] = train_network_gnn(tr["X"], tr["y"], tr["meta"], best_w)
        finally:
            egb.TRAINING_SEED = prev

        for name, m in models.items():
            if name == "M4_gcn":
                sv = gnn_scores(m, va["X"], best_w, va["meta"])
            elif name == "M5_gatv2":
                sv = deep_sets_scores(m, va["X"], topology_mask())
            else:
                sv = deep_sets_scores(m, va["X"])
            thr[name] = choose_threshold(
                np.array([sv[t][i] for t, i in va["keep"]]), va["flat_y"])

        d = degree_probe(models, anom, norm, thr, best_w)
        e = neighbour_density_probe(models, anom, norm, thr, best_w)
        for probe, table in (("degree", d), ("peer_density", e)):
            for name, rows in table.items():
                for level, cell in rows.items():
                    acc.setdefault(probe, {}).setdefault(name, {}).setdefault(
                        level, []).append(cell["recall_at_threshold"])

    return {probe: {name: {lvl: mean_ci(vals) for lvl, vals in rows.items()}
                    for name, rows in tables.items()}
            for probe, tables in acc.items()}


def _per_seed(out, probe, model, level):
    """Probe levels are ints while the study is in memory and strings once the
    JSON has been round-tripped. Accepting both is not defensive dressing: the
    first version of paired_effect was tested against the saved file and then
    crashed on the live run, which is the only path that writes it."""
    rows = out[probe][model]
    if level not in rows:
        level = str(level) if str(level) in rows else int(level)
    return np.asarray(rows[level]["per_seed"], dtype=float)


def _paired_t(d, **extra):
    """Two-sided 95% paired interval over SEEDS for an already-differenced
    vector. Zero variance is reported as undefined rather than as infinite
    significance -- the set models return an identical value at every level of
    both probes, having no neighbourhood to aggregate over."""
    n = len(d)
    if n < 2:
        return {"mean": round(float(d.mean()), 4) if n else None,
                "sd": None, "n_seeds": n, "significant": False,
                "seeds_negative": int((d < 0).sum()),
                "note": "fewer than two seeds; interval undefined", **extra}
    mean, sd = float(d.mean()), float(d.std(ddof=1))
    row = {"mean": round(mean, 4), "sd": round(sd, 4), "n_seeds": n,
           "seeds_negative": int((d < 0).sum()), **extra}
    if sd == 0.0:
        row.update({"significant": False, "note": "flat by construction"})
        return row
    t = float(student_t.ppf(0.975, n - 1))
    half = t * sd / np.sqrt(n)
    row.update({"ci95": [round(mean - half, 4), round(mean + half, 4)],
                "t": round(mean / (sd / np.sqrt(n)), 3), "t_crit": t,
                "multiplier": "t",
                "significant": bool(abs(mean) > half),
                "per_seed": [round(float(x), 4) for x in d]})
    return row


def paired_effect(out, probe, model, lo, hi):
    """Per-seed CHANGE between an intervention's two extreme levels.

    The per-level intervals above are dominated by a between-seed LEVEL offset --
    GATv2's d=1 cell spans 0.19..0.91 across ten seeds -- which swamps the
    within-seed change the mechanism claim is actually about. Pairing each seed
    against itself cancels that offset. Reporting only the per-level intervals
    understates a real effect; reporting seed 0 alone overstates it, and seed 0
    is the largest of the ten on probe E."""
    d = (_per_seed(out, probe, model, hi) - _per_seed(out, probe, model, lo))
    r = _paired_t(d, levels=f"{lo}->{hi}")
    r["mean_delta"] = r.pop("mean")
    return r


def interaction_contrast(out, pairs, model_a, model_b):
    """Test the architecture x intervention pattern DIRECTLY, on the seeds.

    Two separate intervals, one excluding zero and one including it, do not
    establish that the two effects differ -- that inference is the classic
    difference-of-significance error, and it is the one this study is most
    exposed to because GATv2's degree interval is wide. Every quantity here is
    formed inside a seed before it is averaged, so the between-seed level offset
    cancels in the contrast as well as in the effects.

    Reported per model: (degree effect) - (peer-density effect), which asks
    whether that architecture is differentially sensitive to the two probes.
    Reported across models: the difference of those two contrasts, which is the
    interaction itself. A significant interaction is what licenses 'distinct and
    directionally opposed topology sensitivities'; the separate effects alone
    only license a statement about each architecture on its own."""
    (pa, alo, ahi), (pb, blo, bhi) = pairs
    per_model = {}
    for m in (model_a, model_b):
        da = _per_seed(out, pa, m, ahi) - _per_seed(out, pa, m, alo)
        db = _per_seed(out, pb, m, bhi) - _per_seed(out, pb, m, blo)
        per_model[m] = _paired_t(da - db, contrast=f"{pa} minus {pb}")
    ia = (_per_seed(out, pa, model_a, ahi) - _per_seed(out, pa, model_a, alo))         - (_per_seed(out, pb, model_a, bhi) - _per_seed(out, pb, model_a, blo))
    ib = (_per_seed(out, pa, model_b, ahi) - _per_seed(out, pa, model_b, alo))         - (_per_seed(out, pb, model_b, bhi) - _per_seed(out, pb, model_b, blo))
    return {"within_model": per_model,
            "across_models": _paired_t(
                ia - ib, contrast=f"({model_a} - {model_b}) of "
                                  f"({pa} minus {pb})")}


def _selfcheck():
    """The cap logic is the one piece here that can fail silently: a threshold
    that misses boundary ties still produces a plausible table, just with an FPR
    quietly below the point that was selected. Asserted on scores whose answer
    is known by construction."""
    rng = np.random.default_rng(0)
    labels = np.array([1] * 900 + [0] * 100)                  # 1 = normal
    scores = np.concatenate([rng.uniform(0.6, 1.0, 900), rng.uniform(0.0, 0.4, 100)])
    for cap in (0.0, 0.01, 0.05, 0.5):
        thr = threshold_at_fpr_cap(scores, labels, cap)
        got = metrics(scores, labels, thr)["false_positive_rate"]
        assert got <= cap + 1e-9, (cap, got)
    # separable data: a 1% budget is more than enough to catch every anomaly
    assert metrics(scores, labels, threshold_at_fpr_cap(scores, labels, 0.01))["recall"] == 1.0
    # ties at the boundary must be INSIDE the selected point, not excluded by <
    tied = np.array([0.5] * 10 + [0.9] * 10)
    tied_labels = np.array([0] * 10 + [1] * 10)
    assert metrics(tied, tied_labels, threshold_at_fpr_cap(tied, tied_labels, 0.0))["recall"] == 1.0
    # disjoint halves
    meta = [{"scenario": "A", "tick": t} for t in range(10)]
    keep = [(t, 0) for t in range(10)]
    a, b = validation_halves(meta, keep)
    assert not (a & b).any() and (a | b).all() and a.sum() == 5
    print("selfcheck ok")


def seeds_main(n_seeds):
    """Standalone mode: the mechanism claim under repeated training seeds."""
    data = {}
    for split in ("train", "validation", "test"):
        X, y, meta, _ = build_snapshots(split)
        flat_X, flat_y, keep = flatten_for_concat(X, y, meta)
        data[split] = dict(X=X, y=y, meta=meta, flat_X=flat_X, flat_y=flat_y, keep=keep)

    # Self-loop weight is NOT re-swept per seed: it was selected on validation in
    # the main run and re-selecting it here would let the GCN pick a different
    # graph for every seed, turning a seed study into a second hyperparameter
    # search. The GCN is therefore held at the setting it won with.
    best_w = 5.0
    seeds = list(range(n_seeds))
    print("=" * 96)
    print(f"MECHANISM CLAIM UNDER {n_seeds} TRAINING SEEDS  (seeds {seeds}, "
          f"GCN self-loop weight fixed at {best_w})")
    print("=" * 96)
    print("Interval is over TRAINING SEEDS at a fixed dataset. It answers 'does this")
    print("reproduce on a refit', not 'does this hold on another test set'. One split")
    print("is still one split.")

    out = seed_study(data, seeds, best_w)
    labels = {"degree": ("D. TARGET DEGREE (n=10, peers complete)", (1, 2, 3, 5, 9), "d"),
              "peer_density": ("E. PEER DENSITY (n=10, target degree 3)",
                               (0, 4, 9, 18, 36), "edges")}
    order_p = ["M4_gcn", "M5_gatv2", "M6_set_transformer", "M3_deep_sets"]
    for probe, (title, levels, unit) in labels.items():
        print()
        print(title)
        hdr = f"{'model':20s}" + "".join(f"{(unit + '=' + str(l)):>18s}" for l in levels)
        print("-" * len(hdr)); print(hdr); print("-" * len(hdr))
        for name in order_p:
            row = out[probe][name]
            cells = []
            for l in levels:
                c = row[l]
                cells.append(f"{c['mean']:.3f}+-{(c['ci95'] or 0):.3f}".rjust(18))
            print(f"{name:20s}" + "".join(cells))
        print("-" * len(hdr))

    # The claim is not "each cell has a tight interval" -- it is "each model
    # responds to one intervention and not the other". That is a statement about
    # the CHANGE across an intervention, so it is tested on the change.
    pairs = (("degree", 1, 9), ("peer_density", 0, 36))
    eff = {}
    print()
    print("MECHANISM DISSOCIATION -- per-seed change across each intervention")
    print("Paired within seed, so the between-seed level offset cancels.")
    hdr = (f"{'model':20s}{'intervention':14s}{'mean delta':>12s}"
           f"{'95% CI':>20s}{'t':>9s}{'sig':>6s}{'down':>7s}")
    print("-" * len(hdr)); print(hdr); print("-" * len(hdr))
    for name in order_p:
        for probe, lo, hi in pairs:
            r = paired_effect(out, probe, name, lo, hi)
            eff.setdefault(probe, {})[name] = r
            ci = ("--" if "ci95" not in r
                  else f"[{r['ci95'][0]:+.3f},{r['ci95'][1]:+.3f}]")
            tv = "--" if "t" not in r else f"{r['t']:+.2f}"
            print(f"{name:20s}{probe:14s}{r['mean_delta']:>+12.4f}{ci:>20s}"
                  f"{tv:>9s}{('YES' if r['significant'] else 'no'):>6s}"
                  f"{(str(r['seeds_negative']) + '/' + str(r['n_seeds'])):>7s}")
    print("-" * len(hdr))

    # Two separate intervals do not test whether two effects DIFFER. The
    # contrast below does, on the same seeds.
    inter = interaction_contrast(out, pairs, "M4_gcn", "M5_gatv2")
    print()
    print("INTERACTION -- tested directly, not inferred from separate intervals")
    for label, r in list(inter["within_model"].items()) + [
            ("interaction", inter["across_models"])]:
        ci = ("--" if "ci95" not in r
              else f"[{r['ci95'][0]:+.3f},{r['ci95'][1]:+.3f}]")
        tv = "--" if "t" not in r else f"{r['t']:+.2f}"
        print(f"  {label:20s}{r['contrast']:44s}{r['mean']:>+9.4f}"
              f"{ci:>20s}{tv:>9s}  {'SIG' if r['significant'] else 'ns'}")

    path = os.path.join(RESULTS_DIR, "seed_study.json")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"seeds": seeds, "gcn_self_loop_weight": best_w,
                   "interval": "two-sided 95% over training seeds, t multiplier",
                   "probes": out, "paired_effects": eff,
                   "interaction": inter}, f, indent=2, default=float)
    print()
    print(f"written to {path}")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    elif "--seeds" in sys.argv:
        seeds_main(int(sys.argv[sys.argv.index("--seeds") + 1]))
    elif "--m9-sanity" in sys.argv:
        m9_sanity_check()
    elif "--m9-seeds" in sys.argv:
        m9_seed_study(int(sys.argv[sys.argv.index("--m9-seeds") + 1]))
    elif "--m9-ablation-investigation" in sys.argv:
        m9_ablation_investigation()
    else:
        main()
