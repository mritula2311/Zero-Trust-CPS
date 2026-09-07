# Research problem and motivation

[VERIFIED: implementation scope] A message can authenticate successfully while describing a physical fault. Conversely, an invalid signature does not demonstrate that the claimed device or its process is faulty: the claimed identity may be attacker-controlled. ZT-Duo separates these situations to avoid trust poisoning and conflating operational faults with authentication failures.

The implemented research question is whether separate cyber-behaviour and physical-process assessments support distinct, explainable CPS decisions. A second question compares local and whole-network score representations under isolated/coordinated constructed anomalies. A third studies how model architecture responds to controlled topology/cardinality/provenance changes. None of these questions establishes literature novelty without the comparison work in [20](20_RELATED_WORK_POSITIONING.md).

| Question | Implemented experiment | What it can establish |
|---|---|---|
| Can rejected claimed identities poison legitimate trust? | Gateway rejection and invariant tests | Behaviour of implemented state boundaries under tested inputs |
| Does indexed cross-device information help? | `evaluate_gnn_baselines.py`, Task 2 | Fixed-corpus accuracy relative to a network-count baseline |
| Which relational candidate balances errors? | `benchmark_crossdevice_models.py`, M1–M9 | Descriptive model ranking at declared validation operating points |
| Does topology affect the models? | Degree, peer-density and dilution probes | Sensitivity under the actual interventions |
| How far can real-derived augmentation be pushed? | Generator validation and M9 stress | Internal consistency and OOD failure boundary |
| Does the complete selected architecture work on hardware? | Preserved GCN-era physical replay; current M6 software integration | Historical component-chain observations; physical M6 end-to-end validation remains pending |

Source implementations: [gateway](../../src/gateway.py), [baseline evaluation](../../scripts/evaluate_gnn_baselines.py), [relational benchmark](../../scripts/benchmark_crossdevice_models.py). Safe motivation is a need to distinguish evidence types. Avoid claiming that Zero Trust, ensemble anomaly detection, set attention or contextual bandits are themselves new inventions.
