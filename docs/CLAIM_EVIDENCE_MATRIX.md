# Claim–Evidence Matrix

Every substantive claim the manuscript may make, the experiment that supports
it, what that experiment does **not** establish, and the wording that is and is
not permitted.

A claim absent from this table has no evidence behind it and must not be made.

Numbers below are the **measured, leakage-free** values as of 2026-09-03.
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
| **Experiment** | 10-node hybrid network, four scenarios, fit on TRAIN, selected on VALIDATION, reported on TEST. |
| **Real / Sim / Hybrid** | **Hybrid** — 1 real node contributing real rows, 8 simulated, 1 real node PENDING. |
| **Metric** | Test accuracy: single-node view (anomalous-node count only) **0.4142** → concatenated MLP **0.6567**. |
| **Limitation** | Simulated-node-dominated. Node 02 contributed no data. A 4-way accuracy of 0.657 is a modest result, not a strong one. |
| **Allowed** | "Cross-device relational information improved coordinated anomaly detection in the evaluated hybrid network." |
| **Disallowed** | "Multi-device fusion is necessary for CPS anomaly detection." |

---

## C3 — The GNN specifically ⚠ **CLAIM WITHDRAWN**

| | |
|---|---|
| **Claim tested** | Graph structure, as opposed to merely multi-device information, is what produces the benefit. |
| **Evidence** | `results/gnn_baselines/metrics.json`, both tasks. |
| **Result** | **The GNN does not beat simpler models given identical information.** Task 1 (per-node anomaly, test F1): concat MLP **0.9852**, single-device **0.9771**, GNN **0.8381**, concat logistic 0.7785, coordinated rule 0.6156. Task 2 (coordination pattern, test accuracy): concat MLP **0.6567**, concat logistic 0.6433, GNN **0.6058**, node-count 0.4142. |
| **Self-loop weight** | Swept `{1,2,3,5}` on VALIDATION only; 5.0 selected (validation F1 0.8254). The GNN loses *at its own best swept setting*. |
| **Real / Sim / Hybrid** | Hybrid. |
| **Limitation** | One topology, one graph size, one GCN architecture, one testbed. This is not proof that graph learning cannot help — it is proof that **in this testbed it did not**. |
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

| | |
|---|---|
| **Claim tested** | The adaptive policy outperforms static alternatives. |
| **Evidence** | `results/policy_comparison/metrics.json`, untouched test split, five policies on identical inputs. |
| **Result** | Macro-F1: **static-optimised 0.5879**, decision tree 0.5834, **adaptive bandit 0.5329**, multiclass LR 0.4355, deployed static 0.2744. A static threshold table with thresholds selected on validation **beats** the adaptive policy. |
| **Terminology** | It is **not reinforcement learning**. The update is an incremental sample average; no discount factor, no next-state bootstrapping, reward a fixed function of (state, action). It is a **contextual bandit with sample-average action-value estimation**. |
| **Limitation** | Synthetic test session; the class mix drives macro-F1 heavily. |
| **Allowed** | "An adaptive contextual-bandit policy improved on the deployed static table (macro-F1 0.533 vs 0.274) but did not outperform the same table with thresholds selected on validation (0.588)." |
| **Disallowed** | "Reinforcement learning" / "the adaptive policy outperforms static policies". |

---

## C7 — Common vs separate thresholds

| | |
|---|---|
| **Claim** | Separate thresholds for the two channels are justified. |
| **Evidence** | `results/policy_comparison/metrics.json`, both configurations selected on VALIDATION by macro-F1. |
| **Metric** | Common `θ = 0.7`: test macro-F1 **0.4876**. Separate `θ_sec = 0.7`, `θ_proc = 0.05`: **0.5879**. |
| **Limitation** | **Important caveat.** The selected `θ_proc = 0.05` would make the deployed system nearly blind to process anomalies — it maximises macro-F1 on a class mix dominated by normal and security-concern examples. The selection objective is not the deployment objective. The deployed thresholds remain 0.6/0.6. |
| **Allowed** | "Separate thresholds scored higher macro-F1 on validation-selected settings, but the selected process threshold (0.05) is not operationally usable; the deployed configuration retains a common 0.6." |
| **Disallowed** | "Separate thresholds are required." |

---

## C8 — Rare combined class (BLOCK) — negative result, reported

| | |
|---|---|
| **Claim** | The combined cyber+physical class is detected. |
| **Result** | **It is essentially not.** Support 33. BLOCK recall: static 0.000, static-optimised 0.000, adaptive bandit 0.000, multiclass LR 0.030, decision tree **1.000 at precision 0.021** (1529 false blocks, 52.7% false-block rate). |
| **Limitation** | The combined class is `stealthy_forged_values` — a correctly authenticated device deliberately reporting normal-looking values. By construction its `(s_sec, s_proc)` state is indistinguishable from normal, so no policy over those two inputs can separate it. This is a known and acknowledged architectural blind spot, not a tuning failure. |
| **Allowed** | "Recall on the rare combined class is effectively zero for every policy that maintains a usable false-block rate. The one policy achieving full recall (a decision tree) does so at 2.1% precision and a 52.7% false-block rate, which is not deployable. This limits immediate deployment suitability for that threat class." |
| **Disallowed** | Omitting the class, merging it into another, or reporting only the decision tree's recall. |

---

## C9 — Latency

| | |
|---|---|
| **Evidence** | `results/latency/latency.json`, warm, `time.perf_counter_ns`, host in `docs/ENVIRONMENT.md`. |
| **Metric** | Total pipeline per message: mean **3.49 ms**, p50 1.45 ms, p95 11.30 ms, p99 **13.84 ms**, max 201.35 ms. Cold start 1288 ms, reported separately. Dominant stages: Isolation Forest (mean 5.12 ms) and LSTM-AE (1.38 ms). 10-node network tick: mean 71 ms → ~141 messages/s. |
| **Limitation** | Single host. The audit-log figure is the hash-chain computation only; the SQLite write is I/O-bound and excluded (stated, not omitted). Max is ~138× the median — a mean alone materially misrepresents this pipeline. |
| **Allowed** | "Per-message pipeline latency was 1.25 ms median, 14.5 ms at p99, on the host specified in docs/ENVIRONMENT.md." |
| **Disallowed** | Reporting the mean alone. "Real-time guaranteed." "Industrially scalable" from a ten-node benchmark. |

---

## C10 — Ten-node hybrid network

| | |
|---|---|
| **Claim** | The evaluation used a 10-node hybrid CPS network. |
| **Evidence** | `config/graph_topology.json`, `config/simulated_nodes.json`, `data/collected/network/`. Asserted at import: `len(NETWORK_NODES) == 10 and len(REAL_NODES) == 2 and len(SIMULATED_NODES) == 8`. |
| **Real / Sim / Hybrid** | 2 real (**one of which has no captured data yet**), 8 simulated. |
| **Limitation** | `esp32-vib-002` currently contributes 0 rows; all its network records are `PENDING_REAL_HARDWARE_DATA` and excluded from every metric. So the network as *evaluated* is 1 real + 8 simulated + 1 pending. |
| **Allowed** | "The evaluation used a 10-node hybrid CPS network consisting of two physical ESP32 devices and eight simulated nodes parameterized from real-device telemetry. At the time of this evaluation the second physical node had not yet been captured, and its rows are excluded." |
| **Disallowed** | "Ten physical ESP32 nodes were tested." / any phrasing implying ten devices exist. |

---

## C11 — Heterogeneous sensing

| | |
|---|---|
| **Claim** | The two physical nodes test cross-device, heterogeneous-sensor behaviour. |
| **Evidence** | `src/feature_engineering_sw420.py`, `firmware/main_sw420.py`, `firmware/HARDWARE_SETUP_SW420.md`. |
| **Limitation** | Because the sensors differ in kind (accelerometer vs binary contact switch), **no same-model replication is possible**. The SW-420 cannot produce rms/kurtosis/dominant-frequency even in principle. |
| **Allowed** | "Because the two physical nodes employ heterogeneous sensors, the experiment evaluates cross-device and heterogeneous-sensor behaviour rather than same-model MPU6050 sensor-to-sensor replication." |
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
