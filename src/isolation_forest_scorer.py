"""
Module 3, Phase 6a: Isolation Forest anomaly scorer -- INFERENCE ONLY.

CLAUDE.md Section 8: training happens offline in
scripts/train_isolation_forest.py, which saves a fitted
sklearn.ensemble.IsolationForest per feature_vector device to
config.isolation_forest_path(device_id).
This file only ever loads that artifact and calls .decision_function() --
it never calls .fit() in the live gateway path.

Specific to esp32-vib-001's 5-feature vibration vector (rms, peak,
crest_factor, kurtosis, dominant_freq) -- the two scalar simulated devices
(sensor-002, actuator-001) don't have an Isolation Forest model of their
own; gateway.py mirrors their rule_score into the fusion/GNN feature slots
this scorer would otherwise fill (see gnn_scorer.py's docstring).
"""

import json
import os

import joblib
import numpy as np

from config import (
    isolation_forest_path, isolation_forest_meta_path, FEATURE_VECTOR_DEVICE_IDS, FEATURE_NAMES,
    feature_names_for,
)


# Calibration (see scripts/train_isolation_forest.py, which measures and saves
# `raw_normal_median`). sklearn's decision_function is NOT a [-0.5, 0.5]-spanning
# score: with contamination=c it is defined so that exactly c of the TRAINING data
# falls below 0.0, and its inlier side is compressed into a narrow positive band
# (measured on this model: normal median +0.079, best-case +0.121). The previous
# mapping, `raw + 0.5`, therefore capped the score for a PERFECTLY normal reading
# at 0.62 and put the median normal at 0.58 -- both under config.PROCESS_THRESHOLD
# (0.6), so this signal could never actually express "normal" and dragged the fused
# score below threshold on genuinely healthy telemetry (including the real ESP32 at
# rest). Two anchors fix that, both taken from the NORMAL class only, so this stays
# unsupervised -- no anomalous example is consulted to calibrate:
#   raw == 0.0                -> 0.5  (sklearn's OWN inlier/outlier boundary, so the
#                                      model's decision boundary is the neutral point)
#   raw == raw_normal_median  -> 0.9  (this codebase's "looks normal" convention,
#                                      matching lstm_ae_scorer/gnn_scorer's fallback)
# and linear in between, clipped to [0, 1]. Monotonic in raw, so it reorders nothing --
# it only rescales a signal that was previously squeezed into an unusable range.
NEUTRAL_SCORE = 0.5
NORMAL_SCORE = 0.9


def _calibrate(raw: float, raw_normal_median: float | None) -> float:
    if not raw_normal_median or raw_normal_median <= 0:
        return raw + 0.5  # not calibrated yet (pre-existing model artifact) -- legacy mapping
    return NEUTRAL_SCORE + (NORMAL_SCORE - NEUTRAL_SCORE) * (raw / raw_normal_median)


class IsolationForestScorer:
    """Per-device model registry: one fitted IsolationForest PER feature_vector
    device (keyed by device_id), each trained only on that device's own raw
    vibration distribution. A device with no trained model yet scores the
    neutral fallback, so a newly-onboarded board is never scored by another
    device's model. Still one shared instance -- it just holds a dict of
    models instead of a single one."""

    def __init__(self):
        self.models: dict = {}       # device_id -> fitted IsolationForest
        self._calibration: dict = {}  # device_id -> raw decision_function value that maps to NORMAL_SCORE
        self._explainers: dict = {}  # device_id -> shap.TreeExplainer (lazy, per device)
        self._load()

    def _load(self):
        for device_id in FEATURE_VECTOR_DEVICE_IDS:
            path = isolation_forest_path(device_id)
            if os.path.exists(path):
                self.models[device_id] = joblib.load(path)
            meta_path = isolation_forest_meta_path(device_id)
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    self._calibration[device_id] = json.load(f)["raw_normal_median"]

    def score(self, device_id: str, feature_vec: list[float]) -> float:
        model = self.models.get(device_id)
        if model is None:
            return 0.9  # no model for this device yet -- defer to the rule-based score
        raw = model.decision_function([feature_vec])[0]  # higher = more normal
        return float(np.clip(_calibrate(raw, self._calibration.get(device_id)), 0.0, 1.0))

    def is_trained(self, device_id: str | None = None) -> bool:
        return bool(self.models) if device_id is None else device_id in self.models

    def level2_explain(self, device_id: str, feature_vec: list[float]) -> tuple[str, float] | None:
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
        model = self.models.get(device_id)
        if model is None:
            return None
        if device_id not in self._explainers:
            import shap
            self._explainers[device_id] = shap.TreeExplainer(model)
        x = np.asarray([feature_vec], dtype=np.float64)
        shap_values = np.array(self._explainers[device_id].shap_values(x))[0]
        idx = int(np.argmax(np.abs(shap_values)))
        return feature_names_for(device_id)[idx], float(shap_values[idx])
