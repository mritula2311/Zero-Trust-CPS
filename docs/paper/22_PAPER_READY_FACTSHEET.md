# Paper-ready factsheet

| Item | Verified reference |
|---|---|
| Project | ZT-Duo / Zero-Trust-CPS; implemented gateway and research benchmark |
| Goal | Separate cyber-behaviour authenticity concerns from physical-process abnormality |
| Architecture | Security Trust and Process Trust meet at static/contextual-bandit policy; [02](02_SYSTEM_ARCHITECTURE.md) |
| Security | Identity, revocation, HMAC, finite payload, boot/seq, freshness gates; accepted-only EWMA; [03](03_THREAT_MODEL_AND_ZERO_TRUST_DESIGN.md) |
| Process | Rule+IF+LSTM→runtime M6→four-score logistic fusion; high means normal; [10](10_FUSION_AND_PROCESS_TRUST.md) |
| Hardware | One MPU6050-equipped and one SW-420-equipped ESP32; both now have held-out VALIDATION/TEST as of 2026-09-07 (SW-420: 0/108 resting FP, 115/115 detection); [04](04_HARDWARE_DATA_AND_PROVENANCE.md) |
| Features | MPU5, SW4; peak-to-peak/RMS crest definition; [05](05_PROCESS_FEATURES_AND_PREPROCESSING.md) |
| Local models | IF/LSTM runtime; Transformer ablation-only; [06](06_LOCAL_ANOMALY_MODELS.md) |
| Relational model status | M6 is selected in the standalone benchmark; a corrected M6 checkpoint is deployed in serving as of the 2026-09-07 promotion, comparative fusion/policy gain over GCN now measured (held-out-replay-qualified); [07](07_RELATIONAL_MODELS_M1_M9.md), [10](10_FUSION_AND_PROCESS_TRUST.md) and [13 O4/O5](13_RESULTS_MASTER_TABLES.md) |
| M6 headline | Macro-F1 0.9898; FPR0.0025; precision0.9652; isolated recall0.9800; coordinated0.9993; ROC-AUC0.9999; [13 B](13_RESULTS_MASTER_TABLES.md) |
| M6 cost |2,609 parameters; saved mean inference1.3448ms,200 samples; [13 R/S](13_RESULTS_MASTER_TABLES.md) |
| Data |20-node constructed benchmark,2 physical-source+18 legacy simulated;19 valid held-out; [04](04_HARDWARE_DATA_AND_PROVENANCE.md) |
| Generator | Five additional MPU-derived virtual streams; LOW internal consistency, higher regimes stress; [09](09_VIRTUAL_DEVICE_GENERATION.md) |
| Policy | Corrected-M6 contextual bandit (`adaptive_pdp_qtable_m6_corrected.json`) selected in runtime as of the 2026-09-07 promotion, macro-F1 0.5332 vs. a fair clean-provenance GCN baseline 0.5303; P6 constrained static comparator; [11](11_POLICY_ENGINE.md) and [13 O5](13_RESULTS_MASTER_TABLES.md) |
| Explanation | Actual linear SHAP in log-odds plus modality-aware detector perturbations; [10](10_FUSION_AND_PROCESS_TRUST.md) |
| Task2 | B0 count0.3958; B2 indexed MLP0.5267; B1 indexed LR0.5433; GCN-score vector0.5375; corrected-M6 arm 0.5983 (best of five, 2026-09-07); [13 N](13_RESULTS_MASTER_TABLES.md) |
| Hardware result | 30/30 disturbances, 5/12 resting false alarms — identical across GCN, originally-deployed M6 and corrected M6 (no regression); [13 O4/O5, Q](13_RESULTS_MASTER_TABLES.md) |
| Demonstration interface | Static implementation/demonstration presentation, no gateway connection, not a research contribution; [design/](../../design/README.md) |
| Strong contributions | Implemented two-score separation; auditable explanation; controlled benchmark/mechanism evidence; corrected-M6 comparative fusion/policy gain (held-out-replay-qualified); [17](17_CLAIM_EVIDENCE_MATRIX.md) |
| Negative findings | Transformer tie, GCN isolation failure, M8/M9 tradeoffs, hardware false alarms, BLOCK unreachable for either policy arm; [16](16_ABLATIONS_AND_NEGATIVE_RESULTS.md) |
| Limits | Fixed-split refit CIs; one physical identity per modality, no manufacturing/fleet generalization; no full physical network. M6 comparative/training/policy provenance gaps are RESOLVED as of 2026-09-07 (13 O4/O5); [18](18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md) |
| Pending work | Claim-scoped blockers and reproduction gaps; [25](25_OPEN_ITEMS_BEFORE_SUBMISSION.md) |

Numbers are protocol-specific references to13; do not recombine them into a single system-wide accuracy, latency or “final model” row. Fresh runtime verification refers to tests and offline replay, not a newly observed live hardware deployment.
