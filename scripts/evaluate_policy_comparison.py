"""
Policy comparison (reviewer concerns N, O, and the rare-class concern).

The adaptive policy was only ever compared against the static 2x2 table. Four
comparators now receive the SAME (s_sec, s_proc) inputs on the SAME untouched
test samples:

    P1  static           the 2x2 threshold table (policy_engine.decide)
    P2  static_optimised thresholds re-selected on VALIDATION, same table shape
    P3  decision_tree    sklearn DecisionTreeClassifier on (s_sec, s_proc)
    P4  multiclass_lr    sklearn LogisticRegression on (s_sec, s_proc)
    P5  adaptive         the trained contextual-bandit Q-table

TERMINOLOGY. P5 is NOT reinforcement learning, despite the RL_* config names.
adaptive_pdp.update() is an incremental sample average, there is no discount
factor, no next-state bootstrapping, and the reward is a fixed function of
(state, action). It is a CONTEXTUAL BANDIT with sample-average action-value
estimation. That is a sound choice here -- the problem has no state transitions
to credit -- but calling it RL overstates it. See docs/REPOSITORY_AUDIT.md 2.6.

Emits full 4x4 confusion matrices (ALLOW / ALERT / STEP_UP / BLOCK) as CSV plus
per-class precision/recall/F1/support, macro-F1, weighted-F1, false-block rate
and false-step-up rate. The rare combined/BLOCK class is reported with its
support and its precision, however poor -- it is not omitted and not merged.
"""

import collections
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, confusion_matrix

from config import (
    DATA_COLLECTED_DIR, SECURITY_THRESHOLD, PROCESS_THRESHOLD, TRAINING_SEED,
    is_feature_vector,
)
import feature_engineering as fe
from trust_engine import RuleBasedTrustEngine, rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from adaptive_pdp import AdaptivePDP, CORRECT_ACTION_FOR_SITUATION
from policy_engine import decide
from generate_training_data import situation_for_event_type

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "policy_comparison")
ACTIONS = ["ALLOW", "ALERT", "STEP_UP", "BLOCK"]

VALIDATION_PATH = os.path.join(DATA_COLLECTED_DIR, "validation_policy_session.json")
TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")


# Deployment bounds for P6, declared before the grid is searched. R_MIN_PROCESS
# is set just below the deployed P1 policy ALERT recall, so the constraint
# encodes "do not become blinder to physical faults than the system already is".
# The false-block bound is the operationally expensive error: it stops data.
R_MIN_PROCESS = 0.90
EPS_FALSE_BLOCK = 0.01


def build_triples(path):
    """Replays a session IN ORDER through the full two-score pipeline, exactly
    as train_adaptive_pdp.py does -- Security Trust is stateful (EWMA + decay
    per device via one shared engine), so record order matters and a shuffled
    replay would produce scores the live gateway never generates.

    Records rejected at Module 2 (auth_ok=False, or event_type 'replay') are
    excluded: they never reach the policy layer live, so scoring a policy on
    them measures something the policy is never asked to do."""
    with open(path) as f:
        records = json.load(f)
    engine = RuleBasedTrustEngine()
    if_s, lstm_s, gnn_s, fusion = (IsolationForestScorer(), LSTMAEScorer(),
                                   GNNScorer(), FusionEngine())
    out = []
    for r in sorted(records, key=lambda x: x["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue
        device_id = r["device_id"]
        rule, _ = rule_range_score(device_id, r["reading"])
        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            iso, lstm = if_s.score(device_id, fv), lstm_s.score(device_id, fv)
        else:
            iso = lstm = rule
        gnn = gnn_s.score(device_id, rule, iso, lstm)
        fused, _, _ = fusion.combine(rule, iso, lstm, gnn)
        sec, _ = engine.score_security_trust(device_id, is_flood=r.get("simulated_flood", False))
        out.append({"s_sec": sec, "s_proc": fused,
                    "situation": situation_for_event_type(r["event_type"]),
                    "correct": CORRECT_ACTION_FOR_SITUATION[situation_for_event_type(r["event_type"])],
                    "device_id": device_id, "event_type": r["event_type"]})
    return out


def static_policy(t, th_sec=SECURITY_THRESHOLD, th_proc=PROCESS_THRESHOLD):
    """The deployed 2x2 table, with the thresholds as parameters so P2 can
    re-select them without a second implementation of the table."""
    sec_high, proc_high = t["s_sec"] >= th_sec, t["s_proc"] >= th_proc
    if sec_high and proc_high:
        return "ALLOW"
    if sec_high and not proc_high:
        return "ALERT"
    if not sec_high and proc_high:
        return "STEP_UP"
    return "BLOCK"


def score_actions(preds, truths):
    labels = ACTIONS
    p, r, f, s = precision_recall_fscore_support(
        truths, preds, labels=labels, zero_division=0)
    cm = confusion_matrix(truths, preds, labels=labels)
    macro = float(np.mean(f))
    weighted = float(np.average(f, weights=s)) if s.sum() else 0.0
    # A false block is a message the policy BLOCKED that should not have been
    # blocked. That is the operationally expensive error -- it stops data.
    false_block = sum(1 for pr, tr in zip(preds, truths) if pr == "BLOCK" and tr != "BLOCK")
    n_non_block = sum(1 for tr in truths if tr != "BLOCK")
    false_stepup = sum(1 for pr, tr in zip(preds, truths) if pr == "STEP_UP" and tr != "STEP_UP")
    n_non_stepup = sum(1 for tr in truths if tr != "STEP_UP")
    return {
        "accuracy": round(float(np.mean([a == b for a, b in zip(preds, truths)])), 4),
        "macro_f1": round(macro, 4),
        "weighted_f1": round(weighted, 4),
        "false_block_rate": round(false_block / max(n_non_block, 1), 4),
        "false_step_up_rate": round(false_stepup / max(n_non_stepup, 1), 4),
        "per_class": {
            a: {"support": int(s[i]), "precision": round(float(p[i]), 4),
                "recall": round(float(r[i]), 4), "f1": round(float(f[i]), 4),
                "tp": int(cm[i, i]),
                "fp": int(cm[:, i].sum() - cm[i, i]),
                "fn": int(cm[i, :].sum() - cm[i, i]),
                "tn": int(cm.sum() - cm[i, :].sum() - cm[:, i].sum() + cm[i, i])}
            for i, a in enumerate(ACTIONS)},
        "confusion_matrix": cm.tolist(),
    }


def write_confusion_csv(name, cm):
    path = os.path.join(RESULTS_DIR, f"confusion_matrix_{name}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["true\\predicted"] + ACTIONS)
        for i, a in enumerate(ACTIONS):
            w.writerow([a] + list(cm[i]))
    return path


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=" * 78)
    print("POLICY COMPARISON -- five policies, identical inputs, untouched test set")
    print("=" * 78)

    val = build_triples(VALIDATION_PATH)
    test = build_triples(TEST_PATH)
    print(f"validation {len(val)} decisions (SIM_SESSION_VAL_002)")
    print(f"test       {len(test)} decisions (SIM_SESSION_TEST_001, read once)\n")

    Xv = np.array([[t["s_sec"], t["s_proc"]] for t in val])
    yv = [t["correct"] for t in val]
    Xt = np.array([[t["s_sec"], t["s_proc"]] for t in test])
    yt = [t["correct"] for t in test]

    results, choices = {}, {}

    # P1 -- deployed static table
    results["P1_static"] = score_actions([static_policy(t) for t in test], yt)

    # P2 -- same table, thresholds re-selected on VALIDATION by macro-F1.
    # Macro-F1 rather than accuracy: the classes are heavily imbalanced and
    # accuracy would be maximised by ignoring the rare ones entirely.
    grid = [round(0.05 * i, 2) for i in range(1, 20)]
    best = max(((a, b) for a in grid for b in grid),
               key=lambda ab: score_actions([static_policy(t, ab[0], ab[1]) for t in val],
                                            yv)["macro_f1"])
    choices["P2_static_optimised"] = {"theta_sec": best[0], "theta_proc": best[1],
                                      "objective": "macro-F1 on validation"}
    results["P2_static_optimised"] = score_actions(
        [static_policy(t, best[0], best[1]) for t in test], yt)

    # P6 -- the SAME grid and the SAME objective as P2, under explicit
    # deployment constraints.
    #
    # P2 exists to show what unconstrained selection does, and what it does is
    # pick theta_proc=0.05, which maximises macro-F1 by declaring nearly every
    # reading physically healthy. That is not a tuning accident: macro-F1 over a
    # class mix dominated by normal and security examples genuinely IS maximised
    # by ignoring the rare physical class. The fix is not a different objective,
    # it is a feasible set.
    #
    # ALERT is the physical-fault action (security ok, process trust low), so
    # recall on ALERT is process-anomaly recall at the policy layer.
    feasible = []
    for a in grid:
        for b in grid:
            m = score_actions([static_policy(t, a, b) for t in val], yv)
            if (m["per_class"]["ALERT"]["recall"] >= R_MIN_PROCESS
                    and m["false_block_rate"] <= EPS_FALSE_BLOCK):
                feasible.append(((a, b), m["macro_f1"]))
    if feasible:
        c_best = max(feasible, key=lambda kv: kv[1])[0]
        results["P6_static_constrained"] = score_actions(
            [static_policy(t, c_best[0], c_best[1]) for t in test], yt)
        choices["P6_static_constrained"] = {
            "theta_sec": c_best[0], "theta_proc": c_best[1],
            "objective": "macro-F1 on validation subject to constraints",
            "constraints": {"min_alert_recall": R_MIN_PROCESS,
                            "max_false_block_rate": EPS_FALSE_BLOCK},
            "feasible_grid_points": len(feasible)}
    else:
        # An empty feasible set is a result, not an error: it says the two
        # scores cannot meet the stated bounds at ANY threshold pair.
        c_best = None
        choices["P6_static_constrained"] = {
            "infeasible": True,
            "constraints": {"min_alert_recall": R_MIN_PROCESS,
                            "max_false_block_rate": EPS_FALSE_BLOCK}}

    # P3 / P4 -- fitted on VALIDATION (never on test), same two inputs.
    tree = DecisionTreeClassifier(max_depth=4, class_weight="balanced",
                                 random_state=TRAINING_SEED).fit(Xv, yv)
    results["P3_decision_tree"] = score_actions(list(tree.predict(Xt)), yt)
    choices["P3_decision_tree"] = {"max_depth": 4, "class_weight": "balanced"}

    lr = LogisticRegression(max_iter=2000, class_weight="balanced").fit(Xv, yv)
    results["P4_multiclass_lr"] = score_actions(list(lr.predict(Xt)), yt)

    # P5 -- the trained contextual bandit, greedy (no exploration at inference).
    pdp = AdaptivePDP()
    results["P5_adaptive_bandit"] = score_actions(
        [pdp.greedy_action(t["s_sec"], t["s_proc"]) for t in test], yt)

    print(f"{'policy':22s} {'acc':>7s} {'macroF1':>8s} {'wtdF1':>7s} "
          f"{'falseBlock':>11s} {'falseStepUp':>12s}")
    print("-" * 78)
    for name in sorted(results):
        m = results[name]
        print(f"{name:22s} {m['accuracy']:>7.4f} {m['macro_f1']:>8.4f} "
              f"{m['weighted_f1']:>7.4f} {m['false_block_rate']:>11.4f} "
              f"{m['false_step_up_rate']:>12.4f}")
        write_confusion_csv(name, m["confusion_matrix"])

    print(f"\nP2 thresholds selected on validation: "
          f"theta_sec={best[0]}, theta_proc={best[1]} "
          f"(deployed: {SECURITY_THRESHOLD}, {PROCESS_THRESHOLD})")

    print()
    if c_best is not None:
        cm6 = results["P6_static_constrained"]
        held = (cm6["per_class"]["ALERT"]["recall"] >= R_MIN_PROCESS
                and cm6["false_block_rate"] <= EPS_FALSE_BLOCK)
        print(f"P6 CONSTRAINED SELECTION: theta_sec={c_best[0]}, "
              f"theta_proc={c_best[1]}, from {len(feasible)} feasible grid points")
        print(f"  constraints: ALERT recall >= {R_MIN_PROCESS}, "
              f"false-block rate <= {EPS_FALSE_BLOCK}")
        print(f"  on TEST: ALERT recall "
              f"{cm6['per_class']['ALERT']['recall']:.4f}, false-block "
              f"{cm6['false_block_rate']:.4f}  -> "
              f"{'constraints held' if held else 'CONSTRAINT BROKE ON TEST'}")
        print(f"  P2 unconstrained, for comparison: ALERT recall "
              f"{results['P2_static_optimised']['per_class']['ALERT']['recall']:.4f} "
              f"at theta_proc={best[1]}")
    else:
        print(f"P6 CONSTRAINED SELECTION: NO FEASIBLE THRESHOLD PAIR at "
              f"ALERT recall >= {R_MIN_PROCESS}, false-block <= {EPS_FALSE_BLOCK}.")
        print("  Reported as the finding: the two scores cannot meet these bounds.")

    # --- Common vs separate thresholds (reviewer concern J) ---
    common = max(grid, key=lambda a: score_actions(
        [static_policy(t, a, a) for t in val], yv)["macro_f1"])
    cfgA = score_actions([static_policy(t, common, common) for t in test], yt)
    cfgB = results["P2_static_optimised"]
    print("\nCOMMON vs SEPARATE THRESHOLDS (concern J), both selected on validation:")
    print(f"  A  theta_sec == theta_proc == {common}: test macro-F1 {cfgA['macro_f1']:.4f}")
    print(f"  B  theta_sec={best[0]}, theta_proc={best[1]}: test macro-F1 {cfgB['macro_f1']:.4f}")
    if abs(cfgA["macro_f1"] - cfgB["macro_f1"]) < 0.01:
        print("  Difference is within 0.01 -- a single common threshold performs "
              "equivalently here. Reported as such; separate thresholds are not "
              "forced to win.")

    # --- The rare class, stated plainly ---
    print("\nRARE COMBINED CLASS (BLOCK) -- reported with its support, not omitted:")
    for name in sorted(results):
        b = results[name]["per_class"]["BLOCK"]
        print(f"  {name:22s} support={b['support']:4d} tp={b['tp']:4d} fp={b['fp']:5d} "
              f"fn={b['fn']:4d} precision={b['precision']:.4f} recall={b['recall']:.4f}")

    out = {"protocol": {"fitted_on": "validation (SIM_SESSION_VAL_002)",
                        "reported_on": "test (SIM_SESSION_TEST_001)",
                        "threshold_objective": "macro-F1 on validation",
                        "terminology": "P5 is a contextual bandit with sample-average "
                                       "action-value estimation, not reinforcement learning"},
           "validation_choices": choices,
           "threshold_configurations": {
               "A_common": {"theta": common, "test_macro_f1": cfgA["macro_f1"]},
               "B_separate": {"theta_sec": best[0], "theta_proc": best[1],
                              "test_macro_f1": cfgB["macro_f1"]}},
           "results": results}
    with open(os.path.join(RESULTS_DIR, "metrics.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwritten to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
