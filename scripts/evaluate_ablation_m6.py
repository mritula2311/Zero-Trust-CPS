"""
Corrected side-by-side comparison: the historical GCN relational path vs the
CURRENTLY DEPLOYED M6 path vs a class-weight-CORRECTED M6 path, on the SAME
held-out data/collected/test_session.json used by scripts/evaluate_ablation.py.

Prior state (fixed here): this script constructed `GNNScorer()` (true GCN)
alongside `FusionEngine()`, which reads the *ambient* config.FUSION_MODEL_PATH
-- correct until the 2026-09-07 M6 deployment (3c827e8) overwrote that path
with the M6-fitted fusion model. After that, the "GCN arm" here silently
paired true GCN relational scores with M6-calibrated fusion coefficients --
not a reproduction of anything real. See src/relational_pin.py and
docs/paper/17_CLAIM_EVIDENCE_MATRIX.md C03/C05/C15.

Each arm below is loaded via an explicit src/relational_pin.py RelationalPin
(checkpoint + matched fusion artifact, hash-verified before use), never via
the ambient FusionEngine()/GNNScorer() default construction. This is
evaluation only -- it does not modify any deployed artifact.

Writes results/gcn_m6_corrected_comparison/standalone_comparison.json and
fusion_comparison.json.
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
from sklearn.metrics import roc_auc_score

from config import DATA_COLLECTED_DIR, is_feature_vector, PROCESS_THRESHOLD, TRAINING_SEED
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
import relational_pin as rp
from generate_training_data import physical_label

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "gcn_m6_corrected_comparison")

# "isolated" maps to anomalous_shock (a single-device physical anomaly);
# "coordinated"/"stealthy_forged_values" are event_type values directly.
# This mapping is explicit, not a silent rename -- see docs/paper/13's
# existing "fused shock/coordinated/stealthy-forged-values recall" wording,
# which this generalizes to isolated/coordinated/stealthy terminology used
# elsewhere in the paper (M1-M9 benchmark table).
EVENT_TYPE_TO_CATEGORY = {
    "anomalous_shock": "isolated_anomaly_recall",
    "coordinated": "coordinated_anomaly_recall",
    "stealthy_forged_values": "stealthy_anomaly_recall",
}


def git_commit_hash():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__) + "/..").decode().strip()


def score_all_arms(records):
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()

    arms = {}
    for name, pin in rp.KNOWN_PINS.items():
        arms[name] = {"scorer": pin.load_relational_scorer(), "fusion": pin.load_fusion_engine()}

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

        row = {"label": target, "event_type": r["event_type"]}
        for name, arm in arms.items():
            relational_score = arm["scorer"].score(device_id, rule_score, if_score, lstm_score)
            fused_score, _, _ = arm["fusion"].combine(rule_score, if_score, lstm_score, relational_score)
            row[f"{name}_relational"] = relational_score
            row[f"{name}_fused"] = fused_score
        rows.append(row)

    print(f"(excluded {excluded} auth_ok=False/replay records -- never reach Process Anomaly scoring live)")
    return rows


def compute_metrics(scores, labels, event_types, threshold=PROCESS_THRESHOLD):
    """Polarity: label 1 = legitimate/normal (matches docs/paper/13's 'local/
    fusion replay F1 treats normal as positive'). FPR = fraction of TRUE
    NORMAL rows wrongly scored below threshold (flagged anomalous) -- the
    same 'false alarm' quantity used for the hardware resting-FP result."""
    scores = np.array(scores)
    labels = np.array(labels)
    preds = (scores >= threshold).astype(int)

    tp = int(np.sum((preds == 1) & (labels == 1)))
    tn = int(np.sum((preds == 0) & (labels == 0)))
    fp_count = int(np.sum((preds == 1) & (labels == 0)))
    fn_count = int(np.sum((preds == 0) & (labels == 1)))

    precision_normal = tp / (tp + fp_count) if (tp + fp_count) else 0.0
    recall_normal = tp / (tp + fn_count) if (tp + fn_count) else 0.0
    f1_normal = 2 * precision_normal * recall_normal / (precision_normal + recall_normal) if (precision_normal + recall_normal) else 0.0

    precision_anom = tn / (tn + fn_count) if (tn + fn_count) else 0.0
    recall_anom = tn / (tn + fp_count) if (tn + fp_count) else 0.0
    f1_anom = 2 * precision_anom * recall_anom / (precision_anom + recall_anom) if (precision_anom + recall_anom) else 0.0

    accuracy = (tp + tn) / len(labels) if len(labels) else 0.0
    macro_f1 = (f1_normal + f1_anom) / 2
    false_alarm_rate = fp_count / (tp + fp_count) if (tp + fp_count) else 0.0  # true-normal rows wrongly flagged
    try:
        roc_auc = float(roc_auc_score(labels, scores)) if len(set(labels.tolist())) > 1 else None
    except ValueError:
        roc_auc = None

    per_event = {}
    event_types = np.array(event_types)
    for et, category in EVENT_TYPE_TO_CATEGORY.items():
        idx = event_types == et
        if not idx.any():
            continue
        # recall of the anomaly for this event type: fraction correctly
        # scored below threshold (label is 0 for every row of these types)
        per_event[category] = float((preds[idx] == 0).mean())

    return {
        "macro_f1": macro_f1,
        "precision_normal": precision_normal,
        "recall_normal": recall_normal,
        "f1_normal": f1_normal,
        "precision_anomalous": precision_anom,
        "recall_anomalous": recall_anom,
        "f1_anomalous": f1_anom,
        "accuracy": accuracy,
        "false_alarm_rate_fpr": false_alarm_rate,
        "roc_auc": roc_auc,
        **per_event,
        "tp": tp, "tn": tn, "fp": fp_count, "fn": fn_count, "n": len(labels),
    }


def measure_latency(pin, n_calls=200):
    scorer = pin.load_relational_scorer()
    x = (0.9, 0.9, 0.9)
    for _ in range(20):  # warm-up
        scorer.score("esp32-vib-001", *x)
    times = []
    for _ in range(n_calls):
        t0 = time.perf_counter()
        scorer.score("esp32-vib-001", *x)
        times.append((time.perf_counter() - t0) * 1000)
    times = np.array(times)
    return {"mean_ms": float(times.mean()), "median_ms": float(np.median(times)),
            "p95_ms": float(np.percentile(times, 95)), "n_calls": n_calls}


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)
    print(f"Scoring {len(records)} held-out test messages through all three pinned arms...")
    rows = score_all_arms(records)
    labels = [row["label"] for row in rows]
    event_types = [row["event_type"] for row in rows]
    print(f"Label balance: {sum(labels)} legitimate, {len(labels) - sum(labels)} suspicious\n")

    meta = {
        "commit": git_commit_hash(),
        "seed": TRAINING_SEED,
        "split": "test_session.json (held-out TEST)",
        "threshold": PROCESS_THRESHOLD,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_scored": len(rows),
        "protocol": "Same rule/IF/LSTM local scores shared across arms; only "
                    "the relational scorer + its matched fusion artifact differ "
                    "per arm. No training in this command.",
        "pins": {name: {
            "relational_checkpoint": pin.relational_checkpoint,
            "relational_checkpoint_sha256": pin.relational_checkpoint_sha256,
            "fusion_model_path": pin.fusion_model_path,
            "fusion_model_sha256": pin.fusion_model_sha256,
        } for name, pin in rp.KNOWN_PINS.items()},
    }

    standalone = {"meta": meta, "results": {}}
    fusion = {"meta": meta, "results": {}}

    print(f"{'Arm':<16} {'Kind':<11} {'MacroF1':>8} {'FPR':>7} {'ROC-AUC':>8} {'NormRec':>8}")
    print("-" * 70)
    for name in rp.KNOWN_PINS:
        rel_scores = [row[f"{name}_relational"] for row in rows]
        fused_scores = [row[f"{name}_fused"] for row in rows]
        rel_m = compute_metrics(rel_scores, labels, event_types)
        fus_m = compute_metrics(fused_scores, labels, event_types)
        standalone["results"][name] = rel_m
        fusion["results"][name] = fus_m
        for kind, m in [("standalone", rel_m), ("fused", fus_m)]:
            print(f"{name:<16} {kind:<11} {m['macro_f1']:>8.4f} {m['false_alarm_rate_fpr']:>7.4f} "
                  f"{(m['roc_auc'] or float('nan')):>8.4f} {m['recall_normal']:>8.4f}")

    print("\nMeasuring standalone relational-scorer inference latency (post-warmup, this environment)...")
    latency = {"meta": meta, "results": {}}
    for name, pin in rp.KNOWN_PINS.items():
        latency["results"][name] = measure_latency(pin)
        print(f"  {name:<16} mean={latency['results'][name]['mean_ms']:.4f}ms "
              f"p95={latency['results'][name]['p95_ms']:.4f}ms")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "standalone_comparison.json"), "w") as f:
        json.dump(standalone, f, indent=2)
    with open(os.path.join(RESULTS_DIR, "fusion_comparison.json"), "w") as f:
        json.dump(fusion, f, indent=2)
    with open(os.path.join(RESULTS_DIR, "latency_comparison.json"), "w") as f:
        json.dump(latency, f, indent=2)
    print(f"\nWrote {RESULTS_DIR}/standalone_comparison.json, fusion_comparison.json, latency_comparison.json")


if __name__ == "__main__":
    main()
