# Topology and robustness analysis

[EXPERIMENTAL] Source: [benchmark](../../scripts/benchmark_crossdevice_models.py), `structural_probes`, `probe_scores`, `complete_adjacency`, `_pools`; [single-seed artifact](../../results/crossdevice_benchmark/metrics.json), [seed study](../../results/crossdevice_benchmark/seed_study.json). Exact values are centralized in [13 D–H](13_RESULTS_MASTER_TABLES.md).

| Intervention | Controlled quantity | What it supports / cannot support |
|---|---|---|
| Target degree | Target's number of neighbors, fixed probe population and other declared construction | Sensitivity consistent with aggregation dilution; not field causality |
| Peer density | Peer-to-peer edges while target degree is held at three | Propagated representation effects, conditional on this graph construction |
| Self-loop weight | 1/2/3/5 candidates, selection on validation | Comparative operating point after separate fits; not a pure fixed-weight causal intervention |
| Dilution/cardinality | One anomaly among n−1 healthy scores, complete graph for graph models | Constructed scaling sensitivity; feature pool shared across generated trials |
| Coordination size | Number of anomalous nodes in a fixed-size constructed population | Response to coordinated pattern size |
| Feature permutation | Permute feature rows, keep original graph adjacency, then restore output indexing | Fixed-topology slot-reassignment sensitivity only |

GCN degree endpoint recall decreases in all ten seed refits, consistent with dilution of target information. GATv2 shows peer-density sensitivity; GCN also changes under peer density, including two seeds with the opposite sign. Preserve those exceptions rather than recasting every model as a textbook mechanism. M3/M6 do not consume graph topology and are flat for topology-only interventions by construction; that is not evidence of robustness to arbitrary sensor/data shift.

## Permutation audit

For graph relabelling, the appropriate test is `f(PX, P A P^T) ≈ P f(X,A)`. The saved experiment shuffles X while keeping A fixed, so nonzero GCN/GAT differences can arise because features are reassigned to structurally different slots. Calling GCN/GAT “order-dependent” from this experiment is invalid. Preserve the old numeric artifact, rename its interpretation, and perform a joint-permutation regression before making formal empirical equivariance claims. Set-model output rows are equivariant; pooled context is invariant. Do not conflate these terms.

## Statistics and confounds

The single-seed dilution routine advances one RNG across models and sizes, so those curves do not use identical per-model draws. Its declared-topology control draws a separate batch at current N=20 despite a historical n10 key. A difference between a curve point and that control cannot be attributed solely to adjacency. Degree and peer-density interventions do reuse a fixed batch at n=10 and are stronger controlled evidence. The permutation probe additionally treats pending slots as valid (meta omitted); this reinforces its status as a synthetic slot-reassignment diagnostic, not an accuracy or missing-node-contract evaluation.

The saved paired endpoint t intervals use ten training seeds, df=9 and a fixed data/probe protocol. They estimate refit variability. Source-pool observations, neighboring node rows and repeated scenarios are dependent; 400 synthetic trials per cell do not provide 400 independent physical systems. The 10→20-node transition changed composition, masking and component artifacts. A causal explanation of its metric movement requires matched corrected-mask experiments at both cardinalities. Status: [REQUIRES CONTROLLED FOLLOW-UP].
