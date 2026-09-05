# Repository Audit — ZT-Duo / zt-cps-starter

**Date:** 2026-09-03
**Commit at audit:** `6a56ba5`
**Scope:** full recursive inspection of `src/`, `scripts/`, `firmware/`, `tests/`,
`data/`, `models/`, and all manuscript-supporting Markdown, ahead of the
revision to a 10-node hybrid CPS network (2 real ESP32 + 8 simulated).

This document records **confirmed problems only** — every finding below was
verified by reading the code that causes it, not inferred from a reviewer
comment. Where a reviewer concern is already correctly handled in the existing
implementation, that is recorded too, under §3, so the revision does not
"fix" something that is not broken.

---

## 1. What exists and works

The repository is a substantially complete Zero-Trust CPS gateway. The
following are correct as built and are **preserved unchanged** by this revision:

| Component | File | Status |
|---|---|---|
| Two-score separation (Security Trust ⟂ Process Anomaly) | `src/trust_engine.py`, `src/policy_engine.py` | Correct. `decide()` takes exactly two scores + staleness. Enforced by `TestTwoScoreSeparation`. |
| HMAC envelope construction | `src/gateway.py:133`, `firmware/main.py:421` | Correct and **non-recursive** — see §3.1. |
| Anti-replay state invariant | `src/trust_engine.py:287` / `:317` | Correct. `check_boot_replay()` is a pure predicate; state advances only in `commit_boot_seq()` after every gate passes. Regression-tested by `TestBootReplayStateIsolation`. |
| Failed-auth attribution | `src/trust_engine.py:163` `IdentityTargetingRisk` | Correct. A rejected message never touches the claimed device's own trust state. |
| Train/serve feature equivalence | `src/feature_engineering.py` ↔ `firmware/main.py` | Correct, and differentially tested (`TestFirmwareReferenceEquivalence`). |
| Preprocessing fit scope | `scripts/train_lstm_ae.py:56-59` | Correct. Normalization mean/std fitted on the **training** normals only, persisted to `*_meta.json`. No test-time refit. |
| No online learning on the live path | `src/gateway.py` | Correct. No `.fit()` / `.update()` anywhere in the inference path. |
| Hash-chained audit log | `src/audit_log.py` | Correct, with checkpointing and four falsification tests. |
| Governance falsifiability | `src/governance_validation.py` | Correct — 7/7 tenets reject an injected falsifier. |

**Test suite:** 46 stdlib-`unittest` tests in `tests/test_invariants.py`. Every
test guards a property that has already been broken once. No test was found
that cannot fail.

---

## 2. Confirmed problems

### 2.1 — Fusion meta-learner leakage (HIGH)

**File:** `scripts/train_fusion_meta_learner.py:32`

`build_dataset()` replays `data/collected/training_session.json` — the *same*
session that `train_isolation_forest.py`, `train_lstm_ae.py` and `train_gnn.py`
were fitted on — through those now-trained base models, and trains the logistic
meta-learner on the resulting `[rule, if, lstm, gnn] → label` pairs.

The base models' scores on their own training data are optimistic. The
meta-learner therefore learns coefficients calibrated to in-sample base-model
behaviour, which is not the behaviour it will see at inference.

This is reviewer concern **H**, and it is real. There is no out-of-fold
stacking and no separate meta-training split.

### 2.2 — No session-level train/validation/test split for real hardware (HIGH)

**Files:** `scripts/merge_real_hardware_data.py:63`, `scripts/evaluate_real_hardware.py:82`

`merge_real_hardware_data.py` takes the `at_rest` rows from **every**
`*_labelled.json` session into the training set.
`evaluate_real_hardware.py` then loads **every** `*_labelled.json` session,
including the disturbance rows from those same sessions, and reports detection
and false-positive rates on them.

So a single physical acquisition session contributes rows to both training and
evaluation. The splits are not disjoint at the session level. This is reviewer
concern **E**.

Secondary consequence: `merge_real_hardware_data.py:104-113` rebuilds each
merged record from scratch and **drops** `phase`, `label_source`, `elapsed_s`
and the source filename. Provenance is destroyed at the merge boundary — a
merged training row cannot be traced back to its session, and carries no
`source_type`.

### 2.3 — No validation split at all (HIGH)

There are exactly two synthetic datasets: `training_session.json` (seed 42) and
`test_session.json` (seed 999). There is no third split.

Consequences, all confirmed by reading the code:

- `SECURITY_THRESHOLD = 0.6` and `PROCESS_THRESHOLD = 0.6` (`src/config.py:577-578`)
  are hardcoded constants with no recorded selection procedure — not tuned on
  test data, but not selected against a validation objective either.
- The fusion meta-learner has nowhere leakage-free to train (§2.1).
- `scripts/train_adaptive_pdp.py:36` trains on `training_session.json`, the
  same file again.
- `GNN_SELF_LOOP_WEIGHT = 3.0` (`src/config.py:529`) has no recorded sweep.

### 2.4 — No multi-device baseline for the GNN (HIGH)

**File:** `scripts/evaluate_ablation.py`

The ablation compares `rule` / `iso` / `lstm` / `gnn` / `fused` — that is,
single-device signals against the GNN. Nothing in the repository compares the
GNN against a **simpler model receiving the same multi-device information**.

Any claim that graph structure is what produced the GNN's advantage is
therefore unsupported by the current evidence: a concatenated logistic
regression over the same per-node scores has never been run. This is reviewer
concern **G**.

### 2.5 — Window-level metrics only (HIGH)

**Files:** `scripts/evaluate_ablation.py`, `scripts/evaluate_real_hardware.py`

Every reported rate is per-window. `evaluate_real_hardware.py` computes Wilson
intervals over window counts (`:57`), but consecutive windows from one physical
disturbance are strongly correlated — they overlap in the LSTM sequence and
come from one continuous operator action.

Treating them as independent binomial trials understates the interval width.
There is no event-level or session-level metric anywhere in the repository.
This is reviewer concern **F**, and it interacts with §2.2: with only four
sessions, session-level reporting is the honest denominator.

### 2.6 — "RL policy" is not reinforcement learning (MEDIUM)

**File:** `src/adaptive_pdp.py:118`

The update rule is

```
Q[a] += (reward - Q[a]) / N(s,a)
```

an incremental **sample average**. There is no discount factor, no next-state
bootstrapping, no temporal credit assignment. Reward depends only on
`(state, action)` via a fixed lookup (`CORRECT_ACTION_FOR_SITUATION`).

This is a **contextual bandit with sample-average action-value estimation**,
which is a legitimate and well-suited choice here — the problem genuinely has
no state transitions. But `USE_RL_POLICY`, `RL_TRAINING_EPISODES`,
`train_adaptive_pdp.py` and the manuscript all call it reinforcement learning.
The terminology is wrong, not the method. Reviewer concern **N**.

Additionally, at the time of this finding it was compared only against the static
2×2 table. (Resolved since: decision-tree and multiclass-LR baselines on the same
`(s_sec, s_proc)` inputs now exist — `docs/CLAIM_EVIDENCE_MATRIX.md` C6, `RESULTS.md`
§0.13.6.)

### 2.7 — Mean-only latency (MEDIUM)

**File:** `scripts/evaluate_latency.py`

Reports aggregate timings without per-stage p50/p95/p99/max breakdown. A mean
hides the tail that matters for a gateway.

### 2.8 — Three-node graph, no topology rationale (MEDIUM)

**File:** `src/gnn_scorer.py:73`

`normalized_adjacency()` connects **every** pair of active devices — a complete
graph. With three nodes this is unremarkable and no justification was needed.
At ten nodes a complete graph is a modelling choice that must be defended or
replaced, and there is no `config/graph_topology.json` or equivalent.

`GNN_SELF_LOOP_WEIGHT = 3.0` is likewise unswept (§2.3).

### 2.9 — Provenance is not carried through the pipeline (MEDIUM)

No record anywhere in `data/collected/` carries `source_type`, `session_id`,
`event_id`, `mounting_condition` or `split`. Session identity exists only as a
filename, and `evaluate_real_hardware.py:79` reconstructs it into a `_session`
key at load time. `merge_real_hardware_data.py` discards it entirely (§2.2).

Real and simulated rows are distinguishable today only because the real ones
happen to have `event_type == "normal"` and a tick number past `TICK_GAP`.
That is an accident of construction, not a provenance field.

### 2.10 — No second physical device (MEDIUM — scope, not defect)

`DEVICE_REGISTRY` holds one `feature_vector` device (`esp32-vib-001`) and two
`scalar` simulated devices carried over from the starter kit. The revised
design requires two real nodes and eight simulated ones.

`config.is_feature_vector()` and `FEATURE_VECTOR_DEVICE_IDS` were written to
make adding devices a data change rather than a code change, so the existing
structure supports this. But the SW-420 second node is **heterogeneous** — a
digital vibration switch produces event-count/duty-cycle features, not
RMS/kurtosis/dominant-frequency — so a third `kind` is required.

### 2.11 — Manuscript overclaiming (LOW, but must be fixed)

Scan of all Markdown for the flagged phrasings returned three occurrences
(`METHODOLOGY.md` ×1, `PRD.md` ×2). Small in count, but the substantive claims
needing bounding are broader than the phrase scan finds — GNN necessity,
explainability structural claims, hardware validation scope, and the
forthcoming ten-node wording. Reviewer concerns §46–§61.

---

## 3. Reviewer concerns that the code already handles correctly

Recorded so the revision does not manufacture a fix for a non-problem.

### 3.1 — HMAC formulation is already non-recursive (concern §23 / §58)

Both implementations build

```
M0        = canonical_json({device_id, rms, peak, crest_factor, kurtosis,
                            dominant_freq, boot_id, seq, ts [, step_up_nonce_echo]})
sigma     = HMAC-SHA256(device_key, M0)
envelope  = {"payload": M0, "signature": sigma}
```

`src/gateway.py:144` signs `json.dumps(payload, sort_keys=True)`;
`firmware/main.py:436` signs `canonical_json(fields)`. The signature is never
an input to itself. `TestCanonicalisationContract` proves the hand-built
MicroPython string matches CPython's `json.dumps` byte-for-byte.

The **implementation is correct**; only the manuscript notation needs to state
it explicitly (it currently does not state it at all).

### 3.2 — Anti-replay state invariant already holds (concern §21)

`check_boot_replay()` carries an explicit `PURE PREDICATE -- must not mutate
auth state` contract and is verified by three tests including
`test_rejected_stale_message_does_not_lock_out_the_real_device`. This was found
by live adversarial testing (commit `560694b`) and already fixed. The revision
formalises the attack record, it does not re-fix the bug.

### 3.3 — Preprocessing is not leaked (concern §34)

`train_lstm_ae.py` fits mean/std on training normals only and persists them.
`isolation_forest_scorer` calibrates from `raw_normal_median` measured on the
same training normals. No scaler is refitted at evaluation time.

### 3.4 — Never training on the live path

Confirmed by grep: no `.fit(` or `.update(` in `src/gateway.py` or any
`*_scorer.py`.

### 3.5 — Real-hardware contribution is already measured, not assumed

`merge_real_hardware_data.py --synthetic-only` exists specifically to retrain
the chain without real rows and measure their contribution (13/49 → 0/49 false
positives, `RESULTS.md` 0.10.9 — ⚠ pre-split: the 0/49 baseline is the withdrawn
leaky figure, so the *direction* holds but the magnitude must be re-measured under
session-level splitting, `docs/CLAIM_EVIDENCE_MATRIX.md` C14). This is the correct
experimental instinct and is retained.

---

## 4. Answers to the audit questions posed in the revision brief

| # | Question | Finding |
|---|---|---|
| 5 | Train/test leakage? | **Yes** — at the session level for real hardware (§2.2). Synthetic train/test are seed-separated and disjoint. |
| 6 | Preprocessing leakage? | **No** (§3.3). |
| 7 | Meta-learner leakage? | **Yes** (§2.1). |
| 8 | How are sessions identified? | Filename only; not a field on any record (§2.9). |
| 9 | How is hardware data collected? | `scripts/collect_hardware_session.py --labelled`, operator-marked intervals, `MARK_MARGIN_S` trimmed. Sound. |
| 10 | How is simulated data generated? | `src/device_simulator.py` `_synthetic_accel_window()`, constants calibrated against measured real telemetry. Sound, but one profile only. |
| 11 | How are graph edges defined? | Complete graph over devices active within `GNN_EDGE_WINDOW_SECONDS` (§2.8). |
| 12 | How are thresholds selected? | They are not — hardcoded 0.6/0.6 (§2.3). |
| 13 | How does Security Trust behave? | Fully implemented (`trust_engine.py:419`), correct, but specified across scattered docstrings rather than one authoritative document (concern **I**). |
| 14 | How is adaptive policy trained? | Contextual bandit, sample-average, on the training session (§2.6, §2.1). |
| 15 | Are result tables traceable? | **Partially.** `RESULTS.md` numbers are reproducible by re-running the named script, but there is no machine-readable `results/` tree and no run manifest. |

---

## 5. Work implied by this audit

Ordered by dependency, not by severity.

1. Provenance fields on every record; session/split manifests (§2.9, §2.2).
2. Session-level split, disjointness enforced by test (§2.2).
3. Leakage-free fusion: base models on TRAIN, meta-learner on VALIDATION (§2.1).
4. Threshold selection on validation, with a stated objective (§2.3).
5. Second real node (SW-420, heterogeneous `kind`) + eight simulated profiles (§2.10).
6. Defensible ten-node topology + self-loop sweep on validation (§2.8).
7. Same-information multi-device baselines against the GNN (§2.4).
8. Policy baselines: static, optimised static, decision tree, multiclass (§2.6).
9. Window / event / session metrics, cluster-aware intervals (§2.5).
10. Per-stage latency percentiles (§2.7).
11. Security Trust specification document (concern **I**).
12. Manuscript bounding pass (§2.11).
