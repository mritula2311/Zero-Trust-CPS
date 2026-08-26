"""
Offline training for Module 3, Phase 6a (Isolation Forest).

CLAUDE.md Section 8: training happens here, in a standalone script,
producing a saved model artifact; `gateway.py` (via
`isolation_forest_scorer.py`) only ever loads it and runs inference.

Trains on esp32-vib-001's NORMAL (label=1) feature vectors only --
Isolation Forest is an unsupervised/self-supervised anomaly detector (it
never sees the anomalous examples during training by design; synopsis
Section 5.3), so the "label" here is only used to select the *normal*
training subset, not as a supervised training target.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import joblib
from sklearn.ensemble import IsolationForest

from config import (
    DATA_COLLECTED_DIR,
    MODELS_DIR,
    ISOLATION_FOREST_MODEL_PATH,
    ISOLATION_FOREST_CONTAMINATION,
    FEATURE_NAMES,
)
import feature_engineering as fe

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    normal = [
        r for r in records
        if r["device_id"] == "esp32-vib-001" and r["label"] == 1 and r["auth_ok"]
    ]
    if len(normal) < 30:
        raise SystemExit(f"only {len(normal)} normal esp32-vib-001 examples -- need at least 30, re-run generate_training_data.py")

    X = [fe.feature_vector(r["reading"]) for r in normal]

    model = IsolationForest(contamination=ISOLATION_FOREST_CONTAMINATION, random_state=0)
    model.fit(X)

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model, ISOLATION_FOREST_MODEL_PATH)
    print(f"trained IsolationForest on {len(X)} normal examples, saved to {ISOLATION_FOREST_MODEL_PATH}")

    # sanity check: score a few normal + the anomalous examples, confirm separation
    anomalous = [
        r for r in records
        if r["device_id"] == "esp32-vib-001" and r["label"] == 0 and r["event_type"] == "anomalous_shock"
    ][:5]
    if anomalous:
        import numpy as np
        normal_scores = model.decision_function(X[:5])
        anom_scores = model.decision_function([fe.feature_vector(r["reading"]) for r in anomalous])
        print("sanity check -- decision_function (higher = more normal):")
        print("  normal samples:  ", np.round(normal_scores, 3))
        print("  anomalous samples:", np.round(anom_scores, 3))


if __name__ == "__main__":
    main()
