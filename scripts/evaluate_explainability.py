"""
Synopsis Section 10.1: "Explainability quality: qualitative and
quantitative review of SHAP reason codes against ground-truth attack
labels -- do the top-ranked features actually correspond to the injected
anomaly?" Also Section 10.2's "SHAP-generated reason codes for a sample of
access decisions, demonstrating the explainability layer functions as
governance evidence, not just a technical add-on."

Replays data/collected/test_session.json through the trained fusion
engine, and for each SUSPICIOUS (label=0) message, checks whether the
SHAP-identified top contributing feature matches what actually caused
that specific event_type -- a quantitative "does the explanation make
physical sense" check, not just eyeballing example strings.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")

# Which SHAP top-feature is "physically sensible" for each injected event
# type -- the ground truth this script checks against. A forged signature
# means auth_ok=False, so if_score/lstm_score get the AUTH_FAIL_SENTINEL
# (0.1) -- rule_score is often still fine (the attacker's claimed value can
# be plausible), so isolation_forest_score/lstm_ae_score are the sensible
# top-feature candidates for that case, not rule_score.
EXPECTED_TOP_FEATURE = {
    "anomalous_shock": {"isolation_forest_score", "lstm_ae_score", "gnn_score"},
    "out_of_range": {"rule_score"},
    "forged_signature": {"isolation_forest_score", "lstm_ae_score", "gnn_score"},
    "replay": {"rule_score", "isolation_forest_score", "lstm_ae_score", "gnn_score"},  # replay bypasses fusion entirely in the live gateway; included for completeness
    # Individually in-range on every device (rule_score stays high on
    # purpose -- see device_simulator.py's module docstring), so rule_score
    # is deliberately EXCLUDED here: a sensible explanation has to come from
    # one of the ML scorers, ideally gnn_score specifically since it's the
    # only one that can see the cross-device co-occurrence at all.
    "coordinated": {"gnn_score", "isolation_forest_score", "lstm_ae_score"},
}


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)

    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()
    fusion = FusionEngine()

    if not fusion.is_trained():
        raise SystemExit("Fusion model not trained -- run scripts/train_fusion_meta_learner.py first.")

    checked = 0
    matched = 0
    examples = []

    for r in sorted(records, key=lambda r: r["tick"]):
        if r["label"] != 0 or r["event_type"] not in EXPECTED_TOP_FEATURE:
            continue

        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])

        if not r["auth_ok"]:
            if_score = lstm_score = 0.1
        elif device_id == "esp32-vib-001":
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        _, _, reason = fusion.combine(rule_score, if_score, lstm_score, gnn_score)

        # reason looks like "fusion: isolation_forest_score=0.10 most lowered trust (SHAP=-5.30)"
        top_feature = reason.split("fusion: ")[-1].split("=")[0] if reason.startswith("fusion: ") else None

        checked += 1
        is_match = top_feature in EXPECTED_TOP_FEATURE[r["event_type"]]
        matched += int(is_match)
        if len(examples) < 8:
            examples.append((r["event_type"], top_feature, is_match, reason))

    print(f"Checked {checked} suspicious (label=0) held-out messages with a trained-fusion SHAP reason.\n")
    print(f"{'Event type':<20} {'SHAP top feature':<26} {'Sensible?'}")
    print("-" * 60)
    for event_type, top_feature, is_match, _ in examples:
        print(f"{event_type:<20} {str(top_feature):<26} {'YES' if is_match else 'no'}")

    if checked:
        print(f"\nOverall: {matched}/{checked} ({matched/checked:.0%}) of SHAP top-feature "
              f"attributions matched the physically-sensible feature set for their injected "
              f"anomaly type -- this is the quantitative explainability-quality figure for "
              f"synopsis Section 10.1/10.2.")
    else:
        print("\nNo suspicious messages with a resolvable SHAP reason were found in the test set.")


if __name__ == "__main__":
    main()
