# Fusion and Process Trust

[VERIFIED: configured serving and artifact selection, 2026-09-07] [FusionEngine](../../src/fusion_engine.py) loads `models/fusion_meta_learner.joblib` and `models/fusion_background.npy`. Both are byte-identical to the retained M6 variants. The gateway supplies `[rule_score, isolation_forest_score, lstm_ae_score, gnn_score]`; the last field now carries `SetTransformerScorer` output. It is a compatibility name, not evidence that a GCN produced the value. Security Trust never enters this model.

The four-input sklearn LogisticRegression returns `sigmoid(intercept + Σ coefficient_i * score_i) = P(normal)`. Current coefficients, artifact hashes and historical coefficient lineage are in the single [numerical authority](13_RESULTS_MASTER_TABLES.md). The older [model metadata](../../results/final_verification/model_metadata.json) describes the retained GCN-fitted backup, not today's active fusion. Do not combine that metadata with the current runtime.

[M6 fusion training](../../scripts/train_fusion_meta_learner_m6.py) replays frozen local/M6 scorers on simulated VAL_001, excludes rejected/replay records and normal windows containing earlier anomalies, and fits class-balanced logistic regression. Its background sample comes from that fit matrix. Base TRAIN and meta-training VALIDATION are separate; this is not held-out physical calibration. Serving loads artifacts and performs inference only.

`confidence=max(P(class))` expresses decisiveness, not calibrated uncertainty. Missing model/background files trigger the mean of four process scores with confidence 0.5. Missing relational weights can trigger a neutral score. Transport startup does not prove every learned model is loaded.

## Explainability and policy boundary

The implementation constructs `shap.LinearExplainer(model, background)` and calls `shap_values`. Actual SHAP is therefore computed. For this interventional logistic-linear explanation, background-centered contributions are `w_i*(x_i−E_background[x_i])`; the expected value plus their sum reconstructs the log-odds margin. They are not additive probability changes or causal effects. Isolation Forest Level 2 separately uses actual TreeExplainer; sequence and relational Level 2 use perturbations, which must not be relabeled SHAP.

The largest absolute fusion contribution selects a Level-2 explanation. Current M6 peer attribution removes a peer from the attention key set. Historical GCN peer attribution perturbs graph context. The compatibility field `gnn_score` is retained, while public Level-2 text calls it a relational score. No measurable peer perturbation is not proof that no peers are active.

The gateway stores Process Trust and supplies it alongside separate Security Trust to the configured offline contextual bandit. The saved Q table lacks producing model/data hashes. Its trainer still constructs GCN scores and default, now-M6 fusion, so a matched M6 policy-training lineage is **not verified**. Runtime lookup is implemented; comparative policy quality and end-to-end M6 policy validation remain open.

## Evidence and reproduction boundary

The preserved GCN-era local, hardware, policy and explainability results remain valid for their recorded protocols. Primary held-out single-channel repair is 79/219; exploratory best-three-channel repair is 179/182 across pooled splits. The latter does not replace the former. See [13](13_RESULTS_MASTER_TABLES.md).

The historical results log reports a GCN-to-M6 fusion improvement, but no matching machine-readable comparison receipt was found. After promotion, `evaluate_ablation_m6.py` loads default M6-fitted fusion for its labelled GCN arm. Legacy hardware/local/explanation evaluators also explicitly use GCN with default fusion. Running these commands now would mix model lineages. The retained GCN fusion/background pair must be selected explicitly in an isolated reproduction before a comparison is publishable. No measured artifact was overwritten in this pass.

Runtime-M6 training additionally calculates class weights over inactive labels before masking the loss. Training uses tick-based activity; serving/replay scorers use execution wall time. These limit validity and reproducibility. A correction requires a separately recorded retrain and evaluation, not editing old numbers. There is no matched local-only versus local-plus-M6 complementarity result, physical M6 field trial or acquisition-to-enforcement latency result. These are claim-scoped follow-ups in [25](25_OPEN_ITEMS_BEFORE_SUBMISSION.md).
