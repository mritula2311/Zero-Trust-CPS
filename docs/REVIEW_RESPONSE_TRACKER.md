# Reviewer Response Tracker

> **2026-09-05 audit update:** Completion labels below record the earlier review round. The Astra audit reopens temporal continuity, calibration independence, missing-node context, provenance and deployment security; old completion does not close these findings.
> Current evidence and limitations: RESULTS §0.13.17.

Status vocabulary, used strictly:

| Status | Meaning |
|---|---|
| `COMPLETED` | Implemented, run, and reported on genuine data. |
| `IMPLEMENTED_PENDING_DATA` | Code and protocol complete; awaits a physical capture that has not happened. **No number is reported.** |
| `PARTIALLY_COMPLETED` | Some sub-parts done, others not; both named. |
| `NOT_YET_ADDRESSED` | Not started. |
| `NOT_APPLICABLE_WITH_JUSTIFICATION` | Does not apply here, with the reason. |

**No hardware experiment is marked `COMPLETED` without genuine measurements.**

---

## C — Coordinated physical disturbances

| | |
|---|---|
| **Status** | `IMPLEMENTED_PENDING_DATA` |
| **Code** | `scripts/collect_hardware_session.py` gains `--coordinated` and `--devices a,b`; a `COORDINATED_EVENTS` schedule covering C1 (both normal), C2 (node 01 only), C3 (node 02 only), C4 (both simultaneously). Refuses to run without two devices. |
| **Experimental** | The 10-node extension exists and runs: `scripts/generate_network_data.py` builds `NETWORK_NORMAL` / `SCENARIO_A` / `SCENARIO_B` / `SCENARIO_C` across train/validation/test. |
| **Docs** | `docs/EXPERIMENTAL_PROTOCOL.md` §5.1. |
| **Evidence** | Network scenarios generated and evaluated (`results/gnn_baselines/`). The **physical** C1–C4 conditions have not been captured — `esp32-vib-002` has no sessions. |
| **Files** | `scripts/collect_hardware_session.py`, `scripts/generate_network_data.py`, `config/graph_topology.json` |
| **Remaining limitation** | C1–C4 require both boards publishing simultaneously. Until then every node-02 row is `PENDING_REAL_HARDWARE_DATA` and excluded. **Command is in the protocol doc §7.2.** |

---

## D — Mounting and orientation robustness

| | |
|---|---|
| **Status** | `IMPLEMENTED_PENDING_DATA` |
| **Code** | `--mount-check` schedule; `--mount` / `--orientation` / `--notes` recorded on **every record** and in the session header. No source edit needed between configurations. |
| **Docs** | `docs/EXPERIMENTAL_PROTOCOL.md` §5.3. |
| **Evidence** | None yet — all four existing sessions predate the metadata and carry no mounting condition. |
| **Remaining limitation** | Three runs needed: `MOUNT_A/ORIENTATION_A`, `MOUNT_A/ORIENTATION_B`, `MOUNT_B/ORIENTATION_A`. **This is now the highest-value outstanding capture**: the 5/12 test false-positive rate (C4 in the claim matrix) is direct evidence the learned normal region may be session- or mounting-specific, and this experiment is what would establish it. |

---

## E — Session-level train/validation/test splitting

| | |
|---|---|
| **Status** | `COMPLETED` |
| **Code** | New `src/splits.py` (manifest loader, `session_id_of`, `split_of`, `labelled_session_paths`, `assert_disjoint`). `merge_real_hardware_data.py` now loads TRAIN sessions only; `evaluate_real_hardware.py` takes `--split`, defaulting to `test`. |
| **Experimental** | Manifest `data/splits/session_split.json`. TRAIN `20260902_171313`, `20260902_102448`; VALIDATION `20260902_173108`; TEST `20260902_221217`. Four `20260901_*` sessions explicitly excluded. Two simulated validation draws (VAL_001 fusion, VAL_002 thresholds/policy). |
| **Tests** | `TestSessionSplit` — 7 tests: pairwise disjointness, no session both allocated and excluded, every file on disk allocated or explicitly excluded, no held-out session id in the merged training file, provenance present on every training row, fusion and policy on different sessions, no `train_*.py` references the test session. |
| **Evidence** | The leak was real and load-bearing: real at-rest training rows fell 121 → 103, and the real-hardware false-positive rate moved **0/49 → 5/12**. The whole published figure had been resting on the overlap. |
| **Remaining limitation** | Four sessions is a very small denominator — the TEST split has 12 resting windows. More sessions is the only fix. |

---

## F — Window, event, and session-level results

| | |
|---|---|
| **Status** | `PARTIALLY_COMPLETED` |
| **Done** | Window-level and **event-level** metrics in `scripts/evaluate_gnn_baselines.py` (`event_metrics()`), with the detection criterion stated explicitly: an event counts as detected if at least one scoreable window inside its interval yields an anomaly decision. Event recall reported for all five comparators. |
| **Not done** | Per-session metric tables (`session_metrics.csv`) are not emitted for the real-hardware evaluation — with one test session there is one row, so the table would restate the headline rather than add information. Deferred until more sessions exist. |
| **Docs** | `docs/EXPERIMENTAL_PROTOCOL.md` §6. |
| **Remaining limitation** | Cluster-bootstrap intervals over sessions are described in the protocol but not implemented; with one test session there is nothing to resample over. Window-level Wilson intervals remain, explicitly labelled window-level. |

---

## G — Fair multi-device baselines against the GNN

| | |
|---|---|
| **Status** | `COMPLETED` — **and the GNN lost.** |
| **Code** | `scripts/evaluate_gnn_baselines.py`. Five comparators on byte-identical inputs, built once and shared: B0 single-device, B1 concatenated logistic regression, B2 small MLP (32,16 / ReLU / Adam / lr 1e-3 / 400 iters), B3 coordinated rule (`k` from validation), GNN. |
| **Experimental** | Two declared tasks. Fit on TRAIN, all selection on VALIDATION (thresholds by F1, `k`, self-loop weight from `{1,2,3,5}`), TEST read once. |
| **Evidence** | Task 1 test F1 — MLP **0.9852**, single-device 0.9771, GNN **0.8381**, logistic 0.7785, rule 0.6156. Task 2 test accuracy — MLP **0.6567**, logistic 0.6433, GNN **0.6058**, node-count 0.4142. |
| **Files** | `results/gnn_baselines/metrics.json`, `self_loop_sweep.json` |
| **Consequence** | GNN-superiority claims are **withdrawn**. The defensible claim is about cross-device information (0.4142 → 0.6567), not graph structure. See `docs/CLAIM_EVIDENCE_MATRIX.md` C2/C3. |
| **Remaining limitation** | One topology, one graph size, one GCN architecture. Node 02 absent. This shows the GNN did not help *here*, not that graph learning cannot help. |

---

## H — Meta-learner / stacking leakage

| | |
|---|---|
| **Status** | `COMPLETED` |
| **Code** | `train_fusion_meta_learner.py` now replays `validation_session.json` (SIM_SESSION_VAL_001) instead of the training session the base models were fitted on. `train_adaptive_pdp.py` uses a **second** validation draw (VAL_002), because it consumes fusion's output and sharing a session would reintroduce the same optimism one level up. |
| **Method** | Held-out stacking, not out-of-fold — recorded and justified in the script docstring (the base chain is stateful; k-fold would mean k full retrains and k artifact sets for no honest gain over one clean split). |
| **Evidence** | The leak was measurable in the fitted coefficients. Under the old in-sample fit the LSTM-AE coefficient came out **−0.46** — the wrong sign for a signal whose whole purpose is to fall on anomalies. Leakage-free it is **+5.97**: `[rule −0.003, iso +2.97, lstm +5.97, gnn +8.33]`. |
| **Tests** | `test_fusion_and_policy_do_not_train_on_the_same_session`, `test_no_trainer_reads_the_test_session`. |
| **Remaining limitation** | The real VALIDATION session is not used in meta-training — after the mandatory `2·LSTM_SEQ_LEN` warmup discard it yields ~15 rows, too few to move a four-coefficient fit. Recorded in the script rather than done silently. |

---

## I — Security Trust specification

| | |
|---|---|
| **Status** | `COMPLETED` |
| **Docs** | New `docs/SECURITY_TRUST_SPEC.md` — initial value and rationale, update rule in order, both decay clamps and why each exists, silence handling (and why Process Anomaly's differs), flood/rate measurement, failed-auth attribution, recovery, threshold and how it was chosen, full constant table. |
| **Code** | No behavioural change — the implementation was already correct. The audit (`docs/REPOSITORY_AUDIT.md` §3) records this explicitly so the revision did not manufacture a fix. |
| **Remaining limitation** | `SECURITY_THRESHOLD = 0.6` remains a reasoned choice, not an optimised one. The validation sweep that would replace it selected `θ_proc = 0.05`, which is not operationally usable — reported, not adopted (concern J). |

---

## J — Common vs separate thresholds

| | |
|---|---|
| **Status** | `COMPLETED` |
| **Code** | `scripts/evaluate_policy_comparison.py`, both configurations selected on VALIDATION by macro-F1, reported on the untouched test split. |
| **Evidence** | Common `θ = 0.7`: test macro-F1 **0.4865**. Separate `θ_sec = 0.7`, `θ_proc = 0.05`: **0.5614**. |
| **Interpretation** | Separate scored higher, but the selected `θ_proc = 0.05` would make the deployed system nearly blind to process anomalies. **The selection objective is not the deployment objective.** Deployed thresholds unchanged at 0.6/0.6, and the gap is reported as the finding. |

---

## K — Authenticated malicious/anomalous telemetry

| | |
|---|---|
| **Status** | `IMPLEMENTED_PENDING_DATA` |
| **Code/Protocol** | `docs/EXPERIMENTAL_PROTOCOL.md` §5.4. A correctly authenticated board (valid identity, HMAC, boot_id, seq, timestamp, TLS) producing deliberately abnormal physical telemetry. |
| **Evidence** | The *architecture* already produces this outcome on real data: in the TEST session, disturbed blocks scored process 0.000 while Security Trust remained untouched throughout — which is the two-score separation behaving exactly as intended, on genuine hardware. |
| **Remaining limitation** | Not yet run as a **named, deliberately-provoked** experiment with the outcome recorded as such. The outcome is measured, never hard-coded. |

---

## L — Anti-replay state regression test

| | |
|---|---|
| **Status** | `COMPLETED` (pre-existing, verified and documented, not re-fixed) |
| **Code** | `check_boot_replay()` is a pure predicate; `commit_boot_seq()` is the sole mutator and runs only after every admission gate passes. |
| **Tests** | `TestBootReplayStateIsolation` — `test_predicate_does_not_mutate`, `test_rejected_stale_message_does_not_lock_out_the_real_device`, `test_commit_is_monotonic`. |
| **Evidence** | Found by live adversarial testing, fixed in commit `560694b`. Replay protection was not weakened to make the test pass. Recorded in `docs/REPOSITORY_AUDIT.md` §3.2 as already-correct. |

---

## M — Low/medium/high amplitude

| | |
|---|---|
| **Status** | `PARTIALLY_COMPLETED` |
| **Done** | The TEST session already contains graded `fault_weak` (22 scored windows) / `fault_strong` (8), both detected 100%. `--intensity` schedule added for an explicit low/medium/high sweep. |
| **Not done** | The intensity sweep has not been captured. |
| **Wording** | Explicitly **not calibrated** — no shaker table, no reference accelerometer. Reported as "operator-controlled low-intensity disturbance", with observed rms/peak/crest/dominant_freq published alongside. |
| **Remaining limitation** | The detection floor has **not been located** — both graded levels were detected, so the floor lies below `fault_weak`. |

---

## N — Adaptive-policy comparison and terminology

| | |
|---|---|
| **Status** | `COMPLETED` — **and the adaptive policy lost.** |
| **Terminology** | Corrected throughout: it is a **contextual bandit with sample-average action-value estimation**, not reinforcement learning. No discount factor, no next-state bootstrapping, reward a fixed function of (state, action). `RL_*` config names retained to avoid a ~20-site rename; the method is described correctly in the docstring, the spec, and the manuscript. |
| **Evidence** | Test macro-F1: static-optimised **0.5614**, decision tree 0.6453, adaptive bandit **0.5271**, multiclass LR 0.4410, deployed static 0.2744. |
| **Files** | `results/policy_comparison/metrics.json` |
| **Remaining limitation** | Synthetic test session; macro-F1 is sensitive to the class mix. |

---

## O — Complete confusion matrices

| | |
|---|---|
| **Status** | `COMPLETED` |
| **Files** | `results/policy_comparison/confusion_matrix_{P1..P5}.csv` (4×4, ALLOW/ALERT/STEP_UP/BLOCK) plus per-class support/TP/FP/TN/FN/precision/recall/F1, macro-F1, weighted-F1, accuracy, false-block rate, false-step-up rate in `metrics.json`. |
| **Rare class** | Reported in full, not hidden — see below. |

---

## Rare combined class (BLOCK)

| | |
|---|---|
| **Status** | `COMPLETED` — reported as a **negative result** |
| **Evidence** | Support 33. Recall: static 0.000, static-optimised 0.000, adaptive 0.000, multiclass LR 0.030, decision tree 1.000 **at precision 0.021** (1529 false positives, 52.7% false-block rate). |
| **Interpretation** | The class is `stealthy_forged_values` — a correctly authenticated device reporting normal-looking values. Its `(s_sec, s_proc)` state is by construction indistinguishable from normal, so no policy over those two inputs can separate it. A known architectural blind spot, not a tuning failure. |
| **Required discussion** | "Recall on the combined class is effectively zero for every policy with a usable false-block rate; the one policy achieving full recall does so at 2.1% precision and a 52.7% false-block burden, limiting immediate deployment suitability." |

---

## P — Latency measurement

| | |
|---|---|
| **Status** | `COMPLETED` |
| **Code** | `scripts/evaluate_latency_stages.py` — eleven stages timed independently with `time.perf_counter_ns`; count/mean/sd/p50/p95/p99/max for each. |
| **Evidence** | Total pipeline mean **2.93 ms**, p50 1.25, p95 10.91, p99 **14.48**, max **324.71**. Cold start 1268 ms reported separately, never amortised. 10-node network tick mean 163 ms ≈ 61 msg/s. |
| **Files** | `results/latency/latency.json`, `latency.csv`; host in `docs/ENVIRONMENT.md` |
| **Honesty note** | Max is ~110× the median. A mean alone materially misrepresents this pipeline — which is precisely the concern. The audit-log figure is hash-chain computation only; the SQLite write is I/O-bound and excluded, stated rather than omitted. |
| **Remaining limitation** | Ten nodes is not evidence of industrial scalability and is not presented as such. |

---

## Writing concerns (§46–§61)

| Concern | Status | Where |
|---|---|---|
| §46 Reduce overclaiming / GNN necessity | `COMPLETED` | C3 withdrawn outright; permitted/forbidden wording in `CLAIM_EVIDENCE_MATRIX.md` |
| §47 Explainability "structurally invalid" | `PARTIALLY_COMPLETED` | Bounded wording specified in C13; **`METHODOLOGY.md` prose not yet rewritten** |
| §48 Hardware / industrial claim | `COMPLETED` | C4, protocol §8 — proof-of-concept wording, industrial validation named as future work |
| §49 Ten-node claim | `COMPLETED` | Required wording fixed in protocol §1 and C10; assertion in `config.py` |
| §50 Sensor replication | `COMPLETED` | C11 — heterogeneous, not same-model |
| §51 Abstract | `NOT_YET_ADDRESSED` | Awaits the numbers above being folded into the manuscript |
| §52 Contribution list | `NOT_YET_ADDRESSED` | Must drop any GNN-necessity contribution given C3 |
| §53 Related work / "systematic" | `NOT_YET_ADDRESSED` | No literature-search protocol exists, so "representative recent work" is the only permissible framing |
| §54 Novelty claim | `NOT_YET_ADDRESSED` | Bounded phrasing required |
| §55 Exact SHAP terminology | `COMPLETED` | C13 — margin-space, relative to baseline |
| §56 Random seeds | `COMPLETED` | `ENVIRONMENT.md` §6 — optimization stability, not generalization |
| §57 Rare class discussion | `COMPLETED` | Rare-class row above, C8 |
| §58 HMAC notation | `COMPLETED` | Audit §3.1 — implementation already non-recursive; notation now stated |
| §59 Results/discussion structure | `NOT_YET_ADDRESSED` | Observation/Interpretation/Alternative/Limitation/Implication framing not yet applied to `RESULTS.md` |
| §60 Limitations section | `COMPLETED` | `EXPERIMENTAL_PROTOCOL.md` §8 |
| §61 Conclusion | `NOT_YET_ADDRESSED` | Awaits §51/§52 |

---

## Summary

| Status | Count |
|---|---|
| `COMPLETED` | 11 |
| `PARTIALLY_COMPLETED` | 3 |
| `IMPLEMENTED_PENDING_DATA` | 3 |
| `NOT_YET_ADDRESSED` | 5 (all manuscript prose) |

**Two findings overturn previously published claims** and must propagate into
the manuscript before submission:

1. **The GNN does not beat simpler models on identical information** (concern G).
2. **A validation-tuned static policy beats the adaptive policy** (concern N).

**One published number is withdrawn**: the 0/49 real-hardware false-positive
rate was measured under session leakage; the honest figure is 5/12.
