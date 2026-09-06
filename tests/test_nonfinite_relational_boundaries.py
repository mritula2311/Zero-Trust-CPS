"""Invalid observations must be excluded before floating-point arithmetic."""
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import benchmark_crossdevice_models as bcm
import gnn_scorer as live


class TestNonfiniteRelationalBoundaries(unittest.TestCase):
    def test_isolated_invalid_gat_query_does_not_poison_other_nodes(self):
        torch.manual_seed(14)
        model = bcm.GATv2().eval().to(bcm._TORCH_DEVICE)
        x = np.full((1, 3, 3), 0.8, dtype=np.float32)
        meta = [{'valid': np.array([True, False, True])}]
        adjacency = torch.eye(3, dtype=torch.bool, device=bcm._TORCH_DEVICE).view(1, 1, 3, 3)
        expected = bcm.deep_sets_scores(model, x, adjacency, meta=meta)
        self.assertTrue(np.isfinite(expected[:, [0, 2]]).all())
        x[:, 1] = np.nan
        actual = bcm.deep_sets_scores(model, x, adjacency, meta=meta)
        np.testing.assert_allclose(actual[:, [0, 2]], expected[:, [0, 2]], atol=1e-6)

    def test_mixed_provenance_training_excludes_invalid_content(self):
        rng = np.random.default_rng(14)
        x = rng.uniform(0.1, 0.9, (4, 3, 3)).astype(np.float32)
        labels = np.array([[1, 1, 0]] * 4, dtype=np.float32)
        meta = [{'valid': np.array([True, False, True])}] * 4
        changed = x.copy()
        changed[:, 1] = np.nan
        with patch.object(bcm, 'DEEPSETS_EPOCHS', 2):
            expected, _, _ = bcm._train_pooled_sets([(x, labels, meta)], (3,), seed=14)
            actual, _, _ = bcm._train_pooled_sets([(changed, labels, meta)], (3,), seed=14)
        for name, weight in actual.state_dict().items():
            torch.testing.assert_close(weight, expected.state_dict()[name], atol=1e-6, rtol=1e-6)

    def test_set_scoring_excludes_nonfinite_invalid_payloads(self):
        rng = np.random.default_rng(14)
        x = rng.uniform(0.1, 0.9, (2, 6, 3)).astype(np.float32)
        meta = [{'valid': np.array([True, False, True, True, True, True])}] * 2
        for factory in (bcm.DeepSets, bcm.GATv2, bcm.SetTransformer,
                        bcm.NodePreservingSetTransformer):
            torch.manual_seed(14)
            model = factory().eval().to(bcm._TORCH_DEVICE)
            adjacency = bcm.topology_mask(6) if factory is bcm.GATv2 else None
            expected = bcm.deep_sets_scores(model, x, adjacency, meta=meta)
            for value in (np.nan, np.inf, -np.inf, np.finfo(np.float32).max):
                with self.subTest(model=factory.__name__, value=value):
                    changed = x.copy()
                    changed[:, 1] = value
                    actual = bcm.deep_sets_scores(model, changed, adjacency, meta=meta)
                    np.testing.assert_allclose(actual[:, [0, 2, 3, 4, 5]],
                                               expected[:, [0, 2, 3, 4, 5]], atol=1e-6)
                    self.assertTrue(np.isfinite(actual).all())

    def test_live_inactive_node_content_cannot_change_current_score(self):
        with patch.object(live.GNNScorer, '_load'):
            scorer = live.GNNScorer()
        torch.manual_seed(14)
        scorer.model = live._GCN().eval().to(live._TORCH_DEVICE)
        target = scorer.device_ids[0]
        with patch.object(live.time, 'time', return_value=1000.0):
            expected = scorer.score(target, 0.8, 0.7, 0.6)
            for value in (np.nan, np.inf, -np.inf, np.finfo(np.float32).max):
                with self.subTest(value=value):
                    scorer.last_features[1:] = value
                    actual = scorer.score(target, 0.8, 0.7, 0.6)
                    self.assertTrue(np.isfinite(actual))
                    self.assertAlmostEqual(actual, expected, places=6)
                    self.assertIsNone(scorer.level2_explain(target))


if __name__ == '__main__':
    unittest.main()
