# Ablations, negative results and superseded interpretations

Negative findings constrain the architecture and are part of the research record. Numerical sources are [13](13_RESULTS_MASTER_TABLES.md), [RESULTS chronology](../../RESULTS.md), [baseline audit](../PAPER_GNN_BASELINE_VERIFICATION.md) and preserved [historical metrics](../../results/astra_masking_review/historical_metrics.json).

| Experiment / observation | Current interpretation | Architectural consequence / paper-safe wording |
|---|---|---|
| Temporal Transformer fair comparison ties LSTM | [REJECTED / ABLATION-ONLY] No current deployment advantage | Retain LSTM; report the negative architecture comparison |
| NP-ST adds gated local path | [EXPERIMENTAL NEGATIVE] No balanced advantage over M6 | Soft residual preservation is not guaranteed and extra parameters are not justified by this result |
| GCN isolated recall zero at chosen point | [CURRENT] Poor isolated-anomaly performance in the constructed benchmark | Keep as mechanism/runtime-lineage comparator; do not claim graph necessity |
| GCN target-degree sensitivity | [CURRENT EXPERIMENTAL] Consistent with aggregation dilution | Topology affects representation under these interventions |
| GATv2 peer-density sensitivity | [CURRENT EXPERIMENTAL] Learned attention does not eliminate structural sensitivity | Report peer-density effects and seed variation |
| M8 higher FPR than M6 | [CURRENT] Cardinality robustness trades in-distribution errors | Do not call mixed-cardinality training an unconditional improvement |
| M9 LOW→MEDIUM→HIGH degradation | [CURRENT FOR SAVED PROTOCOL] High recall accompanies very high false alarms | Report FPR/precision and keep high heterogeneity OOD |
| Virtual-only versus hybrid superiority | [INCONCLUSIVE] Corrected masking and cardinality/provenance changes confound chronology | Do not claim either training provenance universally wins |
| Earlier M1/M2 isolated collapse | [SUPERSEDED INTERPRETATION] Missing-node leakage was found; corrected recall recovers | Preserve original numbers and initial distribution-gap diagnosis as historical, not current causal explanation |
| Task-2 cross-device claim | [SUPPORTED BUT WEAKER] Indexed representations improve a network-count comparator | B0 is not single-device; best concat exceeds GCN-score vector numerically |
| Old graph permutation conclusion | [REJECTED INTERPRETATION] Adjacency was not jointly permuted | Call it fixed-topology slot reassignment, not failure of graph equivariance |
| Current hardware resting FPR | [VERIFIED] 5/12 in held-out post-warm-up replay | Physical cross-session generalization is limited |
| SW held-out performance | [PENDING VALIDATION] TRAIN capture exists, no physical VAL/TEST | No two-sensor held-out accuracy claim |
| Final M6 fusion | [IMPLEMENTED; COMPARATIVE VALIDATION RESOLVED 2026-09-07] Active corrected-M6 checkpoint/fusion; pinned comparator (`src/relational_pin.py`) and valid-only class weights, both fixed | Modest, held-out-replay-qualified gain over GCN is measured (13 O4/O5) — cite with that qualifier, not as unconditional superiority |
| Nonfinite pending inputs | [FIXED IN FINAL AUDIT] NaN/Infinity survived late masks | Canonicalize before arithmetic; retain red and green tests |
| Mixed-sensor explainability repair analysis | [CORRECTED EVALUATION] MPU-only routine ingested SW rows | Explicit sensor scope before sequence construction; preserve failure log |
| Single-channel explanation repair | [VERIFIED NEGATIVE]79/219 (36%) recover versus70% target | Separate exploratory all-split best-three-channel179/182 result cannot replace the failed single-channel result |

Historical chronology is not erased: initial observation → proposed distribution-gap interpretation → masking defect → corrected evaluation → revised conclusion. The 10-node historical, 20-node pre-fix and corrected 20-node Task-2 metrics remain separately available. Source repair does not retroactively attest undocumented past runs. Old M9 seed-study labels and missing immutable fingerprints remain provenance limitations even when the code now uses a 25-column pool.
