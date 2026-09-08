"""
Verifies the "isolation_forest_score is a constant term for SW-420" claim
against evaluate_real_hardware.py's own output: iso == 0.500 and rule ==
0.900 for every one of the 223 TEST / 179 VALIDATION real esp32-vib-002
windows (results/sw420_real_hardware/window_scores_{split}.json, produced by
`evaluate_real_hardware.py --device esp32-vib-002`'s SW-420-path dump).

Question this answers: does the Isolation Forest signal carry any real,
window-specific discriminative information for SW-420, or is its
contribution to the fused score just a constant offset the intercept could
absorb just as well? Answered three ways, not just algebraically asserted:

1. EXACT re-derivation: since iso is bit-identical across every window in
   the dump, algebraically iso_coef*iso is a constant, so
   new_intercept = old_intercept + iso_coef*iso must reproduce the
   ORIGINAL fused score exactly (same sigmoid input) once iso is dropped
   from the linear combination. This is a sanity check on the dump, not
   the interesting claim.
2. IN-SAMPLE refit: a fresh intercept is fit (1-D Newton-Raphson on the
   real logistic loss), holding the rule/lstm/gnn coefficients FROZEN at
   their trained values, against THIS SAME SPLIT's phase-derived ground
   truth (at_rest = normal, everything else = physical disturbance -- the
   same target evaluate_real_hardware.py's own FP/detection-rate numbers
   use). This is fit and evaluated on the same data, so on its own it only
   shows an intercept EXISTS that reproduces every decision here -- not
   that it would generalize. The dumped `label` field is a SECURITY-trust
   label, constant 1 throughout because no attack was performed in these
   sessions, so it carries no information for this check and is
   deliberately not used as the target.
3. CROSS-SPLIT refit: the same fit, but the intercept is fit on the OTHER
   split's ground truth and then applied, unmodified, to THIS split's
   decisions -- test-fit-on-validation and validation-fit-on-test. This is
   the check that actually speaks to generalization: if it also reproduces
   every decision, the constant an intercept would settle on isn't an
   artifact of fitting and grading on the same rows.

All three are compared, window by window, against the ORIGINAL flagged
decision (fused < PROCESS_THRESHOLD). This is a verification of the
constant-term argument, not a new training run: the fusion meta-learner
itself is never re-fit, only its scalar intercept, and only against data it
was never fit on in the first place.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import joblib
import numpy as np

from config import FUSION_MODEL_PATH_GCN_BACKUP, PROCESS_THRESHOLD

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "sw420_real_hardware")
NORMAL_PHASES = {"at_rest"}  # matches evaluate_real_hardware.py's own definition


def refit_intercept(offset: np.ndarray, y: np.ndarray, n_iter: int = 100) -> float:
    """1-D Newton-Raphson: minimizes logistic loss over intercept b alone,
    holding `offset` (the other three signals' fixed linear combination,
    coefficients frozen) constant per row. Convex and 1-dimensional, so
    this converges in a handful of iterations."""
    b = 0.0
    for _ in range(n_iter):
        p = 1.0 / (1.0 + np.exp(-(offset + b)))
        grad = np.sum(p - y)
        hess = np.sum(p * (1 - p)) + 1e-12
        step = grad / hess
        b -= step
        if abs(step) < 1e-12:
            break
    return float(b)


def load_split(split: str) -> dict:
    dump_path = os.path.join(RESULTS_DIR, f"window_scores_{split}.json")
    if not os.path.exists(dump_path):
        raise SystemExit(
            f"{dump_path} not found -- run:\n"
            f"    python evaluate_real_hardware.py --device esp32-vib-002 --split {split}\n"
            "first (it writes this dump on the SW-420 path).")
    with open(dump_path) as f:
        rows = json.load(f)
    rule = np.array([r["rule"] for r in rows])
    iso = np.array([r["iso"] for r in rows])
    lstm = np.array([r["lstm"] for r in rows])
    gnn = np.array([r["gnn"] for r in rows])
    fused = np.array([r["fused"] for r in rows])
    phase = [r["phase"] for r in rows]
    y = np.array([1.0 if p in NORMAL_PHASES else 0.0 for p in phase])
    return {"path": dump_path, "n": len(rows), "rule": rule, "iso": iso, "lstm": lstm,
            "gnn": gnn, "fused": fused, "phase": phase, "y": y}


OTHER_SPLIT = {"test": "validation", "validation": "test"}


def main():
    split = sys.argv[sys.argv.index("--split") + 1] if "--split" in sys.argv else "test"
    other_split = OTHER_SPLIT[split]
    data = load_split(split)
    other = load_split(other_split)
    rule, iso, lstm, gnn, fused, y = data["rule"], data["iso"], data["lstm"], data["gnn"], data["fused"], data["y"]

    model = joblib.load(FUSION_MODEL_PATH_GCN_BACKUP)
    coef_rule, coef_iso, coef_lstm, coef_gnn = (float(c) for c in model.coef_[0])
    intercept = float(model.intercept_[0])

    print(f"{data['n']} windows loaded from {data['path']}")
    print(f"iso values observed:  {sorted(set(iso.tolist()))}")
    print(f"rule values observed: {sorted(set(rule.tolist()))}")
    if len(set(iso.tolist())) != 1:
        print("NOTE: iso is not constant on this split -- the exact re-derivation below no longer applies verbatim.")

    # Sanity: the dumped `fused` reproduces the model's own predict_proba
    # exactly -- this script's re-derivation starts from the real artifact
    # and the real dump, not from a guess at either.
    features = np.stack([rule, iso, lstm, gnn], axis=1)
    reproduced = model.predict_proba(features)[:, 1]
    assert np.allclose(reproduced, fused, atol=1e-9), "coefficient read-back does not match the dumped fused score"

    old_logit = coef_rule * rule + coef_iso * iso + coef_lstm * lstm + coef_gnn * gnn + intercept
    old_flagged = fused < PROCESS_THRESHOLD

    offset_no_iso = coef_rule * rule + coef_lstm * lstm + coef_gnn * gnn  # IF term dropped

    # (1) exact algebraic re-derivation
    exact_intercept = intercept + coef_iso * float(iso[0])
    exact_logit = offset_no_iso + exact_intercept
    exact_trust = 1.0 / (1.0 + np.exp(-exact_logit))
    exact_flagged = exact_trust < PROCESS_THRESHOLD
    exact_mismatches = int(np.sum(exact_flagged != old_flagged))
    print(f"\n[1] exact re-derivation: new intercept = {exact_intercept:.6f} "
          f"(old {intercept:.6f} + iso_coef*iso {coef_iso * float(iso[0]):.6f})")
    print(f"    max |logit diff| vs original = {np.max(np.abs(exact_logit - old_logit)):.2e}")
    print(f"    flagged mismatches vs original: {exact_mismatches}/{data['n']}")

    # (2) in-sample refit against THIS split's own phase-derived ground truth
    refit_b = refit_intercept(offset_no_iso, y)
    refit_logit = offset_no_iso + refit_b
    refit_trust = 1.0 / (1.0 + np.exp(-refit_logit))
    refit_flagged = refit_trust < PROCESS_THRESHOLD
    refit_mismatches = int(np.sum(refit_flagged != old_flagged))
    print(f"\n[2] in-sample refit: intercept = {refit_b:.6f} "
          f"(fit AND graded on {split}'s own ground truth, rule/lstm/gnn coefficients frozen)")
    print(f"    flagged mismatches vs original: {refit_mismatches}/{data['n']}")

    # (3) cross-split refit: fit on the OTHER split's ground truth, applied
    # unchanged to THIS split -- the check that actually speaks to whether
    # the constant an intercept settles on generalizes, since it is never
    # fit on the rows it is graded against.
    other_offset_no_iso = coef_rule * other["rule"] + coef_lstm * other["lstm"] + coef_gnn * other["gnn"]
    cross_b = refit_intercept(other_offset_no_iso, other["y"])
    cross_logit = offset_no_iso + cross_b
    cross_trust = 1.0 / (1.0 + np.exp(-cross_logit))
    cross_flagged = cross_trust < PROCESS_THRESHOLD
    cross_mismatches = int(np.sum(cross_flagged != old_flagged))
    print(f"\n[3] cross-split refit: intercept = {cross_b:.6f} "
          f"(fit on {other_split}'s ground truth only, applied unmodified to {split})")
    print(f"    flagged mismatches vs original: {cross_mismatches}/{data['n']}")

    verdict = ("CONFIRMED" if exact_mismatches == 0 and refit_mismatches == 0 and cross_mismatches == 0
               else "NOT CONFIRMED")
    print(f"\n{verdict}: dropping isolation_forest_score and refitting only the "
          f"fusion intercept {'reproduces' if verdict == 'CONFIRMED' else 'does NOT reproduce'} "
          f"every window's flagged/not-flagged outcome on the {split} split, including under a "
          f"{other_split}-fit intercept the {split} rows never informed.")

    out = {
        "split": split,
        "other_split": other_split,
        "n": data["n"],
        "iso_values_observed": sorted(set(iso.tolist())),
        "rule_values_observed": sorted(set(rule.tolist())),
        "fusion_model": FUSION_MODEL_PATH_GCN_BACKUP,
        "original_coefficients": {
            "rule": coef_rule, "isolation_forest": coef_iso, "lstm": coef_lstm, "gnn": coef_gnn,
            "intercept": intercept,
        },
        "exact_rederivation": {"new_intercept": exact_intercept, "flagged_mismatches": exact_mismatches},
        "in_sample_refit": {"new_intercept": refit_b, "flagged_mismatches": refit_mismatches},
        "cross_split_refit": {
            "fit_on": other_split, "new_intercept": cross_b, "flagged_mismatches": cross_mismatches,
        },
        "verdict": verdict,
    }
    out_path = os.path.join(RESULTS_DIR, f"if_ablation_check_{split}.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
