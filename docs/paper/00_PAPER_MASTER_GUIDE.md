# Verified paper reference: ZT-Duo

[CURRENT] Reconciled on 2026-09-07 against fetched `main` at `30079024b4159d08f293118c46ebd7e18f27008c`. This package is a paper-writing reference. Implementation and measured artifacts take precedence over narrative; historical metrics retain their original protocol. See the [readiness audit](../PAPER_READINESS_VERIFICATION.md) and [verification inventory](../../results/final_verification/repository_inventory.json).

ZT-Duo authenticates CPS telemetry, evaluates cyber behaviour and physical-process behaviour on separate trust-style scales, and uses both at a policy decision boundary. A compromised identity and an abnormal physical process require different responses. The runtime implements this separation with authenticated-behaviour Security Trust and local detectors plus an M6 (Set Transformer)/logistic Process Trust pipeline (M6 superseded GCN as the deployed relational scorer 2026-09-07; a confirmed class-weight training defect in that initial deployment was found and fixed the same day, and the corrected checkpoint/fusion/policy were promoted after a full gate review — see [17](17_CLAIM_EVIDENCE_MATRIX.md) C03/C05/C15 and [13](13_RESULTS_MASTER_TABLES.md) O4/O5). The four policy actions are ALLOW, ALERT, STEP_UP and BLOCK.

The research benchmark compares M1–M9 on a 20-node constructed heterogeneous network. M6 Set Transformer is the selected standalone relational candidate, with Macro-F1 0.9898 and FPR 0.0025 at its validation-selected operating point. Separately, the gateway loads a runtime M6 checkpoint (the corrected one, as of the 2026-09-07 promotion) and its matched logistic fusion. Offline scenario verification exercises this integration, confirmed by direct gateway-module introspection (`results/m6_corrected_policy/runtime_verification.json`). The GCN-to-M6 gain is now a persisted, correctly pinned comparison via `src/relational_pin.py` — a modest, held-out-replay-qualified gain on fusion (~1-1.2 Macro-F1 points) and policy (+0.0029 macro-F1); quote it with that qualifier, not as unconditional superiority. All numbers resolve to the [master result tables](13_RESULTS_MASTER_TABLES.md).

## Evidence that can carry the paper

- [VERIFIED] Code and tests enforce separate trust evidence and rejection-state isolation. The actual gateway policy branch uses an offline contextual bandit by default; the static two-score table remains available.
- [EXPERIMENTAL] The corrected fixed-split M1–M9 benchmark favors M6 by Macro-F1, FPR and anomaly F1. This is descriptive evidence, not universal superiority or a significance result.
- [VERIFIED] Pending-node masking repairs and regression evidence are retained. The final audit additionally excludes nonfinite invalid content before model arithmetic.
- [EXPERIMENTAL] Controlled topology interventions expose architecture-dependent score/recall sensitivity. The historical feature permutation is a fixed-topology reassignment probe, not a test of graph equivariance.
- [VERIFIED] Physical captures exist for one ESP32/MPU6050 and one ESP32/SW-420. **[UPDATED 2026-09-07]** Both now have held-out physical validation/test sessions — SW-420's closed this date (`results/sw420_real_hardware/summary.md`): VALIDATION 0/70 resting FP, 109/109 detection; TEST 0/108 resting FP, 115/115 detection, identical under both the GCN and the deployed corrected-M6 relational pin. Two sessions is a real minimum, not a large sample. The constructed benchmark also contains eighteen legacy simulated identities.

## Limitations that must travel with the results

The preserved GCN-era held-out MPU6050 replay detects 30/30 disturbances but flags 5/12 resting windows after its stated warm-up exclusion. SW-420 has only a TRAIN capture. LOW generator validation is an internal TRAIN-residual diagnostic; MEDIUM/HIGH remain stress regimes. Temporal Transformer and NP-ST do not establish a deployment advantage. Task-2 B0 is a network-wide count, not a single-device comparator. The strongest cross-device claim is indexed representations versus this count; graph superiority is unsupported. Multi-seed intervals measure refit variability on a fixed corpus. Existing runtime latency excludes broker transit, acquisition and SQLite persistence.

Do not claim twenty physical devices, two MPU6050 devices, physical end-to-end M6 validation, unconditional runtime-M6 superiority (the verified gain is modest and held-out-replay-qualified), full reinforcement learning, compliance certification, graph necessity or population-level generator realism. The deployed M6's class-weight bug (which DID include inactive placeholders) is fixed as of the 2026-09-07 promotion — do not describe it as a live defect. Read the [claim gate](17_CLAIM_EVIDENCE_MATRIX.md) and [open items](25_OPEN_ITEMS_BEFORE_SUBMISSION.md) before drafting the Abstract.

## Canonical document index

| File | Role |
|---|---|
| [01 Problem](01_RESEARCH_PROBLEM_AND_MOTIVATION.md) | Motivation and bounded research questions |
| [02 Architecture](02_SYSTEM_ARCHITECTURE.md) | Runtime, candidate and implementation contracts |
| [03 Threat model](03_THREAT_MODEL_AND_ZERO_TRUST_DESIGN.md) | Authentication, transport and trust boundaries |
| [04 Provenance](04_HARDWARE_DATA_AND_PROVENANCE.md) | Physical sessions and every constructed node |
| [05 Features](05_PROCESS_FEATURES_AND_PREPROCESSING.md) | Modality schemas and temporal construction |
| [06 Local models](06_LOCAL_ANOMALY_MODELS.md) | Training, inference and ablation status |
| [07 M1–M9](07_RELATIONAL_MODELS_M1_M9.md) | Architectures and selection decision |
| [08 Topology](08_TOPOLOGY_AND_ROBUSTNESS_ANALYSIS.md) | Mechanisms and permutation interpretation |
| [09 Generator](09_VIRTUAL_DEVICE_GENERATION.md) | Equation and validated regime boundary |
| [10 Fusion](10_FUSION_AND_PROCESS_TRUST.md) | Actual logistic model and candidate gap |
| [11 Policy](11_POLICY_ENGINE.md) | Actions, comparator constraints and evidence |
| [12 Protocol](12_EXPERIMENTAL_PROTOCOL.md) | Dataset/split master table |
| [13 Results](13_RESULTS_MASTER_TABLES.md) | Single numerical source for writing |
| [14 Statistics](14_STATISTICAL_ANALYSIS.md) | Units, intervals and significance limits |
| [15 Hardware validation](15_HARDWARE_VALIDATION.md) | Captures versus fresh replay evidence |
| [16 Negative results](16_ABLATIONS_AND_NEGATIVE_RESULTS.md) | Rejections and superseded interpretations |
| [17 Claims](17_CLAIM_EVIDENCE_MATRIX.md) | Contribution and wording gates |
| [18 Limitations](18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md) | Threats to validity |
| [19 Figures/tables](19_FIGURE_AND_TABLE_PLAN.md) | Evidence-backed publication artifact plan |
| [20 Related work](20_RELATED_WORK_POSITIONING.md) | Literature work still needed |
| [21 Outline](21_FINAL_PAPER_OUTLINE.md) | Evidence-first IEEE-style structure |
| [22 Factsheet](22_PAPER_READY_FACTSHEET.md) | Fast reference |
| [23 Terminology](23_TERMINOLOGY_AND_NOTATION.md) | Canonical notation and labels |
| [24 Reproduction](24_REPRODUCIBILITY_GUIDE.md) | Commands, inputs and unavailable evidence |
| [25 Open items](25_OPEN_ITEMS_BEFORE_SUBMISSION.md) | P0/P1/P2 priorities |
| [Cleanup manifest](REPOSITORY_CLEANUP_MANIFEST.md) | Preservation and normalization decisions |

Writing order: Experimental Methodology → Results → Architecture/Methods → Discussion → Limitations → Introduction → Related Work → Conclusion → Abstract. Claims should follow validated results. The package supports evidence-bounded paper writing. Submission still requires the explicitly listed submission items; software integration does not certify a running physical deployment.
