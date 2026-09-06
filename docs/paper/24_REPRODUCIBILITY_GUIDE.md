# Reproducibility guide

Run commands from the repository root. [Inventory](../../results/final_verification/repository_inventory.json) records observed Python/package versions and SHA-256 hashes for tracked data, checkpoints, source and artifacts; [numeric source map](../../results/final_verification/paper_numeric_sources.json) ties generated tables to exact bytes. This checkout uses Python 3.12.10, torch 2.11.0+cu128, numpy 2.4.4 and scikit-learn 1.9.0. Installed versions are a snapshot; requirements contain lower bounds and do not provide a lockfile.

## Tests and verified replay commands

```powershell
python -m pytest -q
python -m unittest discover -s tests
python scripts/evaluate_ablation.py
python scripts/evaluate_real_hardware.py --split test
python scripts/evaluate_explainability_level2.py
python scripts/validate_virtual_device_generator.py
python scripts/audit_repository_evidence.py
python scripts/build_paper_results.py
python scripts/verify_paper_package.py
```

pytest was absent from the original environment. For this audit it was installed into `<WORKSPACE_ROOT>/verification-tools`; test commands used `$env:PYTHONPATH='<WORKSPACE_ROOT>/verification-tools'` before `python -m pytest`. This is an audit-local runner dependency, not a runtime requirement. Stdlib unittest remains supported. No model training is required for the replay commands above. Generator validation returns 1 because the stress presets fail internal marginal checks; use the per-preset outcomes rather than treating this as a software exception.

| Result / table | Command / producing script | Required inputs / checkpoint / seed | Output and expected result | Reproduction status / limitation |
|---|---|---|---|---|
| Local/fusion13A/O | `python scripts/evaluate_ablation.py` | `test_session.json`; IF/LSTM/Transformer/GNN/fusion artifacts; fixed TEST seed999 | Console; captured in final_verification/local_fusion_evaluation.log; fair temporal tie | Replayed; timing-dependent graph state may differ on very slow hosts |
| Hardware13Q | `python scripts/evaluate_real_hardware.py --split test` | Labelled MPU TEST capture/split manifest; same runtime artifacts | Console; hardware_evaluation.log;30/30 and5/12 | Replayed offline; new acquisition needs physical equipment |
| Explainability | `python scripts/evaluate_explainability_level2.py` | Model artifacts; legacy and physical captures | Console; corrected log preserved | Sensor-scope bug fixed; threshold/subset qualifiers required |
| Generator13I | `python scripts/validate_virtual_device_generator.py` | TRAIN MPU runs, virtual_generator.json, deterministic identities | Console; generator_validation.log; LOW passes, stress marginal failures | Replayed internal check; not held-out realism |
| Task1/2 and self-loop | `python scripts/evaluate_gnn_baselines.py` | Twelve network JSONs; current IF/LSTM models; seed 0 | results/gnn_baselines; models/gnn_network.pt | Prior exact replay retained; no expensive rerun in final audit |
| M1–M9 / structural13B–H | `python scripts/benchmark_crossdevice_models.py` | Network+virtual JSONs; local models; config; seed 0 | crossdevice_benchmark/metrics.json | Code/artifact audited; fits in memory, no per-model checkpoint hashes |
| Ten-seed topology | `python scripts/benchmark_crossdevice_models.py --seeds 10` | Same fixed network/probe pools; seeds 0–9 | crossdevice_benchmark/seed_study.json | Preserved; fixed-split refit CI; immutable original provenance incomplete |
| M9 seed stress | `python scripts/benchmark_crossdevice_models.py --m9-seeds 10` | Hybrid+virtual LOW/MEDIUM/HIGH streams; current dynamically sized pool | crossdevice_benchmark/m9_seed_study.json | Historical metadata insufficient to attest original run cardinality |
| M9 provenance slices | `python scripts/benchmark_crossdevice_models.py --m9-ablation-investigation` | Same streams and splits; default 10 seeds | crossdevice_benchmark/m9_ablation_investigation.json | Preserve original before rerun; causal interpretation unresolved |
| Policy13P | `python scripts/evaluate_policy_comparison.py` | VAL_002 and legacy TEST; current full saved chain and Q table | results/policy_comparison/metrics.json and matrices | Audited saved artifact; not freshly rerun; timing-state limitation |
| Stage latency13R | `python scripts/evaluate_latency_stages.py` | Current models, legacy/network data, host | results/latency/latency.json/csv | Saved measurement historical; full acquisition/broker/persistence absent |

Commands that train or regenerate write canonical artifacts. Run them only in a disposable branch/copy after preserving prior outputs and their hashes; do not overwrite the historical reference to claim a replication. Script flags must be checked against current dispatch before execution. A new code/data version creates a new result lineage, even when the filename is unchanged.

## Demonstration interface checks

The [static demonstration interface](../../design/README.md) has its own reproducible,
sandboxed checks; none of them contact a production gateway or physical device.

```powershell
python design/verify-runtime.py
python design/check-package.py
node design/verify-dashboard.mjs
```

`verify-runtime.py` exercises real fitted-model inference (fusion, runtime GCN, offline
bandit) against synthetic readings with temporary keys and a controlled clock, entirely
offline. `check-package.py` is a scoped source/secret/link scan over `design/`.
`verify-dashboard.mjs` requires Node.js and a local Chrome/Chromium (`CHROME_PATH` to
override); it drives a headless browser against loopback fixtures and reports viewport,
interaction and numeric-comparison results, recorded in
[design/browser-verification.json](../../design/browser-verification.json). See
[design/READINESS.md](../../design/READINESS.md) for the last recorded run and its scope.

## Complete offline chain

After changing training data/schema/temporal construction, rebuild in order: `train_isolation_forest.py` → `train_lstm_ae.py` → `train_transformer.py` (ablation) → `train_gnn.py` → `train_fusion_meta_learner.py` → `train_adaptive_pdp.py`. Each script is under scripts/. Keep TRAIN/VAL_001/VAL_002/TEST allocations fixed. Do not fit M6 fusion by simply substituting scores into the existing logistic coefficients.

Raw capture generation requires sensors, configured credentials, broker/TLS and explicit session allocation. Those resources are not portable tracked artifacts. Fresh clone reproduction can run offline research from preserved data/checkpoints but cannot prove a live hardware deployment. Missing physical SW held-out data, M6 fusion and full end-to-end timing are [P0 for their respective claims]. Missing immutable original M9/checkpoint provenance and a fully pinned environment are [P1].
