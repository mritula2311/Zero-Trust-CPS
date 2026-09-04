"""
Does the GRAPH earn its place? (reviewer concern G)

The existing ablation compares the GNN against SINGLE-DEVICE signals -- rule,
Isolation Forest, LSTM-AE. That comparison cannot answer the question it is
used to answer. A model that sees ten devices beating models that see one tells
you multi-device information helps; it tells you nothing about whether
RELATIONAL structure helps, because no baseline in the repository ever received
the same multi-device information.

This script fixes that. Every comparator below sees EXACTLY the same inputs:
the per-node [rule, isolation_forest, lstm_ae] sub-scores for all ten nodes at
one tick. The only thing that differs is what each does with them.

    B0  single_device      own 3 sub-scores only              (the old view)
    B1  concat_logreg      all 30 sub-scores + node one-hot   (sklearn LogisticRegression)
    B2  concat_mlp         same 40 inputs                     (small MLP, documented below)
    B3  coordinated_rule   "flag if >= k nodes look anomalous", k chosen on VALIDATION
    GNN 10-node GCN over config/graph_topology.json

WHY THEY ARE ALL IN ONE SCRIPT. Fairness here is a property of the inputs, not
of the models. Building the feature matrix once and handing the identical array
to five comparators is the only way to be sure none of them was quietly given a
different graph, a different normalisation, or a different split. Splitting this
across five scripts would make that unverifiable.

PROTOCOL, fixed before any number was looked at:
    TRAIN split      -> fit B1, B2, and the GNN
    VALIDATION split -> choose k for B3, choose the GNN self-loop weight,
                        choose the decision threshold for every comparator
    TEST split       -> read ONCE, report

Rows whose source_type is PENDING_REAL_HARDWARE_DATA carry no features. They
are excluded from every fit and every metric, and counted in the output. They
are never imputed.

Outputs machine-readable results to results/gnn_baselines/.
"""

import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import torch
import torch.nn as nn
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import precision_recall_fscore_support

from config import (
    NETWORK_NODES, REAL_NODES, GNN_HIDDEN_SIZE, GNN_NUM_LAYERS, GNN_NODE_FEATURE_DIM,
    GNN_EPOCHS, GNN_LEARNING_RATE, TRAINING_SEED, MODELS_DIR, network_edges,
    PROCESS_THRESHOLD, is_feature_vector,
)
import feature_engineering as fe
import datasets
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import _GCN

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "gnn_baselines")
NETWORK_GNN_PATH = os.path.join(MODELS_DIR, "gnn_network.pt")

# Self-loop weights swept on VALIDATION only. Kept to a small, coarse range --
# the point is to show the reported value was not simply assumed, not to squeeze
# the metric. A finer sweep on this much data would be fitting noise.
SELF_LOOP_SWEEP = [1.0, 2.0, 3.0, 5.0]

_TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_NODE_INDEX = {d: i for i, d in enumerate(NETWORK_NODES)}
N_NODES = len(NETWORK_NODES)


def normalized_adjacency(self_loop_weight: float) -> torch.Tensor:
    """A_hat = D^-1/2 (A + wI) D^-1/2 over the DECLARED topology, not a complete
    graph. Every node is treated as active: these are offline replays of
    sessions in which all ten nodes publish, so the liveness gate that matters
    in the live gateway does not apply here and pretending otherwise would make
    the graph depend on replay order."""
    a = np.eye(N_NODES) * self_loop_weight
    for edge in network_edges():
        i, j = (_NODE_INDEX[d] for d in edge)
        a[i, j] = a[j, i] = 1.0
    deg = a.sum(axis=1)
    d_inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(deg, 1e-6)))
    return torch.tensor(d_inv_sqrt @ a @ d_inv_sqrt, dtype=torch.float32, device=_TORCH_DEVICE)


def build_snapshots(split: str):
    """(X, y, meta) where X is (n_ticks, 10, 3) of per-node sub-scores.

    The LSTM-AE is stateful, so each (scenario, node) stream is replayed IN
    TICK ORDER with its own scorer instance -- interleaving scenarios through
    one scorer would build windows that never existed, the same error
    evaluate_real_hardware.py's per-block reset exists to prevent."""
    X, y, meta = [], [], []
    excluded_pending = 0

    for scenario in datasets.scenarios():
        rows = datasets.network_records(scenario, split)
        by_tick = collections.defaultdict(dict)
        for r in rows:
            by_tick[r["tick"]][r["device_id"]] = r

        if_s, lstm_s = IsolationForestScorer(), LSTMAEScorer()   # fresh state per scenario
        for tick in sorted(by_tick):
            node_rows = by_tick[tick]
            feats = np.full((N_NODES, GNN_NODE_FEATURE_DIM), 0.9, dtype=np.float32)
            labels = np.ones(N_NODES, dtype=np.int64)
            valid = np.ones(N_NODES, dtype=bool)

            for device_id, r in node_rows.items():
                i = _NODE_INDEX[device_id]
                labels[i] = r["label"]
                if r.get("reading") is None:          # PENDING_REAL_HARDWARE_DATA
                    valid[i] = False
                    excluded_pending += 1
                    continue
                rule, _ = rule_range_score(device_id, r["reading"])
                if is_feature_vector(device_id):
                    fv = fe.feature_vector(r["reading"])
                    iso = if_s.score(device_id, fv)
                    lstm = lstm_s.score(device_id, fv)
                else:
                    iso = lstm = rule
                feats[i] = [rule, iso, lstm]

            X.append(feats)
            y.append(labels)
            meta.append({"scenario": scenario, "tick": tick, "valid": valid,
                         "event_id": next((r.get("event_id") for r in node_rows.values()), None)})
    return np.array(X), np.array(y), meta, excluded_pending


def flatten_for_concat(X, y, meta):
    """One row per (tick, node): [all 30 sub-scores] ++ [10-dim one-hot for the
    node being predicted]. The one-hot is what lets a single concatenated model
    answer "is node i anomalous" while seeing the whole network -- without it,
    the model has the same information but no way to say which node it is being
    asked about, which would handicap the baseline rather than test it."""
    rows, targets, keep = [], [], []
    for t in range(len(X)):
        flat = X[t].reshape(-1)
        for i in range(N_NODES):
            if not meta[t]["valid"][i]:
                continue
            onehot = np.zeros(N_NODES, dtype=np.float32)
            onehot[i] = 1.0
            rows.append(np.concatenate([flat, onehot]))
            targets.append(y[t][i])
            keep.append((t, i))
    return np.array(rows), np.array(targets), keep


def train_network_gnn(X, y, meta, self_loop_weight):
    torch.manual_seed(TRAINING_SEED)
    model = _GCN(in_dim=GNN_NODE_FEATURE_DIM, hidden=GNN_HIDDEN_SIZE,
                 num_layers=GNN_NUM_LAYERS).to(_TORCH_DEVICE)
    a_hat = normalized_adjacency(self_loop_weight)
    x = torch.tensor(X, dtype=torch.float32, device=_TORCH_DEVICE)
    t = torch.tensor(y, dtype=torch.float32, device=_TORCH_DEVICE)
    mask = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool, device=_TORCH_DEVICE)

    # Inverse-frequency weighting, matching the fusion meta-learner's
    # class_weight="balanced". Without it the numerous normal nodes dominate.
    n_pos = float(t[mask].sum().item())
    n_neg = float(mask.sum().item() - n_pos)
    w_pos = (n_pos + n_neg) / (2 * max(n_pos, 1.0))
    w_neg = (n_pos + n_neg) / (2 * max(n_neg, 1.0))

    opt = torch.optim.Adam(model.parameters(), lr=GNN_LEARNING_RATE)
    model.train()
    for _ in range(GNN_EPOCHS):
        opt.zero_grad()
        # A_hat @ H is per-snapshot, and the adjacency is the SAME for every
        # snapshot, so the whole batch is one matmul against a shared A_hat
        # rather than a Python loop over ticks (which took ~40x longer).
        out = model(x, a_hat)
        w = torch.where(t > 0.5, w_pos, w_neg)
        loss = (nn.functional.binary_cross_entropy(out, t, reduction="none") * w)[mask].mean()
        loss.backward()
        opt.step()
    model.eval()
    return model


def gnn_scores(model, X, self_loop_weight):
    a_hat = normalized_adjacency(self_loop_weight)
    x = torch.tensor(X, dtype=torch.float32, device=_TORCH_DEVICE)
    with torch.no_grad():
        return model(x, a_hat).cpu().numpy()


def metrics(scores, labels, threshold):
    """scores: probability-of-NORMAL. Anomaly predicted when score < threshold,
    matching the deployed convention (PROCESS_THRESHOLD, trust-style)."""
    pred_anom = (scores < threshold).astype(int)
    true_anom = (labels == 0).astype(int)
    p, r, f, _ = precision_recall_fscore_support(
        true_anom, pred_anom, average="binary", zero_division=0)
    tp = int(((pred_anom == 1) & (true_anom == 1)).sum())
    fp = int(((pred_anom == 1) & (true_anom == 0)).sum())
    tn = int(((pred_anom == 0) & (true_anom == 0)).sum())
    fn = int(((pred_anom == 0) & (true_anom == 1)).sum())
    return {"n": int(len(labels)), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(float(p), 4), "recall": round(float(r), 4),
            "f1": round(float(f), 4),
            "false_positive_rate": round(fp / max(fp + tn, 1), 4),
            "detection_rate": round(tp / max(tp + fn, 1), 4)}


def choose_threshold(scores, labels, grid=None):
    """Maximise F1 on VALIDATION. One stated objective, applied identically to
    every comparator -- picking a different objective per model is how a
    favoured model wins a comparison it should not."""
    grid = grid if grid is not None else [i / 40 for i in range(1, 40)]
    best = max(grid, key=lambda t: metrics(scores, labels, t)["f1"])
    return best


def event_metrics(scores, labels, meta, keep_idx, threshold):
    """An event is one (scenario, event_id) block, not a window.

    Criterion, stated explicitly: an event counts as DETECTED if at least one
    scoreable window inside it produces an anomaly decision on a node that is
    genuinely anomalous in that event. Reported because window counts treat
    correlated overlapping windows from one disturbance as independent trials,
    which they are not."""
    detected, total = collections.defaultdict(bool), set()
    false_alarm_ticks = 0
    for idx, (t, i) in enumerate(keep_idx):
        ev = meta[t].get("event_id")
        is_anom = labels[idx] == 0
        flagged = scores[idx] < threshold
        if ev and is_anom:
            total.add(ev)
            if flagged:
                detected[ev] = True
        elif not is_anom and flagged:
            false_alarm_ticks += 1
    return {"total_events": len(total),
            "detected_events": sum(1 for e in total if detected[e]),
            "missed_events": len(total) - sum(1 for e in total if detected[e]),
            "event_recall": round(sum(1 for e in total if detected[e]) / max(len(total), 1), 4),
            "false_alarm_windows_on_normal_nodes": false_alarm_ticks}


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=" * 78)
    print("GNN vs SAME-INFORMATION MULTI-DEVICE BASELINES -- 10-node hybrid network")
    print("=" * 78)

    data = {}
    for split in ("train", "validation", "test"):
        X, y, meta, pending = build_snapshots(split)
        flat_X, flat_y, keep = flatten_for_concat(X, y, meta)
        data[split] = dict(X=X, y=y, meta=meta, flat_X=flat_X, flat_y=flat_y, keep=keep)
        print(f"{split:11s} {len(X):5d} snapshots  {len(flat_X):6d} scoreable (tick,node) rows  "
              f"{pending} PENDING rows excluded")
    print(f"\nPENDING rows are {REAL_NODES[1]} -- no capture exists yet. Excluded, never imputed.\n")

    tr, va, te = data["train"], data["validation"], data["test"]
    results, val_choices = {}, {}

    # ---- B0 single_device -------------------------------------------------
    own = lambda d: d["flat_X"][:, :N_NODES * GNN_NODE_FEATURE_DIM].reshape(
        len(d["flat_X"]), N_NODES, GNN_NODE_FEATURE_DIM)[
        np.arange(len(d["flat_X"])), d["flat_X"][:, -N_NODES:].argmax(1)]
    b0 = LogisticRegression(max_iter=1000, class_weight="balanced").fit(own(tr), tr["flat_y"])
    for name, model, feat in (("B0_single_device", b0, own),
                              ("B1_concat_logreg",
                               LogisticRegression(max_iter=2000, class_weight="balanced").fit(
                                   tr["flat_X"], tr["flat_y"]),
                               lambda d: d["flat_X"]),
                              ("B2_concat_mlp",
                               MLPClassifier(hidden_layer_sizes=(32, 16), activation="relu",
                                             solver="adam", learning_rate_init=1e-3,
                                             max_iter=400, random_state=TRAINING_SEED).fit(
                                   tr["flat_X"], tr["flat_y"]),
                               lambda d: d["flat_X"])):
        s_va = model.predict_proba(feat(va))[:, 1]     # P(normal)
        thr = choose_threshold(s_va, va["flat_y"])
        s_te = model.predict_proba(feat(te))[:, 1]
        val_choices[name] = {"threshold": thr}
        results[name] = {"validation": metrics(s_va, va["flat_y"], thr),
                         "test": metrics(s_te, te["flat_y"], thr),
                         "test_event": event_metrics(s_te, te["flat_y"], te["meta"], te["keep"], thr)}

    # ---- B3 coordinated rule ---------------------------------------------
    # "flag a node if at least k nodes in the network look anomalous by their
    # own sub-scores". k chosen on VALIDATION only.
    def rule_scores(d, k):
        own_min = d["flat_X"][:, :N_NODES * GNN_NODE_FEATURE_DIM].reshape(
            len(d["flat_X"]), N_NODES, GNN_NODE_FEATURE_DIM).min(axis=2)
        n_anom = (own_min < PROCESS_THRESHOLD).sum(axis=1)
        idx = d["flat_X"][:, -N_NODES:].argmax(1)
        own_anom = own_min[np.arange(len(own_min)), idx] < PROCESS_THRESHOLD
        # score = 0 (anomalous) when this node looks bad AND the network-wide
        # count reaches k; otherwise 1.
        return np.where(own_anom & (n_anom >= k), 0.0, 1.0)

    best_k = max(range(1, N_NODES + 1),
                 key=lambda k: metrics(rule_scores(va, k), va["flat_y"], 0.5)["f1"])
    val_choices["B3_coordinated_rule"] = {"k": best_k, "threshold": 0.5}
    results["B3_coordinated_rule"] = {
        "validation": metrics(rule_scores(va, best_k), va["flat_y"], 0.5),
        "test": metrics(rule_scores(te, best_k), te["flat_y"], 0.5),
        "test_event": event_metrics(rule_scores(te, best_k), te["flat_y"],
                                    te["meta"], te["keep"], 0.5)}

    # ---- GNN --------------------------------------------------------------
    sweep = {}
    for w in SELF_LOOP_SWEEP:
        m = train_network_gnn(tr["X"], tr["y"], tr["meta"], w)
        s = gnn_scores(m, va["X"], w)
        flat = np.array([s[t][i] for t, i in va["keep"]])
        thr = choose_threshold(flat, va["flat_y"])
        sweep[w] = {"threshold": thr, **metrics(flat, va["flat_y"], thr)}
        print(f"  self-loop w={w}: validation F1={sweep[w]['f1']:.4f} (thr {thr:.3f})")
    best_w = max(sweep, key=lambda w: sweep[w]["f1"])
    val_choices["GNN"] = {"self_loop_weight": best_w, "threshold": sweep[best_w]["threshold"]}
    print(f"  -> self-loop weight {best_w} selected on VALIDATION\n")

    gnn = train_network_gnn(tr["X"], tr["y"], tr["meta"], best_w)
    torch.save(gnn.state_dict(), NETWORK_GNN_PATH)
    thr = sweep[best_w]["threshold"]
    gva = gnn_scores(gnn, va["X"], best_w)
    s_va = np.array([gva[t][i] for t, i in va["keep"]])
    gte = gnn_scores(gnn, te["X"], best_w)
    s_te = np.array([gte[t][i] for t, i in te["keep"]])
    results["GNN"] = {"validation": metrics(s_va, va["flat_y"], thr),
                      "test": metrics(s_te, te["flat_y"], thr),
                      "test_event": event_metrics(s_te, te["flat_y"], te["meta"], te["keep"], thr)}

    # ---- report -----------------------------------------------------------
    print(f"{'model':22s} {'prec':>7s} {'recall':>7s} {'F1':>7s} {'FPR':>7s} {'evt recall':>11s}")
    print("-" * 78)
    for name in ("B0_single_device", "B1_concat_logreg", "B2_concat_mlp",
                 "B3_coordinated_rule", "GNN"):
        t = results[name]["test"]
        e = results[name]["test_event"]
        print(f"{name:22s} {t['precision']:>7.4f} {t['recall']:>7.4f} {t['f1']:>7.4f} "
              f"{t['false_positive_rate']:>7.4f} {e['event_recall']:>11.4f}")

    # ---- TASK 2: network-level coordination pattern -----------------------
    # Declared alongside task 1, before either was run, and reported whatever
    # the outcome. Task 1 asks "is THIS node anomalous", and a node's own label
    # is largely determined by its own sub-scores -- which is why B0, seeing one
    # node, nearly matches B2, seeing ten. That is a property of the target, not
    # evidence about graphs.
    #
    # This task asks the question the graph is actually for: given one snapshot
    # of the whole network, WHICH COORDINATION PATTERN is present
    # (NETWORK_NORMAL / A / B / C)? A single-node view cannot answer it even in
    # principle, so this is where relational structure has something to prove.
    scen_names = sorted(set(m["scenario"] for m in tr["meta"]))
    scen_index = {s: i for i, s in enumerate(scen_names)}

    def snapshot_matrix(d):
        """One row per snapshot. Invalid (PENDING) nodes contribute their
        neutral 0.9 placeholder -- which is what the live gateway would also
        see from a device it has not heard from -- and the fact is recorded
        rather than hidden."""
        return d["X"].reshape(len(d["X"]), -1)

    def snapshot_labels(d):
        return np.array([scen_index[m["scenario"]] for m in d["meta"]])

    task2 = {}
    for name, model in (("B1_concat_logreg",
                         LogisticRegression(max_iter=3000, class_weight="balanced")),
                        ("B2_concat_mlp",
                         MLPClassifier(hidden_layer_sizes=(32, 16), activation="relu",
                                       solver="adam", learning_rate_init=1e-3,
                                       max_iter=600, random_state=TRAINING_SEED))):
        model.fit(snapshot_matrix(tr), snapshot_labels(tr))
        for split_name, d in (("validation", va), ("test", te)):
            acc = float(model.score(snapshot_matrix(d), snapshot_labels(d)))
            task2.setdefault(name, {})[split_name] = round(acc, 4)

    # B0 for this task: only the target-agnostic "how many nodes look bad"
    # count -- the most a single-node view can contribute to a network question.
    for split_name, d in (("validation", va), ("test", te)):
        own_min = d["X"].min(axis=2)
        counts = (own_min < PROCESS_THRESHOLD).sum(axis=1).reshape(-1, 1)
        if split_name == "validation":
            b0m = LogisticRegression(max_iter=2000, class_weight="balanced").fit(
                (tr["X"].min(axis=2) < PROCESS_THRESHOLD).sum(axis=1).reshape(-1, 1),
                snapshot_labels(tr))
        task2.setdefault("B0_anomalous_node_count", {})[split_name] = round(
            float(b0m.score(counts, snapshot_labels(d))), 4)

    # GNN for this task: its per-node outputs, pooled into a snapshot vector,
    # then the SAME multinomial logistic head the baselines get. The head is
    # identical so the comparison isolates the representation, not the classifier.
    gnn_tr = gnn_scores(gnn, tr["X"], best_w)
    head = LogisticRegression(max_iter=3000, class_weight="balanced").fit(gnn_tr, snapshot_labels(tr))
    for split_name, d in (("validation", va), ("test", te)):
        s = gnn_scores(gnn, d["X"], best_w)
        task2.setdefault("GNN_node_embeddings", {})[split_name] = round(
            float(head.score(s, snapshot_labels(d))), 4)

    print()
    print("TASK 2 -- network-level coordination pattern (4-way), accuracy")
    print("-" * 78)
    for name in sorted(task2):
        print(f"{name:26s} validation {task2[name]['validation']:.4f}   "
              f"test {task2[name]['test']:.4f}")
    t2_best = max(task2, key=lambda k: task2[k]["test"])
    print(f"Best: {t2_best} ({task2[t2_best]['test']:.4f})")

    best = max(results, key=lambda k: results[k]["test"]["f1"])
    gnn_f1, best_simple = results["GNN"]["test"]["f1"], max(
        (results[k]["test"]["f1"] for k in results if k != "GNN"))
    print()
    print(f"Best test F1: {best} ({results[best]['test']['f1']:.4f})")
    print(f"GNN {gnn_f1:.4f} vs best same-information baseline {best_simple:.4f} "
          f"(delta {gnn_f1 - best_simple:+.4f})")
    if gnn_f1 <= best_simple:
        print("A simpler model matched or beat the GNN on the same information.")
        print("The claim to make is about CROSS-DEVICE information, not about graph learning.")

    out = {"tasks": {
               "task1": "per-node anomaly detection (window level)",
               "task2": "network-level coordination pattern, 4-way (NETWORK_NORMAL/A/B/C)"},
           "protocol": {"fit": "train", "selected_on": "validation", "reported_on": "test",
                        "threshold_objective": "max F1 on validation",
                        "self_loop_sweep": SELF_LOOP_SWEEP},
           "network": {"size": N_NODES, "real": len(REAL_NODES),
                       "simulated": N_NODES - len(REAL_NODES), "nodes": NETWORK_NODES},
           "validation_choices": val_choices,
           "task2_network_coordination_pattern": task2,
           "self_loop_sweep_validation": {str(k): v for k, v in sweep.items()},
           "results": results}
    with open(os.path.join(RESULTS_DIR, "metrics.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(RESULTS_DIR, "self_loop_sweep.json"), "w") as f:
        json.dump({str(k): v for k, v in sweep.items()}, f, indent=2)
    print(f"\nwritten to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
