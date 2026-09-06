# Experimental protocol and split master table

[VERIFIED: source allocation; limitations explicit] Physical sessions are allocated by [session_split.json](../../data/splits/session_split.json) and enforced by [splits.py](../../src/splits.py). TRAIN: MPU 20260902_171313 and weaker transcript reconstruction 20260902_102448; SW 20260905_162002. VALIDATION: MPU 20260902_173108. TEST: MPU 20260902_221217. Obsolete 20260901 sessions are excluded. No SW physical VALIDATION/TEST exists.

| Experiment | TRAIN / source | Validation / calibration | TEST / support | Seeds / cardinality / artifact |
|---|---|---|---|---|
| Local IF/LSTM | `training_session.json` for primary; network TRAIN for others | TRAIN-normal score mapping, not held-out probability calibration | Legacy TEST; 2,933 accepted messages, 3 identities | Fit seed 0; saved per-device models; fresh local log |
| Temporal Transformer | Merged TRAIN; normal runs | In-sample reconstruction baseline | Conditional 254-row primary-device fair subset | Seed 0; ablation-only; local log |
| Runtime GCN | Offline TRAIN replay and declared generated network training path | Offline model protocol, runtime self-loop 3 | Legacy three-identity replay; not canonical M4 | `models/gnn.pt`; no M6 involvement |
| Fusion | Frozen TRAIN base models | `validation_session.json`, simulated VAL_001 seed 4242; class-balanced fit | `test_session.json`, seed 999 | Four process scores; joblib/background files |
| Policy | Frozen process chain | `validation_policy_session.json`, VAL_002 seed 4243 | Same 2,933 accepted TEST rows | Six comparators; policy JSON |
| Task 1 / M1–M9 | Four `network_*_train.json`; 2,400×20 snapshots/rows | Separate 1,200 snapshots; max-F1 and self-loop selection | Four test scenarios; 22,800 valid rows; 150 isolated/1,350 coordinated anomalous | Seed 0; declared 20/held-out-valid 19; canonical metrics |
| Alarm-budget calibration | Same frozen relational models | Isotonic on one validation half, FPR cap on disjoint half | Same frozen TEST | 1%/3% budgets; separate rows in canonical metrics |
| Task 2 | TRAIN 4-way scenario labels | Validation accuracy reported | 1,200 network snapshots, four scenario classes | B0 network count, B1/B2 indexed scores, GCN-score vector; GNN baseline JSON |
| Topology probes | Same fitted relational models; valid score pools | Frozen thresholds | 400 generated trials/cell; controlled graphs | Single-seed and separate seeds 0–9; structural JSON |
| M8 | Cardinalities2/3/5/10 sampled from TRAIN network | Same network validation | Canonical20 plus constructed cardinality probes | Seed0 standalone row; ST weights not persisted |
| M9 | Current pool20 hybrid+5 LOW virtual; sizes2/3/5/10/15 | Full network validation for canonical row | Canonical20; separate virtual n5 stress lineage | Seed0 canonical; separate10-seed artifacts lack immutable run fingerprints |
| Generator validity | 103 MPU TRAIN rest rows, seven runs | Internal residual diagnostics using same TRAIN source | Generated618 rows/preset; no external device TEST | Deterministic preset/identity streams; validation log |
| Hardware replay | Current saved runtime chain | No TEST threshold fitting | MPU TEST, 116 raw→42 post-warmup rows | One physical test session; hardware log |

Exact producing scripts, hashes and output paths: [24](24_REPRODUCIBILITY_GUIDE.md), [inventory](../../results/final_verification/repository_inventory.json), [13](13_RESULTS_MASTER_TABLES.md). `training_session.json` has 15,493 records: 15,250 simulated and 243 real at-rest additions (103 MPU +140 SW). Both fusion/policy validation files contain 3,050 simulated rows. Legacy TEST contains 3,050 rows without complete `source_type` metadata; its generator/seed lineage supports describing it as legacy synthetic evaluation, not real hardware.

## Independence and limits

No inspected fit/threshold function loads TEST for parameter optimization. Base normalization and class weights use their designated training matrices. Neural comparison training uses fixed epochs rather than test-selected checkpoints. Validation-max-F1 and FPR-calibrated operating points must remain separate. `validation_halves` allocates temporal blocks within validation; disjoint row indices do not guarantee independent temporal observations or independent physical pools.

Ten refits reuse one fixed split. Their intervals describe optimizer/initialization variability, not uncertainty from new devices, capture sessions or test populations. Test-set reporting in repeated project development can still influence human design decisions; source-level split separation cannot prove a preregistered untouched research process. Preserved historical negative results and explicit chronology reduce, but do not eliminate, that risk.

Temporal TRAIN windows are checked before construction for session/scenario/phase and source-tick continuity. Resampled network ticks remain generated data and cannot establish physically contiguous acquisition. Scalar surrogate scores, invalid-node exclusions, warm-up/residue exclusions and shared capture pools are essential protocol details, not optional footnotes.
