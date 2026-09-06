# Claim–Evidence Matrix

> **[Paper-reference authority, 2026-09-07]** The [verified paper package](paper/00_PAPER_MASTER_GUIDE.md) governs current research claims. This document is retained as supporting implementation/history; earlier measurements and interpretations are historical unless reconfirmed there. Runtime uses M6 (Set Transformer) fusion as of 2026-09-07, superseding GCN after a held-out fusion-level comparison (`scripts/evaluate_ablation_m6.py`) showed a fused-decision improvement; prior GCN fusion artifacts are retained for reproducibility. SW-420 has TRAIN capture only.


Every substantive claim the manuscript may make, the experiment that supports
it, what that experiment does **not** establish, and the wording that is and is
not permitted.

A claim absent from this table has no evidence behind it and must not be made.

Numbers below are archived measurements with corrections through 2026-09-05.
Physical session separation does not establish generated-source or temporal
independence. Deployed models (IF, LSTM-AE, Transformer, GNN, fusion, bandit)
were retrained in order on the contiguous-window trainer repair
(`datasets.normal_sequences`) as of 2026-09-05; figures elsewhere in this
document predating that rebuild are noted where they differ.
Several are worse than previously published; those are marked ⚠ and the reason
is given. Where a result contradicts an earlier claim, the earlier claim is
withdrawn, not the result.

---

## C1 — Two-score separation

| | |
|---|---|
| **Claim** | Security-trust evidence and physical-process evidence are preserved as separate decision variables until the policy stage. |
| **Evidence** | `src/policy_engine.py` (`decide()` takes two scores + staleness, nothing else); `tests/test_invariants.py::TestTwoScoreSeparation` — four tests including signature inspection of the Security Trust scorer. |
| **Experiment** | Architectural invariant test, not a measurement. |
| **Real / Sim / Hybrid** | Architectural — applies to all. |
| **Metric** | Falsifiable structural property: a third evidence input to `decide()` fails the suite. |
| **Limitation** | Demonstrates separation is *implemented*, not that separation improves outcomes. No ablation runs a blended-score variant end to end. |
| **Allowed** | "Cyber-security and physical-process evidence are preserved as separate decision variables until the policy stage, enforced by an executable invariant." |
| **Disallowed** | "Two-score separation outperforms blended scoring." — never measured. |

---

## C2 — Node-indexed representations improve Task-2 classification over a global count

| | |
|---|---|
| **Status** | **SUPPORTED BUT WEAKER**, for the scoped observation below. A literal single-device Task-2 comparison requires controlled follow-up. |
| **Claim** | Node-indexed score representations outperform a global anomalous-node-count representation in this constructed 20-node benchmark. |
| **Evidence** | `results/gnn_baselines/metrics.json` at `4f6afa2`, Task 2; independently audited in `docs/PAPER_GNN_BASELINE_VERIFICATION.md` and RESULTS §0.13.25. |
| **Experiment** | Four-way scenario classification. Fits use TRAIN; thresholds, rule k and GNN self-loop weight use VALIDATION. TEST is reused for this verification, with no test-driven retuning. |
| **Real / Sim / Hybrid** | 20 declared nodes: 10 MPU6050-type and 10 SW-420-type. Two physical identities, but SW-420 has TRAIN observations only; VALIDATION/TEST have one observed physical node, 18 simulated nodes and one pending slot. Raw simulated rows use `source_type=SIMULATED`; LEGACY_SIMULATED is their benchmark provenance category. |
| **Metric** | TEST accuracy: B0 global count **0.3958**, B1 concat logistic **0.5433** (+0.1475), B2 concat MLP **0.5267** (+0.1309), GNN output-vector head **0.5375** (+0.1417). B1 is the strongest observed TEST comparison; GNN has the highest VALIDATION accuracy (0.5475). |
| **Limitation** | B0 already sees all valid nodes through a count; it is not a single-node baseline. No statistical superiority test, independent physical deployment claim, or isolated network-size effect. Cardinality, sensor mix, provenance and model chain differ across historical runs. |
| **Allowed** | "In the current constructed 20-node benchmark, concat logistic regression achieved Task-2 accuracy 0.5433 versus 0.3958 for a global anomalous-node-count baseline." |
| **Disallowed** | "Cross-device information always improves anomaly detection." / "The Task-2 comparator sees one device." / "Statistically significant." / attributing the historical change to network size alone. |

---

## C3 — GNN superiority is not established

| | |
|---|---|
| **Claim tested** | The evaluated GCN outperforms simpler representations of the same available per-node sub-scores. |
| **Evidence** | `results/gnn_baselines/metrics.json` at `4f6afa2`; historical artifacts and exact model/metric ledger in `docs/PAPER_GNN_BASELINE_VERIFICATION.md`. |
| **Task 1** | TEST F1: B0 **0.9708**, B2 **0.9174**, B1 **0.7371**, GNN **0.5865**, B3 **0.3082**. GNN loses to B0/B1/B2 and beats B3. B2 degraded materially from pre-audit **0.9662 to 0.9174**; FP rose **28 to 270**. |
| **Task 2** | TEST accuracy: B1 **0.5433** > GNN **0.5375** > B2 **0.5267** > B0 **0.3958**. There is no separate B3 Task-2 classifier. "GNN loses to every simple baseline on both tasks" is withdrawn. |
| **Self-loop weight** | `{1,2,3,5}` swept using Task-1 VALIDATION F1; 5.0 selected, F1 **0.5797**. Task-2 uses this Task-1-trained GNN's scalar output per node, not hidden embeddings or a GNN optimized for Task 2. |
| **Inputs** | Shared upstream sub-scores, not byte-identical classifier inputs: B0 gets three own scores; B1/B2 get masked indexed scores, validity and target identity; GNN also gets the declared adjacency. |
| **Masking** | Finite pending content is excluded from GNN message passing, loss and scored target rows; pending output columns are constant 0.5 in the Task-2 head. B1/B2 canonicalize invalid blocks, and B3/count rules explicitly gate validity. |
| **Limitation** | One configured topology and GCN architecture. Historical 10-to-20-node differences confound size, sensor mix, provenance and rebuilt upstream models. Masking correction combines zeroing with added validity channels; its metric change does not isolate either intervention. |
| **Allowed** | "The evaluated GCN scored below concat logistic regression on Task 2 and below B0/B1/B2 on Task 1, while outperforming B3 on Task 1 and B0/B2 on Task 2." |
| **Disallowed** | Universal claims that graph learning cannot help, is necessary, or is superior; claims that this comparison alone isolates the causal contribution of graph structure. |

---

## C4 — Real-hardware physical anomaly detection ⚠ **NUMBER CHANGED**

| | |
|---|---|
| **Claim** | The pipeline distinguishes a resting physical board from a disturbed one. |
| **Evidence** | `scripts/evaluate_real_hardware.py --split test`, session `20260902_221217`. |
| **Metric** | Detection **30/30 (100%)**, 95% CI [88.6%, 100%]. False positives on a genuinely resting board **5/12 (41.7%)**, 95% CI [19.3%, 68.0%]. Validation split (`20260902_173108`): detection 14/14, FP 0/3. |
| **⚠ Why this differs from the published 0/49** | The previously reported false-positive rate was measured while the test session's own at-rest rows were in the training set (`docs/REPOSITORY_AUDIT.md` 2.2). With session-level splitting enforced, the honest figure is 5/12. **The 0/49 figure is withdrawn.** |
| **Real / Sim / Hybrid** | **Real**, single physical node, operator-marked labels. |
| **Limitation** | 12 resting windows in the test split — the interval is very wide. One session, one mounting configuration, laboratory disturbances. Not industrial fault detection. |
| **Allowed** | "On an untouched operator-marked session, the pipeline detected 30/30 real physical disturbances, with 5/12 false positives on resting windows (95% CI 19–68%). The false-positive rate is materially worse than earlier figures measured before session-level splitting was enforced." |
| **Disallowed** | "0% false positives on real hardware." / "ZT-Duo was validated for industrial bearing faults." |

---

## C5 — Low-amplitude detection floor

| | |
|---|---|
| **Claim** | Detection extends to sustained low-amplitude disturbance, not only violent manipulation. |
| **Evidence** | Test session `20260902_221217` contains `fault_weak` (22 scored windows) and `fault_strong` (8). Both detected at 100%. |
| **Real / Sim / Hybrid** | Real. |
| **Limitation** | **Not calibrated.** The excitation source is a phone on continuous vibrate at a controlled distance; there is no shaker table and no reference accelerometer. The detection *floor* has not been located — both graded levels were detected, so the floor lies below `fault_weak`, wherever that is. |
| **Allowed** | "A sustained operator-controlled low-intensity disturbance was detected in all 22 scored windows; the detection floor lies below this level and has not been located." |
| **Disallowed** | "calibrated low-amplitude testing" / any implied amplitude in engineering units. |

---

## C6 — Adaptive policy ⚠ **CLAIM WITHDRAWN**

| Field | Current evidence |
|---|---|
| Status | **Partially supported**: configured contextual bandit improves on deployed static; no overall constrained winner established. |
| Evidence | `results/policy_comparison/metrics.json`; RESULTS 0.13.6–7. |
| Result | Macro-F1 P3 0.6453, P2 0.5614, P5 0.5271, P4 0.4410, P6 0.2777, P1 0.2744. P3 false-block 0.1510; P2 ALERT recall 0.5850. P5 ALERT recall 0.9600 / false-block 0.0000; P6 0.9900 / 0.0000. |
| Allowed | P6 is the best feasible static grid point under its declared constraints. P5 also meets those bounds on saved test data and has higher macro-F1. |
| Disallowed | “P6 is the best constrained policy overall”; “full reinforcement learning”; silently replacing the configured bandit with a benchmark candidate. |
| Limitation | Synthetic test session, fixed split, saved pre-Astra temporal artifacts. Compare every family under identical validation constraints before selection. |


## C7 — Common vs separate thresholds

| | |
|---|---|
| **Claim** | Separate thresholds for the two channels are justified. |
| **Evidence** | `results/policy_comparison/metrics.json`, both configurations selected on VALIDATION by macro-F1. |
| **Metric** | Common `θ = 0.7`: test macro-F1 **0.4865**. Separate `θ_sec = 0.7`, `θ_proc = 0.05`: **0.5614**. |
| **Limitation** | **Important caveat.** The selected `θ_proc = 0.05` would make the deployed system nearly blind to process anomalies — it maximises macro-F1 on a class mix dominated by normal and security-concern examples. The selection objective is not the deployment objective. The deployed thresholds remain 0.6/0.6. |
| **Allowed** | "Separate thresholds scored higher macro-F1 on validation-selected settings, but the selected process threshold (0.05) is not operationally usable; the deployed configuration retains a common 0.6." |
| **Disallowed** | "Separate thresholds are required." |

---

## C8 — Rare combined class (BLOCK) — negative result, reported

| Field | Current evidence |
|---|---|
| Status | **Not established at a useful false-block rate.** |
| Evidence | `results/policy_comparison/metrics.json`, RESULTS 0.13.6; support 33. |
| Limitation | Validly authenticated normal-looking forged values can be indistinguishable from ordinary readings in the two-score state. Preserve per-class confusion matrices and false-block rates. |
| Allowed | P3's high macro-F1 accompanies 15.1% false-block on the current saved chain; policy aggregate metrics cannot hide the combined-class limitation. |
| Disallowed | Quoting old 52.7%/2.1%-precision tree figures as current, omitting combined-class outcomes, claiming all compromises are detectable. |


## C9 — Latency

| | |
|---|---|
| **Evidence** | `results/latency/latency.json`, warm, `time.perf_counter_ns`, host in `docs/ENVIRONMENT.md`. |
| **Metric** | Total pipeline per message: mean **3.49 ms**, p50 1.45 ms, p95 11.30 ms, p99 **13.84 ms**, max 201.35 ms. Cold start 1288 ms, reported separately. Dominant stages: Isolation Forest (mean 5.12 ms) and LSTM-AE (1.38 ms). 10-node network tick: mean 71 ms → ~141 messages/s. |
| **Limitation** | Single host. The audit-log figure is the hash-chain computation only; the SQLite write is I/O-bound and excluded (stated, not omitted). Max is ~138× the median — a mean alone materially misrepresents this pipeline. |
| **Allowed** | "Per-message pipeline latency was 1.45 ms median, 13.84 ms at p99, on the host specified in docs/ENVIRONMENT.md." |
| **Disallowed** | Reporting the mean alone. "Real-time guaranteed." "Industrially scalable" from a ten-node benchmark. |

---

## C10 — Ten-node hybrid network

| | |
|---|---|
| **Claim** | The evaluation used a 20-node hybrid CPS network (⚠ grown from 10 — RESULTS.md §0.13.18; earlier sections of this document predating 2026-09-05 describe the superseded 10-node network). |
| **Evidence** | `config/graph_topology.json`, `config/simulated_nodes.json`, `data/collected/network/`. Asserted at import: `len(NETWORK_NODES) == 20 and len(REAL_NODES) == 2 and len(SIMULATED_NODES) == 18`. |
| **Real / Sim / Hybrid** | 2 real (`esp32-vib-001` full split; `esp32-vib-002` **TRAIN-only, VALIDATION/TEST still pending**), 18 LEGACY_SIMULATED (equalised 10 MPU6050-type + 10 SW-420-type; the SW-420-type profiles' disturbance magnitudes are anchored to `esp32-vib-002`'s real measured phase means). |
| **Limitation** | `esp32-vib-002` contributes real TRAIN rows only; its VALIDATION/TEST network records are still `PENDING_REAL_HARDWARE_DATA` and excluded from every metric. So the network as *evaluated* on VALIDATION/TEST is 1 fully-real + 18 simulated + 1 TRAIN-only-real/pending-elsewhere. RESULTS.md §0.13.18.2/§0.13.19 measured a concrete cost of this gap and corrected an earlier misdiagnosis of it. |
| **Allowed** | "The evaluation used twenty configured slots: two captured physical sources (one with a full split, one TRAIN-only) and eighteen calibrated simulated streams. Pending targets are excluded from loss and metrics, while their neutral placeholder still enters model context unless explicitly masked (RESULTS.md §0.13.19)." |
| **Disallowed** | "Twenty physical ESP32 nodes were tested." / any phrasing implying twenty devices exist. |

---

## C11 — Heterogeneous sensing

| | |
|---|---|
| **Claim** | The two physical nodes test cross-device, heterogeneous-sensor behaviour. |
| **Evidence** | `src/feature_engineering_sw420.py`, `firmware/main_sw420.py`, `firmware/HARDWARE_SETUP_SW420.md`. |
| **Limitation** | Because the sensors differ in kind (accelerometer vs binary contact switch), **no same-model replication is possible**. The SW-420 cannot produce rms/kurtosis/dominant-frequency even in principle. |
| **Allowed** | "Because the two physical nodes employ heterogeneous sensors, the planned experiment will evaluate cross-device and heterogeneous-sensor behaviour after Device 2 capture rather than same-model MPU6050 sensor-to-sensor replication." |
| **Disallowed** | "Validated across two MPU6050 sensors." |

---

## C12 — Anti-replay state invariant

| | |
|---|---|
| **Claim** | A rejected message never mutates persistent authentication or anti-replay state. |
| **Evidence** | `src/trust_engine.py` `check_boot_replay()` (pure predicate) / `commit_boot_seq()` (sole mutator, called after all gates pass); `tests/test_invariants.py::TestBootReplayStateIsolation`, three tests. Found by live adversarial testing, fixed in commit `560694b`. |
| **Real / Sim / Hybrid** | Architectural + live-hardware corroboration. |
| **Allowed** | "Rejected messages do not mutate replay state, verified by regression test and corroborated in live adversarial testing." |
| **Disallowed** | "The system is replay-proof." |

---

## C13 — Exact additive fusion decomposition

| | |
|---|---|
| **Claim** | The fusion decision admits an exact additive attribution. |
| **Evidence** | `src/fusion_engine.py::_explain` — `shap.LinearExplainer` on a logistic model; verified empirically that `expected_value + Σ shap_values` reproduces `decision_function(x)` exactly. |
| **Limitation** | The decomposition is exact **in log-odds (margin) space relative to the chosen background**, not in probability space. No exact additive decomposition into probability contributions exists for a logistic model, since `σ(a+b) ≠ σ(a)+σ(b)`. Direction is always correct (σ is monotonic); magnitude is in log-odds units. |
| **Allowed** | "The linear fusion margin admits an exact additive decomposition relative to the selected baseline." |
| **Disallowed** | "Exact SHAP values for the trust score." / any probability-space additivity claim. |

---

## C14 — Real hardware carries the result

| | |
|---|---|
| **Claim** | The small number of real at-rest rows is load-bearing, not decoration. |
| **Evidence** | `merge_real_hardware_data.py --synthetic-only` ablation, `RESULTS.md` 0.10.9: withholding the real rows and retraining the whole chain gives 13/49 operator-marked false positives instead of 0/49, detection unchanged. |
| **Limitation** | ⚠ This ablation was measured under the **pre-split** regime and its baseline (0/49) is the withdrawn leaky figure (see C4). The *direction* — real rows materially reduce false positives — is unaffected, but the magnitude must be re-measured under session-level splitting before it is quoted again. |
| **Allowed** | "Withholding the real at-rest rows and retraining materially increased false positives; the magnitude requires re-measurement under the corrected splits." |
| **Disallowed** | Quoting "13/49 vs 0/49" as a current result. |

## C15–C20 — Current relational research claims

| ID | Claim and status | Evidence | Boundary / prohibited extrapolation |
|---|---|---|---|
| C15 | **Supported on saved fixed-split refits, re-run at 20 nodes (RESULTS.md §0.13.22):** different GCN/GATv2 topology-sensitivity patterns, pattern unchanged and sharper | `crossdevice_benchmark/seed_study.json`: GCN degree −0.9430, density −0.3255 (⚠ was −0.8160 / +0.1895 at 10 nodes); GATv2 degree −0.2687 now significant (⚠ was CI-includes-zero at 10 nodes), density −0.4093; interaction (GCN−GATv2 of degree−density) −0.7580, CI [−1.124,−0.392] (⚠ was −1.2132, CI [−1.583,−0.843] at 10 nodes) | Not strict double dissociation; ten training seeds are not ten datasets. Direction/significance pattern held across the 10→20 node re-measurement; exact figures should not be quoted from the 10-node run. |
| C16 | **Partially supported:** set models stable under evaluated topology/cardinality probes | `crossdevice_benchmark/metrics.json`, RESULTS 0.13.3–14 | Adjacency invariance is by construction. No universal superiority, no deployed M9 claim. Concat MLP remains efficiency baseline; NP-ST rejected. |
| C17 | **Supported narrowly:** LOW TRAIN resting-residual consistency | `validate_virtual_device_generator.py`; audit validator transcript | 103 source rest rows; 0.086 correlation / 0.097 ACF difference; discriminator 0.466. Not held-out realism or long-stream/fault validation. MEDIUM/HIGH are OOD. |
| C18 | **Partially supported:** mixed-cardinality training M8/M9 is implemented | `benchmark_crossdevice_models.py::_train_pooled_sets`, `train_mixed_provenance`, `m9_seed_study`; `m9_seed_study.json` | M9 samples training sizes {2,3,5,10,15} from the current 20 existing + 5 virtual column pool; saved evaluations use 20 existing / 5 virtual slots. Validity masks are passed explicitly. No saved n=15 test: tested scalability at that size remains **pending**. |
| C19 | **Supported for the current stored experiment:** shift degrades virtual performance | `c5cd38d:results/crossdevice_benchmark/m9_seed_study.json`, unchanged on this Astra branch: LOW/MEDIUM/HIGH mean F1 **0.6812/0.4636/0.2952**, FPR **0.1641/0.4082/0.8341**, ROC-AUC **0.9819/0.9128/0.6900** | MEDIUM/HIGH reuse each seed's LOW-selected threshold; both false-positive rates and discrimination degrade. No additional physical-node validation. Earlier F1 0.7563/0.5436/0.3060, FPR 0.1126/0.2956/0.7921 and AUC 0.9870/0.9578/0.6583 belong to `7388338:results/crossdevice_benchmark/m9_seed_study.json` (10-node source pool), retained as history rather than current evidence. |
| C20 | ⚠ **WITHDRAWN — did not reproduce at 20 nodes (RESULTS.md §0.13.21).** Superseded 10-node result: virtual-only F1 0.9769 > hybrid 0.9671. Current 20-node result: hybrid F1 0.9675 ±0.0071 vs. virtual-only 0.9640 ±0.0129 — **overlapping CIs, opposite nominal direction**; 2 of 5 checked slices also reversed. **No directional claim is currently supported.** | M9 seed study and ablation investigation, both re-run at 20 nodes with corrected pending-node masking (RESULTS.md §0.13.19) | Node-count change and the masking fix landed together for M9 — this measurement cannot isolate which caused the reversal (RESULTS.md §0.13.21 names the controlled rerun that would). Do not claim either "virtual-only superiority" or "hybrid superiority" from current evidence. |
