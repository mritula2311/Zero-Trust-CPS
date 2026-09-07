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

False-block rate counts predicted BLOCK on non-BLOCK truth divided by all non-BLOCK truth. ALERT recall uses physical-fault truth. Macro-F1 averages ALLOW/ALERT/STEP_UP/BLOCK class F1, including the rare failed class. These are offline classification metrics after the auth filter. `build_triples` uses simulated flood flags and execution wall time, not a full broker/challenge/enforcement replay; some state timing can therefore depend on machine speed. A controlled timestamp replay and physically validated policy experiment remain important limitations.

## Current serving versus saved experiment

The table above is preserved GCN-era evidence. Current serving supplies M6-fused Process Trust, but `train_adaptive_pdp.py` still imports `gnn_scorer.GNNScorer` and uses default fusion, which is now M6-fitted. `evaluate_rl_policy.py` reuses that producer. The saved Q table contains bucket/action values without producing hashes; neither a matched M6 retrain nor its absence can be inferred from those values. Do not describe the saved policy experiment as current M6-policy validation. Correct and independently record that lineage before making the claim; this pass changes no policy behavior or weights.
