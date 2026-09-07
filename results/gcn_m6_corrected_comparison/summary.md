# GCN vs M6 corrected comparison — summary

**Date:** 2026-09-07. **Commit lineage:** starts from `2175ebe` (documentation audit HEAD); this work's own commits follow in `git log`. **Seed:** 0 throughout (`config.TRAINING_SEED`). Deployed runtime artifacts (`set_transformer_runtime.pt`, `fusion_meta_learner.joblib`, `gateway.py`) are **unchanged** — verified byte-identical hashes before and after this work.

## What this fixes

A prior audit found but deliberately deferred fixing: `evaluate_ablation_m6.py`, `evaluate_real_hardware.py`, `evaluate_policy_comparison.py` and `evaluate_explainability_level2.py` all built their "GCN arm" via bare `FusionEngine()`, which reads the ambient `config.FUSION_MODEL_PATH` — correct until the 2026-09-07 M6 deployment overwrote it with the M6-fitted model. Every "GCN arm" since then silently paired true GCN relational scores with M6-calibrated fusion coefficients. Fixed via `src/relational_pin.py`: three explicit, hash-verified `RelationalPin`s (`gcn`, `m6_deployed`, `m6_corrected`), with constructor-level overrides added to `GNNScorer`, `SetTransformerScorer` and `FusionEngine` so a comparator can bypass ambient config entirely. Full audit: `results/comparator_repair/comparator_audit.json`.

## Two new findings

1. **Class-weight bug in `scripts/train_set_transformer.py`, confirmed with numbers.** Class weights were computed over the full, unmasked node-target tensor; the loss only trains on the `valid`-masked ~8.9% of it. Verified against `training_session.json`: this inflated the suspicious-class weight to 45.18 vs. the correct 6.27 — a 7.2x overweight. Effect: the *deployed* M6 checkpoint's standalone relational score is badly miscalibrated (Macro-F1 0.0736, near-zero normal recall at threshold 0.6); a checkpoint retrained after the one-line fix reaches 0.7926. Fixed in the training script; a new, **non-deployed** `set_transformer_corrected.pt` exists for comparison only.
2. **Policy Q-table provenance corrupted.** `models/adaptive_pdp_qtable.json` was retrained during the M6 deployment commit via `train_adaptive_pdp.py`, which has the identical bug at *training* time. A GCN-pinned rerun of `evaluate_policy_comparison.py` shows P1/P2/P6 (threshold-only policies) reproduce within verified wall-clock jitter, but P5 (the bandit) is *stably* 0.5132 vs. the preserved 0.5271 — a real, reproducible gap, not noise. Not corrected (no policy retrain performed — explicit scope decision).

## Results

| Category | GCN | M6 (deployed) | M6 (corrected) | Verdict |
|---|---|---|---|---|
| Standalone Macro-F1 | 0.2734 | 0.0736 | **0.7926** | Deployed M6's raw score is badly miscalibrated; corrected fixes it |
| Fused Macro-F1 | 0.5679 | 0.5787 | **0.5798** | Both M6 variants modestly beat GCN fusion (~1-1.2 pts), held-out-replay qualified |
| Hardware (30/30 det., 5/12 resting FP) | same | same | same | No regression on available physical evidence |
| Latency (mean, standalone) | **1.08ms** | 1.92ms | 2.08ms | GCN ~1.8-2x faster; both well within pipeline latency budget |
| Task-1 (benchmark protocol) | 0.5865 F1 | — | **0.9736 F1** (from-scratch M6 arm, new) | M6 architecture substantially stronger on this same-information task |
| Task-2 (4-way coordination) | 0.5375 acc | — | **0.5983 acc** (from-scratch M6 arm, new) | M6 best of five methods |
| Policy | P5=0.5271 (historical, now unreproducible) | not attempted | not attempted | INVALID COMPARATOR — no M6 policy artifact, and the GCN baseline's own provenance is now suspect |

## Retraining decision (objective §7)

**C: both a comparator fix AND a targeted M6 retrain were required** — comparator-only repair was NOT sufficient, because the deployed M6 checkpoint's own training had a confirmed, material defect independent of the comparator bug. GCN required no retrain (no equivalent defect found). Policy was evaluated and found to need retraining too (Q-table provenance), but that retrain was explicitly out of scope for this pass per user decision — reported as an open finding, not silently done or silently ignored.

## What remains open

- No M6-trained policy artifact (Claim D stays INVALID COMPARATOR).
- SW-420 physical VALIDATION/TEST still doesn't exist (not invented here).
- Whether to redeploy `set_transformer_corrected.pt` in place of the current checkpoint is a separate decision this work does not make — the deployment fact (Claim A) is unchanged.
- Full test suite, verification scripts and exact commit hashes: see the session's final report.
