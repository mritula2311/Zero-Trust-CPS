# Figure and table plan

No paper figures were fabricated. Two figure sets are tracked separately here: Fig1-Fig4 are CONCEPTUAL/ARCHITECTURE diagrams for the eventual paper draft, still proposed and not yet rendered. The result-generated figures below are COMPLETE as of 2026-09-07, produced by `scripts/generate_corrected_m6_figures.py` from the corrected-M6 evidence, superseding every figure previously under [docs/figures](../figures) (the old `fig1`-`fig17`/`figA`-`figD` set, predating the comparator repair, was deleted — see `docs/paper/REPOSITORY_CLEANUP_MANIFEST.md`'s 2026-09-07 follow-up entry and RESULTS.md's Figure Index for the record).

| No. / title | Purpose and source | Script / artifact | Exists / regeneration / status |
|---|---|---|---|
| Fig1: Problem formulation | Separate forged identity and physical fault; architecture doc | Conceptual schematic from 02/03 | Proposed; no empirical visual claim |
| Fig2: Actual and candidate architectures | Configured corrected-M6, separate benchmark M6 and historical GCN lineage | 02, gateway and fusion source | Mermaid in02 exists; publication redraw required |
| Fig3: Two-trust decision flow | Two axes meet at policy | policy_engine / adaptive_pdp | Proposed; regenerate with explicit protocol (the historical figB this row referenced was deleted 2026-09-07, see follow-up entry above) |
| Fig4: Hardware/data provenance | Two physical modalities,18 simulated, separate5 virtual | 04, split manifest, node profiles | Proposed; no20-device photograph implied |

## Result-generated figures (COMPLETE, 2026-09-07, refined the same day)

Every figure reads directly from a `results/*.json`/`.log` artifact, or recomputes with the exact same replay logic an `evaluate_*.py` script uses (the hardware score-distribution figure calls `evaluate_real_hardware.score_all()` directly) — no number is invented. Regenerate all 15 with `python scripts/generate_corrected_m6_figures.py`.

Two tiers. **Paper-ready figures** (added in a same-day refinement pass, priority-labelled by the requester) supersede six of the original R-numbered figures outright — R1/R3/R4/R5/R6/R14 were deleted, not left redundant, because the new versions answer the same question with more precisely specified panels (e.g. the model-performance figure below combines what R1/R3/R8 showed separately; the policy figure switched from a two-arm GCN-vs-M6 comparison to a single-arm precision/recall/F1 diagnostic of the actually-deployed policy, which is the more paper-relevant question). R2/R7-R13/R15 are unaffected.

| Title | Type | Source | Priority |
|---|---|---|---|
| Corrected GCN vs. M6 performance (`model_performance_gcn_vs_m6.png`) | 2-panel: grouped bar + bar | standalone/fusion Macro-F1 (`gcn_m6_corrected_comparison/{standalone,fusion}_comparison.json`) + Task-2 (`task2_comparison.json`) | **Must have** — main model-performance figure |
| Policy action performance (`policy_action_performance.png`) | Grouped bar | `results/m6_corrected_policy/policy_action_metrics.json`, deployed corrected-M6 arm | **Must have** |
| Hardware validation (`hardware_validation.png`) | Compact rate/count bar with Wilson CI | `results/gcn_m6_corrected_comparison/hardware_comparison.json`, deployed corrected-M6 arm | High |
| Local detector attack-class recall (`local_detector_attack_class_recall.png`) | Grouped bar (Rule/IF/LSTM-AE only) | `results/final_verification/local_fusion_evaluation.log` [GCN-era preserved replay, labelled as such] | High |
| M6 training correction (`m6_training_correction.png`) | 2-panel before/after bar | class-weight fix, checkpoint F1 + weight magnitude (13 O4) | Optional (discussion/ablation) |
| Pending-node/B2 masking correction (`pending_node_masking_correction.png`) | 2-panel before/after bar | Task-1 F1 + false positives (13 N) | Optional |
| R2: M1-M9 relational benchmark | Horizontal grouped bar | `results/crossdevice_benchmark/metrics.json` | High / may go to supplementary |
| R7: GCN vs M6 latency | Grouped bar | `results/gcn_m6_corrected_comparison/latency_comparison.json` | Medium |
| R8: Fusion comparison | Grouped bar | `results/gcn_m6_corrected_comparison/fusion_comparison.json` | High |
| R9: Topology sensitivity | Line plot | `results/crossdevice_benchmark/metrics.json` structural_probes | Optional — include only if topology robustness is a final contribution claim |
| R10: Generator validity/OOD behavior | Bar (RMS spread) | doc 13 I / `results/final_verification/generator_validation.log` | Medium |
| R11: Explainability contribution distribution | Grouped bar | `models/fusion_meta_learner_{gcn_backup,m6_corrected_variant}.joblib` coefficients | Optional |
| R12: Policy confusion matrix | Heatmap (2 panels) | `results/m6_corrected_policy/confusion_matrix_*.csv` | Optional |
| R13: Hardware score distributions | Box plot (2 panels) | live replay via `evaluate_real_hardware.score_all()`, pinned gcn/m6_corrected | Very useful |
| R15: Seed/statistical robustness | Error-bar (forest plot) | `results/crossdevice_benchmark/seed_study.json` paired_effects | Optional |

| Table | Content / numerical source | Key message / status |
|---|---|---|
| I | Threat model /03 | Implemented controls and unaddressed threats |
| II | Features /05 | Modality-specific width/units and crest definition |
| III | Hardware/provenance /04 | Physical support separated from generated row counts |
| IV | M1–M9 /13 B | Descriptive standalone selection; no fused-M6 claim |
| V | Topology /13 D–H | Controlled mechanisms and correct permutation interpretation |
| VI | Negative results /16 | Preserve failed models and superseded diagnosis |
| VII | Fusion /10 and13 A/O4/O5 | Current (corrected-M6) artifact identity; correctly-pinned GCN-vs-M6 fusion AND policy comparison now measured, held-out-replay-qualified |
| VIII | Policy /13 P | Comparator constraint tradeoffs |
| IX | Hardware /13 Q | Small dependent sample, false alarms included |
| X | Validity limits /18 | Scope of admissible claims |

Every exported chart should record source artifact hash, generator command, metric polarity, threshold protocol, cardinality, provenance and status in its caption/source notes. A plot generated from superseded numbers must remain marked historical until regenerated.

## Figure types and publication gate

Fig1 is CONCEPTUAL. Fig2 is an ARCHITECTURE DIAGRAM. Fig3 must label a static-policy schematic CONCEPTUAL; any observed policy chart is MEASURED RESULT for its saved protocol. Fig4 is GENERATED FROM VERIFIED ARTIFACT (provenance inventory), not a photograph of a physical fleet. Every figure in the result-generated table above is MEASURED RESULT / GENERATED FROM VERIFIED ARTIFACT, using the exact `results/` source mappings listed there — the local-detector attack-class-recall figure alone carries an explicit [GCN-era preserved replay] qualifier in its title since no equivalent M6-runtime per-signal breakdown exists. None of these labels turns a proposed figure (Fig1-Fig4) into completed evidence; the result-generated set already is.
