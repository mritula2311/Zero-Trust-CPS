# Reproducibility guide

Run commands from the repository root. [Inventory](../../results/final_verification/repository_inventory.json) records observed package versions and tracked input/model/source hashes; [numeric sources](../../results/final_verification/paper_numeric_sources.json) bind the tables to bytes. Requirements are lower bounds, not a fully pinned reproduction environment. Historical experiment provenance is incomplete; see the lineage gates below.

## Tests and verified replay commands

```powershell
python -m unittest discover -s tests
python scripts/audit_repository_evidence.py
python scripts/build_paper_results.py
python scripts/verify_paper_package.py
```

These verification/table commands do not fit models. Stdlib unittest is the canonical test runner. The generator diagnostic is listed separately below: it returns 1 for expected MEDIUM/HIGH marginal failures. Do not run historical GCN evaluators with today's default M6 fusion and call their outputs replications.

| Result / table | Command / producing script | Required inputs / checkpoint / seed | Output and expected result | Reproduction status / limitation |
|---|---|---|---|---|
| Local/fusion13A/O | `python scripts/evaluate_ablation.py` | `test_session.json`; IF/LSTM/Transformer/GNN/fusion artifacts; fixed TEST seed999 | Console; captured in final_verification/local_fusion_evaluation.log; fair temporal tie | Preserved GCN-era log; explicitly select GCN fusion/background backups before replay; wall-clock activity caveat |
| Hardware13Q | `python scripts/evaluate_real_hardware.py --split test` | Labelled MPU TEST capture/split manifest; same runtime artifacts | Console; hardware_evaluation.log;30/30 and5/12 | Preserved GCN-era log; matching GCN fusion/background required; physical acquisition needs equipment |
| Explainability | `python scripts/evaluate_explainability_level2.py` | Model artifacts; legacy and physical captures | Console; corrected log preserved | Historical GCN protocol; matching GCN fusion/background and threshold/subset qualifiers required |
| Generator13I | `python scripts/validate_virtual_device_generator.py` | TRAIN MPU runs, virtual_generator.json, deterministic identities | Console; generator_validation.log; LOW passes, stress marginal failures | Replayed internal check; not held-out realism |
| Task1/2 and self-loop | `python scripts/evaluate_gnn_baselines.py` | Twelve network JSONs; current IF/LSTM models; seed 0 | results/gnn_baselines; models/gnn_network.pt | Prior exact replay retained; no expensive rerun in final audit |
| M1–M9 / structural13B–H | `python scripts/benchmark_crossdevice_models.py` | Network+virtual JSONs; local models; config; seed 0 | crossdevice_benchmark/metrics.json | Code/artifact audited; fits in memory, no per-model checkpoint hashes |
| Ten-seed topology | `python scripts/benchmark_crossdevice_models.py --seeds 10` | Same fixed network/probe pools; seeds 0–9 | crossdevice_benchmark/seed_study.json | Preserved; fixed-split refit CI; immutable original provenance incomplete |
| M9 seed stress | `python scripts/benchmark_crossdevice_models.py --m9-seeds 10` | Hybrid+virtual LOW/MEDIUM/HIGH streams; current dynamically sized pool | crossdevice_benchmark/m9_seed_study.json | Historical metadata insufficient to attest original run cardinality |
| M9 provenance slices | `python scripts/benchmark_crossdevice_models.py --m9-ablation-investigation` | Same streams and splits; default 10 seeds | crossdevice_benchmark/m9_ablation_investigation.json | Preserve original before rerun; causal interpretation unresolved |
| Policy13P | `python scripts/evaluate_policy_comparison.py` | VAL_002 and legacy TEST; historical GCN chain and producing policy artifacts | results/policy_comparison/metrics.json and matrices | Preserved artifact; current policy producer mismatches M6 serving and Q-table lineage is unverified |
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

`verify-runtime.py` exercises real fitted-model inference (fusion, runtime M6, offline
bandit) against synthetic readings with temporary keys and a controlled clock, entirely
offline. `check-package.py` is a scoped source/secret/link scan over `design/`.
`verify-dashboard.mjs` requires Node.js and a local Chrome/Chromium (`CHROME_PATH` to
override); it drives a headless browser against loopback fixtures and reports viewport,
interaction and numeric-comparison results, recorded in
[design/browser-verification.json](../../design/browser-verification.json). See
[design/READINESS.md](../../design/READINESS.md) for the last recorded run and its scope.

## Complete offline chain

The historical dependency order is IF → LSTM-AE → temporal Transformer (ablation) → GCN → GCN-fitted fusion → policy. The separate M6 branch adds `train_set_transformer.py` and `train_fusion_meta_learner_m6.py`. These scripts are not yet a validated replacement reproduction chain: correct valid-target class weights and replay-clock alignment, explicitly select scorer/fusion artifacts, and align the policy trainer before any separately versioned rebuild. Do not retrain over frozen evidence or substitute scores into coefficients trained for another relational model.

Raw capture generation requires sensors, configured credentials, broker/TLS and explicit session allocation. Those resources are not portable tracked artifacts. Fresh clone reproduction can run offline research from preserved data/checkpoints but cannot prove a live hardware deployment. Missing SW held-out data, correctly pinned M6 comparison/policy lineage and end-to-end timing block their respective claims; they do not block bounded writing. Missing immutable original M9/checkpoint provenance and a fully pinned environment are [P1].

## Artifact selection required before experimental reproduction

| Intended result | Relational checkpoint | Fusion / background | Current-command limitation |
|---|---|---|---|
| Preserved GCN local/hardware/explanation logs | models/gnn.pt (identical to gnn_backup.pt) | fusion_meta_learner_gcn_backup.joblib / fusion_background_gcn_backup.npy | Evaluators use GCN but default to promoted M6 fusion; select backups explicitly in an isolated copy |
| Configured M6 offline scenarios | models/set_transformer_runtime.pt | active fusion_meta_learner.joblib / fusion_background.npy, identical to M6 variants | design/verify-runtime.py exercises real inference, not statistical effectiveness |
| Reported GCN-to-M6 gain | Separate GCN and M6 checkpoints | Each arm's matched fusion/background pair | No persisted raw comparison receipt; current GCN arm reads M6 fusion; comparative publication pending |
| M6-trained policy effectiveness | M6 checkpoint and matched fusion | New policy artifact with producing hashes | Current trainer still uses GCN; current Q table does not attest training lineage |

No hardware sessions, models, generators or experimental metrics were regenerated by the paper cleanup. The old model_metadata.json remains GCN-era evidence; current fusion coefficients are inspected directly by build_paper_results.py into 13 O2. Historical receipt file names do not imply current runtime equivalence.
