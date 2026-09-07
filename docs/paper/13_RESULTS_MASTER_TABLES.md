# Results master tables

[CURRENT NUMERICAL AUTHORITY] Generated from frozen JSON, preserved replay logs and inspected model artifacts. A result is current for its stated protocol, not automatically for every runtime or data revision. Final invalid-content hardening has new regression/parity evidence; archived benchmark metrics were not overwritten. Missing PR-AUC/checkpoint identities are explicit.

**Polarity:** relational F1 treats anomaly as positive; local/fusion replay F1 treats normal as positive. Macro-F1 averages class F1 values. A normality score below its threshold flags an anomaly.

## A / O. Local detectors and preserved GCN fusion

Source: [results/final_verification/local_fusion_evaluation.log](../../results/final_verification/local_fusion_evaluation.log); producer [scripts/evaluate_ablation.py](../../scripts/evaluate_ablation.py). [VERIFIED PRESERVED GCN-ERA REPLAY; SUPERSEDED AS RUNTIME LINEAGE] 3,050 legacy synthetic TEST records, 117 rejected excluded, 2,933 accepted (2,700 normal/233 anomalous); three identities; threshold 0.6. Printed precision is three decimals. Two scalar identities substitute rule scores into learned local channels; this is not a three-physical-device evaluation. Current default fusion is M6-fitted, so the producer requires explicit GCN backup selection for a matched replication.


| Signal | Accuracy | Normal precision | Normal recall | Normal F1 |
|---|---|---|---|---|
| rule_score | 0.921 | 0.921 | 1.000 | 0.959 |
| isolation_forest_score | 0.919 | 0.960 | 0.951 | 0.956 |
| lstm_ae_score | 0.753 | 0.957 | 0.766 | 0.851 |
| transformer_score | 0.754 | 0.957 | 0.768 | 0.852 |
| gnn_score | 0.287 | 0.983 | 0.229 | 0.372 |
| fused_score | 0.698 | 0.992 | 0.677 | 0.805 |


Fair primary-device temporal subset: 1,000 MPU test rows, 746 window-residue normal rows excluded, 254 retained. Conditional results, not full-stream performance.


| Signal | Accuracy | Normal precision | Normal recall | Normal F1 |
|---|---|---|---|---|
| lstm_ae_score | 0.945 | 0.878 | 1.000 | 0.935 |
| transformer_score | 0.945 | 0.878 | 1.000 | 0.935 |


The log also reports anomaly-event recall: fused shock 1.000, coordinated 0.983, stealthy-forged-values 0.636. These are event-type window recalls, not independent attack trials. M6 fusion comparison is [REQUIRES FINAL FUSION VALIDATION].

## O2. Configured fusion artifact identity, not a performance result

[SUPERSEDED BY THE 2026-09-07 CORRECTED-M6 PROMOTION — see O5] This table originally described the artifact deployed by commit `3c827e8`, through the comparator-repair pass that produced O4; kept for chronology. As of the corrected-M6 promotion (O5), `config.py`'s ambient `FUSION_MODEL_PATH` / `FUSION_BACKGROUND_PATH` point at `fusion_meta_learner_m6_corrected_variant.joblib` instead — included below, marked CURRENT. `fusion_meta_learner.joblib` itself is untouched on disk (still byte-identical to its row below) and remains reachable as the historical/superseded deployed artifact via `src/relational_pin.py`'s `M6_DEPLOYED` pin.

[VERIFIED ARTIFACT INSPECTION, 2026-09-07] Active fusion/background match the M6 variants. The fourth input retains the legacy name `gnn_score`, but the gateway supplies M6. The older model_metadata.json describes the GCN backup. Source: the following saved joblib files; producer of this inspection: `scripts/build_paper_results.py`. No evaluation or fitting occurs.


| Artifact | Coefficients: rule, IF, LSTM, relational | Intercept | SHA-256 |
|---|---|---|---|
| [models/fusion_meta_learner.joblib](../../models/fusion_meta_learner.joblib) (historical: deployed until the O5 promotion) | -0.01457110136, 2.808748237, 5.249222727, 12.18787891 | -8.53572 | d5e2bfeecc57142bf432ed233ec8f50c0e45a787f448a3590c8d849af955e934 |
| [models/fusion_meta_learner_m6_variant.joblib](../../models/fusion_meta_learner_m6_variant.joblib) | -0.01457110136, 2.808748237, 5.249222727, 12.18787891 | -8.53572 | d5e2bfeecc57142bf432ed233ec8f50c0e45a787f448a3590c8d849af955e934 |
| [models/fusion_meta_learner_gcn_backup.joblib](../../models/fusion_meta_learner_gcn_backup.joblib) | -0.004829691542, 3.286754353, 4.31543991, 5.007398278 | -7.26074 | 20ea7bcbba43861b21736c857c47d80434cd8e0daea42cd645a6aabd4abbf8e8 |
| [models/fusion_meta_learner_m6_corrected_variant.joblib](../../models/fusion_meta_learner_m6_corrected_variant.joblib) (CURRENT: deployed as of O5) | 0.01327222603, 3.33760767, 5.570895115, 7.884517403 | -11.4255 | 6d89db099e2fd4efd438af27ad2d6da6ea72d093fb7e31f055f11c69bfed19fa |


## O3. Historical reported M6 comparison — SUPERSEDED by O4

[SUPERSEDED — see O4] [RESULTS.md](../../RESULTS.md) records normal-positive fused F1 0.805→0.815, accuracy 0.698→0.712, normal false negatives 872→833 and anomaly misses 14→13. No matching raw comparison log/JSON was found for that specific prose observation, and the comparator that would have reproduced it (`evaluate_ablation_m6.py`) had a confirmed artifact-mismatch bug (its "GCN arm" silently read the M6-fitted fusion model — see O2). That bug is fixed (2026-09-07, results/comparator_repair/comparator_audit.json); O4 below is the current, correctly-pinned replacement. Keep this paragraph for chronology only — do not cite it as a current number.

## O4. Corrected GCN vs M6 comparator (2026-09-07)
[CURRENT — explicit artifact pinning] Fixes the O2/O3 comparator-mismatch bug: `evaluate_ablation_m6.py`, `evaluate_real_hardware.py`, `evaluate_policy_comparison.py` and `evaluate_explainability_level2.py` previously constructed `FusionEngine()` with no arguments, which read the *ambient* `config.FUSION_MODEL_PATH` — correct until the 2026-09-07 deployment overwrote it with the M6-fitted model, after which every "GCN arm" silently paired true GCN relational scores with M6-calibrated fusion coefficients. Fixed via `src/relational_pin.py`: three explicit, hash-verified `RelationalPin`s (`gcn`, `m6_deployed`, `m6_corrected`) — see [results/comparator_repair/comparator_audit.json](../../results/comparator_repair/comparator_audit.json) for the full per-script before/after audit. `gcn` and `m6_deployed` reference the exact deployed/preserved artifacts (verified byte-identical, unchanged by this repair). `m6_corrected` is a **new** checkpoint, retrained after fixing a confirmed class-weight bug in `scripts/train_set_transformer.py` (below) — **not deployed**; evaluation/comparison only.
**Class-weight bug, confirmed with numbers.** `train_set_transformer.py` computed its inverse-frequency `pos_weight`/`neg_weight` over the full, unmasked node-target tensor, but the loss only ever trains on the `valid`-masked subset (verified against `training_session.json`: 656,040 total node-slots, only 58,486 / 8.9% ever valid). Actual (buggy) vs. correct: `neg_weight` (suspicious class) = 45.18 vs. 6.27 — a **7.2x overweight**. `train_gnn.py` does not have this bug (its loss is unmasked by design). Fixed by counting `ys[valids]`; `m6_corrected` is one retrain with the fix, deployed `set_transformer_runtime.pt` untouched (verified byte-identical hash before/after this work).
**Standalone relational score** (`test_session.json`, threshold 0.6, normal-positive polarity):

| Arm | Macro-F1 | Precision (normal) | Recall (normal) | FPR | ROC-AUC |
|---|---|---|---|---|---|
| gcn | 0.273425 | 0.98254 | 0.229259 | 0.0174603 | 0.909436 |
| m6_deployed | 0.0735944 | 0 | 0 | 0 | 0.904196 |
| m6_corrected | 0.792559 | 0.985827 | 0.927407 | 0.0141732 | 0.925842 |

The deployed M6 checkpoint's raw/standalone score is badly miscalibrated at the deployed threshold (near-zero normal recall). The corrected retrain repairs this dramatically. ROC-AUC (threshold-independent) is comparable across all three, showing the raw discriminative information was less damaged than the threshold-0.6 operating point suggests.
**Fusion** (Rule+IF+LSTM+relational, matched fusion artifact per arm):

| Arm | Macro-F1 | Recall (normal) | FPR | ROC-AUC |
|---|---|---|---|---|
| gcn | 0.567874 | 0.677037 | 0.00760043 | 0.849158 |
| m6_deployed | 0.578715 | 0.691481 | 0.00691489 | 0.860375 |
| m6_corrected | 0.579818 | 0.694074 | 0.00741525 | 0.860949 |

Both M6 variants modestly beat the GCN fusion arm on this held-out replay, now under a genuinely matched comparison — safe to describe as a **modest, held-out-replay-qualified** improvement (17 Claim C), not a general claim. The fusion layer visibly compensates for the deployed checkpoint's poor standalone calibration.
**Latency** (standalone relational-scorer inference, post-warmup, this environment):

| Arm | Mean (ms) | p95 (ms) | n calls |
|---|---|---|---|
| gcn | 1.078 | 1.84228 | 200 |
| m6_deployed | 1.92356 | 3.23929 | 200 |
| m6_corrected | 2.08064 | 3.68294 | 200 |

M6 (either variant) is slower per call than GCN; both remain a small fraction of the previously measured end-to-end pipeline latency (R below), so this does not by itself threaten the practical latency budget.
**Hardware** (real MPU6050 TEST session, inference only, no retrain on test data):

| Arm | Resting FP | Resting FP rate | Detection | Detection rate |
|---|---|---|---|---|
| gcn | 5/12 | 41.7% | 30/30 | 100.0% |
| m6_deployed | 5/12 | 41.7% | 30/30 | 100.0% |
| m6_corrected | 5/12 | 41.7% | 30/30 | 100.0% |

Identical across all three arms — no regression from GCN to either M6 variant on the available physical evidence (Gate H).
**Policy** (`evaluate_policy_comparison.py`, GCN pin):

| Policy | GCN-pin rerun Macro-F1 | Preserved historical Macro-F1 |
|---|---|---|
| P1_static | 0.272 | 0.2744 |
| P2_static_optimised | 0.5512 | 0.5614 |
| P6_static_constrained | 0.278 | 0.2777 |
| P5_adaptive_bandit | 0.5132 | 0.5271 |

P1/P2/P6 (pure threshold policies) reproduce within verified wall-clock jitter. P5 (adaptive bandit) is stable across repeated runs but differs from its preserved number by more than that jitter — evidence `models/adaptive_pdp_qtable.json` was itself retrained during the 2026-09-07 deployment under the same mismatched-artifact bug. **No M6 policy arm is reported here**: no policy retrain was performed in this earlier pass (explicit scope decision at the time). **This gap is closed in O5 below**, the same day's final pass (17 Claim D).
Source for this section: `results/gcn_m6_corrected_comparison/` (`standalone_comparison.json`, `fusion_comparison.json`, `hardware_comparison.json`, `latency_comparison.json`, `policy_comparison.json`, `artifact_lineage.json`, `summary.md`); producers `scripts/evaluate_ablation_m6.py`, `scripts/evaluate_real_hardware.py --relational-model {gcn,m6_deployed,m6_corrected}`. Commit 2175ebe3c4a3fad31d80d3b2899c51fe0a33b86b; seed 0.

## O5. Corrected M6 policy comparison and deployment promotion (2026-09-07 final pass)
[CURRENT] Closes the O4/17-Claim-D gap. Two fixes made this possible, both additive/opt-in (default behaviour of every existing caller unchanged, verified via the pre-existing 193-test suite passing unmodified): (1) `scripts/train_adaptive_pdp.py` now requires an explicit `src/relational_pin.py` `RelationalPin` (`ZTCPS_ADAPTIVE_PDP_PIN` env var, default `gcn`) instead of the bare `GNNScorer()`/`FusionEngine()` that corrupted `models/adaptive_pdp_qtable.json`'s provenance during the M6 deployment; a metadata sidecar records full lineage, and `relational_pin.verify_policy_lineage()` fails loudly on any future mismatch. (2) `GNNScorer`/`SetTransformerScorer`'s active-neighbour window and `RuleBasedTrustEngine`'s Security Trust EWMA decay both accept an injected deterministic `clock` (default `None` -> `time.time()`, so live-gateway freshness semantics are provably unchanged) — offline replay now uses each record's own `ts` field instead of wall-clock time, fixing a confirmed non-determinism (see `tests/test_policy_training_determinism.py`).
Two Q-tables were trained fresh (seed 0, deterministic clock, `validation_policy_session.json`, `'combined'`/stealthy-forged-values excluded as unlearnable — same protocol the historical table used): `adaptive_pdp_qtable_gcn_corrected.json` (GCN + matched GCN fusion — a **fair, clean-provenance GCN baseline**, distinct from the corrupted-provenance `adaptive_pdp_qtable.json`) and `adaptive_pdp_qtable_m6_corrected.json` (corrected M6 + matched corrected-M6 fusion). Evaluated on the untouched `test_session.json`:

| Policy | Macro-F1 | Weighted-F1 | Accuracy | False-block rate | False-step-up rate |
|---|---|---|---|---|---|
| m6_corrected | 0.5332 | 0.79 | 0.7307 | 0 | 0.0007 |
| gcn_corrected | 0.5303 | 0.7863 | 0.7259 | 0 | 0.0007 |

Per-action (BLOCK recall reported as measured, not hidden or substituted, whatever its value):

| Arm | Action | Support | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|---|---|
| m6_corrected | ALLOW | 2541 | 0.9895 | 0.7068 | 0.8246 | 1796 | 19 | 745 |
| m6_corrected | ALERT | 200 | 0.2015 | 0.97 | 0.3336 | 194 | 769 | 6 |
| m6_corrected | STEP_UP | 159 | 0.9871 | 0.9623 | 0.9745 | 153 | 2 | 6 |
| m6_corrected | BLOCK | 33 | 0 | 0 | 0 | 0 | 0 | 33 |
| gcn_corrected | ALLOW | 2541 | 0.9895 | 0.7013 | 0.8208 | 1782 | 19 | 759 |
| gcn_corrected | ALERT | 200 | 0.2002 | 0.98 | 0.3325 | 196 | 783 | 4 |
| gcn_corrected | STEP_UP | 159 | 0.9869 | 0.9497 | 0.9679 | 151 | 2 | 8 |
| gcn_corrected | BLOCK | 33 | 0 | 0 | 0 | 0 | 0 | 33 |

BLOCK is unreachable for **both** arms — the pre-existing, architectural `stealthy_forged_values`/`combined`-class blind spot (excluded from training as unlearnable from a `(security_trust, process_trust)` state space; see `train_adaptive_pdp.py`'s docstring), not specific to either relational model. ALERT precision is low for both (matching the project's already-documented finding that a validation-tuned static policy beats the adaptive bandit — see 18). **Corrected M6's policy modestly outperforms the fair GCN baseline** on macro-F1 and weighted-F1 — consistent in direction and magnitude with the fusion-level gap in O4, small enough that it should be described as "matches or modestly exceeds," not a strong claim.
**Deployment decision: PROMOTE_CORRECTED_M6.** Given the confirmed training defect in the checkpoint deployed by `3c827e8` (O4), and clean results on every gate (lineage, fusion, policy, 193/193 tests, no hardware regression — NO REGRESSION. All three arms (GCN, flawed-deployed M6, corrected M6) produce byte-identical hardware detection/false-po…, latency unchanged and within budget, runtime integration verified — `design/verify-runtime.py` ok=True, runtime_relational_model='M6 Set Transformer'), `config.py`'s ambient `SET_TRANSFORMER_MODEL_PATH` / `FUSION_MODEL_PATH` / `FUSION_BACKGROUND_PATH` / `ADAPTIVE_PDP_MODEL_PATH` now point at the corrected checkpoint, its matched fusion artifact, and `adaptive_pdp_qtable_m6_corrected.json` respectively. **No previously-deployed artifact was modified or deleted** — `set_transformer_runtime.pt`, `fusion_meta_learner.joblib`/`fusion_meta_learner_m6_variant.joblib` and `adaptive_pdp_qtable.json` remain on disk byte-identical, and are additionally preserved under `models/adaptive_pdp_qtable_m6_deployed_20260907_corrupted_provenance.json`. `src/relational_pin.py`'s `M6_DEPLOYED` pin now resolves via an explicit, ambient-independent constant (`SET_TRANSFORMER_MODEL_PATH_M6_DEPLOYED_FLAWED_20260907`) so it remains hash-verifiable regardless of what is deployed later.
Source for this section: `results/m6_corrected_policy/` (`policy_metrics.json`, `policy_action_metrics.json`, `artifact_lineage.json`, `policy_training_config.json`, `runtime_verification.json`, `hardware_regression.json`, `summary.md`); producers `scripts/evaluate_m6_corrected_policy.py`, `scripts/train_adaptive_pdp.py`. Seed 0; deterministic clock (per-record `ts`).

## B / C. M1–M9, validation max-anomaly-F1 operating point

Source: [results/crossdevice_benchmark/metrics.json](../../results/crossdevice_benchmark/metrics.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [CURRENT EXPERIMENTAL] Seed 0; fit TRAIN 2,400 snapshots/48,000 valid rows, select VALIDATION 1,200 snapshots/22,800 valid rows, report TEST with same held-out counts; declared network 20 (19 valid held-out); hybrid provenance. TEST has 1,500 anomalous rows: 150 isolated and 1,350 coordinated, plus 21,300 normal; 15 anomaly events.


| Model | Macro-F1 | Precision | Recall | Anomaly F1 | FPR | Isolated recall | Coordinated recall | ROC-AUC | PR-AUC | Threshold |
|---|---|---|---|---|---|---|---|---|---|---|
| M1_concat_mlp | 0.9443 | 0.813 | 1 | 0.8969 | 0.0162 | 1 | 1 | 0.9998 | NOT REPORTED / undefined | 0.8 |
| M2_grad_boosting | 0.9513 | 0.8585 | 0.9667 | 0.9094 | 0.0112 | 0.98 | 0.9652 | 0.9969 | NOT REPORTED / undefined | 0.25 |
| M3_deep_sets | 0.9837 | 0.9427 | 0.998 | 0.9696 | 0.0043 | 0.98 | 1 | 0.9998 | NOT REPORTED / undefined | 0.15 |
| M4_gcn | 0.7755 | 0.5017 | 0.706 | 0.5865 | 0.0494 | 0 | 0.7844 | 0.9458 | NOT REPORTED / undefined | 0.15 |
| M5_gatv2 | 0.9857 | 0.9533 | 0.994 | 0.9732 | 0.0034 | 0.9733 | 0.9963 | 0.9995 | NOT REPORTED / undefined | 0.025 |
| M6_set_transformer | 0.9898 | 0.9652 | 0.9973 | 0.981 | 0.0025 | 0.98 | 0.9993 | 0.9999 | NOT REPORTED / undefined | 0.025 |
| M7_np_st | 0.985 | 0.9475 | 0.998 | 0.9721 | 0.0039 | 0.98 | 1 | 0.9997 | NOT REPORTED / undefined | 0.7 |
| M8_set_transformer_mixed_n | 0.9713 | 0.8987 | 1 | 0.9467 | 0.0079 | 1 | 1 | 0.9997 | NOT REPORTED / undefined | 0.025 |
| M9_mixed_provenance | 0.9842 | 0.9445 | 0.998 | 0.9705 | 0.0041 | 0.98 | 1 | 0.9997 | NOT REPORTED / undefined | 0.55 |


JSON keys: `results.<model>.test.*`, `test_macro_f1`, `test_roc_auc`, `recall_isolated_anomaly`, `recall_coordinated_anomaly`. PR-AUC is absent from these nine max-F1 rows, not zero. The offline M1–M9 benchmark fits have no saved per-model checkpoints. A separate runtime M6 checkpoint exists; it does not inherit these benchmark numbers. M4 has a distinct baseline GCN checkpoint lineage.

## R / S. M1–M9 model cost


| Model | Parameters | Epochs | Train total ms | Inference mean ms | p50 ms | p95 ms | Timed samples |
|---|---|---|---|---|---|---|---|
| M1_concat_mlp | 3777 | 42 | 7207.2 | 0.0654 | 0.0565 | 0.0684 | 200 |
| M2_grad_boosting | NOT REPORTED / undefined | 200 | 6633.23 | 3.91 | 3.8399 | 4.7013 | 200 |
| M3_deep_sets | 2121 | 300 | 1453.49 | 0.7883 | 0.6347 | 1.3012 | 200 |
| M4_gcn | 1217 | 150 | 384.95 | 0.556 | 0.5367 | 0.7449 | 200 |
| M5_gatv2 | 945 | 300 | 10725.2 | 1.3507 | 1.0562 | 2.3297 | 200 |
| M6_set_transformer | 2609 | 300 | 4692.17 | 1.3448 | 1.0697 | 2.4967 | 200 |
| M7_np_st | 3778 | 300 | 4987.84 | 1.6596 | 1.368 | 3.0439 | 200 |
| M8_set_transformer_mixed_n | 2609 | 300 | 4364.56 | 1.4397 | 1.5006 | 2.293 | 200 |
| M9_mixed_provenance | 2609 | 300 | 4305.53 | 0.8625 | 0.7788 | 1.5348 | 200 |


Same source as B. Host timing of an individual scored sample/snapshot; not sensor-to-enforcement latency. Parameters for tree ensembles are not comparable to neural weights.

## Calibration and alarm-budget operating points

Isotonic mapping fits one validation half; threshold selection uses the other half. These rows are different operating points from B. The declared cap is a selection rule, not a guarantee on future data.


| Model | FPR cap | Selected threshold | TEST FPR | Macro-F1 | Anomaly F1 | Precision | Recall | Cap held |
|---|---|---|---|---|---|---|---|---|
| M1_concat_mlp | 0.01 | 0.736842 | 0.0237 | 0.9221 | 0.8562 | 0.7485 | 1 | False |
| M1_concat_mlp | 0.03 | 0.956084 | 0.0291 | 0.9071 | 0.829 | 0.7079 | 1 | True |
| M2_grad_boosting | 0.01 | 0.666667 | 0.0118 | 0.9556 | 0.9175 | 0.8553 | 0.9893 | False |
| M2_grad_boosting | 0.03 | 0.666667 | 0.0118 | 0.9556 | 0.9175 | 0.8553 | 0.9893 | True |
| M3_deep_sets | 0.01 | 0.928093 | 0.0103 | 0.9632 | 0.9317 | 0.8721 | 1 | False |
| M3_deep_sets | 0.03 | 0.964826 | 0.0197 | 0.9338 | 0.8774 | 0.7817 | 1 | True |
| M4_gcn | 0.01 | 0.439153 | 0.0009 | 0.4947 | 0.0234 | 0.4737 | 0.012 | True |
| M4_gcn | 0.03 | 0.439153 | 0.0026 | 0.5134 | 0.0611 | 0.4712 | 0.0327 | True |
| M5_gatv2 | 0.01 | 0.94166 | 0.0046 | 0.9825 | 0.9674 | 0.9386 | 0.998 | True |
| M5_gatv2 | 0.03 | 0.953846 | 0.0046 | 0.9825 | 0.9674 | 0.9386 | 0.998 | True |
| M6_set_transformer | 0.01 | 0.736842 | 0.0085 | 0.9694 | 0.9431 | 0.8923 | 1 | True |
| M6_set_transformer | 0.03 | 0.974178 | 0.0114 | 0.9597 | 0.9251 | 0.8606 | 1 | True |
| M7_np_st | 0.01 | 0.895833 | 0.0039 | 0.985 | 0.9721 | 0.9475 | 0.998 | True |
| M7_np_st | 0.03 | 0.964286 | 0.0295 | 0.9058 | 0.8267 | 0.7046 | 1 | True |
| M8_set_transformer_mixed_n | 0.01 | 0.85 | 0.0088 | 0.9685 | 0.9413 | 0.8892 | 1 | True |
| M8_set_transformer_mixed_n | 0.03 | 0.93402 | 0.03 | 0.9046 | 0.8244 | 0.7013 | 1 | True |
| M9_mixed_provenance | 0.01 | 0.74359 | 0.0097 | 0.9653 | 0.9355 | 0.8787 | 1 | True |
| M9_mixed_provenance | 0.03 | 0.941176 | 0.0247 | 0.919 | 0.8506 | 0.74 | 1 | True |



| Model | Raw TEST Brier | Calibrated TEST Brier |
|---|---|---|
| M1_concat_mlp | 0.00889 | 0.00661 |
| M2_grad_boosting | 0.01163 | 0.01005 |
| M3_deep_sets | 0.00483 | 0.00315 |
| M4_gcn | 0.10357 | 0.04034 |
| M5_gatv2 | 0.00437 | 0.00323 |
| M6_set_transformer | 0.00494 | 0.00277 |
| M7_np_st | 0.0032 | 0.0029 |
| M8_set_transformer_mixed_n | 0.02205 | 0.0033 |
| M9_mixed_provenance | 0.00371 | 0.00313 |


## D. Target-degree intervention

Source: [results/crossdevice_benchmark/metrics.json](../../results/crossdevice_benchmark/metrics.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL] `structural_probes.neighbour_degree_at_n10`; n=10; 400 synthetic probe draws/cell built from valid score pools; model fitted once. Degree/peer interventions reuse a shared batch. Dilution draws advance across models/sizes and are not paired with the separately sampled declared-topology control.


| Model | Intervention level | Mean anomaly probability | Recall at frozen threshold |
|---|---|---|---|
| M3_deep_sets | 1 | 0.9493 | 0.94 |
| M3_deep_sets | 2 | 0.9493 | 0.94 |
| M3_deep_sets | 3 | 0.9493 | 0.94 |
| M3_deep_sets | 5 | 0.9493 | 0.94 |
| M3_deep_sets | 9 | 0.9493 | 0.94 |
| M4_gcn | 1 | 0.9491 | 0.9675 |
| M4_gcn | 2 | 0.8935 | 0.835 |
| M4_gcn | 3 | 0.8126 | 0.3625 |
| M4_gcn | 5 | 0.5974 | 0.06 |
| M4_gcn | 9 | 0.2228 | 0.0175 |
| M5_gatv2 | 1 | 0.918 | 0.725 |
| M5_gatv2 | 2 | 0.9039 | 0.5925 |
| M5_gatv2 | 3 | 0.8935 | 0.415 |
| M5_gatv2 | 5 | 0.8793 | 0.2275 |
| M5_gatv2 | 9 | 0.868 | 0.2125 |
| M6_set_transformer | 1 | 0.9732 | 0.885 |
| M6_set_transformer | 2 | 0.9732 | 0.885 |
| M6_set_transformer | 3 | 0.9732 | 0.885 |
| M6_set_transformer | 5 | 0.9732 | 0.885 |
| M6_set_transformer | 9 | 0.9732 | 0.885 |
| M7_np_st | 1 | 0.8655 | 0.965 |
| M7_np_st | 2 | 0.8655 | 0.965 |
| M7_np_st | 3 | 0.8655 | 0.965 |
| M7_np_st | 5 | 0.8655 | 0.965 |
| M7_np_st | 9 | 0.8655 | 0.965 |
| M8_set_transformer_mixed_n | 1 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 2 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 3 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 5 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 9 | 0.9918 | 0.995 |


## E. Peer-density intervention

Source: [results/crossdevice_benchmark/metrics.json](../../results/crossdevice_benchmark/metrics.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL] `structural_probes.peer_density_at_n10_degree3`; n=10; 400 synthetic probe draws/cell built from valid score pools; model fitted once. Degree/peer interventions reuse a shared batch. Dilution draws advance across models/sizes and are not paired with the separately sampled declared-topology control.


| Model | Intervention level | Mean anomaly probability | Recall at frozen threshold |
|---|---|---|---|
| M3_deep_sets | 0 | 0.9493 | 0.94 |
| M3_deep_sets | 4 | 0.9493 | 0.94 |
| M3_deep_sets | 9 | 0.9493 | 0.94 |
| M3_deep_sets | 18 | 0.9493 | 0.94 |
| M3_deep_sets | 36 | 0.9493 | 0.94 |
| M4_gcn | 0 | 0.8953 | 0.79 |
| M4_gcn | 4 | 0.878 | 0.71 |
| M4_gcn | 9 | 0.8546 | 0.5875 |
| M4_gcn | 18 | 0.8053 | 0.355 |
| M4_gcn | 36 | 0.8126 | 0.3625 |
| M5_gatv2 | 0 | 0.9909 | 0.9725 |
| M5_gatv2 | 4 | 0.9791 | 0.9225 |
| M5_gatv2 | 9 | 0.9618 | 0.84 |
| M5_gatv2 | 18 | 0.9136 | 0.6475 |
| M5_gatv2 | 36 | 0.8935 | 0.415 |
| M6_set_transformer | 0 | 0.9732 | 0.885 |
| M6_set_transformer | 4 | 0.9732 | 0.885 |
| M6_set_transformer | 9 | 0.9732 | 0.885 |
| M6_set_transformer | 18 | 0.9732 | 0.885 |
| M6_set_transformer | 36 | 0.9732 | 0.885 |
| M7_np_st | 0 | 0.8655 | 0.965 |
| M7_np_st | 4 | 0.8655 | 0.965 |
| M7_np_st | 9 | 0.8655 | 0.965 |
| M7_np_st | 18 | 0.8655 | 0.965 |
| M7_np_st | 36 | 0.8655 | 0.965 |
| M8_set_transformer_mixed_n | 0 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 4 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 9 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 18 | 0.9918 | 0.995 |
| M8_set_transformer_mixed_n | 36 | 0.9918 | 0.995 |


## H / K. Mixed-cardinality dilution

Source: [results/crossdevice_benchmark/metrics.json](../../results/crossdevice_benchmark/metrics.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL] `structural_probes.dilution_one_anomaly_among_n_minus_1_healthy`; n=2/3/5/10/20; 400 synthetic probe draws/cell built from valid score pools; model fitted once. Degree/peer interventions reuse a shared batch. Dilution draws advance across models/sizes and are not paired with the separately sampled declared-topology control.


| Model | Intervention level | Mean anomaly probability | Recall at frozen threshold |
|---|---|---|---|
| M3_deep_sets | 2 | 0.9402 | 0.9275 |
| M3_deep_sets | 3 | 0.9445 | 0.94 |
| M3_deep_sets | 5 | 0.9533 | 0.9625 |
| M3_deep_sets | 10 | 0.9646 | 0.98 |
| M3_deep_sets | 20 | 0.9849 | 0.9975 |
| M4_gcn | 2 | 0.9611 | 0.9575 |
| M4_gcn | 3 | 0.9323 | 0.9025 |
| M4_gcn | 5 | 0.8022 | 0.4925 |
| M4_gcn | 10 | 0.2545 | 0.0175 |
| M4_gcn | 20 | 0.061 | 0 |
| M5_gatv2 | 2 | 0.9894 | 0.9725 |
| M5_gatv2 | 3 | 0.9852 | 0.9575 |
| M5_gatv2 | 5 | 0.9811 | 0.875 |
| M5_gatv2 | 10 | 0.8958 | 0.215 |
| M5_gatv2 | 20 | 0.4885 | 0.1975 |
| M6_set_transformer | 2 | 0.9847 | 0.92 |
| M6_set_transformer | 3 | 0.9813 | 0.945 |
| M6_set_transformer | 5 | 0.9915 | 0.9625 |
| M6_set_transformer | 10 | 0.9795 | 0.935 |
| M6_set_transformer | 20 | 0.9834 | 0.91 |
| M7_np_st | 2 | 0.9758 | 0.99 |
| M7_np_st | 3 | 0.9777 | 0.99 |
| M7_np_st | 5 | 0.9583 | 0.98 |
| M7_np_st | 10 | 0.886 | 0.9925 |
| M7_np_st | 20 | 0.7862 | 0.97 |
| M8_set_transformer_mixed_n | 2 | 0.993 | 0.9975 |
| M8_set_transformer_mixed_n | 3 | 0.9928 | 0.9975 |
| M8_set_transformer_mixed_n | 5 | 0.9926 | 0.9975 |
| M8_set_transformer_mixed_n | 10 | 0.9921 | 0.9975 |
| M8_set_transformer_mixed_n | 20 | 0.9914 | 0.9975 |


## Coordinated-count intervention

Source: [results/crossdevice_benchmark/metrics.json](../../results/crossdevice_benchmark/metrics.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL] `structural_probes.coordination_k_of_10_anomalous`; n=10; 400 synthetic probe draws/cell built from valid score pools; model fitted once. Degree/peer interventions reuse a shared batch. Dilution draws advance across models/sizes and are not paired with the separately sampled declared-topology control.


| Model | Intervention level | Mean anomaly probability | Recall at frozen threshold |
|---|---|---|---|
| M3_deep_sets | 1 | 0.9493 | 0.94 |
| M3_deep_sets | 2 | 0.9822 | 1 |
| M3_deep_sets | 3 | 0.9892 | 1 |
| M3_deep_sets | 5 | 0.9946 | 1 |
| M3_deep_sets | 10 | 0.9998 | 1 |
| M4_gcn | 1 | 0.2545 | 0.0175 |
| M4_gcn | 2 | 0.6925 | 0.2575 |
| M4_gcn | 3 | 0.9406 | 0.955 |
| M4_gcn | 5 | 0.9728 | 0.99 |
| M4_gcn | 10 | 0.9878 | 1 |
| M5_gatv2 | 1 | 0.8878 | 0.2375 |
| M5_gatv2 | 2 | 0.9928 | 0.9425 |
| M5_gatv2 | 3 | 0.9975 | 0.9975 |
| M5_gatv2 | 5 | 0.9985 | 1 |
| M5_gatv2 | 10 | 0.9996 | 1 |
| M6_set_transformer | 1 | 0.9856 | 0.925 |
| M6_set_transformer | 2 | 0.9965 | 0.9975 |
| M6_set_transformer | 3 | 0.998 | 1 |
| M6_set_transformer | 5 | 0.9984 | 1 |
| M6_set_transformer | 10 | 0.9975 | 1 |
| M7_np_st | 1 | 0.8942 | 0.995 |
| M7_np_st | 2 | 0.9879 | 0.9975 |
| M7_np_st | 3 | 0.9954 | 1 |
| M7_np_st | 5 | 0.997 | 1 |
| M7_np_st | 10 | 0.9993 | 1 |
| M8_set_transformer_mixed_n | 1 | 0.992 | 0.9975 |
| M8_set_transformer_mixed_n | 2 | 0.9928 | 1 |
| M8_set_transformer_mixed_n | 3 | 0.9931 | 1 |
| M8_set_transformer_mixed_n | 5 | 0.9934 | 1 |
| M8_set_transformer_mixed_n | 10 | 0.9935 | 1 |


## Declared-topology control

Source: [results/crossdevice_benchmark/metrics.json](../../results/crossdevice_benchmark/metrics.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL] `structural_probes.dilution_n10_declared_topology`; n=20 declared topology (historical artifact key says n10); 400 synthetic probe draws/cell built from valid score pools; model fitted once. Degree/peer interventions reuse a shared batch. Dilution draws advance across models/sizes and are not paired with the separately sampled declared-topology control.


| Model | Intervention level | Mean anomaly probability | Recall at frozen threshold |
|---|---|---|---|
| M3_deep_sets | control | 0.9734 | 0.9625 |
| M4_gcn | control | 0.2582 | 0.015 |
| M5_gatv2 | control | 0.9253 | 0.71 |
| M6_set_transformer | control | 0.9651 | 0.86 |
| M7_np_st | control | 0.7588 | 0.95 |
| M8_set_transformer_mixed_n | control | 0.991 | 0.995 |


## F. Self-loop sweep

Same benchmark source; selection is on VALIDATION, with 20 declared /19 valid nodes. Retrain GCN for each candidate.


| Self-loop weight | Selected threshold | VAL anomaly F1 | VAL precision | VAL recall | VAL FPR |
|---|---|---|---|---|---|
| 1.0 | 0.225 | 0.4367 | 0.3231 | 0.6733 | 0.0993 |
| 2.0 | 0.2 | 0.4446 | 0.3339 | 0.6653 | 0.0935 |
| 3.0 | 0.2 | 0.4432 | 0.3573 | 0.5833 | 0.0739 |
| 5.0 | 0.15 | 0.5797 | 0.5093 | 0.6727 | 0.0456 |


## G. Fixed-topology slot-reassignment probe

Same source, `structural_probes.permutation_max_abs_score_delta`. [VERIFIED INTERPRETATION CORRECTION] Features are permuted while graph adjacency stays fixed. These values do not disprove graph permutation equivariance.


| Model | Maximum absolute score delta |
|---|---|
| M3_deep_sets | 1e-06 |
| M4_gcn | 0.926169 |
| M5_gatv2 | 0.058649 |
| M6_set_transformer | 0 |
| M7_np_st | 0 |
| M8_set_transformer_mixed_n | 0 |


## D / E, repeated refits: paired intervention endpoints

Source: [results/crossdevice_benchmark/seed_study.json](../../results/crossdevice_benchmark/seed_study.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL] Seeds 0–9 on one fixed split/probe corpus. Paired t intervals have df=9; training variability only. No population-resampling CI or multiplicity correction is established.


| Probe | Model | Endpoint change | Mean recall delta | SD | 95% interval | t | Negative seeds | n |
|---|---|---|---|---|---|---|---|---|
| degree | M4_gcn | 1->9 | -0.943 | 0.0479 | [-0.9773, -0.9087] | -62.24 | 10 | 10 |
| degree | M5_gatv2 | 1->9 | -0.2687 | 0.2145 | [-0.4222, -0.1153] | -3.962 | 10 | 10 |
| degree | M6_set_transformer | 1->9 | 0 | 0 | NOT REPORTED / undefined | NOT REPORTED / undefined | 0 | 10 |
| degree | M3_deep_sets | 1->9 | 0 | 0 | NOT REPORTED / undefined | NOT REPORTED / undefined | 0 | 10 |
| peer_density | M4_gcn | 0->36 | -0.3255 | 0.2875 | [-0.5312, -0.1198] | -3.58 | 8 | 10 |
| peer_density | M5_gatv2 | 0->36 | -0.4093 | 0.279 | [-0.6088, -0.2097] | -4.639 | 10 | 10 |
| peer_density | M6_set_transformer | 0->36 | 0 | 0 | NOT REPORTED / undefined | NOT REPORTED / undefined | 0 | 10 |
| peer_density | M3_deep_sets | 0->36 | 0 | 0 | NOT REPORTED / undefined | NOT REPORTED / undefined | 0 | 10 |



| Interaction comparison | Contrast | Mean | SD | 95% interval | t | n |
|---|---|---|---|---|---|---|
| M4_gcn | degree minus peer_density | -0.6175 | 0.2753 | [-0.8144, -0.4206] | -7.094 | 10 |
| M5_gatv2 | degree minus peer_density | 0.1405 | 0.3641 | [-0.12, 0.401] | 1.22 | 10 |
| across_models | (M4_gcn - M5_gatv2) of (degree minus peer_density) | -0.758 | 0.5118 | [-1.1241, -0.3919] | -4.683 | 10 |


## I. Virtual-generator validity boundary

Source: [results/final_verification/generator_validation.log](../../results/final_verification/generator_validation.log); producer [scripts/validate_virtual_device_generator.py](../../scripts/validate_virtual_device_generator.py). [VERIFIED FRESH DIAGNOSTIC] TRAIN: 103 resting source rows in 7 runs; 618 generated rows/42 blocks per preset. These are dependent residual observations, not held-out devices. Overall exit status 1 reflects failed stress marginal checks.


| Regime | Marginal diagnostic | Cross-node RMS spread | Permitted interpretation |
|---|---|---|---|
| LOW | Pass all four measured free coordinates | 0.00794 | Internal TRAIN residual consistency |
| MEDIUM | RMS marginal divergence | 0.01509 | OOD sensitivity regime |
| HIGH | RMS and peak marginal divergence | 0.03842 | OOD sensitivity regime |


The raw log retains every KS statistic/p-value, covariance and lag difference, classifier accuracy, clipping frequency and ordering check. A near-chance discriminator is not proof that real and virtual distributions are identical.

## J / L / M. M9 mixed-provenance and virtual-only ablation

Source: [results/crossdevice_benchmark/m9_seed_study.json](../../results/crossdevice_benchmark/m9_seed_study.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL, PROVENANCE-LIMITED] Ten refits; source artifact omits immutable input/code/cardinality fingerprints. Historical labels say real n=10; current main benchmark uses 20. Do not assume the seed-study file belongs to the seed-0 M9 protocol. LOW virtual test n=5; MEDIUM/HIGH retain LOW-fitted threshold.


| Regime | Metric | Mean | SD | 95% CI half-width | n seeds |
|---|---|---|---|---|---|
| real | threshold | 0.21 | 0.1591 | 0.1138 | 10 |
| real | f1 | 0.9675 | 0.0099 | 0.0071 | 10 |
| real | precision | 0.9521 | 0.0177 | 0.0126 | 10 |
| real | recall | 0.9845 | 0.0307 | 0.022 | 10 |
| real | false_positive_rate | 0.0035 | 0.0013 | 0.001 | 10 |
| real | detection_rate | 0.9845 | 0.0307 | 0.022 | 10 |
| real | roc_auc | 0.9996 | 0.0001 | 0.0001 | 10 |
| real | pr_auc | 0.9931 | 0.0036 | 0.0026 | 10 |
| low | threshold | 0.6125 | 0.2949 | 0.211 | 10 |
| low | f1 | 0.6812 | 0.0165 | 0.0118 | 10 |
| low | precision | 0.5175 | 0.0191 | 0.0136 | 10 |
| low | recall | 0.9972 | 0.001 | 0.0007 | 10 |
| low | false_positive_rate | 0.1641 | 0.0129 | 0.0092 | 10 |
| low | detection_rate | 0.9972 | 0.001 | 0.0007 | 10 |
| low | roc_auc | 0.9819 | 0.0028 | 0.002 | 10 |
| low | pr_auc | 0.8505 | 0.0177 | 0.0127 | 10 |
| medium | threshold | 0.6125 | 0.2949 | 0.211 | 10 |
| medium | f1 | 0.4636 | 0.0338 | 0.0242 | 10 |
| medium | precision | 0.3025 | 0.0286 | 0.0205 | 10 |
| medium | recall | 0.9979 | 0.0008 | 0.0006 | 10 |
| medium | false_positive_rate | 0.4082 | 0.0574 | 0.041 | 10 |
| medium | detection_rate | 0.9979 | 0.0008 | 0.0006 | 10 |
| medium | roc_auc | 0.9128 | 0.0398 | 0.0284 | 10 |
| medium | pr_auc | 0.5661 | 0.1264 | 0.0904 | 10 |
| high | threshold | 0.6125 | 0.2949 | 0.211 | 10 |
| high | f1 | 0.2952 | 0.0109 | 0.0078 | 10 |
| high | precision | 0.1732 | 0.0075 | 0.0054 | 10 |
| high | recall | 1 | 0 | 0 | 10 |
| high | false_positive_rate | 0.8341 | 0.0437 | 0.0313 | 10 |
| high | detection_rate | 1 | 0 | 0 | 10 |
| high | roc_auc | 0.69 | 0.0904 | 0.0647 | 10 |
| high | pr_auc | 0.2606 | 0.0873 | 0.0624 | 10 |
| ablation_real | threshold | 0.875 | 0.0707 | 0.0506 | 10 |
| ablation_real | f1 | 0.964 | 0.0181 | 0.0129 | 10 |
| ablation_real | precision | 0.94 | 0.0346 | 0.0247 | 10 |
| ablation_real | recall | 0.9901 | 0.0044 | 0.0031 | 10 |
| ablation_real | false_positive_rate | 0.0046 | 0.003 | 0.0022 | 10 |
| ablation_real | detection_rate | 0.9901 | 0.0044 | 0.0031 | 10 |
| ablation_real | roc_auc | 0.9993 | 0.0004 | 0.0003 | 10 |
| ablation_real | pr_auc | 0.989 | 0.0068 | 0.0048 | 10 |


Source: [results/crossdevice_benchmark/m9_ablation_investigation.json](../../results/crossdevice_benchmark/m9_ablation_investigation.json); producer [scripts/benchmark_crossdevice_models.py](../../scripts/benchmark_crossdevice_models.py). [EXPERIMENTAL, PROVENANCE-LIMITED] Frozen full-validation threshold; slices do not refit. Separate same-model hybrid versus virtual-only lineage. Normal-only slice F1 is undefined; its FPR remains reportable.


| Training lineage | Slice / metric | Mean | SD | 95% CI half-width | n seeds |
|---|---|---|---|---|---|
| hybrid | col:real_physical_cols | 0.8937 | 0.0788 | 0.0564 | 10 |
| hybrid | col:real_physical_cols:false_positive_rate | 0.0463 | 0.0165 | 0.0118 | 10 |
| hybrid | col:simulated_cols | 0.9849 | 0.0056 | 0.004 | 10 |
| hybrid | col:simulated_cols:false_positive_rate | 0.0017 | 0.0007 | 0.0005 | 10 |
| hybrid | scenario:NETWORK_NORMAL | NOT REPORTED / undefined | NOT REPORTED / undefined | NOT REPORTED / undefined | NOT REPORTED / undefined |
| hybrid | scenario:NETWORK_NORMAL:false_positive_rate | 0.0027 | 0.001 | 0.0008 | 10 |
| hybrid | scenario:SCENARIO_A | 0.86 | 0.2896 | 0.2071 | 10 |
| hybrid | scenario:SCENARIO_A:false_positive_rate | 0.0014 | 0.0005 | 0.0004 | 10 |
| hybrid | scenario:SCENARIO_B | 0.9794 | 0.0072 | 0.0051 | 10 |
| hybrid | scenario:SCENARIO_B:false_positive_rate | 0.0064 | 0.0023 | 0.0016 | 10 |
| hybrid | scenario:SCENARIO_C | 0.9807 | 0.0071 | 0.0051 | 10 |
| hybrid | scenario:SCENARIO_C:false_positive_rate | 0.004 | 0.0021 | 0.0015 | 10 |
| ablation | col:real_physical_cols | 0.9138 | 0.0058 | 0.0041 | 10 |
| ablation | col:real_physical_cols:false_positive_rate | 0.0601 | 0.0058 | 0.0042 | 10 |
| ablation | col:simulated_cols | 0.9776 | 0.0217 | 0.0155 | 10 |
| ablation | col:simulated_cols:false_positive_rate | 0.0021 | 0.0029 | 0.0021 | 10 |
| ablation | scenario:NETWORK_NORMAL | NOT REPORTED / undefined | NOT REPORTED / undefined | NOT REPORTED / undefined | NOT REPORTED / undefined |
| ablation | scenario:NETWORK_NORMAL:false_positive_rate | 0.0049 | 0.0026 | 0.0019 | 10 |
| ablation | scenario:SCENARIO_A | 0.9483 | 0.0129 | 0.0092 | 10 |
| ablation | scenario:SCENARIO_A:false_positive_rate | 0.0025 | 0.0009 | 0.0007 | 10 |
| ablation | scenario:SCENARIO_B | 0.9825 | 0.0133 | 0.0095 | 10 |
| ablation | scenario:SCENARIO_B:false_positive_rate | 0.0054 | 0.0044 | 0.0031 | 10 |
| ablation | scenario:SCENARIO_C | 0.9666 | 0.0159 | 0.0114 | 10 |
| ablation | scenario:SCENARIO_C:false_positive_rate | 0.0055 | 0.0046 | 0.0033 | 10 |


The historical virtual-only advantage remains [INCONCLUSIVE] after masking/cardinality changes. A matched controlled rerun is required for a causal attribution to provenance.

## N. Task-2 chronology and corrected novelty claim

Source: [results/astra_masking_review/historical_metrics.json](../../results/astra_masking_review/historical_metrics.json); producer [scripts/evaluate_gnn_baselines.py](../../scripts/evaluate_gnn_baselines.py). Historical snapshots retain producing commits and Git blob hashes. Each Task-2 row is a 4-way network scenario classification, not per-node anomaly F1.


| Chronology | Producer | Declared n | Representation label | TEST accuracy | VAL accuracy |
|---|---|---|---|---|---|
| early_10_node | ba562f7 | 10 | B1_concat_logreg | 0.6433 | 0.6592 |
| early_10_node | ba562f7 | 10 | B2_concat_mlp | 0.6567 | 0.6475 |
| early_10_node | ba562f7 | 10 | B0_anomalous_node_count | 0.4142 | 0.4592 |
| early_10_node | ba562f7 | 10 | GNN_node_embeddings | 0.6058 | 0.5792 |
| rebuilt_10_node | de3654a | 10 | B1_concat_logreg | 0.6533 | 0.67 |
| rebuilt_10_node | de3654a | 10 | B2_concat_mlp | 0.6567 | 0.6492 |
| rebuilt_10_node | de3654a | 10 | B0_anomalous_node_count | 0.4175 | 0.4575 |
| rebuilt_10_node | de3654a | 10 | GNN_node_embeddings | 0.6117 | 0.5758 |
| pre_audit_20_node | 162d4a6 | 20 | B1_concat_logreg | 0.5208 | 0.5417 |
| pre_audit_20_node | 162d4a6 | 20 | B2_concat_mlp | 0.5283 | 0.5333 |
| pre_audit_20_node | 162d4a6 | 20 | B0_anomalous_node_count | 0.3958 | 0.3833 |
| pre_audit_20_node | 162d4a6 | 20 | GNN_node_embeddings | 0.5375 | 0.5475 |
| corrected_20_node | 4f6afa2 | 20 | B1_concat_logreg | 0.5433 | 0.5375 |
| corrected_20_node | 4f6afa2 | 20 | B2_concat_mlp | 0.5267 | 0.5233 |
| corrected_20_node | 4f6afa2 | 20 | B0_anomalous_node_count | 0.3958 | 0.3833 |
| corrected_20_node | 4f6afa2 | 20 | GNN_node_embeddings | 0.5375 | 0.5475 |
| CURRENT + M6 (2026-09-07) | 4f6afa2 + nonfinite hardening + M6 arm | 20 | B1_concat_logreg | 0.5433 | 0.5375 |
| CURRENT + M6 (2026-09-07) | 4f6afa2 + nonfinite hardening + M6 arm | 20 | B2_concat_mlp | 0.5267 | 0.5233 |
| CURRENT + M6 (2026-09-07) | 4f6afa2 + nonfinite hardening + M6 arm | 20 | B0_anomalous_node_count | 0.3958 | 0.3833 |
| CURRENT + M6 (2026-09-07) | 4f6afa2 + nonfinite hardening + M6 arm | 20 | GNN_node_embeddings | 0.5375 | 0.5475 |
| CURRENT + M6 (2026-09-07) | 4f6afa2 + nonfinite hardening + M6 arm | 20 | M6_node_embeddings | 0.5983 | 0.6083 |


B0 Task 2 counts network anomalies, B1 is indexed concatenated logistic regression, B2 is indexed concatenated MLP; `GNN_node_embeddings` actually concatenates final scalar GCN scores before a logistic head. Corrected B0→B2 is 0.3958→0.5267 (delta +0.1309); pre-fix B2 0.5283 (delta +0.1325). B1 0.5433 exceeds GCN-score 0.5375 numerically. Verdict: SUPPORTED BUT WEAKER for indexed representation versus count; no graph-superiority claim.

**M6 arm added 2026-09-07** (evaluate_gnn_baselines.py previously had none — see 17 Claim B and [results/gcn_m6_corrected_comparison/task2_comparison.json](../../results/gcn_m6_corrected_comparison/task2_comparison.json)). A from-scratch model trained under this script's own protocol (correct valid-only class weighting from the start), NOT the runtime checkpoint. `M6_node_embeddings` is the best of all five Task-2 methods, beating `GNN_node_embeddings` by a wide margin; the companion Task-1 per-node run shows the same pattern more sharply (M6 test F1 0.9736 vs. GNN 0.5865) — a controlled, apples-to-apples result distinct from both the offline M1-M9 sweep (C05) and the separately-flawed runtime M6 checkpoint (O4).

### Task-1 B2 degradation — status table

| Field | Value |
|---|---|
| Claim | B2 (concat MLP) Task-1 anomaly F1 degraded 0.9662 → 0.9174 (false positives 28 → 270, false negatives 72 → 0) between `pre_audit_20_node` and `corrected_20_node` above |
| Status | CURRENT — reproduced fresh 2026-09-07 (byte-identical to the preserved run) |
| Source artifact | [results/astra_masking_review/historical_metrics.json](../../results/astra_masking_review/historical_metrics.json) (`metrics.results.B2_concat_mlp.test`); reproduced in [results/gnn_baselines/metrics.json](../../results/gnn_baselines/metrics.json) |
| Protocol | Fit TRAIN, threshold selected on VALIDATION (max F1), reported on TEST once; 20-node declared network, PENDING-node masking |
| Bug/fix state | Reflects the nonfinite/pending-node masking fix (4f6afa2 + hardening); the recall gain trades against precision — a real, measured degradation, not something to fix further here |
| Current/superseded | CURRENT — numerical authority for B2's Task-1 result; `pre_audit_20_node` is preserved chronology only |


## P. Policy comparison

Source: [results/policy_comparison/metrics.json](../../results/policy_comparison/metrics.json); producer [scripts/evaluate_policy_comparison.py](../../scripts/evaluate_policy_comparison.py). [PRESERVED GCN-ERA ARTIFACT; NOT CURRENT M6 POLICY VALIDATION] 2,933 accepted legacy TEST rows; comparators share two-score replay inputs. Fitting/threshold selection uses simulated VAL_002. These are offline policy classifications, not measured enforcement effectiveness. Current policy producers use GCN plus default M6 fusion; the saved runtime Q table lacks producing-model hashes.


| Policy | Accuracy | Macro-F1 | False-block rate | ALERT recall | BLOCK recall |
|---|---|---|---|---|---|
| P1_static | 0.6577 | 0.2744 | 0 | 0.99 | 0 |
| P2_static_optimised | 0.8646 | 0.5614 | 0.0076 | 0.585 | 0 |
| P6_static_constrained | 0.6662 | 0.2777 | 0 | 0.99 | 0 |
| P3_decision_tree | 0.777 | 0.6453 | 0.151 | 0.985 | 0.6061 |
| P4_multiclass_lr | 0.6679 | 0.441 | 0.0669 | 0.59 | 0.0606 |
| P5_adaptive_bandit | 0.7238 | 0.5271 | 0 | 0.96 | 0 |


P6 is constrained static, P5 contextual bandit. P6 searches under ALERT recall≥0.90 and false-block≤0.01 on validation. P5 was not trained with this constrained search; both meet those bounds descriptively on the saved TEST rows. P5 Macro-F1 exceeds P6. Neither detects the BLOCK class here.

**2026-09-07 comparator fix and finding** (see O4 and [results/gcn_m6_corrected_comparison/policy_comparison.json](../../results/gcn_m6_corrected_comparison/policy_comparison.json)): `evaluate_policy_comparison.py` is now explicitly pinned to `gcn` by default (was silently reading the ambient, now-M6-fitted `FUSION_MODEL_PATH`). A pinned rerun reproduces P1/P2/P6 within verified wall-clock-jitter tolerance, but P5 is stably different from this table's preserved number — evidence `models/adaptive_pdp_qtable.json` was itself retrained under the mismatched-artifact bug during the 2026-09-07 deployment. **Same day, final pass: closed — see O5** for a corrected, deterministic-clock, clean-provenance GCN-vs-M6 policy comparison (17 Claim D).

## Q. Held-out physical hardware

Source: [results/final_verification/hardware_evaluation.log](../../results/final_verification/hardware_evaluation.log); producer [scripts/evaluate_real_hardware.py](../../scripts/evaluate_real_hardware.py). [VERIFIED PRESERVED GCN-ERA REPLAY] One MPU6050 TEST session 20260902_221217. Reset/warm-up exclusion leaves 42 scored observations at threshold 0.6. Raw session has 116 rows.


| Endpoint | Count | Rate | Printed Wilson 95% interval | Limit |
|---|---|---|---|---|
| Rest false alarm | 5 / 12 | 41.7% | 19.3%–68.0% | Small dependent sample |
| Disturbance detection | 30 / 30 | 100% | 88.6%–100% | Hand-induced physical events; no cyberattack |
| SW-420 held-out | see Q2 below | — | — | see Q2 below — CLOSED 2026-09-07, no longer pending |


Two action-labelled windows have peak no greater than resting maximum; 28 movement-containing windows are also all detected. Do not drop the quiet windows silently or use this replay as twenty-device field evidence.

**2026-09-07: M6 comparison now exists.** `evaluate_real_hardware.py --relational-model {gcn,m6_deployed,m6_corrected}` (src/relational_pin.py) reproduces this exact table when pinned to `gcn`, and gives identical numbers for both M6 variants — no regression on the available physical evidence (Gate H). See O4 and [results/gcn_m6_corrected_comparison/hardware_comparison.json](../../results/gcn_m6_corrected_comparison/hardware_comparison.json).

## Q2. SW-420 (esp32-vib-002) held-out physical hardware (2026-09-07)
[CURRENT] Closes the "PENDING VALIDATION" gap in Q above. Until this pass, `esp32-vib-002` (SW-420) had exactly one labelled real-hardware capture (TRAIN-only) and zero held-out VALIDATION/TEST sessions. Two independent new capture sessions were collected under the identical operator-marked protocol Q uses for esp32-vib-001: VALIDATION (session `20260907_165627`, 299 records, 8/8 intervals marked, 299/299 matched to a gateway decision) and TEST (session `20260907_170639`, 343 records, 8/8 intervals marked, 343/343 matched).
**A real evaluator bug this exposed and fixed.** evaluate_real_hardware.py had DEVICE hardcoded to esp32-vib-001; src/splits.py's labelled_session_paths() is split-based, not device-based, so once an esp32-vib-002 session entered the same split-allocation manifest as an esp32-vib-001 session, the evaluator would have silently scored SW-420's trigger_rate-shaped readings through the MPU6050's Isolation Forest/LSTM-AE models. Fixed with an explicit --device argument and per-device row filtering in load_sessions()/score_all(); verified esp32-vib-001's published numbers (5/12 resting FP, 30/30 detection) reproduce byte-identically with the fix applied.

| Split, pin | Resting FP | Rate | Wilson 95% CI | Detection | Rate | Wilson 95% CI |
|---|---|---|---|---|---|---|
| VALIDATION, gcn | 0 / 70 | 0.0% | [0.0%, 5.2%] | 109 / 109 | 100.0% | [96.6%, 100.0%] |
| TEST, gcn | 0 / 108 | 0.0% | [0.0%, 3.4%] | 115 / 115 | 100.0% | [96.8%, 100.0%] |
| TEST, m6_corrected (deployed) | 0 / 108 | 0.0% | [0.0%, 3.4%] | 115 / 115 | 100.0% | [96.8%, 100.0%] |

No regression/difference between the GCN and the actually-deployed corrected-M6 relational pin on this device — consistent with the same finding already established for esp32-vib-001 (Q above, `results/gcn_m6_corrected_comparison/hardware_comparison.json`).
**Read qualification, not a "better sensor" claim.** SW-420 is a binary comparator switch, not an accelerometer -- trigger_rate reads exactly 0 on a still desk by construction (feature_engineering_sw420.py). A 0% resting false-positive rate here reflects a structurally easier discrimination problem than MPU6050's continuous-amplitude resting noise (5/12, 41.7%), not a better-calibrated pipeline. The Isolation Forest sub-score for this device is flat at 0.500 across every phase (not discriminating at all on ~620 total real rows); the fused decision is carried mostly by lstm/gnn. Two independent sessions is a real minimum, not a large sample -- the same caveat already applied to esp32-vib-001's 5/12.
Source for this section: `results/sw420_real_hardware/hardware_evaluation.log`, `results/sw420_real_hardware/hardware_results.json`, `results/sw420_real_hardware/summary.md`; producer `scripts/evaluate_real_hardware.py --device esp32-vib-002`; session allocation `data/splits/session_split.json`.

## Explainability: single-channel and exploratory rank-aware repair

Source: [results/final_verification/explainability_evaluation_corrected.log](../../results/final_verification/explainability_evaluation_corrected.log); producer [scripts/evaluate_explainability_level2.py](../../scripts/evaluate_explainability_level2.py). [VERIFIED PRESERVED GCN-ERA REPLAY] Single-channel evaluation uses flagged resolvable legacy TEST rows and a historical 0.5 threshold, not runtime 0.6. The separate minimal repair analysis pools labelled MPU captures across TRAIN/VALIDATION/TEST and is exploratory, not held-out validation. 2026-09-07: `--relational-model {gcn,m6_deployed,m6_corrected}` now pins this explicitly; default `gcn` reproduces the table below exactly. Not in the required GCN-vs-M6 comparison set, so no new M6 explainability headline number is reported.


| Protocol | Repair | Recovered / denominator | Interpretation |
|---|---|---|---|
| Single-channel TEST | GCN peer | 78 / 78 | Resolvable flagged subset |
| Single-channel TEST | IF feature | 1 / 2 | Tiny subset |
| Single-channel TEST | LSTM feature | 0 / 139 | Does not recover |
| Single-channel TEST | All | 79 / 219 | 36% < declared 70% target |
| Exploratory pooled captures | Best 1 of 5 | 0 / 182 | MPU-only; all-split analysis |
| Exploratory pooled captures | Best 2 of 5 | 11 / 182 | Not held-out |
| Exploratory pooled captures | Best 3 of 5 | 179 / 182 | 98% is a different metric; not a replacement for 36% |
| Exploratory pooled captures | Best 4 of 5 | 182 / 182 | Not held-out |


## R. Runtime stage latency, preserved historical measurement

Source: [results/latency/latency.json](../../results/latency/latency.json); producer [scripts/evaluate_latency_stages.py](../../scripts/evaluate_latency_stages.py). [HISTORICAL / REQUIRES CURRENT END-TO-END MEASUREMENT] Warm perf_counter_ns timing; snapshot environment in docs/ENVIRONMENT.md. Audit stage includes hash computation, excludes SQLite I/O. Mixed scalar/feature workload.


| Stage | Count | Mean ms | SD ms | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|---|
| authentication | 2933 | 0.0192 | 0.0137 | 0.0142 | 0.0354 | 0.0546 |
| security_trust | 2933 | 0.0109 | 0.0993 | 0.0067 | 0.0167 | 0.0266 |
| rule_detector | 2933 | 0.0038 | 0.005 | 0.003 | 0.0073 | 0.0101 |
| isolation_forest | 1000 | 5.1201 | 2.3546 | 4.1168 | 8.9815 | 10.6815 |
| lstm_ae | 1000 | 1.3823 | 2.7923 | 1.1738 | 2.4624 | 3.1695 |
| gnn | 2933 | 0.9104 | 3.3473 | 0.8608 | 1.5682 | 1.993 |
| fusion | 2933 | 0.2723 | 0.1531 | 0.2018 | 0.5383 | 0.7931 |
| policy | 2933 | 0.0083 | 0.0127 | 0.006 | 0.0146 | 0.0223 |
| explainability | 2933 | 0.0157 | 0.0109 | 0.0108 | 0.0277 | 0.0547 |
| audit_logging | 2933 | 0.0254 | 0.0186 | 0.0182 | 0.0498 | 0.0754 |
| total_pipeline | 2933 | 3.4891 | 5.389 | 1.454 | 11.3009 | 13.8442 |
| network_10_node_tick | 600 | 70.6737 | 16.3242 | 67.6454 | 100.341 | 112.953 |


Cold start: 1288.5 ms. The `network_10_node_tick` key is historical and must not be presented as a fresh 20-node measure. No bound on acquisition-to-enforcement latency follows.
