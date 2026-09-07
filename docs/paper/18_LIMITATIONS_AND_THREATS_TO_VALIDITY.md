# Limitations and threats to validity

## Internal validity

Model and threshold fitting use designated splits, but the project has evolved after inspecting test results. The repository cannot prove preregistration or absence of human test-informed redesign. Pending masking and 10→20-node composition changes were not a matched factorial experiment. Some benchmark JSONs lack code/input/checkpoint fingerprints. Offline replay filters stored authentication labels rather than verifying original wire envelopes, and some stateful replays use execution wall time. These limits prevent a blanket “leakage-free and fully reproducible” assertion.

## External validity

Only one MPU6050 physical source has held-out evaluation. SW-420 is a different sensing modality and has only TRAIN data. Eighteen benchmark identities are parametrically simulated; five separate virtual streams are derived from the same MPU source. Network cardinality is not independent-device support. Hand-induced motion on an ESP32 sensor is not a representative industrial failure population.

## Construct validity

Scores estimate normality under constructed labels, not physical safety or an adversary's intent. Scenario classification in Task 2 can exploit indexed patterns and differs from relational anomaly detection. B0 there is a global count, and the named GNN embeddings are scalar node scores. SW-420 zero activity cannot distinguish rest from a disconnected/misadjusted sensor. Implemented crest factor is peak-to-peak/RMS. The historical graph permutation test changes feature-to-topology assignment rather than graph labels.

## Statistical conclusion validity

Ten-seed intervals estimate refit variability on fixed data. Adjacent windows, events, node rows and generated trajectories are dependent. Generator KS tests and row-wise discriminator folds do not provide independent hardware realism tests. Single-seed M1–M9 point differences are not significance evidence. Hardware Wilson intervals are descriptive small-sample summaries and do not remove session dependence. Multiple tests are not documented as multiplicity-adjusted.

## Hardware limitations

The post-warm-up MPU replay has 5/12 false resting alarms despite 30/30 disturbance detection. Board/build/firmware hash and calibrated clock measurements are absent. SW validation/test sessions, potentiometer documentation and independent-device repeats are pending. Early captures with an obsolete acquisition chain are excluded and preserved.

## Generated-data limitations

Real-source network rows are resampled with replacement. Current SW local training counts 1,940 normal rows but only 140 original resting capture rows; temporal generated ticks are not physically contiguous raw acquisition. Primary temporal training is fragmented and yields only 244 length-eight windows. Virtual trajectories wrap short runs and share source sessions. LOW is an internal residual-consistency regime; MEDIUM/HIGH fail marginal diagnostics and show downstream false-alarm degradation. Mixed-provenance historical conclusions remain confounded.

## Deployment limitations

Current serving uses M6 with M6-fitted fusion (unchanged by the 2026-09-07 comparator repair below).

**Comparator artifact mismatch — fixed 2026-09-07.** `evaluate_ablation_m6.py`, `evaluate_real_hardware.py`, `evaluate_policy_comparison.py` and `evaluate_explainability_level2.py` all constructed `FusionEngine()` with no arguments, silently reading the ambient `config.FUSION_MODEL_PATH` — correct until the M6 deployment overwrote it, after which every "GCN arm" paired true GCN scores with M6-fitted fusion. Fixed via explicit, hash-verified artifact pinning (`src/relational_pin.py`); see `results/comparator_repair/comparator_audit.json` for the full audit and `docs/paper/13_RESULTS_MASTER_TABLES.md` O4 for the corrected comparisons this made possible.

**Runtime-M6 class-weight bug — confirmed with numbers, fixed in a non-deployed checkpoint.** `scripts/train_set_transformer.py` computed its inverse-frequency class weights over the full, unmasked node-target tensor, but the loss only trains on the `valid`-masked ~8.9% of it. Verified against `training_session.json`: this inflated the suspicious-class weight to 45.18 vs. the correct 6.27 — a 7.2x overweight, materially distorting the training signal (not a cosmetic difference). Its effect is visible directly: the deployed checkpoint's standalone relational score is badly miscalibrated (Macro-F1 0.0736 on held-out replay, near-zero normal recall at the deployed threshold), while a checkpoint retrained after the one-line fix reaches 0.7926. The fix is applied to the training script; the deployed `set_transformer_runtime.pt` is untouched (verified byte-identical before/after) — the corrected checkpoint (`set_transformer_corrected.pt`) exists for evaluation/comparison only, not as a proposed redeployment.

**Replay-clock alignment — investigated, LIMITED_EFFECT for the GCN-vs-M6 comparison.** Training's per-tick activity window (`EDGE_WINDOW_TICKS=1`, corresponding to ~2s given the generator's `tick*2000`ms timestamps) differs from serving's wall-clock window (`GNN_EDGE_WINDOW_SECONDS=5.0`, `time.time()`-based) — same order of magnitude, and identically shared by both `train_gnn.py` and `train_set_transformer.py`/both live scorers, so this is not a differential threat to a GCN-vs-M6 comparison specifically. It does, however, make any evaluation that drives the live scorers in a loop (e.g. `evaluate_policy_comparison.py`) non-deterministic run-to-run in its raw input scores — verified directly (two identical runs of the same pinned code produced different `s_sec`/`s_proc` values). This is a pre-existing property of the live-scorer path, not introduced by this repair.

**Policy artifact provenance — a new finding, not corrected.** A GCN-pinned rerun of `evaluate_policy_comparison.py` reproduces P1/P2/P6 (pure threshold policies) within the wall-clock jitter above, but P5 (adaptive bandit) is *stably* different from its preserved historical number (0.5132 vs. 0.5271 macro-F1, verified stable across 3 repeated runs) — evidence that `models/adaptive_pdp_qtable.json` was itself retrained during the M6 deployment via `train_adaptive_pdp.py`, which has the identical GCN-scores-with-M6-fusion bug at training time. No policy retrain was performed in this pass (explicit scope decision); a GCN-vs-M6 policy comparison remains INVALID COMPARATOR.

**Task-2 M6 arm — new, correctly implemented from the start.** `evaluate_gnn_baselines.py` had no M6 arm; one was added (a from-scratch training run under that script's own protocol, with class weights correctly computed over valid nodes only from the outset — informed by, not repeating, the bug above). It substantially outperforms the existing GNN arm on both Task 1 (test F1 0.9736 vs. 0.5865) and Task 2 (test accuracy 0.5983 vs. 0.5375) on this controlled, same-information comparison — distinct from both the offline M1–M9 sweep and the (separately flawed) runtime checkpoint.

These defects and fixes bound the corrected comparisons in `docs/paper/13_RESULTS_MASTER_TABLES.md` O4 and the split claims in `docs/paper/17_CLAIM_EVIDENCE_MATRIX.md`; they do not change the frozen M1–M9 benchmark numbers. Historical hardware/explanation logs describe the GCN-era chain and are now reproducible again via explicit pinning (default `gcn`); the deployed policy Q-table's provenance is not. Physical heavy-shake through the webpage remains unverified. Missing model artifacts can trigger neutral/mean fallback despite valid transport startup. Firmware broker-certificate verification is incomplete/unvalidated across modalities. Replay state and revocation durability are limited; the 600-second freshness tolerance is a demonstration accommodation. Simulation keys are deterministically derived public research credentials and unsuitable as production identities. HTTPS is substituted for CoAP. Historical stage latency excludes network transit, acquisition and SQLite persistence. Standards mappings are not certification.

These constraints bound the claims in [17](17_CLAIM_EVIDENCE_MATRIX.md) and generate the prioritized actions in [25](25_OPEN_ITEMS_BEFORE_SUBMISSION.md). They must remain explicit in the paper rather than being softened by aggregate benchmark accuracy.
