# Open items before submission

Only evidence-backed gaps are listed. A blocker is scoped to the claim it prevents; the paper can sometimes omit that claim instead of inventing evidence.

## P0 — paper claim blockers

1. **Final selected-model end-to-end claim:** M6 has no serving/fusion integration or matched complementarity result. Implement a checkpointed adapter, compare local-only versus local+M6 under identical splits, refit/calibrate fusion and evaluate final policy before claiming deployed M6. Otherwise frame M6 as a standalone candidate.
2. **Heterogeneous held-out physical claim:** SW-420 has one TRAIN capture and no physical VALIDATION/TEST. Obtain disjoint sessions or explicitly restrict held-out hardware results to MPU6050.
3. **Low-false-alarm physical claim:** Current MPU replay flags 5/12 resting windows. Obtain a controlled calibration/generalization study without test tuning before claiming hardware operational reliability.
4. **Formal graph-permutation claim:** Existing probe is not joint graph relabelling. Correct the experiment and retain historical numbers, or remove the invalid order-dependence claim. The documentation now removes that interpretation.
5. **Literature novelty/priority claim:** Related work has not been independently verified in this task. Complete primary-source comparison before “first,” “novel” or superiority claims.

## P1 — important before submission

- Freeze exact source/data/checkpoint/command/seed provenance for M1–M9 and M9 seed-study reruns; the old JSON metadata cannot attest every original run cardinality.
- Run corrected-mask 10-versus20 experiments with matched data composition/threshold protocol to separate cardinality from masking and training-chain changes.
- Preserve source-row identity for resampled physical data. Compare raw-session-only SW training and fix/rebuild primary temporal fragmentation if it is changed; current nominal support exaggerates independent observations.
- Perform proper joint graph permutation and all-invalid snapshot checks where those inputs are permitted. Pending payload masking is now tested for nonfinite values; low-level all-invalid model behavior needs an explicit API contract.
- Establish independent-session/block generator validation and uncertainty; LOW is currently an internal fit diagnostic.
- Evaluate P5/P6 under explicitly matched deployment constraints and deterministic timestamp replay; retain the zero BLOCK recall and per-class supports.
- Measure acquisition-to-enforcement latency including broker transit, queuing, explanation and actual persistence. Existing timing is partial/historical.
- Validate broker certificate verification on both actual firmware builds; document freshness tolerance, persistent replay state and model-readiness startup requirements for production claims.
- Regenerate publication figures from the canonical numbers and retain code/input hashes. Pin a reproduction environment.

## P2 — optional strengthening

Add independent physical devices of the same modality for manufacturing variation; independent sites/load regimes; grouped multi-seed uncertainty and multiplicity policy; broader correlated fault families; robustness to missingness mechanisms; cost-matched alternative architectures. These should strengthen a defined claim, not expand the narrative without evidence.

Resolved during this audit: mandatory pytest availability; preserved standalone generator diagnostic; nonfinite invalid-content boundaries; sensor-mixing explainability evaluation defect; explicit Task2/policy/permutation wording; canonical documentation and numerical tables. Resolution evidence is under [final_verification](../../results/final_verification). No new physical capture, M6 deployment, expensive full benchmark rerun or literature-priority proof is implied.
