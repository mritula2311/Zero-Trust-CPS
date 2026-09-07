# Zero-Trust policy engine

[VERIFIED] The first trust-combination boundary is [gateway](../../src/gateway.py)'s static/bandit policy branch. Both scores are high-is-good. The static [decide](../../src/policy_engine.py) table uses 0.6/0.6 thresholds:

| Security Trust | Process Trust | Decision | Meaning |
|---|---|---|---|
| High | High | ALLOW | Authenticated normal behaviour/process |
| High | Low | ALERT | Preserve legitimate telemetry and flag physical concern |
| Low | High | STEP_UP | Require additional proof for cyber concern |
| Low | Low | BLOCK | Combined concern |

`USE_RL_POLICY=True` currently selects [AdaptivePDP.greedy_action](../../src/adaptive_pdp.py). The learner estimates action reward by sample averages in a two-dimensional bucketed context. Offline epsilon-greedy sampling trains its Q table; runtime uses greedy lookup and never `update`. There is no next-state bootstrapping, discount factor or Bellman learning. Use “offline contextual bandit”; RL identifiers are legacy names.

The gateway overrides policy output to BLOCK on step-up TIMEOUT/MISMATCH, publishes challenges for new STEP_UP decisions, signs/publishes decisions, logs the event and then applies configured consecutive-block quarantine. Rejected authentication is a separate REJECTED audit status, not one of the four PDP labels. The silence watchdog is another operational path and does not synthesize new healthy process observations.

## Comparator evidence and decision

The [policy comparison script](../../scripts/evaluate_policy_comparison.py) feeds the same offline two-score triples to all comparators. P1 static, P2 optimized static, P3 tree, P4 multiclass logistic regression, P5 contextual bandit, P6 constrained static. Use these artifact labels consistently.

P6 selects thresholds under validation ALERT recall≥0.90 and false-block≤0.01, then maximizes macro-F1 among feasible grid points. P5 is not trained using that constrained search. On the saved TEST corpus both satisfy those numerical bounds, yet P5 Macro-F1 is 0.5271 versus P6 0.2777. Do not call P6 globally best. Both have zero BLOCK-class recall here. P3 achieves higher Macro-F1 but violates the false-block bound. Exact tables, supports and thresholds are in [13 P](13_RESULTS_MASTER_TABLES.md) and [metrics](../../results/policy_comparison/metrics.json).

False-block rate counts predicted BLOCK on non-BLOCK truth divided by all non-BLOCK truth. ALERT recall uses physical-fault truth. Macro-F1 averages ALLOW/ALERT/STEP_UP/BLOCK class F1, including the rare failed class. These are offline classification metrics after the auth filter. By default `build_triples` still uses simulated flood flags and execution wall time (this table's saved P1-P6 numbers reflect that default, preserved for historical reproducibility), not a full broker/challenge/enforcement replay — some state timing can therefore depend on machine speed. A controlled deterministic-clock replay now exists as an opt-in (`deterministic_clock=True`, `scripts/train_adaptive_pdp.py`'s `deterministic_clock()` helper; `tests/test_policy_training_determinism.py`), used for the corrected-M6 policy evaluation below. A physically validated (not just replayed) policy experiment remains an important limitation.

## Current serving versus saved experiment

The table above is preserved GCN-era evidence, still valid for its recorded (wall-clock) protocol. As of the 2026-09-07 final pass, `train_adaptive_pdp.py` no longer imports `gnn_scorer.GNNScorer`/`FusionEngine()` with ambient defaults — it requires an explicit `RelationalPin` (`ZTCPS_ADAPTIVE_PDP_PIN`) and a deterministic clock, and writes a metadata sidecar (model/fusion/data hashes, seed, clock protocol, commit) next to every Q-table it produces; `relational_pin.verify_policy_lineage()` fails loudly if a Q-table is later scored against a mismatched pin. `evaluate_rl_policy.py` inherits the same fix via `build_training_triples()`'s new default pin. The currently deployed Q table (`adaptive_pdp_qtable_m6_corrected.json`, `config.ADAPTIVE_PDP_MODEL_PATH`) has a verified, matched corrected-M6 lineage — see [13](13_RESULTS_MASTER_TABLES.md) O5 for its measured performance (macro-F1 0.5332) against a fair, clean-provenance GCN baseline (0.5303), both under the deterministic-clock protocol. The historical, corrupted-provenance table (`models/adaptive_pdp_qtable.json`) remains on disk, untouched, preserved for chronology.
