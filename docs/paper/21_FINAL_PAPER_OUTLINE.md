# Evidence-first IEEE-style paper outline

This outline is a writing plan, not paper prose. All numbers resolve to [13](13_RESULTS_MASTER_TABLES.md); claims pass [17](17_CLAIM_EVIDENCE_MATRIX.md). Write methodology/results before the Introduction and Abstract.

| Section / subsection | Purpose / evidence source | Numbers / figure-table | Allowed claim / avoid |
|---|---|---|---|
| I Introduction | Problem and bounded contribution;01/17 | Physical count2, benchmark20 with qualifier; Fig1 | Separate concerns; avoid unverified first/novel priority |
| II Related Work | Compare verified literature;20 | No invented citation; comparison table if supported | Position evidence; avoid universal superiority |
| III System/Problem/Threat Model | Trust assumptions, attacker powers, labels;03/23 | Freshness600s, thresholds0.6; TableI | Implemented threat scope; avoid certification |
| IV Architecture and policy boundary | Configured runtime (corrected M6, 13 O5), benchmark and historical chain;02/11 | Registry22 vs benchmark20; Fig2/3 | Corrected-M6 serving exists (checkpoint/fusion/policy all promoted 2026-09-07); avoid physical deployment claims beyond the available hardware evidence |
| V Security Trust | Gates, rejection isolation, EWMA;02/03 | Alpha0.35, bounded decay; TableI | Tested state contract; avoid DoS immunity |
| VI-A Local detection: features | Sensor math/schema;05 | MPU5/SW4; rates/windows; TableII | Exact features; avoid conventional crest definition mismatch |
| VI-A Local detection: models | TRAIN and inference models;06 | Fair temporal comparison13A; TableVI | Ablation tie; avoid Transformer advantage |
| VI-B Relational models | M1–M9 and masks;07 |13B/C, params/latency; Fig5/TableIV | Standalone candidate comparison |
| VI-C Process fusion | Four-score logistic model;10 | Saved coefficients; TableVII | Historical GCN metrics; configured M6 integration; comparative effectiveness pending |
| IV-B Policy boundary | Static/bandit, overrides and constraints;11 |13P; Fig9/TableVIII | Contextual bandit; avoid P6 global-best claim |
| VII-A Hardware | Physical evidence grade;04/15 | Session counts; TableIII | Two modalities; held-out MPU only |
| VII-B Provenance | Raw/parametric/virtual distinctions;04/12 |48k TRAIN/22.8k valid TEST rows; Fig4 | Constructed network; not physical sample size |
| VII-C Simulation/generation | Equation/regimes/seeds;09 | Presets and internal check13I | Measured structure with sensitivity parameters |
| VII-D Training | Base→fusion→policy order;06/07/12 | Cardinalities, fixed epochs; TableIV | Offline fits; no live learning |
| VII-E Evaluation | Splits, thresholds, exclusions;12 |15 events;42 hardware rows; TableIX | Explicit protocol; no hidden denominator switching |
| VII-F Statistics | Dependence and refit CI;14 |10 seeds, df9; TableV | Refit variability; not population CI |
| VIII-A Local results | Baselines and fair subset;13A | Positive-class convention explicit | Conditional temporal tie |
| VIII-B/C M1–M9 / isolated-coordinated | Balanced error tradeoff;13B/C | M6 Macro-F1/FPR; Fig5 | Descriptive best at this operating point |
| VIII-D Topology | Degree/peer/self-loop/permutation;08/13 | Paired deltas and all seed signs; Fig6 | Consistent with mechanism; not formal proof |
| VIII-E Cardinality | M8 and dilution;07/13H | Tested sizes; Fig7 | Extrapolation within constructed setting |
| VIII-F/G Generator/M9 | Validity boundary and stress;09/13I–M | FPR with recall; Fig8 | Preserve degradation and inconclusive ablation |
| VIII-H Fusion | Runtime replay and gap;10/13O4/O5 | Corrected-M6 vs GCN fusion, held-out replay | Modest, held-out-replay-qualified gain only; no invented M6 gain |
| VIII-I Policy | Shared triples/constraints, deterministic clock;11/13O5/P | Macro-F1, ALERT, false BLOCK, rare class; corrected-M6 vs fair-GCN-baseline | Constrained comparison with limitations; BLOCK unreachable for both arms (architectural, report as-is) |
| VIII-J Hardware | Physical held-out discrimination;15/13Q |5/12 false alarms,30/30 detection; Fig10 | Small-sample physical replay, not attack prevention |
| IX Discussion | Explain architecture consequences;16/17 | Negative evidence TableVI | Qualify combined interpretation |
| X Limitations | Internal/external/statistical validity;18 | TableX | Preserve actual gaps |
| XI Conclusion | Supported findings and bounded next work | No new numbers | Match verified scope |

Abstract and title should be settled last. A title implying physically validated M6 effectiveness or graph necessity would misrepresent the evidence. Configured serving may be described with its explicit validation limits. Figure/table existence and regeneration status are in [19](19_FIGURE_AND_TABLE_PLAN.md).
