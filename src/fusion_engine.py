"""
Module 3, Phase 7: Fusion Engine (stacking meta-learner + SHAP) -- INFERENCE ONLY.

CLAUDE.md Section 8 / synopsis Section 5.3: training happens offline in
scripts/train_fusion_meta_learner.py, which fits a LogisticRegression on
[rule_score, isolation_forest_score, lstm_ae_score, gnn_score] against
REAL ground-truth labels from the generated training session (synopsis
Section 5.3: "Only the stacking meta-learner needs a small labelled
validation set... constructed from the project's own adversarial-testing
scenarios") and saves it + a SHAP background sample to
config.FUSION_MODEL_PATH / FUSION_BACKGROUND_PATH. This file only ever
loads those and calls .predict_proba() -- it never calls .fit().

Combines the four Module 3 signals into one Unified Trust Score with an
attached CONFIDENCE measure (synopsis Section 4.4 / Figure 4.1) -- the
one new field CLAUDE.md's Section 8 hard constraint permits adding to the
score_message() interface. A SHAP explainability layer (grounded in
[33]-[36]) is applied to every fused decision, generating a machine-
readable reason code.
"""

import os

import numpy as np
import shap
from sklearn.linear_model import LogisticRegression

from config import FUSION_MODEL_PATH, FUSION_BACKGROUND_PATH

FEATURE_NAMES = ["rule_score", "isolation_forest_score", "lstm_ae_score", "gnn_score"]


class FusionEngine:
    def __init__(self):
        self.model: LogisticRegression | None = None
        self.explainer = None
        self.last_shap: dict[str, float] | None = None  # see _explain() -- the
        # FULL per-signal SHAP vector for the most recent combine() call, not
        # just the single top-contributing feature that ends up in `reason`.
        # Safe as instance state because gateway.py's MQTT on_message handler
        # (and the HTTPS handler in coap_server.py) process one message fully
        # before the next -- this is a single-threaded pipeline, not a shared
        # object read concurrently by multiple in-flight decisions.
        self._load()

    def _load(self):
        if not (os.path.exists(FUSION_MODEL_PATH) and os.path.exists(FUSION_BACKGROUND_PATH)):
            return
        import joblib
        self.model = joblib.load(FUSION_MODEL_PATH)
        background = np.load(FUSION_BACKGROUND_PATH)
        self.explainer = shap.LinearExplainer(self.model, background)

    def combine(self, rule_score: float, if_score: float, lstm_score: float, gnn_score: float) -> tuple[float, float, str]:
        """Returns (trust, confidence, reason). Before the meta-learner is
        trained: a plain average as a sane fallback (confidence 0.5 --
        maximally uncertain, since there's no learned model backing it)."""
        features = np.array([rule_score, if_score, lstm_score, gnn_score], dtype=np.float64)

        if self.model is None:
            self.last_shap = None
            fused = float(np.mean(features))
            return fused, 0.5, f"ML anomaly score {np.mean([if_score, lstm_score, gnn_score]):.2f} (fusion model not trained yet)"

        proba = self.model.predict_proba(features.reshape(1, -1))[0]
        trust = float(proba[1])       # P(legitimate)
        confidence = float(max(proba))  # how decisive the model is
        reason = self._explain(features)
        return trust, confidence, reason

    def _explain(self, features: np.ndarray) -> str:
        """NOTE on units (verified, not assumed -- see SESSION_LOG.md):
        shap.LinearExplainer explains the model's raw linear margin
        (pre-sigmoid decision_function output), not the 0-1 `trust`
        probability combine() returns above -- confirmed empirically:
        explainer.expected_value + shap_values.sum() reproduces
        model.decision_function(x) exactly, not model.predict_proba(x).
        This is the mathematically correct and unavoidable choice: no exact
        additive decomposition into probability-space contributions exists
        for a logistic model (sigmoid(a+b) != sigmoid(a)+sigmoid(b)), and
        LinearExplainer's speed (exact, closed-form, no sampling) is what
        keeps this affordable to run on every single gateway message.
        Direction (raised/lowered trust) is always correct, since sigmoid
        is monotonic -- only the MAGNITUDE is in log-odds units, not
        directly comparable to trust_score's 0-1 scale. Say so explicitly
        in the reason text and the dashboard, since this feeds a governance
        audit log where unit precision matters."""
        if self.explainer is None:
            self.last_shap = None
            return "fusion model trained (explainer unavailable)"
        shap_values = np.array(self.explainer.shap_values(features.reshape(1, -1)))[0]
        # Stash the FULL vector (all 4 signals), not just the top one --
        # gateway.py reads this right after combine() returns to persist it
        # to audit_log, so the dashboard can show every signal's real
        # contribution instead of only the single top-contributing feature
        # the `reason` sentence below names. Previously computed here and
        # discarded once idx/reason were derived from it.
        self.last_shap = {name: float(v) for name, v in zip(FEATURE_NAMES, shap_values)}
        idx = int(np.argmax(np.abs(shap_values)))
        direction = "raised" if shap_values[idx] > 0 else "lowered"
        return (
            f"fusion: {FEATURE_NAMES[idx]}={features[idx]:.2f} most {direction} trust "
            f"(SHAP={shap_values[idx]:.2f}, log-odds)"
        )

    def is_trained(self) -> bool:
        return self.model is not None
