"""A PENDING/invalid node's raw feature CONTENT must not change any valid
node's score in scripts/benchmark_crossdevice_models.py's M1/M2/M3/M5/M6/M7.

Appending a validity CHANNEL (_with_validity) is not enough on its own: a
learned model can still consume the raw values that channel is attached to.
These tests build two batches differing ONLY in one invalid node's feature
vector -- the historical 0.9 placeholder vs. an arbitrary tampered finite
value -- and assert every valid node's output is identical between them.
They fail against a validity-channel-only implementation and only pass once
the invalid node is actually excluded from pooling/attention (DeepSets,
SetTransformer, NodePreservingSetTransformer) or from the attention mask
(GATv2), or deterministically zeroed before flattening (M1/M2).
"""

import os
import sys
import unittest

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import benchmark_crossdevice_models as bcm


def _ab_batches(n, invalid_idx, feat_dim, seed=0):
    """Two (1, n, feat_dim) batches, identical except at `invalid_idx`: A
    carries the historical PENDING placeholder, B an arbitrary extreme but
    finite value. Returns (a, b, meta) with `invalid_idx` marked invalid."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(0, 1, size=(1, n, feat_dim)).astype(np.float32)
    a = base.copy()
    a[0, invalid_idx] = 0.9
    b = base.copy()
    b[0, invalid_idx] = -1e6
    valid = np.ones((1, n), dtype=bool)
    valid[0, invalid_idx] = False
    meta = [{"valid": valid[0]}]
    return a, b, meta


def _assert_valid_nodes_unaffected(test, out_a, out_b, invalid_idx):
    valid_idx = [i for i in range(out_a.shape[1]) if i != invalid_idx]
    test.assertTrue(
        np.allclose(out_a[:, valid_idx], out_b[:, valid_idx], atol=1e-6),
        "a PENDING/invalid node's raw feature value leaked into a valid node's score")


class TestWithValidity(unittest.TestCase):
    def test_default_meta_is_all_valid(self):
        X = np.zeros((2, 4, 3), dtype=np.float32)
        out = bcm._with_validity(X, meta=None)
        self.assertEqual(out.shape, (2, 4, 4))
        np.testing.assert_array_equal(out[..., -1], np.ones((2, 4), dtype=np.float32))

    def test_appends_the_given_validity_per_row(self):
        X = np.zeros((1, 3, 3), dtype=np.float32)
        meta = [{"valid": np.array([True, False, True])}]
        out = bcm._with_validity(X, meta)
        np.testing.assert_array_equal(out[0, :, -1], [1.0, 0.0, 1.0])


class TestSetModelPendingNodeMasking(unittest.TestCase):
    N, INVALID_IDX = 6, 2

    def test_deep_sets(self):
        torch.manual_seed(0)
        model = bcm.DeepSets(in_dim=bcm.NODE_FEATURE_DIM_WITH_VALIDITY).eval().to(bcm._TORCH_DEVICE)
        a, b, meta = _ab_batches(self.N, self.INVALID_IDX, bcm.GNN_NODE_FEATURE_DIM)
        valid = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool, device=bcm._TORCH_DEVICE)
        with torch.no_grad():
            xa = torch.tensor(bcm._with_validity(a, meta), device=bcm._TORCH_DEVICE)
            xb = torch.tensor(bcm._with_validity(b, meta), device=bcm._TORCH_DEVICE)
            out_a = model(xa, valid=valid).cpu().numpy()
            out_b = model(xb, valid=valid).cpu().numpy()
        _assert_valid_nodes_unaffected(self, out_a, out_b, self.INVALID_IDX)

    def test_gatv2(self):
        torch.manual_seed(0)
        model = bcm.GATv2(in_dim=bcm.NODE_FEATURE_DIM_WITH_VALIDITY).eval().to(bcm._TORCH_DEVICE)
        a, b, meta = _ab_batches(self.N, self.INVALID_IDX, bcm.GNN_NODE_FEATURE_DIM)
        valid = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool, device=bcm._TORCH_DEVICE)
        topo = bcm.topology_mask(self.N)          # complete graph at this size, already on _TORCH_DEVICE
        mask = topo & valid[:, None, None, :]
        with torch.no_grad():
            xa = torch.tensor(bcm._with_validity(a, meta), device=bcm._TORCH_DEVICE)
            xb = torch.tensor(bcm._with_validity(b, meta), device=bcm._TORCH_DEVICE)
            out_a = model(xa, mask).cpu().numpy()
            out_b = model(xb, mask).cpu().numpy()
        _assert_valid_nodes_unaffected(self, out_a, out_b, self.INVALID_IDX)

    def test_set_transformer(self):
        torch.manual_seed(0)
        model = bcm.SetTransformer(in_dim=bcm.NODE_FEATURE_DIM_WITH_VALIDITY).eval().to(bcm._TORCH_DEVICE)
        a, b, meta = _ab_batches(self.N, self.INVALID_IDX, bcm.GNN_NODE_FEATURE_DIM)
        valid = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool, device=bcm._TORCH_DEVICE)
        with torch.no_grad():
            xa = torch.tensor(bcm._with_validity(a, meta), device=bcm._TORCH_DEVICE)
            xb = torch.tensor(bcm._with_validity(b, meta), device=bcm._TORCH_DEVICE)
            out_a = model(xa, valid=valid).cpu().numpy()
            out_b = model(xb, valid=valid).cpu().numpy()
        _assert_valid_nodes_unaffected(self, out_a, out_b, self.INVALID_IDX)

    def test_node_preserving_set_transformer(self):
        torch.manual_seed(0)
        model = bcm.NodePreservingSetTransformer(in_dim=bcm.NODE_FEATURE_DIM_WITH_VALIDITY).eval().to(bcm._TORCH_DEVICE)
        a, b, meta = _ab_batches(self.N, self.INVALID_IDX, bcm.GNN_NODE_FEATURE_DIM)
        valid = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool, device=bcm._TORCH_DEVICE)
        with torch.no_grad():
            xa = torch.tensor(bcm._with_validity(a, meta), device=bcm._TORCH_DEVICE)
            xb = torch.tensor(bcm._with_validity(b, meta), device=bcm._TORCH_DEVICE)
            out_a = model(xa, valid=valid).cpu().numpy()
            out_b = model(xb, valid=valid).cpu().numpy()
        _assert_valid_nodes_unaffected(self, out_a, out_b, self.INVALID_IDX)

    def test_deep_sets_scores_end_to_end(self):
        """deep_sets_scores is the actual production scoring entry point for
        M3/M5/M6/M7/M8/M9 -- confirm the fix holds there, not just at the raw
        nn.Module level."""
        torch.manual_seed(0)
        model = bcm.DeepSets(in_dim=bcm.NODE_FEATURE_DIM_WITH_VALIDITY).eval().to(bcm._TORCH_DEVICE)
        a, b, meta = _ab_batches(self.N, self.INVALID_IDX, bcm.GNN_NODE_FEATURE_DIM)
        out_a = bcm.deep_sets_scores(model, a, meta=meta)
        out_b = bcm.deep_sets_scores(model, b, meta=meta)
        _assert_valid_nodes_unaffected(self, out_a, out_b, self.INVALID_IDX)

    def test_deep_sets_scores_gatv2_end_to_end(self):
        """Same, through deep_sets_scores's adjacency branch (M5_gatv2)."""
        torch.manual_seed(0)
        model = bcm.GATv2(in_dim=bcm.NODE_FEATURE_DIM_WITH_VALIDITY).eval().to(bcm._TORCH_DEVICE)
        a, b, meta = _ab_batches(self.N, self.INVALID_IDX, bcm.GNN_NODE_FEATURE_DIM)
        adjacency = bcm.topology_mask(self.N)
        out_a = bcm.deep_sets_scores(model, a, adjacency, meta=meta)
        out_b = bcm.deep_sets_scores(model, b, adjacency, meta=meta)
        _assert_valid_nodes_unaffected(self, out_a, out_b, self.INVALID_IDX)


class TestConcatCanonicalization(unittest.TestCase):
    """M1/M2 are fixed-width: confirm zero_invalid_concat_blocks makes a
    placeholder and a tampered invalid-node block produce an IDENTICAL row,
    via the actual function main() calls -- not a re-implementation."""

    def test_invalid_block_is_zeroed_identically(self):
        n, feat = 4, bcm.GNN_NODE_FEATURE_DIM
        keep = [(0, i) for i in range(n)]
        meta = [{"valid": np.array([True, False, True, True])}]

        base = np.arange(n * feat, dtype=np.float32)
        flat_a = np.tile(base, (n, 1)).copy()
        flat_a[:, feat:2 * feat] = 0.9                     # node 1's placeholder block
        flat_b = np.tile(base, (n, 1)).copy()
        flat_b[:, feat:2 * feat] = [-1e6, 5e5, 1.0]         # node 1's tampered block

        zeroed_a = bcm.zero_invalid_concat_blocks(flat_a.copy(), keep, meta)
        zeroed_b = bcm.zero_invalid_concat_blocks(flat_b.copy(), keep, meta)
        np.testing.assert_array_equal(zeroed_a, zeroed_b)
        np.testing.assert_array_equal(zeroed_a[:, feat:2 * feat], 0.0)


if __name__ == "__main__":
    unittest.main()
