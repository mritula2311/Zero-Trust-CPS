# Claim–Evidence Matrix

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

## C2 — Cross-device information improves coordinated anomaly detection

| | |
|---|---|
| **Claim** | Information from multiple devices improves detection of coordinated network events over a single-node view. |
| **Evidence** | `results/gnn_baselines/metrics.json`, task 2 (4-way coordination-pattern classification, untouched test split). |
| **Experiment** | 20-node hybrid network (grown from 10, RESULTS.md §0.13.18/§0.13.20), four scenarios, fit on TRAIN, selected on VALIDATION, reported on TEST. |
| **Real / Sim / Hybrid** | **Hybrid** — 2 captured-real nodes (`esp32-vib-001` full split; `esp32-vib-002` TRAIN-only, VALIDATION/TEST still PENDING) + 18 LEGACY_SIMULATED nodes calibrated against real measured values. Not 20 physical devices. |
| **Metric** | Test accuracy: single-node view (anomalous-node count only) **0.3958** → concatenated MLP **0.5283** (RESULTS.md §0.13.20). ⚠ Superseded 10-node figures: 0.4175 → 0.6567 — the advantage is smaller at 20 nodes but still positive; cause not isolated (§0.13.20). |
| **Limitation** | Simulated-node-dominated. `esp32-vib-002` contributes TRAIN rows only, still PENDING in VALIDATION/TEST. A 4-way accuracy of 0.53 is a modest result, not a strong one — weaker than the superseded 10-node figure. `evaluate_gnn_baselines.py`'s own concat baselines may share an unmasked-placeholder issue found and fixed elsewhere (RESULTS.md §0.13.19/§0.13.20) — not yet fixed here. |
| **Allowed** | "Cross-device relational information improved coordinated anomaly detection in the evaluated 20-node hybrid network, though by a smaller margin than in the superseded 10-node experiment." |
| **Disallowed** | "Multi-device fusion is necessary for CPS anomaly detection." / quoting the 10-node 0.4175→0.6567 figures as current. |

---

## C3 — The GNN specifically ⚠ **CLAIM WITHDRAWN**

| | |
|---|---|
| **Claim tested** | Graph structure, as opposed to merely multi-device information, is what produces the benefit. |
| **Evidence** | `results/gnn_baselines/metrics.json`, both tasks. |
| **Result** | **The GNN does not beat simpler models given identical information — and the gap widened at 20 nodes.** Task 1 (per-node anomaly, test F1, 20-node current / 10-node superseded): concat MLP **0.9662 / 0.9823**, single-device 0.9708 / 0.9736, GNN **0.5865 / 0.8760**, concat logistic 0.7351 / 0.7762, coordinated rule 0.3082 / 0.6184. Task 2 (coordination pattern, test accuracy): concat MLP **0.5283 / 0.6567**, concat logistic 0.5208 / 0.6533, GNN **0.5375 / 0.6117**, node-count 0.3958 / 0.4175. RESULTS.md §0.13.20. |
| **Self-loop weight** | Swept `{1,2,3,5}` on VALIDATION only; 5.0 selected (validation F1 0.8646 at 10 nodes, **0.5797 at 20 nodes** — RESULTS.md §0.13.18.1/§0.13.20). The GNN loses *at its own best swept setting*, more decisively at 20 nodes. |
| **Real / Sim / Hybrid** | Hybrid — see C2's row for the current 2-real + 18-LEGACY_SIMULATED breakdown. |
| **Limitation** | One topology, one GCN architecture, one testbed, now measured at two graph sizes (10 and 20 nodes). This is not proof that graph learning cannot help — it is proof that **in this testbed it did not, and got worse as the network grew**, consistent with the neighbourhood-dilution mechanism documented in RESULTS.md §0.13.4/§0.13.18.1. `evaluate_gnn_baselines.py::normalized_adjacency` masks a PENDING node out of every other node's message-passing per snapshot instead of its placeholder propagating through the graph (`tests/test_gnn_pending_node_masking.py`); this GNN result is unaffected by the separate pending-node bug found and fixed in `benchmark_crossdevice_models.py` (RESULTS.md §0.13.19) — `normalized_adjacency`'s masking was already correct. |
| **Allowed** | "In the evaluated hybrid network, a graph convolutional model did not outperform simpler models receiving the same multi-device information; the benefit observed is attributable to cross-device information rather than to graph structure." |
| **Disallowed** | "The GNN is architecturally necessary." / "Graph learning is required for coordinated anomaly detection." / any claim of GNN superiority. |

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
| C18 | **Partially supported:** mixed-cardinality training M8/M9 is implemented | benchmark training functions; `m9_seed_study.json` | M9 trains through 15 slots but evaluates only 10 existing / 5 virtual slots; pending neutral context remains. n=15 tested scalability is **pending**. |
| C19 | **Supported for stored experiment:** shift degrades virtual performance | M9 LOW/MEDIUM/HIGH F1 0.7563/0.5436/0.3060, FPR 0.1126/0.2956/0.7921, AUC 0.9870/0.9578/0.6583 | Frozen LOW threshold; calibration shift dominates MEDIUM, discrimination also degrades at HIGH. No additional physical-node validation. |
| C20 | ⚠ **WITHDRAWN — did not reproduce at 20 nodes (RESULTS.md §0.13.21).** Superseded 10-node result: virtual-only F1 0.9769 > hybrid 0.9671. Current 20-node result: hybrid F1 0.9675 ±0.0071 vs. virtual-only 0.9640 ±0.0129 — **overlapping CIs, opposite nominal direction**; 2 of 5 checked slices also reversed. **No directional claim is currently supported.** | M9 seed study and ablation investigation, both re-run at 20 nodes with corrected pending-node masking (RESULTS.md §0.13.19) | Node-count change and the masking fix landed together for M9 — this measurement cannot isolate which caused the reversal (RESULTS.md §0.13.21 names the controlled rerun that would). Do not claim either "virtual-only superiority" or "hybrid superiority" from current evidence. |
