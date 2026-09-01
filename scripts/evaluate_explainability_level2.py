"""
Module 3 Section C.4's Level-2 explanation VALIDATION procedure
(docs/04_module3_trust_evaluation.md), directly reusing [21]'s method:
for a sample of flagged (suspicious, physically-anomalous) held-out
messages, take `level2_dominant_feature`, deliberately perturb exactly
that feature (replace it with a normal-range value), re-run the full
Process Anomaly Engine, and check whether `process_anomaly_score`
actually flips back to "legitimate" (>= 0.5). Record the percentage of
tests where it does -- target at least 70%, matching the range [21]
reports for an analogous test.

DIRECTION NOTE (AS-BUILT, not a bug): Section C.4's literal wording says
"check whether process_anomaly_score actually drops below the alerting
threshold" -- written for the design doc's anomaly-style scale (high =
anomalous). This project keeps the Process Anomaly Score TRUST-style
(high = normal, see docs/00_overview.md deviation #1) -- under that
scale, replacing an anomaly-causing feature with a normal value should
make the score RISE back above the threshold, not drop below it. This
script checks the AS-BUILT-correct direction (recovers to >= 0.5), which
is the same validation with the sign flipped for the scale this project
actually uses.

Run AFTER all scripts/train_*.py have been run.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import DATA_COLLECTED_DIR, is_feature_vector
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
import explainability
from generate_training_data import physical_label

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")
TRAIN_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
THRESHOLD = 0.5


def _training_medians():
    """Per-feature training-set median over esp32-vib-001's NORMAL
    readings -- the "normal-range value" Section C.4 asks the perturbation
    to substitute in, for the Isolation Forest branch specifically (the
    only scorer here that's stateless enough for the CALLER to build the
    counterfactual vector itself -- see isolation_forest_scorer.py's
    level2_explain() docstring for why)."""
    with open(TRAIN_PATH) as f:
        records = json.load(f)
    normal = [r for r in records if r["device_id"] == "esp32-vib-001" and r["label"] == 1 and r["auth_ok"]]
    vecs = np.array([fe.feature_vector(r["reading"]) for r in normal])
    return {name: float(np.median(vecs[:, i])) for i, name in enumerate(fe.FEATURE_NAMES)}


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)

    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()
    fusion = FusionEngine()
    if not fusion.is_trained():
        raise SystemExit("Fusion model not trained -- run scripts/train_fusion_meta_learner.py first.")

    medians = _training_medians()

    checked = 0
    flipped = 0
    by_signal = {}  # dominant_signal -> [checked, flipped]
    examples = []

    for r in sorted(records, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue
        device_id = r["device_id"]
        rule_score, rule_reason = rule_range_score(device_id, r["reading"])

        fv = None
        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        fused_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)

        # Only validate messages the pipeline actually flagged (fused_score
        # below the threshold) AND that are genuinely physically anomalous
        # (not high_rate/stealthy_forged_values -- there's no "normal
        # value" substitution that makes sense for a scenario whose
        # features already look normal by construction).
        if fused_score >= THRESHOLD or physical_label(r["event_type"]) == 1:
            continue

        dominant = explainability.dominant_signal_name(fusion.last_shap)
        if dominant is None:
            continue

        cf_rule, cf_if, cf_lstm, cf_gnn = rule_score, if_score, lstm_score, gnn_score
        if dominant == "rule_score":
            cf_rule = 0.9  # trivial per C.3 -- "fixing" the violated channel means the rule check passes outright
        elif dominant == "isolation_forest_score" and fv is not None:
            result = if_scorer.level2_explain(device_id, fv)
            if result is None:
                continue
            name, _shap_val = result
            perturbed = list(fv)
            perturbed[fe.FEATURE_NAMES.index(name)] = medians[name]
            cf_if = if_scorer.score(device_id, perturbed)
        elif dominant == "lstm_ae_score":
            result = lstm_scorer.level2_explain(device_id)
            if result is None:
                continue
            _name, _drop, cf_lstm = result
        elif dominant == "gnn_score":
            result = gnn_scorer.level2_explain(device_id)
            if result is None:
                continue
            _name, _change, cf_gnn = result
        else:
            continue

        cf_fused, _, _ = fusion.combine(cf_rule, cf_if, cf_lstm, cf_gnn)

        checked += 1
        did_flip = cf_fused >= THRESHOLD
        flipped += int(did_flip)
        bucket = by_signal.setdefault(dominant, [0, 0])
        bucket[0] += 1
        bucket[1] += int(did_flip)
        if len(examples) < 10:
            examples.append((r["event_type"], dominant, fused_score, cf_fused, did_flip))

    print(f"Checked {checked} flagged, physically-anomalous held-out messages with a resolvable Level-2 feature.\n")
    print(f"{'Event type':<22} {'Dominant signal':<24} {'Before':>8} {'After':>8} {'Flipped?'}")
    print("-" * 75)
    for event_type, dominant, before, after, did_flip in examples:
        print(f"{event_type:<22} {dominant:<24} {before:>8.3f} {after:>8.3f} {'YES' if did_flip else 'no'}")

    print("\nPer-signal breakdown:")
    for name, (n, k) in sorted(by_signal.items()):
        print(f"  {name:<24} {k}/{n} ({k/n:.0%}) flipped back to legitimate after perturbation")

    if checked:
        pct = flipped / checked
        print(
            f"\nOverall: {flipped}/{checked} ({pct:.0%}) of Level-2 perturbation tests flipped "
            f"process_anomaly_score back to >= {THRESHOLD} (the AS-BUILT-correct direction for this "
            f"project's trust-style scale -- see this script's module docstring). "
            f"Target (Section C.4, [21]'s method): >= 70%. "
            f"{'MEETS' if pct >= 0.70 else 'DOES NOT YET MEET'} the target."
        )
    else:
        print("\nNo flagged messages with a resolvable Level-2 feature were found in the test set.")


if __name__ == "__main__":
    main()
