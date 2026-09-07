# Independent research/code review: cross-device benchmark and masking audit

**Scope.** Read-only review of `scripts/benchmark_crossdevice_models.py`, `scripts/evaluate_gnn_baselines.py`, the component training scripts, and artifacts under `results/crossdevice_benchmark`, `results/gnn_baselines`, and `results/astra_masking_review`. I did not rerun expensive training. Numbers below are transcribed from the checked-in JSON and checked against confusion-matrix arithmetic. Branch observed: `<historical-review-branch>`.

## Verdict

**Request changes for paper claims; implementation masking fix itself is supported.** The current artifacts strongly support the narrow claim that PENDING-node payloads are excluded consistently after the masking correction. They do not support broad claims of graph superiority, new graph representation learning, independent-sample confidence intervals, or permutation equivariance. M6 is the strongest single-seed M1–M9 row by test F1; M9 is useful as a robustness/provenance experiment but does not improve the in-distribution M6 result.

## Required findings

1. **Task-2 `GNN_node_embeddings` is materially misnamed.** The representation is the final scalar `P(normal)` output for every node, concatenated into a fixed-order vector, followed by logistic regression; no hidden embedding is extracted. See `evaluate_gnn_baselines.py:512-520`. The paper-safe description is **“logistic regression on the vector of per-node GCN anomaly scores.”** It is also order/index dependent. The artifact key remains `task2_network_coordination_pattern.GNN_node_embeddings`, but the implementation contradicts that name.

2. **The permutation probe is not a joint graph permutation/equivariance test.** It permutes `X`, leaves adjacency in the original slot order, then inverse-permutes outputs (`benchmark_crossdevice_models.py:1324-1346`). This tests sensitivity to reassigning device features among fixed topology slots. A true graph relabelling test must apply `PAP^T` to adjacency together with `PX` and compare `P f(A,X)` to `f(PAP^T,PX)`. Therefore the JSON key `structural_probes.permutation_max_abs_score_delta` can safely be called **fixed-topology slot-reassignment sensitivity**, not lack of permutation equivariance. Its values are M3 `0.000001`, M4 `0.926169`, M5 `0.058649`, M6/M7/M8 `0.0`.

3. **The statistical unit is not 22,800 independent observations.** Each reported Task-1 row is a `(tick,node)` window; windows are nested in only 15 anomaly events and four scenario streams, with temporal overlap/shared LSTM histories. `event_metrics` explicitly acknowledges this (`evaluate_gnn_baselines.py:362-386`). Thus ordinary row-level F1/ROC values are descriptive for this fixed test corpus. The ten-seed t intervals in `seed_study.json` and `m9_seed_study.json` quantify optimizer/initialization variability on the same fixed data, exactly as the code caveat says (`benchmark_crossdevice_models.py:1836-1858`); they are not confidence intervals for population/test-set generalization. Paper inference needs event/scenario/device-level resampling or genuinely independent repeated datasets.

4. **Task-2 cannot establish GNN superiority.** Test accuracies are B0 `0.3958`, B1 `0.5433`, B2 `0.5267`, and GCN-score vector `0.5375` (`gnn_baselines/metrics.json.task2_network_coordination_pattern`). B1 is numerically highest on test, while GCN is highest on validation (`0.5475` versus B1 `0.5375`). The code prints the test winner at lines 528-529; that is acceptable as post-hoc description, but not model selection. Correct novelty/result claim: indexed whole-network score vectors improve over a one-dimensional anomalous-node count on this fixed split; the GCN-derived score vector does not beat concatenated logistic regression.

5. **M8/M9 provenance language must remain precise.** The 20-node “real” benchmark is hybrid: 2 physical devices and 18 parametrically simulated nodes (`metrics.json.network`). M9 adds five LOW-heterogeneity virtual streams derived from `esp32-vib-001`, scored using that base device's fitted IF/LSTM models (`benchmark_crossdevice_models.py:457-507`). This is real-derived synthetic augmentation, not five additional independent physical devices. Current code dynamically concatenates all 20 hybrid columns with 5 virtual columns, so the pool is 25 columns despite stale 15-column comments/docstrings; its examples are not independent across provenance. Historical `m9_seed_study.json` does not embed pool width or input hashes, so its exact training width cannot be established from that artifact alone.

6. **M9 stress exposes severe calibration/precision failure.** In `m9_seed_study.json.summary`, the LOW-fitted threshold is frozen for MEDIUM/HIGH as intended (`benchmark_crossdevice_models.py:770-818`). Mean±training-seed CI: LOW F1 `0.6812±0.0118`, FPR `0.1641±0.0092`; MEDIUM F1 `0.4636±0.0242`, FPR `0.4082±0.0410`; HIGH F1 `0.2952±0.0078`, FPR `0.8341±0.0313`. Recall stays approximately 1 because the detector flags much of the normal population. A paper must report FPR/precision with recall and describe this as degradation under heterogeneity, not robustness.

7. **Single-seed M1–M9 rank differences are not uncertainty-qualified.** The canonical `metrics.json` declares one seed and one test split. Differences such as M6 F1 `0.9810` vs M7 `0.9721` vs M9 `0.9705` should be descriptive. The separate ten-seed mechanism study refits M3–M6 for structural probes, not the full M1–M9 comparison (`benchmark_crossdevice_models.py:1861-1910`).

## Exact canonical M1–M9 table

Source keys are `results/crossdevice_benchmark/metrics.json.results.<model>.{threshold_selected_on_validation,test,test_macro_f1,test_roc_auc,recall_isolated_anomaly,recall_coordinated_anomaly}`. All rows have `test.n=22800`; anomaly support is 1,500 (`150` isolated, `1,350` coordinated), normal support 21,300.

| Model | Val threshold | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Macro-F1 | ROC-AUC | Isolated recall | Coordinated recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 concat MLP | 0.800 | 1500 | 345 | 20955 | 0 | 0.8130 | 1.0000 | 0.8969 | 0.0162 | 0.9443 | 0.9998 | 1.0000 | 1.0000 |
| M2 gradient boosting | 0.250 | 1450 | 239 | 21061 | 50 | 0.8585 | 0.9667 | 0.9094 | 0.0112 | 0.9513 | 0.9969 | 0.9800 | 0.9652 |
| M3 Deep Sets | 0.150 | 1497 | 91 | 21209 | 3 | 0.9427 | 0.9980 | 0.9696 | 0.0043 | 0.9837 | 0.9998 | 0.9800 | 1.0000 |
| M4 GCN | 0.150 | 1059 | 1052 | 20248 | 441 | 0.5017 | 0.7060 | 0.5865 | 0.0494 | 0.7755 | 0.9458 | 0.0000 | 0.7844 |
| M5 GATv2 | 0.025 | 1491 | 73 | 21227 | 9 | 0.9533 | 0.9940 | 0.9732 | 0.0034 | 0.9857 | 0.9995 | 0.9733 | 0.9963 |
| M6 Set Transformer | 0.025 | 1496 | 54 | 21246 | 4 | 0.9652 | 0.9973 | 0.9810 | 0.0025 | 0.9898 | 0.9999 | 0.9800 | 0.9993 |
| M7 NP-ST | 0.700 | 1497 | 83 | 21217 | 3 | 0.9475 | 0.9980 | 0.9721 | 0.0039 | 0.9850 | 0.9997 | 0.9800 | 1.0000 |
| M8 mixed-cardinality ST | 0.025 | 1500 | 169 | 21131 | 0 | 0.8987 | 1.0000 | 0.9467 | 0.0079 | 0.9713 | 0.9997 | 1.0000 | 1.0000 |
| M9 mixed-provenance ST | 0.550 | 1497 | 88 | 21212 | 3 | 0.9445 | 0.9980 | 0.9705 | 0.0041 | 0.9842 | 0.9997 | 0.9800 | 1.0000 |

The exact artifact field names for timing/size are `train_time_ms_total`, `train_epochs`, `train_ms_per_epoch`, `inference_latency.{mean_ms,p50_ms,p95_ms,n}`, and `parameters`; do not rename them to generic `training_ms`, `epochs`, or `params` when extracting.

## Protocol and representation audit

- Train/validation/test are separately loaded; models fit train, thresholds maximize validation F1 on grid `{0.025,...,0.975}`, and test is evaluated at the frozen threshold (`evaluate_gnn_baselines.py:395-462`; benchmark `:1388-1464`). GCN self-loop weight is also selected on validation from `{1,2,3,5}`, yielding weight `5.0` and threshold `0.15`.
- M1/M2 use `3N` masked score blocks + `N` validity bits + `N` target one-hot: 100 features at N=20. B1/B2 in the baseline script use the same representation. B0 extracts only the target's three scores (`evaluate_gnn_baselines.py:215-241`). B3 uses a validity-gated network anomaly count (`:244-262`).
- M3/M5/M6/M7/M8/M9 receive `[rule, IF, LSTM, valid]` per node. M4 receives three score features and removes invalid nodes through per-snapshot adjacency plus pre-linear zeroing. Masked training losses include only valid targets (`evaluate_gnn_baselines.py:289-320`; benchmark `:354-385`).
- No feature standardizer is fitted inside either comparison script because inputs are already component scores. Upstream LSTM/Transformer autoencoders fit per-device mean/std on normal training sequences and save reconstruction-error mean/std (`train_lstm_ae.py:44-106`, `train_transformer.py:53-122`). Isolation Forest fits normal-only per device and saves the training-normal decision-function median (`train_isolation_forest.py:40-69`). Those are training-set calibrations, not held-out threshold estimates.
- Comparison neural models run fixed epochs (GCN 150; set-family 300) with no early stopping or restored best checkpoint. The baseline GNN is retrained after self-loop selection and only that final state is saved (`evaluate_gnn_baselines.py:440-455`). Cross-device M1–M9 models are evaluated in memory; `metrics.json` contains no checkpoint identity/hash, so exact model-to-row provenance relies on deterministic code/environment rather than persisted checkpoints.
- M8 samples random 20-node hybrid-network column subsets at cardinalities 2/3/5/10 each epoch (`benchmark_crossdevice_models.py:393-441`). Current M9 samples cardinalities 2/3/5/10/15 from a dynamically concatenated 25-column pool (20 hybrid + 5 virtual) (`:510-580`); 15 is the largest sampled subset, not the pool width. This validates exposure to variable cardinality, but every epoch consumes all snapshots for one sampled subset and the streams share scenarios/ticks; “mixed cardinality training” should not be described as independent networks. The historical seed-study artifact lacks embedded pool width, so its exact historical pool composition is unknown without commit-specific source reconstruction.

## Masking evidence and chronology

The current `results/gnn_baselines/metrics.json` is byte-identical to `results/astra_masking_review/metrics.json`; both self-loop files are byte-identical. `verification.json` additionally records semantic equality, replayed GNN weight equality, unchanged tracked model/data artifacts, and 143/143 passing tests. `finite_parity.json` shows identical representations/weights/outputs for several finite invalid placeholders. `adversarial_probes.json` shows each masking mutation was detected. Its `nonfinite_boundary` records failures for NaN and ±Infinity in concat, snapshot, and valid GNN outputs; this is historical red evidence, not a current green claim. The final commit chronology is explicit: pre-audit 20-node artifact at `162d4a6`, masking correction at `4f6afa2`, nonfinite hardening at `6d74a0e`, reconciliation docs at `4ecf2a8`.

Historical rows in `historical_metrics.json` must not be mixed: early 10-node (`ba562f7`), rebuilt 10-node (`de3654a`), pre-audit 20-node (`162d4a6`), and corrected 20-node (`4f6afa2`) differ in network size, trained component checkpoints, and/or masking. The artifact explicitly verifies pre-audit commits `c5cd38d` and `162d4a6` had identical metrics; the corrected artifact changes B0/B1/B2 because invalid payload leakage was removed while GNN/B3 numerical results remain the same.

## Structural-probe interpretation

The single-seed complete-graph dilution curve is an intervention outside the declared training topology; the artifact separately reports the declared-topology n=10 point. The ten-seed paired effects in `seed_study.json.paired_effects` are the strongest mechanism evidence because they compare intervention endpoints within seed: degree 1→9 mean recall delta M4 `-0.9430` (95% t interval `[-0.9773,-0.9087]`) and M5 `-0.2687` (`[-0.4222,-0.1153]`); peer density 0→36 M4 `-0.3255` (`[-0.5312,-0.1198]`) and M5 `-0.4093` (`[-0.6088,-0.2097]`). M3/M6 are flat by construction for topology-only interventions. These intervals still cover training-seed variability on synthetic probe draws with fixed RNG, not new datasets.

## Fusion/policy distinction

The M1–M9 and B0–GNN results evaluate anomaly-score fusion/classification. They do not evaluate PDP authorization policy, RL actions, enforcement latency, or end-to-end operational outcomes. Any policy result must cite the separate policy/fusion evaluation artifacts and its own statistical unit; no such inference follows from these JSONs.

## Paper-safe claims

- On this fixed 20-node hybrid test corpus, M6 had the best single-seed Task-1 F1 (`0.9810`) and M4 performed poorly on isolated anomalies (`0.0000` recall at its validation-selected max-F1 threshold).
- Validity masking makes finite PENDING placeholders representation/output invariant in the reviewed tests, and the replayed corrected metrics match the checked artifact.
- Fixed-topology slot reassignment strongly changes GCN outputs and modestly changes GATv2 outputs, while the set models are invariant under the tested feature permutation.
- Mixed-provenance training retains excellent discrimination on the fixed hybrid test (`M9 ROC-AUC 0.9997`) but degrades sharply in precision/FPR as virtual heterogeneity rises.
- Task 2 supports whole-network indexed representations over a one-dimensional anomaly count, but does not show the GCN-score vector outperforming the best concatenated baseline.

> Final reconciliation: this is a point-in-time independent review. The canonical paper package supersedes its interim wording. A fresh generator diagnostic is now preserved. Current M9 dynamically pools20+5=25 columns; historical15-column docstrings are not implementation evidence. Additional GAT empty-query hardening and the corrected sensor-scope explanation run were completed after the initial boundary review.
