# Figure and table plan

No paper figures were fabricated in this audit. Existing images under [docs/figures](../figures) are historical/generated artifacts until their source data and labels are matched to the current numerical reference. The following plan specifies reproducible content; proposed figures still require rendering and visual verification.

| No. / title | Purpose and source | Script / artifact | Exists / regeneration / status |
|---|---|---|---|
| Fig1: Problem formulation | Separate forged identity and physical fault; architecture doc | Conceptual schematic from 02/03 | Proposed; no empirical visual claim |
| Fig2: Actual and candidate architectures | Configured M6, separate benchmark M6 and historical GCN lineage | 02, gateway and fusion source | Mermaid in02 exists; publication redraw required |
| Fig3: Two-trust decision flow | Two axes meet at policy | policy_engine / adaptive_pdp | Historical figB exists; regenerate with explicit protocol |
| Fig4: Hardware/data provenance | Two physical modalities,18 simulated, separate5 virtual | 04, split manifest, node profiles | Proposed; no20-device photograph implied |
| Fig5: M1–M9 error tradeoff | Macro-F1, precision, FPR, isolated/coordinated recall | benchmark / crossdevice metrics | Regenerate from current13 B; do not reuse stale eight-model chart |
| Fig6: Topology intervention | Degree and peer-density changes with seed intervals | benchmark / seed_study | Regenerate; label refit CI, df9 |
| Fig7: Mixed-cardinality dilution | M6/M8 and graph baselines versus declared sizes | benchmark / structural_probes | Regenerate; complete-graph/control labels explicit |
| Fig8: M9 stress | F1 and FPR across LOW/MEDIUM/HIGH | benchmark / m9_seed_study | Regenerate; provenance-limited lineage qualifier |
| Fig9: Policy comparison | Four actions, constraints and rare BLOCK failure | evaluate_policy_comparison / metrics | Regenerate; P5 bandit/P6 constrained static |
| Fig10: Physical replay | Rest false alarms and disturbance detections | evaluate_real_hardware / fresh log | Historical figA exists; regenerate from42-row subset with denominators |

| Table | Content / numerical source | Key message / status |
|---|---|---|
| I | Threat model /03 | Implemented controls and unaddressed threats |
| II | Features /05 | Modality-specific width/units and crest definition |
| III | Hardware/provenance /04 | Physical support separated from generated row counts |
| IV | M1–M9 /13 B | Descriptive standalone selection; no fused-M6 claim |
| V | Topology /13 D–H | Controlled mechanisms and correct permutation interpretation |
| VI | Negative results /16 | Preserve failed models and superseded diagnosis |
| VII | Fusion /10 and13 A/O | Current artifact identity, historical GCN performance and M6 comparison gap |
| VIII | Policy /13 P | Comparator constraint tradeoffs |
| IX | Hardware /13 Q | Small dependent sample, false alarms included |
| X | Validity limits /18 | Scope of admissible claims |

Every exported chart should record source artifact hash, generator command, metric polarity, threshold protocol, cardinality, provenance and status in its caption/source notes. A plot generated from superseded numbers must remain marked historical until regenerated.

## Figure types and publication gate

Fig1 is CONCEPTUAL. Fig2 is an ARCHITECTURE DIAGRAM. Fig3 must label a static-policy schematic CONCEPTUAL; any observed policy chart is MEASURED RESULT for its saved protocol. Fig4 is GENERATED FROM VERIFIED ARTIFACT (provenance inventory), not a photograph of a physical fleet. Fig5–Fig10 are MEASURED RESULT / GENERATED FROM VERIFIED ARTIFACT, using the exact 13 source mappings. Additional M6 gain plots are OPTIONAL and blocked until a correctly pinned comparison exists. None of these labels turns a proposed figure into completed evidence.
