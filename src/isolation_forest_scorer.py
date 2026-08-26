"""
Module 3, Phase 6a: Isolation Forest anomaly scorer -- INFERENCE ONLY.

CLAUDE.md Section 8: training happens offline in
scripts/train_isolation_forest.py, which saves a fitted
sklearn.ensemble.IsolationForest to config.ISOLATION_FOREST_MODEL_PATH.
This file only ever loads that artifact and calls .decision_function() --
it never calls .fit() in the live gateway path.

Specific to esp32-vib-001's 5-feature vibration vector (rms, peak,
crest_factor, kurtosis, dominant_freq) -- the two scalar simulated devices
(sensor-002, actuator-001) don't have an Isolation Forest model of their
own; gateway.py mirrors their rule_score into the fusion/GNN feature slots
this scorer would otherwise fill (see gnn_scorer.py's docstring).
"""

import os

import joblib
import numpy as np

from config import ISOLATION_FOREST_MODEL_PATH


class IsolationForestScorer:
    """Single shared instance -- one model, for esp32-vib-001 specifically,
    not a per-device registry (unlike the old online-learning version,
    there's only ever one device this model applies to)."""

    def __init__(self):
        self.model = None
        self._load()

    def _load(self):
        if os.path.exists(ISOLATION_FOREST_MODEL_PATH):
            self.model = joblib.load(ISOLATION_FOREST_MODEL_PATH)

    def score(self, feature_vec: list[float]) -> float:
        if self.model is None:
            return 0.9  # not trained yet -- defer to the rule-based score
        raw = self.model.decision_function([feature_vec])[0]  # higher = more normal
        return float(np.clip(raw + 0.5, 0.0, 1.0))

    def is_trained(self) -> bool:
        return self.model is not None
