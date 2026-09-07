# Corrected-M6 policy evaluation -- summary

**Date:** 2026-09-07. **Protocol:** deterministic clock (per-record `ts`), same `build_triples`/`score_actions` implementation as `results/policy_comparison/` and `results/gcn_m6_corrected_comparison/`. Both Q-tables trained fresh via the pinned, deterministic `scripts/train_adaptive_pdp.py` -- see `artifact_lineage.json`.

## Result

| Policy | Macro-F1 | Weighted-F1 | Accuracy | False-block rate | False-step-up rate |
|---|---|---|---|---|---|
| GCN + matched GCN fusion (clean, deterministic) | 0.5303 | 0.7863 | 0.7259 | 0.0000 | 0.0007 |
| Corrected M6 + matched corrected-M6 fusion | 0.5332 | 0.7900 | 0.7307 | 0.0000 | 0.0007 |

For context, NOT re-measured here (historical, preserved, wall-clock-jitter protocol, reported for continuity only):
- deployed (corrupted-provenance) Q-table, GCN-pinned rerun: P5=0.5132 (`results/gcn_m6_corrected_comparison/policy_comparison.json`)
- deployed (corrupted-provenance) Q-table, originally reported: P5=0.5271 (`results/policy_comparison/metrics.json`, now flagged unreproducible)

## Per-action detail

### m6_corrected

| Action | Support | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|---|
| ALLOW | 2541 | 0.9895 | 0.7068 | 0.8246 | 1796 | 19 | 745 |
| ALERT | 200 | 0.2015 | 0.9700 | 0.3336 | 194 | 769 | 6 |
| STEP_UP | 159 | 0.9871 | 0.9623 | 0.9745 | 153 | 2 | 6 |
| BLOCK | 33 | 0.0000 | 0.0000 | 0.0000 | 0 | 0 | 33 |

### gcn_corrected

| Action | Support | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|---|
| ALLOW | 2541 | 0.9895 | 0.7013 | 0.8208 | 1782 | 19 | 759 |
| ALERT | 200 | 0.2002 | 0.9800 | 0.3325 | 196 | 783 | 4 |
| STEP_UP | 159 | 0.9869 | 0.9497 | 0.9679 | 151 | 2 | 8 |
| BLOCK | 33 | 0.0000 | 0.0000 | 0.0000 | 0 | 0 | 33 |

## Notes

- BLOCK recall is reported as measured, not hidden or substituted, whatever its value: 0/33 for BOTH arms. This is the known, architectural `stealthy_forged_values`/`combined`-class blind spot (excluded from training as unlearnable from this state space -- see train_adaptive_pdp.py's docstring), not specific to either relational model.
- ALERT precision is low for both arms (~0.20) -- the greedy bandit answers ALERT far more often than the ALERT ground-truth class occurs (769/783 false ALERTs), spilling out of the ALLOW class. This is an existing, honestly-reported bandit weakness (see the project's `zt-cps-known-limitations` finding that a validation-tuned static policy beats the adaptive bandit on macro-F1), not introduced by this pass.
- Neither Q-table is the historically deployed `models/adaptive_pdp_qtable.json` -- that file is untouched by this pass (see PART 11: do not overwrite historical artifacts). It is additionally preserved under an explicit name, `models/adaptive_pdp_qtable_m6_deployed_20260907_corrupted_provenance.json`.
- This IS a valid GCN-vs-M6 policy comparison (Part 7): both arms share the same deterministic-clock protocol and were trained the same way, differing only in which relational/fusion pin they were trained and evaluated against.

## Deployment decision (Part 10)

**CORRECTED_M6_DEPLOYMENT_DECISION: PROMOTE_CORRECTED_M6.**

Gate-by-gate:

| Gate | Status |
|---|---|
| Artifact lineage clean | PASS -- `artifact_lineage.json`, hash-verified via `relational_pin.verify_policy_lineage()` |
| Corrected fusion paired correctly | PASS -- `M6_CORRECTED` pin, hash-verified |
| Corrected policy trained/evaluated correctly | PASS -- this document |
| Tests pass | PASS -- 193/193 (`python -m unittest discover -s tests`) |
| No material hardware regression | PASS -- `hardware_regression.json` (30/30 detection, 5/12 resting FP, identical across GCN/deployed-M6/corrected-M6) |
| Latency acceptable | PASS -- corrected M6 ~2.08ms mean, "well within pipeline latency budget" (`results/gcn_m6_corrected_comparison/summary.md`), unchanged by this pass |
| Policy behaviour operationally acceptable | PASS (qualified) -- corrected-M6 policy macro-F1 (0.5332) is at least as good as the fair GCN baseline (0.5303); known weaknesses (BLOCK unreachable, ALERT precision) are pre-existing and shared by both arms, not introduced |
| Runtime integration works | PASS -- `runtime_verification.json` |

Not decided on standalone Macro-F1 alone (per Part 10's explicit instruction): the deciding factors are the confirmed training defect in the currently-deployed checkpoint (`results/gcn_m6_corrected_comparison/summary.md` finding 1), the corrected checkpoint's consistent (if modest) wins on fusion/Task-2/policy, and a clean bill of health on every operational gate above.

**Promoted:** `config.py`'s ambient `SET_TRANSFORMER_MODEL_PATH`, `FUSION_MODEL_PATH`, `FUSION_BACKGROUND_PATH`, `ADAPTIVE_PDP_MODEL_PATH` now point at `models/set_transformer_corrected.pt`, `models/fusion_meta_learner_m6_corrected_variant.joblib`, `models/fusion_background_m6_corrected_variant.npy`, `models/adaptive_pdp_qtable_m6_corrected.json` respectively. No file already tracked by git was modified in place; the previously-deployed flawed artifacts (`models/set_transformer_runtime.pt`, `models/fusion_meta_learner_m6_variant.joblib`, `models/adaptive_pdp_qtable.json`) remain on disk, untouched, and are still reachable via `src/relational_pin.py`'s `M6_DEPLOYED` pin (now documented HISTORICAL/SUPERSEDED) for reproducibility.
