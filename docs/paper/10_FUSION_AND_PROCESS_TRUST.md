# Fusion and Process Trust

[VERIFIED: current saved model] [FusionEngine](../../src/fusion_engine.py) loads `models/fusion_meta_learner.joblib` and `models/fusion_background.npy`. It consumes exactly `[rule_score, isolation_forest_score, lstm_ae_score, gnn_score]`. There is no Security Trust input, no raw sensor channel input and no M6/Set Transformer input.

The saved model is sklearn LogisticRegression with classes [0,1], four inputs and no additional feature scaler. In that order its coefficients are `[-0.0048296915, 3.2867543531, 4.3154399095, 5.0073982780]`, intercept `-7.2607392810`. Process Trust is `sigmoid(intercept + Σ coefficient_i * score_i) = P(normal)`. Exact precision and background shape (50×4) are preserved in [model_metadata.json](../../results/final_verification/model_metadata.json).

`train_fusion_meta_learner.py` fits class-balanced logistic regression on simulated VAL_001 after replaying frozen base detectors. Rejected/replay rows are excluded. Normal rows whose temporal window contains earlier anomalies are excluded rather than relabelled. It selects a background sample from this same training matrix for explanation. Local TRAIN and meta-training VALIDATION are separate; it is incorrect to describe this as held-out physical calibration.

Runtime returns `confidence=max(P(class))`, a decisiveness measure rather than a calibrated uncertainty interval. If model/background files are absent, it returns an arithmetic mean of the **four process scores** with confidence 0.5. This fallback does not blend Security and Process Trust, but it also is not the trained pipeline.

## Explanation and state

The code actually imports SHAP and constructs `shap.LinearExplainer(model, background)`. For the interventional linear explanation, contributions are background-centered `w_i*(x_i−E_background[x_i])`; expected log-odds plus contributions reconstruct the logistic margin. They are **log-odds contributions**, not additive changes in probability and not merely uncentered `w_i*x_i`. The largest absolute contribution determines the Level-1 explanatory signal. Level-2 repairs features or masks peer scores using the relevant detector; its metrics and thresholds are distinct experiments.

Gateway stores the fused probability in `ProcessAnomalyState`; silence retains the value and changes status. The same fresh fused output reaches the policy branch. As of 2026-09-07, runtime relational input comes from M6 (Set Transformer) in `models/set_transformer_runtime.pt` -- a checkpoint trained on this runtime's own replay pipeline (`scripts/train_set_transformer.py`), separate from both benchmark M4's network checkpoint and the offline M1-M9 sweep's own (unsaved) M6 runs. The prior time-coactive GCN checkpoint (`models/gnn_backup.pt`) is retained for reproducibility but no longer read by the live gateway.

## Standalone versus final fusion evidence

The corrected Level-2 replay reports79/219 single-channel recoveries at its historical 0.5 threshold (36%, below70% target). Separately,179/182 MPU disturbance windows recover under a best-three-channel repair, but that analysis includes TRAIN/VALIDATION/TEST captures and is exploratory. It does not replace the single-channel result or provide held-out98% explainability. See13's explanation table.

The fresh legacy replay and current saved coefficients are verified. They do not establish that M6 improves the final system. No matched comparison of Rule+IF+LSTM versus Rule+IF+LSTM+M6, with consistent train/calibration/test allocation and frozen final thresholds, exists in the inspected artifacts. Status: [REQUIRES FINAL FUSION VALIDATION]. An M6 adapter, checkpoint identity, meta-learner refit, calibration, policy evaluation and realistic latency measurement are required before a deployed-M6 claim. See [13 A/O](13_RESULTS_MASTER_TABLES.md) and [25](25_OPEN_ITEMS_BEFORE_SUBMISSION.md).
