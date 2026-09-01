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

from config import ISOLATION_FOREST_MODEL_PATH, FEATURE_NAMES


class IsolationForestScorer:
    """Single shared instance -- one model, for esp32-vib-001 specifically,
    not a per-device registry (unlike the old online-learning version,
    there's only ever one device this model applies to)."""

    def __init__(self):
        self.model = None
        self._explainer = None  # lazy: shap.TreeExplainer, only built if level2_explain() is ever called
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

    def level2_explain(self, feature_vec: list[float]) -> tuple[str, float] | None:
        """Module 3 Section C.3's Level-2 explanation for this sub-signal:
        `shap.TreeExplainer` directly on the ProcessFeatureVector inputs
        (not the fusion meta-learner's 4-signal inputs -- Level 1 already
        covers that). Returns (feature_name, abs_shap_value) for the
        dominant raw feature, or None if the model isn't trained yet.

        Deliberately does NOT compute a counterfactual score itself, unlike
        LSTMAEScorer/TransformerScorer/GNNScorer's level2_explain() --
        those need internal state (a rolling window / graph snapshot) the
        caller can't easily rebuild, so THEY compute their own
        counterfactual forward pass. This scorer is stateless (`score()`
        takes a feature vector and returns a value, nothing else) --
        building a perturbed vector and calling `score()` again is exactly
        as easy for a caller to do directly, and doing it here too would
        just be a second, redundant place to get the replacement value
        wrong. See scripts/evaluate_explainability_level2.py for where the
        counterfactual vector (training-median substitution) is built."""
        if self.model is None:
            return None
        if self._explainer is None:
            import shap
            self._explainer = shap.TreeExplainer(self.model)
        x = np.asarray([feature_vec], dtype=np.float64)
        shap_values = np.array(self._explainer.shap_values(x))[0]
        idx = int(np.argmax(np.abs(shap_values)))
        return FEATURE_NAMES[idx], float(shap_values[idx])
