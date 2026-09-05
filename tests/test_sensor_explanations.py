"""Explanations must name the features the scored sensor actually supplies."""
import os
import sys
import unittest
from types import SimpleNamespace

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer


class TestSwitchExplanations(unittest.TestCase):
    def test_if_names_switch_feature(self):
        scorer = IsolationForestScorer.__new__(IsolationForestScorer)
        scorer.models = {"esp32-vib-002": object()}
        scorer._explainers = {"esp32-vib-002": SimpleNamespace(
            shap_values=lambda x: np.array([[0.1, 0.2, 0.8, 0.3]]))}
        name, _ = scorer.level2_explain("esp32-vib-002", [1, 0.2, 10, 0.4])
        self.assertEqual(name, "burst_max_ms")

    def test_lstm_perturbs_only_switch_channels(self):
        scorer = LSTMAEScorer.__new__(LSTMAEScorer)
        scorer.models = {"esp32-vib-002": lambda x: torch.zeros_like(x)}
        scorer._history = {"esp32-vib-002": [[1, 2, 5, 3]] * 8}
        scorer.stats = {"esp32-vib-002": dict(mean=np.zeros(4), std=np.ones(4),
                                             baseline_error_mean=0, baseline_error_std=1)}
        name, _, _ = scorer.level2_explain("esp32-vib-002")
        self.assertEqual(name, "burst_max_ms")


if __name__ == "__main__":
    unittest.main()
