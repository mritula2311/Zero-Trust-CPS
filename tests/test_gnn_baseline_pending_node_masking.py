"""Regression tests for the PENDING_REAL_HARDWARE_DATA / invalid-node leakage
audit of scripts/evaluate_gnn_baselines.py's Task-1 (B0/B1/B2/B3) and Task-2
(network-coordination-pattern) baselines (RESULTS.md 0.13.2x).

B0 (own_features) was already immune by construction: it discards every
column but the target node's own three, so it never sees another node's raw
content regardless of validity. B1/B2/B3 (Task 1) and B1/B2/B0 (Task 2,
snapshot-level) were NOT -- they concatenated every node's raw sub-scores,
including a PENDING node's 0.9 placeholder, straight into a model or a
hand-written threshold rule with no masking at all. masked_concat_features(),
rule_scores(), snapshot_matrix(), and anomalous_node_count() are the fix:
zero an invalid node's raw block deterministically and hand any consumer that
reads raw content directly (not through a learned model) an explicit
validity channel instead. The GNN path (normalized_adjacency's `valid`-gated
adjacency) was already correct before this audit and is covered by
test_gnn_pending_node_masking.py; a couple of its core assertions are
repeated here at the actual 20-node cardinality with real device provenance
(section 7 of the audit).

Every test differs ONLY in one (or several) PENDING node's raw feature
content -- never in validity, never in the label of a valid node -- and
asserts every quantity that should logically ignore that content is exactly
unchanged. All calls go through the real evaluate_gnn_baselines functions;
nothing here reimplements their logic.
"""

import os
import sys
import unittest

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import evaluate_gnn_baselines as egb
from gnn_scorer import _GCN


def _ab_snapshots(n_ticks, invalid_idx, seed=0, tampered=-1e6):
    """(X_a, X_b, y, meta): identical valid-node data, differing only at the
    given invalid index/indices -- A carries the historical 0.9 placeholder,
    B an arbitrary finite tampered value. `invalid_idx` may be a single int
    or a tuple of several (multi-pending-node case)."""
    idxs = (invalid_idx,) if isinstance(invalid_idx, int) else tuple(invalid_idx)
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.3, 1.0, size=(n_ticks, egb.N_NODES, egb.GNN_NODE_FEATURE_DIM)).astype(np.float32)
    X_a, X_b = base.copy(), base.copy()
    for i in idxs:
        X_a[:, i, :] = 0.9
        X_b[:, i, :] = tampered
    valid = np.ones((n_ticks, egb.N_NODES), dtype=bool)
    for i in idxs:
        valid[:, i] = False
    y = np.ones((n_ticks, egb.N_NODES), dtype=np.int64)
    meta = [{"scenario": "synthetic", "tick": t, "valid": valid[t], "event_id": None}
            for t in range(n_ticks)]
    return X_a, X_b, y, meta


def _flat_dict(X, y, meta):
    flat_X, flat_y, keep = egb.masked_concat_features(X, y, meta)
    return dict(X=X, y=y, meta=meta, flat_X=flat_X, flat_y=flat_y, keep=keep)


class TestConcatMaskingContract(unittest.TestCase):
    """B1 (LogisticRegression) and B2 (MLPClassifier) are fit and scored
    directly on masked_concat_features()'s output, so row equality here is a
    stronger guarantee than checking model predictions: it holds for ANY
    model trained on this representation, not just the two in the script."""

    def test_identical_across_large_positive_negative_and_plausible_tampering(self):
        for tamper in (-1e6, 1e6, 0.37):
            X_a, X_b, y, meta = _ab_snapshots(6, invalid_idx=2, tampered=tamper)
            flat_a, ya, keep_a = egb.masked_concat_features(X_a, y, meta)
            flat_b, yb, keep_b = egb.masked_concat_features(X_b, y, meta)
            np.testing.assert_array_equal(
                flat_a, flat_b,
                err_msg=f"tamper={tamper}: a PENDING node's raw value leaked into flat_X")
            np.testing.assert_array_equal(ya, yb)
            self.assertEqual(keep_a, keep_b)

    def test_multiple_pending_nodes(self):
        X_a, X_b, y, meta = _ab_snapshots(6, invalid_idx=(1, 5, 11), tampered=-1e6)
        flat_a, _, _ = egb.masked_concat_features(X_a, y, meta)
        flat_b, _, _ = egb.masked_concat_features(X_b, y, meta)
        np.testing.assert_array_equal(flat_a, flat_b)

    def test_validity_block_matches_meta_and_onehot_stays_last(self):
        """Sanity-check the column layout the rest of the module depends on:
        onehot must still be the last N_NODES columns after the validity
        block is inserted (own_features/rule_scores both slice [-N_NODES:])."""
        X, _, y, meta = _ab_snapshots(1, invalid_idx=4, tampered=-1e6)
        flat_X, _, keep = egb.masked_concat_features(X, y, meta)
        onehot = flat_X[:, -egb.N_NODES:]
        for row, (t, i) in enumerate(keep):
            self.assertEqual(int(onehot[row].argmax()), i)
            self.assertEqual(onehot[row].sum(), 1.0)
        validity = flat_X[:, egb.N_FLAT:egb.N_FLAT + egb.N_NODES]
        np.testing.assert_array_equal(validity[0], meta[0]["valid"].astype(np.float32))


class TestB0SingleDevice(unittest.TestCase):
    """B0 was already immune by construction; confirm it stays that way after
    masked_concat_features()'s column layout change (a validity block is now
    inserted between the sub-scores and the one-hot)."""

    def test_own_features_unaffected_by_tampering(self):
        X_a, X_b, y, meta = _ab_snapshots(6, invalid_idx=2, tampered=-1e6)
        da, db = _flat_dict(X_a, y, meta), _flat_dict(X_b, y, meta)
        np.testing.assert_array_equal(egb.own_features(da), egb.own_features(db))


class TestB3CoordinatedRule(unittest.TestCase):
    """B3 reads raw sub-score content directly -- no model to launder it
    through -- so it is exercised both for simple invariance and for the
    specific failure mode a naive zero-fill would introduce: a zeroed block
    reads as [0, 0, 0], which is BELOW PROCESS_THRESHOLD and would otherwise
    always count as "anomalous" regardless of k."""

    def test_rule_scores_unaffected_by_tampering(self):
        X_a, X_b, y, meta = _ab_snapshots(10, invalid_idx=3, tampered=-1e6)
        da, db = _flat_dict(X_a, y, meta), _flat_dict(X_b, y, meta)
        for k in range(1, egb.N_NODES + 1):
            np.testing.assert_array_equal(
                egb.rule_scores(da, k), egb.rule_scores(db, k), err_msg=f"k={k}")

    def test_pending_node_not_counted_toward_coordinated_threshold(self):
        anomalous, normal = egb.PROCESS_THRESHOLD - 0.2, egb.PROCESS_THRESHOLD + 0.3
        X = np.full((1, egb.N_NODES, egb.GNN_NODE_FEATURE_DIM), normal, dtype=np.float32)
        pending_idx, target_idx = 0, 1
        X[0, target_idx, :] = anomalous          # the only VALID anomalous node
        X[0, pending_idx, :] = -1e6              # PENDING, tampered to look extreme
        valid = np.ones((1, egb.N_NODES), dtype=bool)
        valid[0, pending_idx] = False
        y = np.ones((1, egb.N_NODES), dtype=np.int64)
        meta = [{"scenario": "s", "tick": 0, "valid": valid[0], "event_id": None}]
        d = _flat_dict(X, y, meta)
        row = d["keep"].index((0, target_idx))
        # Real anomalous-node count among VALID nodes is 1 (only target_idx).
        # A rule that let the pending node's zeroed block count too would see
        # n_anom=2 and fire at k=2; the correct, masked count must not.
        self.assertEqual(egb.rule_scores(d, 2)[row], 1.0,
                          "a PENDING node was counted toward the coordinated-anomaly threshold")
        self.assertEqual(egb.rule_scores(d, 1)[row], 0.0,
                          "the target's own genuine anomaly should still fire at k=1")


class TestTask2SnapshotFeatures(unittest.TestCase):
    """snapshot_matrix (B1/B2) and anomalous_node_count (B0) back Task 2's
    network-coordination-pattern classifiers -- the ones novelty claim #3's
    cited numbers (single-node vs. concat-MLP) come from."""

    def test_snapshot_matrix_identical_across_tampering(self):
        for tamper in (-1e6, 1e6, 0.42):
            X_a, X_b, _, meta = _ab_snapshots(8, invalid_idx=4, tampered=tamper)
            da, db = dict(X=X_a, meta=meta), dict(X=X_b, meta=meta)
            np.testing.assert_array_equal(egb.snapshot_matrix(da), egb.snapshot_matrix(db))

    def test_anomalous_node_count_identical_across_tampering(self):
        for tamper in (-1e6, 1e6):
            X_a, X_b, _, meta = _ab_snapshots(8, invalid_idx=4, tampered=tamper)
            da, db = dict(X=X_a, meta=meta), dict(X=X_b, meta=meta)
            np.testing.assert_array_equal(
                egb.anomalous_node_count(da), egb.anomalous_node_count(db))

    def test_pending_node_not_counted_as_anomalous(self):
        normal = egb.PROCESS_THRESHOLD + 0.3
        X = np.full((1, egb.N_NODES, egb.GNN_NODE_FEATURE_DIM), normal, dtype=np.float32)
        X[0, 0, :] = -1e6                     # PENDING, tampered to look wildly anomalous
        valid = np.ones((1, egb.N_NODES), dtype=bool)
        valid[0, 0] = False
        meta = [{"scenario": "s", "tick": 0, "valid": valid[0], "event_id": None}]
        counts = egb.anomalous_node_count(dict(X=X, meta=meta))
        self.assertEqual(int(counts[0, 0]), 0,
                          "a PENDING node's tampered value was counted as an anomalous node")


class TestGNNPathAt20NodeCardinality(unittest.TestCase):
    """Repeats the core invariance guarantee from
    test_gnn_pending_node_masking.py at the network's actual current size,
    using real device provenance from config/graph_topology.json: only
    esp32-vib-001 (MPU6050) and esp32-vib-002 (SW-420) are REAL hardware --
    esp32-vib-002 is the PENDING node with no capture yet -- every other
    index is a declared SIMULATED node, not physical hardware."""

    def test_pending_sw420_does_not_change_mpu6050_target_score(self):
        self.assertEqual(egb.N_NODES, 20, "written for the current 20-node topology")
        torch.manual_seed(0)
        model = _GCN(in_dim=egb.GNN_NODE_FEATURE_DIM, hidden=egb.GNN_HIDDEN_SIZE,
                     num_layers=egb.GNN_NUM_LAYERS).eval().to(egb._TORCH_DEVICE)

        pending_idx = egb._NODE_INDEX["esp32-vib-002"]     # REAL, SW-420, no capture yet
        target_idx = egb._NODE_INDEX["esp32-vib-001"]      # REAL, MPU6050

        valid = np.ones((1, egb.N_NODES), dtype=bool)
        valid[0, pending_idx] = False
        a_hat = egb.normalized_adjacency(egb.SELF_LOOP_SWEEP[0], valid)

        rng = np.random.default_rng(3)
        base = rng.uniform(0.3, 1.0, size=(1, egb.N_NODES, egb.GNN_NODE_FEATURE_DIM)).astype(np.float32)
        placeholder, tampered = base.copy(), base.copy()
        placeholder[0, pending_idx] = [0.9, 0.9, 0.9]
        tampered[0, pending_idx] = [-1e6, 1e6, 0.123]

        with torch.no_grad():
            out_placeholder = model(torch.tensor(placeholder, device=egb._TORCH_DEVICE), a_hat)
            out_tampered = model(torch.tensor(tampered, device=egb._TORCH_DEVICE), a_hat)

        self.assertTrue(torch.allclose(out_placeholder[0, target_idx], out_tampered[0, target_idx],
                                        atol=1e-6),
                        "PENDING SW-420 node's tampered value changed the MPU6050 target's score")
        valid_idx = [i for i in range(egb.N_NODES) if i != pending_idx]
        self.assertTrue(torch.allclose(out_placeholder[0, valid_idx], out_tampered[0, valid_idx],
                                        atol=1e-6),
                        "PENDING node's tampered value changed some OTHER valid node's score")

    def test_two_pending_nodes_simultaneously(self):
        torch.manual_seed(0)
        model = _GCN(in_dim=egb.GNN_NODE_FEATURE_DIM, hidden=egb.GNN_HIDDEN_SIZE,
                     num_layers=egb.GNN_NUM_LAYERS).eval().to(egb._TORCH_DEVICE)

        pending_idxs = [egb._NODE_INDEX["esp32-vib-002"], egb._NODE_INDEX["esp32-sim-07"]]
        valid = np.ones((1, egb.N_NODES), dtype=bool)
        for i in pending_idxs:
            valid[0, i] = False
        a_hat = egb.normalized_adjacency(egb.SELF_LOOP_SWEEP[-1], valid)

        rng = np.random.default_rng(4)
        base = rng.uniform(0.3, 1.0, size=(1, egb.N_NODES, egb.GNN_NODE_FEATURE_DIM)).astype(np.float32)
        placeholder, tampered = base.copy(), base.copy()
        for i in pending_idxs:
            placeholder[0, i] = [0.9, 0.9, 0.9]
        tampered[0, pending_idxs[0]] = [-1e6, 5e5, 1.0]
        tampered[0, pending_idxs[1]] = [1e6, -1e6, 0.0]

        with torch.no_grad():
            out_placeholder = model(torch.tensor(placeholder, device=egb._TORCH_DEVICE), a_hat)
            out_tampered = model(torch.tensor(tampered, device=egb._TORCH_DEVICE), a_hat)

        valid_idx = [i for i in range(egb.N_NODES) if i not in pending_idxs]
        self.assertTrue(torch.allclose(out_placeholder[0, valid_idx], out_tampered[0, valid_idx],
                                        atol=1e-6))


if __name__ == "__main__":
    unittest.main()
