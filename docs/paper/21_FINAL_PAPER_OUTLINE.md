# Evidence-first IEEE-style paper outline

This outline is a writing plan, not paper prose. All numbers resolve to [13](13_RESULTS_MASTER_TABLES.md); claims pass [17](17_CLAIM_EVIDENCE_MATRIX.md). Write methodology/results before the Introduction and Abstract.

| Section / subsection | Purpose / evidence source | Numbers / figure-table | Allowed claim / avoid |
|---|---|---|---|
| I Introduction | Problem and bounded contribution;01/17 | Physical count2, benchmark20 with qualifier; Fig1 | Separate concerns; avoid unverified first/novel priority |
| II Related Work | Compare verified literature;20 | No invented citation; comparison table if supported | Position evidence; avoid universal superiority |
| III System/Problem/Threat Model | Trust assumptions, attacker powers, labels;03/23 | Freshness600s, thresholds0.6; TableI | Implemented threat scope; avoid certification |
| IV Architecture | Actual gateway versus candidate;02 | Registry22 vs benchmark20; Fig2/3 | Runtime GCN; avoid deployed M6 |
| V Security Trust | Gates, rejection isolation, EWMA;02/03 | Alpha0.35, bounded decay; TableI | Tested state contract; avoid DoS immunity |
| VI-A Physical features | Sensor math/schema;05 | MPU5/SW4; rates/windows; TableII | Exact features; avoid conventional crest definition mismatch |
| VI-B Local detection | TRAIN and inference models;06 | Fair temporal comparison13A; TableVI | Ablation tie; avoid Transformer advantage |
| VI-C Relational models | M1–M9 and masks;07 |13B/C, params/latency; Fig5/TableIV | Standalone candidate comparison |
| VI-D Process fusion | Four-score logistic model;10 | Saved coefficients; TableVII | GCN fusion measured; M6 extension pending |
| VII Policy | Static/bandit, overrides and constraints;11 |13P; Fig9/TableVIII | Contextual bandit; avoid P6 global-best claim |
| VIII-A Hardware | Physical evidence grade;04/15 | Session counts; TableIII | Two modalities; held-out MPU only |
| VIII-B Provenance | Raw/parametric/virtual distinctions;04/12 |48k TRAIN/22.8k valid TEST rows; Fig4 | Constructed network; not physical sample size |
| VIII-C Simulation/generation | Equation/regimes/seeds;09 | Presets and internal check13I | Measured structure with sensitivity parameters |
| VIII-D Training | Base→fusion→policy order;06/07/12 | Cardinalities, fixed epochs; TableIV | Offline fits; no live learning |
| VIII-E Evaluation | Splits, thresholds, exclusions;12 |15 events;42 hardware rows; TableIX | Explicit protocol; no hidden denominator switching |
| VIII-F Statistics | Dependence and refit CI;14 |10 seeds, df9; TableV | Refit variability; not population CI |
| IX-A Local results | Baselines and fair subset;13A | Positive-class convention explicit | Conditional temporal tie |
| IX-B/C M1–M9 / isolated-coordinated | Balanced error tradeoff;13B/C | M6 Macro-F1/FPR; Fig5 | Descriptive best at this operating point |
| IX-D Topology | Degree/peer/self-loop/permutation;08/13 | Paired deltas and all seed signs; Fig6 | Consistent with mechanism; not formal proof |
| IX-E Cardinality | M8 and dilution;07/13H | Tested sizes; Fig7 | Extrapolation within constructed setting |
| IX-F/G Generator/M9 | Validity boundary and stress;09/13I–M | FPR with recall; Fig8 | Preserve degradation and inconclusive ablation |
| IX-H Fusion | Runtime replay and gap;10/13O | Actual model result | No invented M6 gain |
| IX-I Policy | Shared triples/constraints;11/13P | Macro-F1, ALERT, false BLOCK, rare class | Constrained comparison with limitations |
| IX-J Hardware | Physical held-out discrimination;15/13Q |5/12 false alarms,30/30 detection; Fig10 | Small-sample physical replay, not attack prevention |
| X Discussion | Explain architecture consequences;16/17 | Negative evidence TableVI | Qualify combined interpretation |
| XI Limitations | Internal/external/statistical validity;18 | TableX | Preserve actual gaps |
| XII Conclusion | Supported findings and bounded next work | No new numbers | Match verified scope |

Abstract and title should be settled last. A title centering a “final deployed Set Transformer system” or “graph necessity” would misrepresent the current evidence. Figure/table existence and regeneration status are in [19](19_FIGURE_AND_TABLE_PLAN.md).
