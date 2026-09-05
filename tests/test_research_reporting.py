"""Absent anomaly classes must not erase the normal-control false positives."""
import json
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import benchmark_crossdevice_models as benchmark


class TestSliceMetrics(unittest.TestCase):
    def evaluate(self, labels):
        x = np.zeros((1, 2, 3))
        meta = [{"scenario": "NETWORK_NORMAL", "valid": np.array([True, True])}]
        with patch.object(benchmark, "deep_sets_scores", return_value=np.array([[0.2, 0.9]])):
            return benchmark._eval_slice(None, x, np.array([labels]), meta, 0.6)

    def test_normal_control_keeps_fpr_with_undefined_detection(self):
        result = self.evaluate([1, 1])
        self.assertEqual(result["false_positive_rate"], 0.5)
        self.assertIsNone(result["f1"])
        self.assertIsNone(result["recall"])
        self.assertEqual((result["fp"], result["tn"]), (1, 1))
        json.dumps(result, allow_nan=False)

    def test_anomaly_only_slice_keeps_detection_with_undefined_fpr(self):
        result = self.evaluate([0, 0])
        self.assertEqual(result["recall"], 0.5)
        self.assertIsNone(result["false_positive_rate"])

    def test_mixed_slice_preserves_existing_metrics(self):
        result = self.evaluate([0, 1])
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["false_positive_rate"], 0.0)


class TestSeedIntervals(unittest.TestCase):
    def test_two_seed_interval_uses_student_t_not_normal_approximation(self):
        result = benchmark.mean_ci([0.0, 2.0])
        self.assertAlmostEqual(result["ci95"], 12.7062, places=4)
        self.assertEqual(result["multiplier"], "t")
        paired = benchmark._paired_t(np.array([0.0, 2.0]))
        self.assertEqual(paired["ci95"], [-11.7062, 13.7062])
        self.assertFalse(paired["significant"])

    def test_insufficient_seeds_produce_strict_json_and_no_significance(self):
        for values in ([], [1.0]):
            with self.subTest(values=values):
                result = benchmark.mean_ci(values)
                self.assertIsNone(result["ci95"])
                json.dumps(result, allow_nan=False)
                paired = benchmark._paired_t(np.array(values))
                self.assertFalse(paired["significant"])
                json.dumps(paired, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
