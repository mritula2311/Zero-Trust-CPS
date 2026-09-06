# Adversarial review: nonfinite inactive-node hardening

## Verdict

**Approve the core fix with one required follow-up if all-invalid snapshots are a supported input.** Canonicalizing inactive raw rows before floating-point arithmetic closes the stated NaN/Infinity leak for the ordinary contract where at least one node is active. The patch covers benchmark scoring/training, pooled M9 training, live GNN scoring, and Level-2 explanation. A bounded same-seed real-data parity check produced exactly zero parameter and valid-output delta for all four set/attention factories. The checked canonical benchmark metrics file remains byte-for-byte at its HEAD blob and was not overwritten.

## What changed and why it is correct

- `benchmark_crossdevice_models._with_validity` now uses assignment semantics through `np.where(valid, X, 0.0)` before appending the validity channel (`scripts/benchmark_crossdevice_models.py:159-174`). This is the right boundary: multiplication by zero would not eliminate NaN/Infinity.
- `_train_pooled_sets` had bypassed `_with_validity`; it now independently canonicalizes `X_all` from `valid_all` before tensor creation (`:510-541`). The new two-epoch regression compares same-seed state dicts after replacing an invalid column with NaN (`tests/test_nonfinite_relational_boundaries.py:16-28`).
- Live `GNNScorer.score` and `level2_explain` zero inactive `last_features` before dense GCN multiplication (`src/gnn_scorer.py:119-128,151-160`). This is necessary because normalized adjacency zeros disconnected edges but IEEE `0 * NaN` remains NaN.
- The scoring regression covers NaN, ±Infinity, and `float32.max` for DeepSets, GATv2, SetTransformer, and NP-ST, comparing all valid-node outputs and requiring every output finite when five of six nodes remain valid (`tests/test_nonfinite_relational_boundaries.py:30-50`). The live regression covers the same payload values and also exercises `level2_explain` (`:52-68`).

## Bounded finite parity result

The recorded artifact is `results/final_verification/finite_parity_current.json`. I built the real `NETWORK_NORMAL` train/test snapshots through the checked local scorers (600/300 snapshots), replaced only `_with_validity` with its prior append-only implementation for the old branch, and separately refit each factory for three epochs at seed 314. For DeepSets, GATv2, SetTransformer, and NodePreservingSetTransformer:

- maximum absolute parameter delta: **0.0**;
- maximum absolute valid-node inference delta: **0.0**.

This is stronger than approximate output parity for the sampled protocol: the training trajectories were identical. It is bounded to one real scenario and three epochs, so it does not independently reproduce the published 300-epoch results. The current `results/crossdevice_benchmark/metrics.json` SHA-256 is `a5b6dc75929931d3a1294f6fda294be9d603322be2564be54ed3d03d1e917516`; worktree and HEAD both resolve to Git blob `c8d5850c41757a8681020102719aeb9d5b132536`.

## Required / actionable findings

1. **Required if all-invalid snapshots are supported: define a finite neutral result.** With a 20-node all-invalid snapshot, all four factories return 20 nonfinite outputs. DeepSets takes a max over all `-inf` values (`benchmark_crossdevice_models.py:225`); GATv2 softmaxs an all-`-inf` row (`:252-260`); PyTorch multi-head attention similarly has no valid key (`:304-316`), affecting SetTransformer and NP-ST. The normal network datasets always retain active simulated nodes, so this does not invalidate current benchmark rows. It is still a brittle library boundary and could surface in a fully disconnected deployment/batch. Options: reject all-invalid snapshots before model invocation, or add a sentinel/explicit zero context and return a documented neutral score. Add one regression for that chosen contract.

2. **Consider strengthening the pooled-training regression.** The new pooled test uses only SetTransformer and NaN. The shared canonicalization is factory-independent, so this is adequate branch coverage, but parameterized NaN/±Infinity/extreme-finite tests across the four factories would match the explicit contract and catch later factory-specific preprocessing.

3. **Consider validating metadata shape/type at the boundary.** `_with_validity` assumes one correctly sized `m['valid']` vector per snapshot. A malformed mask currently fails indirectly through NumPy shape/broadcast behavior. An explicit `(n_snapshots,n_nodes)` boolean check would turn silent coercion/object arrays into a clear input-contract error.

4. **FYI: extreme finite values on active nodes remain allowed and can overflow.** The contract covers extreme values only when invalid/inactive. `np.where` deliberately preserves active observations. If external untrusted active scores can exceed their expected [0,1] domain, validation belongs upstream; silently zeroing them here would hide a real observed-data fault.

## Verification

`python -m unittest tests.test_nonfinite_relational_boundaries -v` passed 3/3 tests in 2.226 seconds. The parity harness did not invoke any benchmark `main()` and therefore had no path to canonical result writes.

> Final reconciliation: this is a point-in-time independent review. The canonical paper package supersedes its interim wording. A fresh generator diagnostic is now preserved. Current M9 dynamically pools20+5=25 columns; historical15-column docstrings are not implementation evidence. Additional GAT empty-query hardening and the corrected sensor-scope explanation run were completed after the initial boundary review.
