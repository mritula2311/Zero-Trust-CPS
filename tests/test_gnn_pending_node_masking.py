"""A PENDING_REAL_HARDWARE_DATA node's 0.9 placeholder must not influence a
valid neighbour's GCN prediction through message passing (ASTRA_AUDIT.md P1,
scripts/evaluate_gnn_baselines.py::build_snapshots / normalized_adjacency).
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


class TestNormalizedAdjacencyMasking(unittest.TestCase):
    def test_invalid_node_is_fully_isolated(self):
        n = egb.N_NODES
        valid = np.ones((1, n), dtype=bool)
        valid[0, 2] = False
        a_hat = egb.normalized_adjacency(3.0, valid)[0]
        zero = torch.zeros(n, device=a_hat.device)
        self.assertTrue(torch.equal(a_hat[2, :], zero), "invalid node's row must be all zero")
        self.assertTrue(torch.equal(a_hat[:, 2], zero), "invalid node's column must be all zero")

    def test_valid_only_batch_matches_the_dense_no_mask_adjacency(self):
        n = egb.N_NODES
        valid = np.ones((1, n), dtype=bool)
        masked = egb.normalized_adjacency(3.0, valid)[0]
        dense = egb.normalized_adjacency(3.0)
        self.assertTrue(torch.allclose(masked, dense, atol=1e-6))

    def test_gcn_output_for_valid_nodes_is_unaffected_by_the_placeholder_value(self):
        """Two snapshots differing ONLY in the invalid node's feature vector
        (0.9 placeholder vs. an arbitrary other value) must produce IDENTICAL
        GCN outputs for every valid node, once the adjacency masks it out."""
        torch.manual_seed(0)
        n = egb.N_NODES
        model = _GCN().eval().to(egb._TORCH_DEVICE)

        valid = np.ones((1, n), dtype=bool)
        valid[0, 0] = False
        a_hat = egb.normalized_adjacency(egb.SELF_LOOP_SWEEP[0], valid)

        rng = np.random.default_rng(1)
        base = rng.uniform(0, 1, size=(1, n, 3)).astype(np.float32)
        placeholder = base.copy()
        placeholder[0, 0] = [0.9, 0.9, 0.9]
        tampered = base.copy()
        tampered[0, 0] = [0.01, 0.5, 0.2]

        with torch.no_grad():
            out_placeholder = model(torch.tensor(placeholder, device=egb._TORCH_DEVICE), a_hat)
            out_tampered = model(torch.tensor(tampered, device=egb._TORCH_DEVICE), a_hat)

        self.assertTrue(
            torch.allclose(out_placeholder[0, 1:], out_tampered[0, 1:], atol=1e-6),
            "a pending node's feature value leaked into a valid node's score")


if __name__ == "__main__":
    unittest.main()
