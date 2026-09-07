"""Corrected-M6 policy evaluation (objective PART 5/6/7 of the 2026-09-07
final-corrected-M6-deployment pass).

Evaluates the two NEW policy artifacts trained by
scripts/train_adaptive_pdp.py under this pass's explicit-pin + deterministic-
clock fix (see that script's module docstring):

    models/adaptive_pdp_qtable_m6_corrected.json  -- corrected M6 + matched
                                                       corrected-M6 fusion
    models/adaptive_pdp_qtable_gcn_corrected.json -- true GCN + matched GCN
                                                       fusion (a FAIR, clean-
                                                       provenance baseline;
                                                       see Part 7 -- this is
                                                       NOT the same table as
                                                       the historical
                                                       models/adaptive_pdp_qtable.json,
                                                       whose provenance
                                                       results/gcn_m6_corrected_comparison/
                                                       summary.md found
                                                       corrupted)

Reuses evaluate_policy_comparison.py's build_triples() (with
deterministic_clock=True and an explicit pin) and score_actions() so the
scoring definition is identical to every other policy number this project
reports -- no second implementation to drift.

Before scoring either policy, relational_pin.verify_policy_lineage() checks
the Q-table's own metadata sidecar agrees with the pin used to build its
evaluation triples -- this is the Part 3 mismatch check, enforced at
evaluation time too, not just documented.

Writes results/m6_corrected_policy/{policy_metrics.json,
policy_action_metrics.json, artifact_lineage.json,
policy_training_config.json, summary.md} plus per-policy confusion CSVs.
Does not modify results/policy_comparison/ or
results/gcn_m6_corrected_comparison/ (historical evidence, untouched).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from config import DATA_COLLECTED_DIR
import relational_pin as rp
from adaptive_pdp import AdaptivePDP
from evaluate_policy_comparison import build_triples, score_actions, ACTIONS

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "m6_corrected_policy")


def write_confusion_csv(name: str, cm) -> str:
    """Local variant of evaluate_policy_comparison.write_confusion_csv that
    writes into THIS script's own results/m6_corrected_policy/ directory
    instead of results/policy_comparison/ -- keeps this pass's new evidence
    out of the historical comparator's results directory."""
    import csv
    path = os.path.join(RESULTS_DIR, f"confusion_matrix_{name}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["true\\predicted"] + ACTIONS)
        for i, a in enumerate(ACTIONS):
            w.writerow([a] + list(cm[i]))
    return path
VALIDATION_PATH = os.path.join(DATA_COLLECTED_DIR, "validation_policy_session.json")
TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")

ARMS = {
    "m6_corrected": {
        "pin": rp.M6_CORRECTED,
        "qtable_path": os.path.join(os.path.dirname(__file__), "..", "models", "adaptive_pdp_qtable_m6_corrected.json"),
    },
    "gcn_corrected": {
        "pin": rp.GCN,
        "qtable_path": os.path.join(os.path.dirname(__file__), "..", "models", "adaptive_pdp_qtable_gcn_corrected.json"),
    },
}


def evaluate_arm(name: str, pin: rp.RelationalPin, qtable_path: str):
    print(f"\n{'=' * 78}\nARM: {name}  (pin={pin.name}, qtable={qtable_path})\n{'=' * 78}")

    # Part 3 mismatch check: the Q-table's own recorded lineage must agree
    # with the pin we are about to score it against.
    meta = rp.verify_policy_lineage(pin, qtable_path)
    print(f"lineage verified: pin={meta['pin_name']} seed={meta['seed']} "
          f"clock_protocol={meta['clock_protocol']}")

    test = build_triples(TEST_PATH, pin=pin, deterministic_clock=True)
    print(f"test set: {len(test)} decisions (SIM_SESSION_TEST_001, deterministic clock)")

    pdp = AdaptivePDP(path=qtable_path)
    if not pdp.is_trained():
        raise SystemExit(f"{qtable_path} not found -- run scripts/train_adaptive_pdp.py first "
                          f"(ZTCPS_ADAPTIVE_PDP_PIN={pin.name}, ZTCPS_ADAPTIVE_PDP_OUTPUT={qtable_path})")

    preds = [pdp.greedy_action(t["s_sec"], t["s_proc"]) for t in test]
    truths = [t["correct"] for t in test]
    metrics = score_actions(preds, truths)
    write_confusion_csv(f"m6_corrected_policy_{name}", metrics["confusion_matrix"])
    return metrics, meta, len(test)


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    results = {}
    metas = {}
    for name, cfg in ARMS.items():
        metrics, meta, n = evaluate_arm(name, cfg["pin"], cfg["qtable_path"])
        results[name] = metrics
        metas[name] = meta

    print(f"\n{'=' * 78}\nSUMMARY -- corrected M6 policy vs. fair GCN policy baseline, "
          f"same test protocol, deterministic clock\n{'=' * 78}")
    print(f"{'arm':16s} {'acc':>7s} {'macroF1':>8s} {'wtdF1':>7s} "
          f"{'falseBlock':>11s} {'falseStepUp':>12s}")
    for name, m in results.items():
        print(f"{name:16s} {m['accuracy']:>7.4f} {m['macro_f1']:>8.4f} "
              f"{m['weighted_f1']:>7.4f} {m['false_block_rate']:>11.4f} "
              f"{m['false_step_up_rate']:>12.4f}")

    print("\nPER-ACTION (ALLOW / ALERT / STEP_UP / BLOCK) -- both arms:")
    for name, m in results.items():
        print(f"\n  {name}:")
        for a in ACTIONS:
            b = m["per_class"][a]
            print(f"    {a:8s} support={b['support']:4d} precision={b['precision']:.4f} "
                  f"recall={b['recall']:.4f} f1={b['f1']:.4f} "
                  f"tp={b['tp']:4d} fp={b['fp']:4d} fn={b['fn']:4d}")

    # --- policy_metrics.json / policy_action_metrics.json -------------------
    with open(os.path.join(RESULTS_DIR, "policy_metrics.json"), "w") as f:
        json.dump({
            "protocol": {
                "fitted_on": "validation (SIM_SESSION_VAL_002)",
                "reported_on": "test (SIM_SESSION_TEST_001)",
                "clock": "deterministic, per-record ts/1000.0 -- see relational_pin/train_adaptive_pdp.py",
                "terminology": "both arms are contextual bandits with sample-average "
                               "action-value estimation, not reinforcement learning",
            },
            "results": {name: {k: v for k, v in m.items() if k != "per_class"} for name, m in results.items()},
        }, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "policy_action_metrics.json"), "w") as f:
        json.dump({name: m["per_class"] for name, m in results.items()}, f, indent=2)

    # --- artifact_lineage.json -----------------------------------------------
    with open(os.path.join(RESULTS_DIR, "artifact_lineage.json"), "w") as f:
        json.dump({name: metas[name] for name in ARMS}, f, indent=2)

    # --- policy_training_config.json ------------------------------------------
    with open(os.path.join(RESULTS_DIR, "policy_training_config.json"), "w") as f:
        json.dump({name: metas[name].get("training_config", {}) | {
            "seed": metas[name].get("seed"),
            "clock_protocol": metas[name].get("clock_protocol"),
            "commit_hash": metas[name].get("commit_hash"),
        } for name in ARMS}, f, indent=2)

    # --- summary.md ------------------------------------------------------------
    m6 = results["m6_corrected"]
    gcn = results["gcn_corrected"]
    hist = 0.5271  # results/gcn_m6_corrected_comparison/policy_comparison.json, historical_preserved_2026_09_04, P5
    corrupted = 0.5132  # same file, gcn_pin_repaired_rerun P5 (corrupted-provenance Q-table)
    lines = [
        "# Corrected-M6 policy evaluation -- summary",
        "",
        f"**Date:** 2026-09-07. **Protocol:** deterministic clock (per-record `ts`), "
        f"same `build_triples`/`score_actions` implementation as "
        f"`results/policy_comparison/` and `results/gcn_m6_corrected_comparison/`. "
        f"Both Q-tables trained fresh via the pinned, deterministic "
        f"`scripts/train_adaptive_pdp.py` -- see `artifact_lineage.json`.",
        "",
        "## Result",
        "",
        "| Policy | Macro-F1 | Weighted-F1 | Accuracy | False-block rate | False-step-up rate |",
        "|---|---|---|---|---|---|",
        f"| GCN + matched GCN fusion (clean, deterministic) | {gcn['macro_f1']:.4f} | "
        f"{gcn['weighted_f1']:.4f} | {gcn['accuracy']:.4f} | {gcn['false_block_rate']:.4f} | "
        f"{gcn['false_step_up_rate']:.4f} |",
        f"| Corrected M6 + matched corrected-M6 fusion | {m6['macro_f1']:.4f} | "
        f"{m6['weighted_f1']:.4f} | {m6['accuracy']:.4f} | {m6['false_block_rate']:.4f} | "
        f"{m6['false_step_up_rate']:.4f} |",
        "",
        "For context, NOT re-measured here (historical, preserved, wall-clock-jitter "
        "protocol, reported for continuity only):",
        f"- deployed (corrupted-provenance) Q-table, GCN-pinned rerun: P5={corrupted:.4f} "
        f"(`results/gcn_m6_corrected_comparison/policy_comparison.json`)",
        f"- deployed (corrupted-provenance) Q-table, originally reported: P5={hist:.4f} "
        f"(`results/policy_comparison/metrics.json`, now flagged unreproducible)",
        "",
        "## Per-action detail",
        "",
    ]
    for name, m in results.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| Action | Support | Precision | Recall | F1 | TP | FP | FN |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for a in ACTIONS:
            b = m["per_class"][a]
            lines.append(f"| {a} | {b['support']} | {b['precision']:.4f} | {b['recall']:.4f} | "
                         f"{b['f1']:.4f} | {b['tp']} | {b['fp']} | {b['fn']} |")
        lines.append("")
    lines += [
        "## Notes",
        "",
        "- BLOCK recall is reported as measured, not hidden or substituted, whatever its value.",
        "- Neither Q-table is the historically deployed `models/adaptive_pdp_qtable.json` -- "
        "that file is untouched by this pass (see PART 11: do not overwrite historical artifacts).",
        "- This IS a valid GCN-vs-M6 policy comparison (Part 7): both arms share the same "
        "deterministic-clock protocol and were trained the same way, differing only in "
        "which relational/fusion pin they were trained and evaluated against.",
    ]
    with open(os.path.join(RESULTS_DIR, "summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nwritten to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
