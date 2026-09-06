# Local anomaly models

[VERIFIED: code/checkpoints; CURRENT: fresh replay] Numerical results live in [13](13_RESULTS_MASTER_TABLES.md). Local evaluation prints precision/recall/F1 for **normal** class 1; relational tables instead treat anomalies as positive. These metrics must not share an unlabeled F1 column.

| Model | Implementation / offline script | Input and TRAIN | Score / threshold | Checkpoint | Status and rationale |
|---|---|---|---|---|---|
| Rule | `trust_engine.rule_range_score` | Registry ranges; no fitting | High normality, static Process Trust threshold 0.6 in replay | None | Runtime baseline; transparent but misses in-range constructed faults |
| Isolation Forest | `isolation_forest_scorer.py`; `train_isolation_forest.py` | Normal authenticated per-device rows, sensor width 5 or 4 | Decision function mapped using TRAIN-normal median; clipped normality | `models/isolation_forest_<id>.joblib` + metadata | Runtime; retain complementary point-model detection |
| LSTM-AE | `lstm_ae_scorer.py`; `train_lstm_ae.py` | Eight-step contiguous normal TRAIN runs, per-device mean/std | Reconstruction error z-score mapped to clipped normality | `models/lstm_ae_<id>.pt` + metadata | Runtime sequence detector; correlated residuals and calibration limits |
| Temporal Transformer AE | `transformer_scorer.py`; `train_transformer.py` | Same primary normal runs; denoising Transformer input width follows sensor | Reconstruction-score mapping; same deployment threshold in fair comparison | `models/transformer_ae_<id>.pt` + metadata | [REJECTED / ABLATION-ONLY]; fair retraining shows no deployment advantage |

The local-score replay uses 2,933 accepted messages from 3,050 legacy test records. Only 1,000 are primary MPU rows; the two scalar identities mirror rule scores in the IF/LSTM/Transformer positions. Its fair temporal comparison excludes 746 normal rows contaminated by preceding anomaly-window residue, leaving 254 rows: both temporal models have accuracy 0.945 and normal-class F1 0.935 at printed precision. This conditional subset result is not an estimate of overall gateway accuracy.

SW-420 checkpoints exist with four-channel metadata. All 140 raw at-rest readings are zero; IF normal median is zero and reconstruction-error variance is extremely small. Existence of a checkpoint does not validate disturbance performance, sensor attachment, potentiometer setting, or held-out generalization. The current Transformer training pipeline contains models for the two physical identities only; the IF/LSTM chain additionally has models for eighteen simulated nodes. Parameter counts and latency for relational models are distinct from local-model size/timing and are not interchangeable.

Sources: [datasets](../../src/datasets.py), [metadata](../../results/final_verification/model_metadata.json), [fresh evaluation log](../../results/final_verification/local_fusion_evaluation.log), [historical stage latency](../../results/latency/latency.json). Local latency is gateway-host timing, not ESP32 execution. Scalar fallback, warm-up and training-support limitations must accompany any retention argument.

Direct checkpoint inspection counted LSTM parameters: MPU 3,029 and SW 2,884; Transformer parameters: MPU 17,701 and SW 17,636. These are saved model weight counts, distinct from the relational costs. The models are scored on the gateway host; no ESP32 neural inference latency is claimed.
