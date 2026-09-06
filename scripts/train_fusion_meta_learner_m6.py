"""
Fits a SEPARATE fusion meta-learner on [rule, if, lstm, m6_score] instead of
[rule, if, lstm, gnn_score] -- an evaluation variant, NOT a replacement for
the deployed model. Saves to config.FUSION_MODEL_PATH_M6_VARIANT /
FUSION_BACKGROUND_PATH_M6_VARIANT, never touching FUSION_MODEL_PATH itself.

Identical dataset-construction logic to scripts/train_fusion_meta_learner.py
(see that file's docstring for the full rationale of window_compromised
tracking, physical_label targets, and excluded auth-failed/replay records --
duplicated here rather than imported because the only difference is which
scorer produces the fourth feature, and threading that through as a
parameter would touch the verified, deployed training script for no reason).

Run this AFTER train_isolation_forest.py, train_lstm_ae.py, and
train_set_transformer.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import joblib
from sklearn.linear_model import LogisticRegression

from config import (
    DATA_COLLECTED_DIR, MODELS_DIR, FUSION_MODEL_PATH_M6_VARIANT,
    FUSION_BACKGROUND_PATH_M6_VARIANT, FUSION_SHAP_BACKGROUND_SIZE,
    LSTM_SEQ_LEN, is_feature_vector,
)
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from set_transformer_scorer import SetTransformerScorer
from generate_training_data import physical_label
import splits

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "validation_session.json")


def build_dataset(records):
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    m6_scorer = SetTransformerScorer()

    label_window: dict[str, list[int]] = {}
    X, y = [], []
    for r in sorted(records, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])
        target = physical_label(r["event_type"])
        window_compromised = False

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
            lw = label_window.setdefault(device_id, [])
            window_compromised = any(l == 0 for l in lw)
            lw.append(target)
            if len(lw) > LSTM_SEQ_LEN:
                del lw[0]
        else:
            if_score = lstm_score = rule_score

        m6_score = m6_scorer.score(device_id, rule_score, if_score, lstm_score)

        if target == 1 and window_compromised:
            continue  # ambiguous residue -- excluded, not relabelled

        X.append([rule_score, if_score, lstm_score, m6_score])
        y.append(target)

    return np.array(X), np.array(y)


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    splits.assert_disjoint()
    print(f"[M6 VARIANT -- evaluation only] meta-training on VALIDATION split: "
          f"{os.path.basename(SESSION_PATH)} ({len(records)} records).")
    print("building fusion training set (replaying through trained IF/LSTM-AE/M6 scorers)...")
    X, y = build_dataset(records)
    print(f"built {len(X)} examples, class balance: {np.bincount(y.astype(int))}")

    if len(set(y.tolist())) < 2:
        raise SystemExit("only one class present in labels -- need both 0 and 1 examples to train a classifier")

    model = LogisticRegression(max_iter=500, class_weight="balanced")
    model.fit(X, y)
    train_acc = model.score(X, y)
    print(f"trained LogisticRegression, training accuracy={train_acc:.3f}, coefficients={model.coef_[0].round(3)}")

    rng = np.random.default_rng(0)
    background_idx = rng.choice(len(X), min(FUSION_SHAP_BACKGROUND_SIZE, len(X)), replace=False)
    background = X[background_idx]

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model, FUSION_MODEL_PATH_M6_VARIANT)
    np.save(FUSION_BACKGROUND_PATH_M6_VARIANT, background)
    print(f"saved M6-variant fusion model to {FUSION_MODEL_PATH_M6_VARIANT} (evaluation only)")


if __name__ == "__main__":
    main()
