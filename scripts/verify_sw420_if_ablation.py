"""
Verifies the "isolation_forest_score is a constant term for SW-420" claim
against evaluate_real_hardware.py's own output: iso == 0.500 and rule ==
0.900 for every one of the 223 TEST / 179 VALIDATION real esp32-vib-002
windows (results/sw420_real_hardware/window_scores_{split}_{pin}.json,
produced by `evaluate_real_hardware.py --device esp32-vib-002
--relational-model {pin}`'s SW-420-path dump).

--pin selects which fusion artifact's coefficients this check verifies
against (default "gcn", matching evaluate_real_hardware.py's own default).
The dropped-IF/refit-intercept result is a property of a SPECIFIC fitted
fusion model's coefficients, not of the fusion architecture in the
abstract -- iso/rule being constant transfers across pins (they don't
depend on which relational scorer or fusion artifact is loaded), but
"an intercept exists that reproduces every decision" must be re-checked
per pin, since each pin's coefficients (and its relational/gnn score,
which differs between GCN and the M6 SetTransformer) differ. Passing
--pin m6_corrected checks it against the CURRENTLY DEPLOYED fusion
artifact rather than the historical GCN one.

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
2. IN-SAMPLE feasibility: does ANY intercept exist (rule/lstm/gnn
   coefficients frozen) that reproduces THIS split's original
   flagged/not-flagged decisions exactly? Answered by direct interval
   construction, not by fitting a logistic regression: threshold t means
   "flagged" iff logit < logit(t), so each flagged row requires
   b < logit(t) - offset_i and each non-flagged row requires
   b >= logit(t) - offset_i; intersecting those per-row constraints gives
   an exact feasible range [b_lo, b_hi) for b (see feasible_interval()).
   Deliberately NOT a maximum-likelihood refit: an earlier version of this
   script fit b by 1-D Newton-Raphson on the logistic loss, which is the
   wrong tool here -- these classes turn out to be perfectly (or
   near-perfectly) separable by the frozen coefficients alone once IF is
   dropped, and unregularized logistic MLE has NO FINITE OPTIMUM under
   perfect separation (the likelihood keeps improving as b -> -inf).
   Newton-Raphson duly ran off to +/-1e13 and overflowed, producing a
   nonsense intercept and a false "does not reproduce" verdict on the
   m6_corrected pin -- a bug in the verification method, not a real
   finding about that fusion model. The interval construction above has
   no such failure mode: it asks only "does a intercept exist", not "what
   does maximum-likelihood say", so it always returns a finite, exact
   answer.
3. CROSS-SPLIT feasibility: same construction, but the representative
   intercept is the midpoint of the OTHER split's OWN feasible interval
   (computed from the other split's original decisions only) and is then
   applied, unmodified, to THIS split. This is the check that actually
   speaks to generalization: it never looks at the split it is graded
   against.

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

from config import PROCESS_THRESHOLD
import relational_pin as rp

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "sw420_real_hardware")
NORMAL_PHASES = {"at_rest"}  # matches evaluate_real_hardware.py's own definition
LOGIT_THRESHOLD = float(np.log(PROCESS_THRESHOLD / (1 - PROCESS_THRESHOLD)))  # trust<t  <=>  logit<this


def feasible_interval(offset: np.ndarray, flagged: np.ndarray) -> tuple[float, float]:
    """Exact half-open range [b_lo, b_hi) of intercepts b for which
    `offset + b < LOGIT_THRESHOLD` reproduces `flagged` on every row.
    Non-empty (b_lo < b_hi) iff `offset` alone already separates the two
    classes with a big enough gap for a threshold to fit in between --
    which is exactly "is there an intercept that works", asked directly
    instead of via a maximum-likelihood fit that can diverge (see module
    docstring, point 2)."""
    b_hi = LOGIT_THRESHOLD - offset[flagged].max() if flagged.any() else np.inf
    b_lo = LOGIT_THRESHOLD - offset[~flagged].min() if (~flagged).any() else -np.inf
    return float(b_lo), float(b_hi)


def representative_intercept(b_lo: float, b_hi: float) -> float:
    """A concrete point inside [b_lo, b_hi), for actually recomputing
    decisions with (rather than reasoning about the interval abstractly).
    Midpoint when bounded on both sides -- both bounds are finite in every
    split used here, since each split contains both flagged and
    non-flagged windows."""
    if np.isinf(b_lo) and np.isinf(b_hi):
        return 0.0
    if np.isinf(b_lo):
        return b_hi - 1.0
    if np.isinf(b_hi):
        return b_lo + 1.0
    return (b_lo + b_hi) / 2.0


def load_split(split: str, pin_name: str) -> dict:
    dump_path = os.path.join(RESULTS_DIR, f"window_scores_{split}_{pin_name}.json")
    if not os.path.exists(dump_path):
        raise SystemExit(
            f"{dump_path} not found -- run:\n"
            f"    python evaluate_real_hardware.py --device esp32-vib-002 --split {split} "
            f"--relational-model {pin_name}\n"
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
    pin_name = sys.argv[sys.argv.index("--pin") + 1] if "--pin" in sys.argv else "gcn"
    pin = rp.KNOWN_PINS[pin_name]  # raises KeyError loudly on an unknown name
    other_split = OTHER_SPLIT[split]
    data = load_split(split, pin_name)
    other = load_split(other_split, pin_name)
    rule, iso, lstm, gnn, fused = data["rule"], data["iso"], data["lstm"], data["gnn"], data["fused"]

    model = joblib.load(pin.fusion_model_path)
    coef_rule, coef_iso, coef_lstm, coef_gnn = (float(c) for c in model.coef_[0])
    intercept = float(model.intercept_[0])

    print(f"pin = {pin_name}   (fusion artifact {pin.fusion_model_path})")
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
    assert np.array_equal(old_logit < LOGIT_THRESHOLD, old_flagged), "logit-threshold reconstruction disagrees with fused-threshold decision"

    offset_no_iso = coef_rule * rule + coef_lstm * lstm + coef_gnn * gnn  # IF term dropped

    # (1) exact algebraic re-derivation
    exact_intercept = intercept + coef_iso * float(iso[0])
    exact_flagged = (offset_no_iso + exact_intercept) < LOGIT_THRESHOLD
    exact_mismatches = int(np.sum(exact_flagged != old_flagged))
    print(f"\n[1] exact re-derivation: new intercept = {exact_intercept:.6f} "
          f"(old {intercept:.6f} + iso_coef*iso {coef_iso * float(iso[0]):.6f})")
    print(f"    flagged mismatches vs original: {exact_mismatches}/{data['n']}")

    # (2) in-sample feasibility on THIS split's own original decisions
    b_lo, b_hi = feasible_interval(offset_no_iso, old_flagged)
    in_sample_feasible = b_lo < b_hi
    in_sample_b = representative_intercept(b_lo, b_hi)
    in_sample_flagged = (offset_no_iso + in_sample_b) < LOGIT_THRESHOLD
    in_sample_mismatches = int(np.sum(in_sample_flagged != old_flagged))
    print(f"\n[2] in-sample feasibility: intercept range [{b_lo:.6f}, {b_hi:.6f}) "
          f"{'non-empty' if in_sample_feasible else 'EMPTY -- no intercept can reproduce every decision'}")
    print(f"    representative intercept = {in_sample_b:.6f}   flagged mismatches vs original: {in_sample_mismatches}/{data['n']}")

    # (3) cross-split feasibility: representative intercept comes from the
    # OTHER split's own interval, applied unmodified to THIS split.
    other_old_flagged = other["fused"] < PROCESS_THRESHOLD
    other_offset_no_iso = coef_rule * other["rule"] + coef_lstm * other["lstm"] + coef_gnn * other["gnn"]
    ob_lo, ob_hi = feasible_interval(other_offset_no_iso, other_old_flagged)
    cross_feasible = ob_lo < ob_hi
    cross_b = representative_intercept(ob_lo, ob_hi)
    cross_flagged = (offset_no_iso + cross_b) < LOGIT_THRESHOLD
    cross_mismatches = int(np.sum(cross_flagged != old_flagged))
    print(f"\n[3] cross-split feasibility: {other_split}'s own intercept range [{ob_lo:.6f}, {ob_hi:.6f}) "
          f"{'non-empty' if cross_feasible else 'EMPTY on ' + other_split + ' itself'}")
    print(f"    representative intercept (from {other_split} only) = {cross_b:.6f}   "
          f"applied to {split}: flagged mismatches vs original: {cross_mismatches}/{data['n']}")

    verdict = ("CONFIRMED" if exact_mismatches == 0 and in_sample_mismatches == 0 and cross_mismatches == 0
               else "NOT CONFIRMED")
    print(f"\n{verdict}: dropping isolation_forest_score and refitting only the "
          f"fusion intercept {'reproduces' if verdict == 'CONFIRMED' else 'does NOT reproduce'} "
          f"every window's flagged/not-flagged outcome on the {split} split, including under a "
          f"{other_split}-only intercept the {split} rows never informed.")

    out = {
        "split": split,
        "other_split": other_split,
        "pin": pin_name,
        "n": data["n"],
        "iso_values_observed": sorted(set(iso.tolist())),
        "rule_values_observed": sorted(set(rule.tolist())),
        "fusion_model": pin.fusion_model_path,
        "original_coefficients": {
            "rule": coef_rule, "isolation_forest": coef_iso, "lstm": coef_lstm, "gnn": coef_gnn,
            "intercept": intercept,
        },
        "exact_rederivation": {"new_intercept": exact_intercept, "flagged_mismatches": exact_mismatches},
        "in_sample_feasibility": {
            "interval": [b_lo, b_hi], "feasible": in_sample_feasible,
            "representative_intercept": in_sample_b, "flagged_mismatches": in_sample_mismatches,
        },
        "cross_split_feasibility": {
            "fit_on": other_split, "interval": [ob_lo, ob_hi], "feasible": cross_feasible,
            "representative_intercept": cross_b, "flagged_mismatches": cross_mismatches,
        },
        "verdict": verdict,
    }
    out_path = os.path.join(RESULTS_DIR, f"if_ablation_check_{split}_{pin_name}.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
