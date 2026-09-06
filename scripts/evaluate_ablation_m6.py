"""
Side-by-side comparison: the DEPLOYED GCN-based fusion vs the M6 (Set
Transformer) fusion variant, on the SAME held-out data/collected/
test_session.json used by scripts/evaluate_ablation.py -- so the two
numbers below are directly comparable to each other and to the currently
reported fusion metrics.

This is evaluation only. It does not modify src/fusion_engine.py,
config.FUSION_MODEL_PATH, or any deployed artifact. See
scripts/train_set_transformer.py and scripts/train_fusion_meta_learner_m6.py
for how the M6 candidate and its fusion variant were produced.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import joblib
import numpy as np

from config import (
    DATA_COLLECTED_DIR, LSTM_SEQ_LEN, is_feature_vector, PROCESS_THRESHOLD,
    FUSION_MODEL_PATH_M6_VARIANT,
)
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from set_transformer_scorer import SetTransformerScorer
from fusion_engine import FusionEngine
from generate_training_data import physical_label

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")


def score_all_signals(records):
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()
    m6_scorer = SetTransformerScorer()
    fusion = FusionEngine()  # deployed GCN-based fusion, unmodified
    m6_fusion_model = joblib.load(FUSION_MODEL_PATH_M6_VARIANT)

    rows = []
    excluded = 0
    for r in sorted(records, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            excluded += 1
            continue
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])
        target = physical_label(r["event_type"])

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        m6_score = m6_scorer.score(device_id, rule_score, if_score, lstm_score)
        fused_gcn, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)
        fused_m6 = float(m6_fusion_model.predict_proba(
            np.array([[rule_score, if_score, lstm_score, m6_score]]))[0, 1])

        rows.append({
            "gnn_score": gnn_score, "m6_score": m6_score,
            "fused_gcn": fused_gcn, "fused_m6": fused_m6,
            "label": target,
        })
    print(f"(excluded {excluded} auth_ok=False/replay records -- never reach Process Anomaly scoring live)")
    return rows


def metrics_at_threshold(scores, labels, threshold=PROCESS_THRESHOLD):
    scores = np.array(scores)
    labels = np.array(labels)
    preds = (scores >= threshold).astype(int)
    tp = int(np.sum((preds == 1) & (labels == 1)))
    tn = int(np.sum((preds == 0) & (labels == 0)))
    fp = int(np.sum((preds == 1) & (labels == 0)))
    fn = int(np.sum((preds == 0) & (labels == 1)))
    accuracy = (tp + tn) / len(labels) if len(labels) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)
    print(f"Scoring {len(records)} held-out test messages through both pipelines...")
    rows = score_all_signals(records)
    labels = [row["label"] for row in rows]
    print(f"Label balance: {sum(labels)} legitimate, {len(labels) - sum(labels)} suspicious\n")

    print(f"{'Signal':<28} {'Accuracy':>9} {'Precision':>10} {'Recall':>8} {'F1':>8} {'FP':>6} {'FN':>6}")
    print("-" * 80)
    for name in ["gnn_score", "m6_score", "fused_gcn", "fused_m6"]:
        scores = [row[name] for row in rows]
        m = metrics_at_threshold(scores, labels)
        print(f"{name:<28} {m['accuracy']:>9.3f} {m['precision']:>10.3f} {m['recall']:>8.3f} "
              f"{m['f1']:>8.3f} {m['fp']:>6d} {m['fn']:>6d}")

    print("\nBy event_type recall (fused_gcn vs fused_m6), at PROCESS_THRESHOLD:")
    with open(TEST_PATH) as f:
        raw = json.load(f)
    event_types = {}
    j = 0
    for r in sorted(raw, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue
        event_types.setdefault(r["event_type"], []).append(j)
        j += 1
    fused_gcn = np.array([row["fused_gcn"] for row in rows])
    fused_m6 = np.array([row["fused_m6"] for row in rows])
    labels_arr = np.array(labels)
    for et, idxs in sorted(event_types.items()):
        idxs = np.array(idxs)
        lab = labels_arr[idxs]
        if lab.sum() == len(lab):
            continue  # all-legitimate event types have no "recall" to report
        gcn_recall = ((fused_gcn[idxs] >= PROCESS_THRESHOLD).astype(int) == lab)[lab == 0].mean() if (lab == 0).any() else float("nan")
        m6_recall = ((fused_m6[idxs] >= PROCESS_THRESHOLD).astype(int) == lab)[lab == 0].mean() if (lab == 0).any() else float("nan")
        print(f"  {et:<30} n={len(idxs):<5} gcn_recall={gcn_recall:.3f} m6_recall={m6_recall:.3f}")


if __name__ == "__main__":
    main()
