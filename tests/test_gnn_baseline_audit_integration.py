"""Independent cross-review checks for the finite pending-content contract."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from test_gnn_baseline_pending_node_masking import _ab_snapshots, egb


class TestAuditIntegration(unittest.TestCase):
    def test_nonfinite_pending_concat_and_snapshot_blocks_are_canonical(self):
        for value in (np.nan, np.inf, -np.inf):
            with self.subTest(value=value):
                a, b, y, meta = _ab_snapshots(3, (1, 6), tampered=value)
                with np.errstate(invalid='ignore'):
                    expected, _, _ = egb.masked_concat_features(a, y, meta)
                    actual, _, _ = egb.masked_concat_features(b, y, meta)
                    np.testing.assert_array_equal(actual, expected)
                    np.testing.assert_array_equal(
                        egb.snapshot_matrix(dict(X=b, meta=meta)),
                        egb.snapshot_matrix(dict(X=a, meta=meta)))

    def test_nonfinite_pending_content_cannot_poison_gnn_inference_or_training(self):
        for value in (np.nan, np.inf, -np.inf):
            with self.subTest(value=value), patch.object(egb, 'GNN_EPOCHS', 2):
                a, b, y, meta = _ab_snapshots(3, (1, 6), tampered=value)
                reference = egb.train_network_gnn(a, y, meta, 5.0)
                np.testing.assert_array_equal(
                    egb.gnn_scores(reference, b, 5.0, meta),
                    egb.gnn_scores(reference, a, 5.0, meta))
                candidate = egb.train_network_gnn(b, y, meta, 5.0)
                for name, expected in reference.state_dict().items():
                    torch.testing.assert_close(candidate.state_dict()[name], expected, rtol=0, atol=0)

    def test_b0_ignores_pending_content_even_before_concat_masking(self):
        # This distinguishes B0's original immunity from the new shared mask.
        for tamper in (-1e6, 1e6, 0.42):
            a, b, y, meta = _ab_snapshots(3, (1, 6), tampered=tamper)
            for X in (a, b):
                flat, _, keep = egb.flatten_for_concat(X, y, meta)
                expected = np.array([a[t, i] for t, i in keep])
                np.testing.assert_array_equal(egb.own_features({'flat_X': flat}), expected)

    def test_actual_topology_and_split_provenance(self):
        root = Path(egb.__file__).resolve().parents[1]
        nodes = json.loads((root / 'config/graph_topology.json').read_text())['nodes']
        self.assertEqual([n['device_id'] for n in nodes], egb.NETWORK_NODES)
        self.assertEqual(len(nodes), 20)
        self.assertEqual(sum(n['sensor_type'].startswith('MPU6050') for n in nodes), 10)
        self.assertEqual(sum(n['sensor_type'].startswith('SW-420') for n in nodes), 10)
        real = {n['device_id']: n['sensor_type'] for n in nodes if n['source_type'] == 'REAL'}
        self.assertEqual(real, {'esp32-vib-001': 'MPU6050', 'esp32-vib-002': 'SW-420'})
        for split in ('train', 'validation', 'test'):
            for scenario in egb.datasets.scenarios():
                rows = egb.datasets.network_records(scenario, split)
                by_tick = {}
                for row in rows:
                    by_tick.setdefault(row['tick'], []).append(row['device_id'])
                    pending = row['device_id'] == 'esp32-vib-002' and split != 'train'
                    self.assertEqual(row['reading'] is None, pending)
                    expected_source = ('PENDING_REAL_HARDWARE_DATA' if pending else
                                       'REAL' if row['device_id'] in real else 'SIMULATED')
                    self.assertEqual(row['source_type'], expected_source)
                    node = next(n for n in nodes if n['device_id'] == row['device_id'])
                    self.assertEqual(row['sensor_type'], node['sensor_type'])
                for ids in by_tick.values():
                    self.assertCountEqual(ids, egb.NETWORK_NODES)

    def test_main_fits_and_evaluates_all_paths_without_pending_content(self):
        # Only replace the expensive replay boundary and shorten GNN training.
        # Actual feature helpers, sklearn fits, GNN training, selection, Task-2
        # heads, and metric serialization all run through the production main.
        datasets = {}
        for seed, split in enumerate(('train', 'validation', 'test')):
            a, b, y, meta = _ab_snapshots(12, (1, 6), seed=seed)
            b[:, 1] = [-1e6, 1e6, 0.42]
            b[:, 6] = [1e6, -1e6, 0.73]
            y[:] = (a.min(axis=2) >= 0.6).astype(int)
            for t, m in enumerate(meta):
                m['scenario'] = ('NETWORK_NORMAL', 'SCENARIO_A', 'SCENARIO_B', 'SCENARIO_C')[t % 4]
            datasets[split] = (a, b, y, meta)

        outputs, states, predictions = [], [], []
        for variant in (0, 1):
            def snapshots(split):
                a, b, y, meta = datasets[split]
                return (a if variant == 0 else b), y, meta, 24

            # Observe the real inference results, including ALL columns handed
            # to Task 2's logistic head, not merely valid-node GNN predictions.
            seen = []
            original_scores = egb.gnn_scores

            def scores(*args, **kwargs):
                result = original_scores(*args, **kwargs)
                seen.append(result.copy())
                return result

            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                model_path = str(Path(tmp) / 'gnn_network.pt')
                with patch.object(egb, 'build_snapshots', snapshots), \
                        patch.object(egb, 'GNN_EPOCHS', 2), \
                        patch.object(egb, 'SELF_LOOP_SWEEP', [1.0, 5.0]), \
                        patch.object(egb, 'gnn_scores', scores), \
                        patch.object(egb, 'RESULTS_DIR', tmp), \
                        patch.object(egb, 'NETWORK_GNN_PATH', model_path):
                    egb.main()
                outputs.append(json.loads((Path(tmp) / 'metrics.json').read_text()))
                states.append(torch.load(model_path, weights_only=True))
                predictions.append(seen)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(len(predictions[0]), len(predictions[1]))
        for a, b in zip(predictions[0], predictions[1]):
            np.testing.assert_array_equal(a, b)
            np.testing.assert_array_equal(a[:, [1, 6]], 0.5)
        for name in states[0]:
            torch.testing.assert_close(states[0][name], states[1][name], rtol=0, atol=0)


if __name__ == '__main__':
    unittest.main()
