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
    isolation_forest_path,
    isolation_forest_meta_path,
    ISOLATION_FOREST_CONTAMINATION,
    FEATURE_VECTOR_DEVICE_IDS,
    FEATURE_NAMES, TRAINING_SEED,
)
import feature_engineering as fe
import datasets

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")


def train_one(records, device_id) -> bool:
    """Trains ONE device's Isolation Forest on ITS OWN normal readings and
    saves it to that device's per-device path. Returns True if a model was
    trained, False if the device had too few examples (skipped, not fatal --
    a device with no captured data yet simply gets no model, and its scorer
    falls back to the neutral score, per isolation_forest_scorer.py)."""
    normal = [
        r for r in records
        if r["device_id"] == device_id and r["label"] == 1 and r["auth_ok"]
    ]
    if len(normal) < 30:
        print(f"[skip] {device_id}: only {len(normal)} normal examples (< 30) -- no model trained")
        return False

    X = [fe.feature_vector(r["reading"]) for r in normal]
    model = IsolationForest(contamination=ISOLATION_FOREST_CONTAMINATION, random_state=TRAINING_SEED)
    model.fit(X)

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model, isolation_forest_path(device_id))
    print(f"[{device_id}] trained IsolationForest on {len(X)} normal examples, saved to {isolation_forest_path(device_id)}")

    # Score-calibration anchor for isolation_forest_scorer._calibrate() -- see the
    # long comment there for why the old raw+0.5 mapping made this signal unable to
    # ever read as "normal". Measured on the SAME normal training set the model was
    # just fitted to (no anomalous example consulted, so training stays unsupervised).
    import numpy as np
    raw_normal_median = float(np.median(model.decision_function(X)))
    with open(isolation_forest_meta_path(device_id), "w") as f:
        json.dump({"raw_normal_median": raw_normal_median}, f, indent=2)
    print(f"  calibration: raw decision_function median on normals = {raw_normal_median:+.4f} -> maps to 0.9")

    # sanity check: score a few normal + this device's anomalous examples, confirm separation
    anomalous = [
        r for r in records
        if r["device_id"] == device_id and r["label"] == 0 and r["event_type"] == "anomalous_shock"
    ][:5]
    if anomalous:
        import numpy as np
        normal_scores = model.decision_function(X[:5])
        anom_scores = model.decision_function([fe.feature_vector(r["reading"]) for r in anomalous])
        print("  sanity check -- decision_function (higher = more normal):")
        print("    normal samples:  ", np.round(normal_scores, 3))
        print("    anomalous samples:", np.round(anom_scores, 3))
    return True


def main():
    # Per-device training corpus: esp32-vib-001 from training_session.json,
    # every other network node from the TRAIN split of the network scenarios.
    # See src/datasets.py for why the primary device's corpus is unchanged.
    records = datasets.training_records()

    trained = sum(train_one(records, d) for d in FEATURE_VECTOR_DEVICE_IDS)
    if trained == 0:
        raise SystemExit("no feature_vector device had >= 30 normal examples -- re-run generate_training_data.py "
                         "(and merge_real_hardware_data.py if you have real captures)")
    print(f"trained {trained}/{len(FEATURE_VECTOR_DEVICE_IDS)} per-device Isolation Forest model(s)")


if __name__ == "__main__":
    main()
