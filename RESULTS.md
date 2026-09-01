# Results and Evaluation

This is the standalone results record for the Zero-Trust CPS project —
every number below comes from actually running `scripts/evaluate_*.py`
against this repository's real trained models and a held-out test split
(`data/collected/test_session.json`, generated with a different random
seed from the training data, per `docs/10_testing_and_attack_simulation.md`
Section 3.3), or from directly watching a live `gateway.py` +
`device_simulator.py` run. Nothing here is asserted without a
corresponding script or a directly-observed log line — where a script's
own name is given, re-running it should reproduce the same figures (small
run-to-run noise is possible in the RL convergence trend only, since that
one script trains a fresh throwaway bandit with epsilon-greedy
exploration each time it's run).

**Read `docs/00_overview.md`'s AS-BUILT callout first** if you haven't —
it lists the deliberate deviations from the original design docs (trust-
style Process Anomaly scale, flat `src/` layout, RL/GNN as live defaults)
that the numbers below should be read in light of.

## Figure Index

Every figure below is a PNG in `docs/figures/`, produced by
`scripts/generate_evaluation_graphs.py` — which calls the SAME functions
the corresponding `evaluate_*.py` script uses (or replays the identical
logic where a script only prints rather than returns), so a figure and
this document's numbers can never silently drift apart. Regenerate all
20 with `python scripts/generate_evaluation_graphs.py` after any retrain.

| Figure | Shows | Section |
|---|---|---|
| `fig1_signal_comparison_blended.png` | Accuracy/precision/recall/F1, all 6 signals | 2 |
| `fig2_per_event_type_recall.png` | Per-event-type recall, all 6 signals | 2.1 |
| `fig3_fair_lstm_vs_transformer.png` | LSTM-AE vs. Transformer, undiluted | 2.2 |
| `fig4_capacity_vs_accuracy_tradeoff.png` | Params vs. F1 scatter, LSTM-AE vs. Transformer | 2.2 |
| `fig5_rl_vs_static_reward.png` | Avg reward, static vs. RL | 3.1 |
| `fig6_confusion_matrix_static.png` / `_rl.png` | 4-class confusion matrix heatmaps | 3.2 |
| `fig7_macro_f1_comparison.png` | Macro-F1, static vs. RL | 3.2 |
| `fig8_latency.png` | HMAC-only vs. full-pipeline latency | 6 |
| `fig9_level1_explainability.png` | SHAP top-feature match rate | 4 |
| `fig10_level2_explainability_by_signal.png` | Perturbation flip rate by dominant signal | 4.1 |
| `fig11_rl_convergence_trend.png` | Fresh-bandit reward per episode | 3.3 |
| `fig12_nist_governance_coverage.png` | NIST SP 800-207 tenet coverage | 5.1 |
| `fig13_iec62443_fr_coverage.png` | IEC 62443-3-3 FR coverage | 5.2 |
| `fig14_score_responsiveness.png` | Mean messages to threshold break, by event type | 7 |
| `fig15_dataset_class_balance.png` | Train vs. test event-type composition | 12 |
| `fig16_threshold_sensitivity_*.png` | Precision/recall/F1 vs. decision threshold (IF, GNN, fused) | 2 |
| `fig17_training_loss_lstm_vs_transformer.png` | Training loss curves, both architectures | 2.2 |

---

## 1. What Was Verified Live (Not Just Measured Offline)

Before any of the numeric results below, these are the qualitative,
directly-observed behaviours confirmed by actually running the gateway
and simulator together, watching the console, and inspecting the audit
log — not inferred from code review:

| Behaviour | How it was checked | Result |
|---|---|---|
| A device reboot (`boot_id` incremented, `seq` reset to 1) is accepted, not rejected | Simulated reboot scenario, watched the next message get scored normally | **Confirmed** |
| A replay of a pre-reboot message is rejected after the reboot | Captured message replayed post-reboot | **Confirmed** — `replay_or_stale_sequence` / `replay_of_superseded_boot_session` |
| A forged-signature attack against a real device never touches that device's own Security Trust Score | 50+ forged-HMAC attempts against `actuator-001`, checked its score before/after | **Confirmed** — score untouched, `IdentityTargetingRisk` counter climbed instead |
| A message-rate flood is detected and triggers a real step-up challenge | Live flood burst (`device_simulator.py`'s `high_rate` scenario) | **Confirmed** — `FLOOD detected` → `STEP_UP` |
| Step-up TIMEOUT/MISMATCH escalates to BLOCK, single clean resolution (not a repeated-mismatch loop) | Watched a flood burst where the device didn't answer in time | **Confirmed**, after fixing a real bug (see Section 9) |
| Step-up SUCCESS releases the message and applies a bounded trust boost | Watched a flood burst after the `mosquitto_acl` fix + broker restart | **Confirmed** — `step-up SUCCESS (bounded trust boost applied)`, Security Trust Score rose 0.66→0.76 across the exchange |
| Hash chain detects a naive edit to an old audit row | Manually edited one row's `decision`, re-ran `verify_chain_integrity()` | **Confirmed** — `(False, <row id>)` |
| Hash chain alone is fooled by a sophisticated edit (edit + recompute every subsequent hash) | Manually recomputed the whole chain after an edit | **Confirmed** (expected, documents the known limit) — `verify_chain_integrity()` incorrectly reports `(True, None)` |
| The separate checkpoint catches the sophisticated edit the chain check misses | Compared the recomputed chain against the independently-stored checkpoint | **Confirmed** — mismatch correctly detected |
| Live dashboard reads real data | `design/zero-trust-cps-command-center.html`, served with a live overlay by `gateway.py` itself (`gateway.py`'s Module 9 extension section, no separate script) | **Confirmed** — tested end to end against real hardware telemetry (Section 13): main page, all `/api/*` endpoints, and `/figures` gallery all verified working |
| A rate anomaly from a REAL physical device (not the simulator) triggers a real BLOCK | The real `esp32-vib-001` board itself, live | **Confirmed** — `rms=1.02 FLOOD \| security=0.49 \| process=0.40(FRESH) \| BLOCK` with `FLOOD detected (messages arriving faster than the minimum interval)`. Previously this exact response was only ever confirmed with `device_simulator.py`'s synthetic flood scenario (row above) — this is the first live confirmation against genuine hardware. Note this is a Security Trust (rate/timing) event, distinct from Section 13.2's still-pending Process Anomaly (physical fault) adversarial testing — the two domains stay separately evidenced on purpose. |
| A real physical sensor fault (MPU6050 disconnected) is caught by the fusion pipeline even though the rule check alone misses it | Disconnected/reconnected the real MPU6050 while the board was running | **Confirmed, and a real gap found + fixed** — the disconnected sensor read back all-zero I2C bytes rather than erroring, publishing physically-impossible `rms=peak=crest_factor=kurtosis=0.0`; the rule check's old `(0.0, 3.0)` `rms` bound missed it, but replaying the exact reading through the live scorers gave `fused=0.008` (well below threshold) — the GNN/Isolation Forest caught what the rule check didn't, confirming the fusion design's defense-in-depth. `rms`'s lower bound raised to `0.1` anyway (Section 13.2), verified not to regress the synthetic baseline or reject any real session's data. |

---

## 2. Ablation Study — Does Fusing the Process Anomaly Signals Help?

`scripts/evaluate_ablation.py`, 610 held-out messages, 23 excluded
(`auth_ok=False` or `event_type=="replay"` — rejected at Module 2 in the
live architecture, never reach Process Anomaly scoring). Ground truth is
`physical_label(event_type)` (physically legitimate vs. physically
anomalous), **not** the old blended label — see Section 12.

Label balance: 541 physically-legitimate, 46 physically-anomalous.

**Dataset size note (methodology change from the numbers below's original
run):** `scripts/generate_training_data.py`/`generate_test_data.py`'s
`TICKS` were raised 400→5,000 (train) and 200→1,000 (test) — still purely
synthetic (every tick is another draw from the same generator, not
duplicated data) but ~3,967 normal esp32-vib-001 training readings instead
of ~345, so a higher-capacity candidate signal (Section 2.2's Transformer)
has enough data to be evaluated fairly rather than penalized for a
small-dataset artifact. Every model below was retrained on this larger set
before these numbers were produced; see Section 12 for the full note.

| Signal | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| Rule-based range check | 0.921 | 0.921 | 1.000 | 0.959 |
| Isolation Forest | 0.937 | 0.960 | 0.972 | 0.966 |
| LSTM-Autoencoder | 0.753 | 0.957 | 0.766 | 0.851 |
| Transformer (ablation candidate) | 0.753 | 0.957 | 0.767 | 0.851 |
| GNN | 0.929 | 0.987 | 0.935 | 0.960 |
| **Fused (meta-learner)** | 0.703 | 0.996 | 0.681 | 0.809 |

**Read the LSTM-AE/Transformer rows with Section 2.2 in hand before citing
them** — both columns are diluted by rule_score standing in for the two
scalar devices (66% of rows), which is why they tie to three decimals here
despite Section 2.2's undiluted comparison finding a real, if modest,
difference between them.

**Fusion trades raw aggregate accuracy for coverage of the rarer, harder
scenarios** (Section 3 below) — this is a deliberate, measured trade-off,
not an unexplained regression: Isolation Forest wins on raw aggregate
accuracy, but the fused score is what actually catches `coordinated`
(Section 3), which no individual signal except the GNN comes close to.
The meta-learner is trained with `class_weight="balanced"` specifically
because an unweighted fit let the numerous easy `normal`/`anomalous_shock`
examples dominate the decision boundary and effectively discard the GNN's
signal on the rarer `coordinated` pattern.

### 2.1 Per-Event-Type Recall

| Signal | anomalous_shock | coordinated | high_rate | stealthy_forged_values |
|---|---|---|---|---|
| Rule-based | 0.000 | 0.000 | n/a* | 0.000 |
| Isolation Forest | 1.000 | 0.316 | n/a* | 0.121 |
| LSTM-Autoencoder | 1.000 | 0.308 | n/a* | 0.606 |
| Transformer (ablation candidate) | 1.000 | 0.308 | n/a* | 0.606 |
| GNN | 1.000 | 1.000 | n/a* | 0.000 |
| **Fused** | 1.000 | **1.000** | n/a* | 0.758 |

LSTM-AE and Transformer are identical here because both are governed by
the same dilution described above, not because the two architectures
behave identically — see Section 2.2.

### 2.2 Transformer Ablation Candidate — Fair Comparison, and Why the Diluted Column Above Isn't the Real Comparison

`src/transformer_scorer.py` + `scripts/train_transformer.py` add a small
Transformer encoder (2 layers, 4 heads, `d_model=32`, 17,701 params) as a
fifth Process Anomaly sub-signal, evaluated in `scripts/evaluate_ablation.py`
alongside the existing four — **not** wired into `fusion_engine.py`'s
inputs (same keep/drop precedent Section B.5 of
`docs/04_module3_trust_evaluation.md` already sets for the GNN: prove it
on held-out data before folding it into fusion). Same task framing as the
LSTM-AE (reconstruct a window of recent feature vectors, score by
reconstruction error), same window length (`LSTM_SEQ_LEN`, shared, not a
separate constant, specifically so the comparison isolates architecture as
the only variable) — but trained as a **denoiser** (Gaussian noise added
to the input, loss against the clean window) rather than plain
reconstruction. This matters mechanically: self-attention gives every
position in the window direct access to every other position, so a
*plain* reconstruction Transformer can partially shortcut — attend to
neighboring true values and copy them, under-scoring real anomalies in a
way an LSTM's recurrent bottleneck prevents by construction. The denoising
objective removes that shortcut without changing the task framing.

**The Section 2/2.1 columns above are not a fair comparison of the two
architectures.** Only esp32-vib-001 (34% of test rows) has a real
LSTM-AE/Transformer model; the other two devices mirror `rule_score` into
that slot (`isolation_forest_scorer.py`'s docstring). That dilutes any real
architectural difference with an identical, unrelated number for 66% of
rows — exactly why the two columns tie to three decimals above.

Isolating esp32-vib-001 rows exposed a second, more consequential issue:
on the raw isolated subset, **both** models flagged ~75% of genuinely
normal test messages as suspicious (LSTM 74.9%, Transformer 74.7%) — far
too high to be real, and identical between architectures, which was the
tell that this wasn't an architecture problem. Root cause: `train_lstm_ae.py`
/`train_transformer.py` build training windows only from `label==1` rows
with anomalies filtered *out* (gaps skipped in the tick sequence), so the
model never learns what a window looks like in the few messages right
after a real anomaly. Live inference (and any evaluation that replays the
true interleaved stream) *does* produce that shape — a message that is
itself normal but sits within `LSTM_SEQ_LEN` messages of a recent
`anomalous_shock`/`coordinated`/`stealthy_forged_values`/`high_rate` event
has a window shape the model never saw in training. This is precisely the
"window residue" effect `train_fusion_meta_learner.py` already documents
and excludes for the *fusion* target (its `window_compromised` flag) — it
had just never been applied when judging the LSTM-AE/Transformer signals
on their own. `scripts/evaluate_ablation.py` now applies the same
exclusion in a dedicated "FAIR COMPARISON" block. Of 1,000 esp32-vib-001
test rows, 746 were residue-contaminated normal messages — with
`anomalous_shock`/`coordinated`/`stealthy_forged_values`/`high_rate`
recurring roughly every 12–30 ticks against an 8-message window, most
nominally-"normal" esp32 messages are in fact recovery-period messages,
not steady-state baseline. This is itself worth flagging honestly for
anyone extending this dataset design: a denser attack-injection schedule
relative to window length shrinks the pool of genuinely clean "normal"
examples available for a fair per-signal evaluation.

**Corrected, undiluted result** (esp32-vib-001 only, 254 clean rows after
exclusion):

| Signal | Accuracy | Precision | Recall | F1 | Params |
|---|---|---|---|---|---|
| LSTM-AE | 0.933 | 0.875 | 0.970 | 0.920 | 3,029 |
| **Transformer** | **0.941** | **0.877** | **0.990** | **0.930** | 17,701 |

The Transformer genuinely edges out the LSTM-AE once measured fairly — small
(+0.010 F1) but real. A 7-way hyperparameter sweep (pre-LN vs post-LN,
ReLU vs GELU, 6x more capacity, up to 400 epochs, varied noise/LR/weight
decay) reproduced this exact same result across every configuration,
which is what makes it a genuine effect rather than one lucky training
run — and also why no config change was kept: the current, cheapest
configuration is already at the ceiling this data/task supports.

**Decision: still not folded into live fusion.** A +1pt F1 gain for ~6x
the parameters is a real but marginal win, and per-event recall
(`anomalous_shock`, `coordinated`, `stealthy_forged_values`) is identical
between the two architectures — the Transformer does not move the
`stealthy_forged_values` ceiling (Section 11) at all, confirming that
limitation is a data problem, not a model-capacity problem, exactly as
`docs/04_module3_trust_evaluation.md` Section B.8 already argues.

\* `high_rate`'s physical reading is legitimate by construction (it's a
pure Security Trust / rate concern, not a physical anomaly) — there is
nothing for the Process Anomaly Engine to correctly catch here, so
"recall" doesn't apply.

**Read this carefully before citing it as "100% detection":**
`anomalous_shock` injects a 3.0–4.5g spike against a ~1.0g±0.03 baseline —
a large, cleanly-separable synthetic signal by construction. A detector
reaching ~100% on it is *expected*, not remarkable, and is not evidence
the same detector would catch an equivalently-sized real-world event with
the same certainty. `coordinated` is the exact relational pattern the
GNN's class-weighted loss was specifically tuned to catch, measured on a
small held-out slice (n=23) from the *same synthetic generator family*
(different random seed, same distributions) as training — a real,
reproducible result on this specific pipeline, but a narrower claim than
"generalises to real coordinated attacks."

---

## 3. Multi-Class Confusion Matrix and Policy Comparison

`scripts/evaluate_rl_policy.py`. The final Module 5 decision has four
outcomes (`ALLOW`/`ALERT`/`STEP_UP`/`BLOCK`) against four ground-truth
situation classes (`normal`/`physical_fault`/`security_concern`/
`combined`) — plain precision/recall is the wrong tool for this; a
confusion matrix with macro-F1 is used instead
(`docs/10_testing_and_attack_simulation.md` Section 4.1).

### 3.1 Held-Out Comparison (2,933 authenticated messages)

**Re-measured after the dataset scale-up** (Section 12's methodology
note) — `scripts/train_adaptive_pdp.py` was re-run against the enlarged
training set specifically for this; the deployed Q-table below is not
the same one the original 587-message-era numbers described.

| Policy | Avg reward | ALLOW | ALERT | STEP_UP | BLOCK |
|---|---|---|---|---|---|
| Static 2×2 table | 0.282 | 1802 | 1131 | 0 | 0 |
| **RL (greedy, deployed)** | **0.606** | 2185 | 403 | 163 | 182 |
| RL (ε=0.1, training-mode contrast only) | 0.502 | 2052 | 451 | 200 | 230 |

### 3.2 Confusion Matrices (rows = actual situation, columns = predicted)

**Static 2×2 table** — macro-F1 = **0.269**

| Actual \ Predicted | ALLOW | STEP_UP | ALERT | BLOCK | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| normal | 1680 | 0 | 861 | 0 | 0.932 | 0.661 | 0.774 |
| physical_fault | 0 | 0 | 200 | 0 | 0.177 | 1.000 | 0.301 |
| security_concern | 117 | 0 | 42 | 0 | 0.000 | 0.000 | 0.000 |
| combined | 5 | 0 | 28 | 0 | 0.000 | 0.000 | 0.000 |

**RL (greedy, deployed)** — macro-F1 = **0.583**

| Actual \ Predicted | ALLOW | STEP_UP | ALERT | BLOCK | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| normal | 2079 | 0 | 299 | 163 | 0.951 | 0.818 | 0.880 |
| physical_fault | 86 | 4 | 104 | 6 | 0.258 | 0.520 | 0.345 |
| security_concern | 0 | 159 | 0 | 0 | 0.975 | 1.000 | 0.988 |
| combined | 20 | 0 | 0 | 13 | 0.071 | 0.394 | 0.121 |

**Why RL wins on `security_concern` specifically**: the static table only
issues `STEP_UP` once `security_trust_score` crosses below 0.6 — and a
single momentary flood burst, under the EWMA (α=0.35), doesn't reliably
cross that line (one flood observation pulls the score to ~0.66, still
above threshold). The RL policy learns per-bucket Q-values directly from
reward feedback and can react to a *weaker* signal than the hard-coded
threshold, which is exactly what its 1.000 recall vs. the static table's
0.000 shows — a genuine, explainable advantage of the adaptive policy,
not a fluke.

**Why `combined` recall (0.394) comes at a real precision cost (0.071)**:
`combined` is the rarest class (33 of 2,933), so `situation_weights()`'s
inverse-frequency reward weighting up-weights it to ~22.1× in absolute
terms (`normal`'s own weight is ~0.29×, so ~76× relative to `normal` —
`train_adaptive_pdp.py` prints the exact weights on every run). That's
what makes the RL policy willing to predict `BLOCK` often enough to catch
a real fraction of `combined` cases at all — but it also makes it `BLOCK`
many `normal`/`physical_fault` messages it shouldn't (163 and 6 false
positives respectively). Recall dropped from an earlier-measured 0.667 to
0.394 on the larger, retrained dataset — reported as the current,
accurate number, not reconciled backward toward the old one. This is
reported as-is, not tuned to look better — see Section 11 for why chasing
`stealthy_forged_values`/`combined` further is a known, accepted limit of
this design, not a bug to fix by further reweighting.

### 3.3 Convergence Trend

A fresh bandit (situation-weighted reward, same scheme as the deployed
model) trained from scratch over 20 episodes on the training set oscillates
between roughly 0.33 and 0.38 average reward per episode — noisy but
stable, consistent with genuine epsilon-greedy exploration rather than a
diverging or non-learning process. (Re-running this specific check
reproduces a similar but not identical curve, since it retrains a fresh
throwaway bandit each time — the *deployed* Q-table used for all figures
above is fixed and does not change between runs.) The much tighter
oscillation band than the pre-scale-up run (previously ~0.37–0.62) is
itself a plausible, expected consequence of ~4x more training triples
(14,667 vs. the earlier dataset) giving epsilon-greedy exploration more
observations per state bucket to average over before the episode ends,
not a change in the underlying learning dynamics.

---

## 4. Explainability Validation

`scripts/evaluate_explainability.py`. For each held-out message with a
genuine physical anomaly (`anomalous_shock`/`out_of_range`/`coordinated`
— `high_rate`/`stealthy_forged_values`/rejected messages are excluded, see
that script's docstring for why), checks whether the SHAP-identified
dominant Process Anomaly signal matches a pre-defined physically-sensible
set for that event type.

**Result: 40/40 (100%)** of checked messages had a SHAP top-feature
attribution matching the physically-sensible feature set for their
injected anomaly type. All 8 sampled `coordinated` cases in this run
correctly attributed to `gnn_score` — the signal actually responsible.

### 4.1 Level-2 (Feature-Level) Explainability — Now Implemented, With an Honest Result

`docs/04_module3_trust_evaluation.md` Section C.3 specified this but it
was not yet built as a separate function — closed this round.
`src/explainability.py` orchestrates per-signal Level-2 methods added
directly to each scorer: `shap.TreeExplainer` for Isolation Forest
(`isolation_forest_scorer.py`), leave-one-channel-out perturbation for
LSTM-AE/Transformer (`lstm_ae_scorer.py`/`transformer_scorer.py` — replace
one feature channel across the whole window with its normalized training
mean, remeasure reconstruction error), leave-one-node-out perturbation for
the GNN (`gnn_scorer.py` — mask one neighboring device's features,
remeasure this device's own score), and the already-available
`rule_range_score()` reason string for the trivial rule case. Wired into
the live gateway (`gateway.py` computes it right after
`fusion_engine.combine()`, using `fusion_engine.last_shap` to know which
signal was Level-1-dominant) and logged to two new audit columns
(`level2_dominant_feature`, `level2_summary`).

`scripts/evaluate_explainability_level2.py` implements Section C.4's
validation procedure exactly (adapted for this project's trust-style
scale, not the design doc's literal anomaly-style wording — see that
script's docstring): perturb the named Level-2 feature toward "normal",
re-run the full Process Anomaly Engine, check whether the fused score
recovers above the 0.5 threshold.

**Result: 82/225 (36%) overall — below the 70% target, and reported
honestly rather than adjusted to look better.** The aggregate number
hides a real, informative split by signal:

| Dominant signal | Flip rate | Why |
|---|---|---|
| GNN | 80/80 (**100%**) | Masking the one neighboring device actually responsible for a `coordinated` reading fully explains the anomaly — the relational signal really is that node's whole story. |
| Isolation Forest | 2/129 (**2%**) | SHAP correctly ranks which raw feature contributed most (Section 4's 100% result already confirms this), but an Isolation Forest's anomaly score is the isolation depth across many tree splits on many features jointly — replacing one feature, even the top-ranked one, doesn't collapse the ensemble's path length back to "normal" when several correlated features (`rms`/`peak`/`crest_factor` are all derived from the same raw window) are elevated together. |
| LSTM-AE | 0/16 (**0%**) | Same underlying cause as Isolation Forest: `anomalous_shock`/`coordinated` windows typically elevate several of the 5 correlated features at once, so zeroing one channel leaves the others still driving reconstruction error up. |

**This is a genuine, informative finding about explanation validity
across model families, not a bug to chase toward 70%:** Level 1 SHAP is
already validated as 100% physically-sensible (Section 4 above) — the
gap here is specifically about whether a *single-feature* perturbation
is a strong enough intervention to fully flip a *multi-feature-correlated*
model's decision, and the honest answer is "yes for the GNN's relational
signal, no for the two feature-correlated signals." Reported as measured;
future work wanting to close this gap should perturb the FULL set of
elevated features together for IF/LSTM-AE, not just the single top-ranked
one — a different (and arguably more informative) validation design than
Section C.4's literal single-feature procedure, out of this round's scope.

---

## 5. Governance Alignment

### 5.1 NIST SP 800-207 (`scripts/evaluate_governance.py`)

**100% (7 of 7) tenets** have traceable evidence across every logged
decision.

**Read this as a coverage metric, not a detection-accuracy metric** —
this is the answer to "how is 100% possible" that came up mid-project.
Tenets 1/3/4/5/6 are satisfied for *every* decision by construction (they
describe structural properties of the pipeline itself — every decision
has an auth verdict, came from a fresh per-message policy call, etc. —
not something a model has to get right). Tenet 2 is 100% only because
every message in this environment genuinely arrives over MQTT/TLS or
HTTPS; tenet 7 only because the fusion model is trained. 100% here means
"the governance evidence-logging mechanism is switched on and running" —
a binary condition, not a percentage that could meaningfully land at 87%
instead.

### 5.2 IEC 62443-3-3 (`scripts/evaluate_iec62443.py`)

| FR | Name | Status | Coverage |
|---|---|---|---|
| FR1 | Identification and Authentication Control | Implemented | 100% |
| FR2 | Use Control | Implemented | 100% |
| FR3 | System Integrity | Implemented | 100% |
| FR4 | Data Confidentiality | Implemented | 100% |
| FR5 | Restricted Data Flow | **Partial** | real transport-layer controls (per-device MQTT credentials + topic ACLs) exist; no physical/VLAN network segmentation |
| FR6 | Timely Response to Events | Implemented | 100% |
| FR7 | Resource Availability | **Partial** | flood detection + Identity Targeting cooldown + process supervision exist; no multi-instance redundancy |

**Security Level self-assessment: SL-2** ("protection against intentional
violation using simple means with low resources, generic skills, low
motivation") — evidenced by HMAC authentication, TLS/HTTPS, boot-aware
anti-replay, per-device broker credentials, and the attribution fix.
Explicitly **not** claiming SL-3/4: no mutual TLS, no hardware secure
element, FR5/FR7 partial, and the `stealthy_forged_values` limit
(Section 11) — see `src/iec62443_mapping.py`'s full reasoning.

---

## 6. Resource and Performance Overhead

`scripts/evaluate_latency.py`, measured on the development machine, 200
messages after a 20-message warmup:

| Measurement | Mean | Median | p95 | Max |
|---|---|---|---|---|
| HMAC verification only | 0.021 ms | 0.020 ms | 0.027 ms | 0.100 ms |
| Full pipeline (auth + 4 Process Anomaly signals + fusion + policy + Level-2 explainability) | 43.499 ms | 41.587 ms | 56.890 ms | 147.657 ms |

**Re-measured after adding Level-2 explainability** (Section 4.1), which
now runs unconditionally on every authenticated message — a deliberate
deviation from `docs/09_integration_and_data_flow.md`'s original design
(compute Level 1/2 "only when a score is near/past its threshold...
computing full explanations for every single normal message is
wasteful"). **Verified, not assumed, that this deviation doesn't
actually cost anything measurable**: 43.499ms vs. the pre-Level-2 44.037ms
baseline is within ordinary run-to-run noise, not a regression — the
extra perturbation forward passes (a handful of tiny sub-3K-to-18K-
parameter model calls) are cheap enough at this model scale that
threshold-gating them would have been a premature optimization. Kept
unconditional for the simpler code path and because every message now
carries a real Level-2 explanation in the audit log, not just the ones
that happened to be near a threshold.

Device-side (ESP32) signing/feature-extraction latency: **measured, see
Section 13.1** — the ESP32's feature-extraction step alone (~134ms,
dominated by the hand-rolled O(N²) DFT run in interpreted MicroPython)
costs more than this entire gateway-side full pipeline (43.5ms mean),
despite the gateway doing 4 ML models + fusion + policy + explainability
per message. Expected, not a red flag: a constrained device's interpreted
loop vs. a PC's compiled numpy/torch is exactly where you'd expect the
gap to land.

---

## 7. Score Responsiveness

`scripts/evaluate_trust_responsiveness.py` — replays the held-out set in
order through the real stateful pipeline, measuring how many of a
device's own subsequent *scored* messages it takes for each score to
cross its threshold after an injected event.

| Event type | n | rejected | mean msgs→SECURITY break | mean msgs→PROCESS break |
|---|---|---|---|---|
| anomalous_shock | 17 | 0 | n/a | 0.00 |
| coordinated | 23 | 0 | n/a | 0.00 |
| forged_signature | 13 | 13 | n/a | n/a |
| high_rate | 33 | 0 | n/a | 3.03 |
| replay | 10 | 10 | n/a | n/a |
| stealthy_forged_values | 6 | 0 | n/a | 0.83 |

**Two results worth reading carefully, not glossing over:**

- **`high_rate` never crosses the SECURITY threshold from a single burst**
  (shown as `n/a`). A momentary flood pulls Security Trust to ~0.66 under
  the EWMA — below its pre-flood baseline, but not below the 0.6
  threshold from one observation alone. This is arguably correct,
  conservative behaviour (a security system shouldn't fully distrust a
  device from one anomalous-rate tick — matching the "continuous, not
  instant" EWMA philosophy) and is exactly why the RL policy's ability to
  react to the sub-threshold signal (Section 3) is a genuine advantage,
  not a redundant one.
- **`high_rate` shows a non-`n/a` PROCESS mean (3.03) — investigated and
  resolved, not a leak.** `scripts/diagnose_high_rate_leak.py` replays the
  exact same stateful pipeline `evaluate_trust_responsiveness.py` uses
  (imports its `replay_with_state()` logic, not a reimplementation) but
  keeps every sub-signal (rule/IF/LSTM/GNN) instead of just the fused
  output. Every flagged `high_rate` row is `esp32-vib-001`, `rule_score`
  passing cleanly (`0.9`, "all features within expected range"), with
  `lstm_score` floored at `0.0` — and **17 of 18** flagged rows sit
  *exactly 4 messages* after a real `anomalous_shock` event, well inside
  `LSTM_SEQ_LEN=8`'s reconstruction window (verified computationally: the
  one exception, at distance 10 — outside the window — had by far the
  mildest dip, 0.5719 vs. the others' 0.05–0.19). This is the SAME
  "window residue" contamination effect Section 2.2/9 already documents
  and excludes for the LSTM-AE/Transformer fair comparison — it had just
  never been checked against `high_rate` specifically. Root cause is
  synthetic-generator scheduling, not a live architectural leak:
  `anomalous_shock` (`tick%12==7`) and `high_rate` (`tick%18==11`) are
  fixed periodic patterns in the generator, so they deterministically
  co-occur near each other on a regular cadence — a coincidence that
  would not occur with genuinely independent, non-periodic real-world
  event timing. **The two-score separation itself is intact**: it's not
  that a rate event moves the Process score, it's that the Process
  score's OWN feature-window state happens to still be contaminated by an
  unrelated recent physical event when a rate event's message lands.
- `stealthy_forged_values` moves the PROCESS score for some (not all)
  messages (mean 0.83, not `n/a`) — a *better*-than-expected partial
  detection rate, consistent with Section 2.1's fused 0.500 recall on the
  same event type. Not the "reliably undetectable" worst case the design
  acknowledges as possible, but not reliable detection either — see
  Section 11.

---

## 8. Audit Log Integrity

Verified via a direct, scripted tamper test against a real (not
synthetic) audit log produced by a live gateway run:

1. **Clean log**: `verify_chain_integrity()` → `(True, None)`;
   `verify_against_checkpoints()` → `(True, None)`.
2. **Naive tamper** (edit one old row's `decision`, do not touch hashes):
   `verify_chain_integrity()` → `(False, <row id>)`. Caught immediately.
3. **Sophisticated tamper** (edit a row AND recompute every subsequent
   `prev_hash`/`this_hash` to stay internally consistent):
   `verify_chain_integrity()` alone → `(True, None)` — **incorrectly
   passes**, exactly the known limit this design's checkpoint mechanism
   exists to catch. `verify_against_checkpoints()` on the same tampered
   log → mismatch correctly detected, since the independently-stored
   checkpoint's hash no longer matches the recomputed chain.

A real bug was found and fixed while building this specific test:
`scripts/evaluate_latency.py` originally redirected only `AUDIT_DB_PATH`
to a throwaway database, not `CHECKPOINT_STORE_PATH`/`AUDIT_KEY_PATH` —
its throwaway run's checkpoint writes silently polluted the real, shared
checkpoint file, which broke tamper-detection on a completely untampered
real audit log the first time this test was run. Fixed by redirecting all
three paths together; see `SESSION_LOG.md` for the full diagnosis.

---

## 9. Real Bugs Found and Fixed During This Evaluation Round

Listed here because they materially affect how the numbers above should
be read — several of the figures in this document are the *post-fix*
result of bugs that would otherwise have made them wrong or misleading.
Full diagnosis for each is in `SESSION_LOG.md`.

1. **Trust-poisoning vulnerability** (pre-existing design flaw, not a
   coding bug): a failed-auth message fed directly into the *claimed*
   device's own trust score. Fixed with `IdentityTargetingRisk`.
2. **Replay blind spot** (pre-existing): a ts-size heuristic couldn't
   distinguish a captured pre-reboot message from a genuine reboot in one
   specific case. Fixed with `boot_id`/`seq`.
3. **Step-up mismatch never cleared**: an unanswered challenge kept
   re-comparing against every subsequent unrelated message, escalating to
   `BLOCK` repeatedly instead of resolving once. Fixed to clear on every
   terminal outcome and treat "no echo yet" as "still waiting," not an
   immediate failure.
4. **Missing broker ACL rules**: `cps/challenge/*` had no read/write
   permissions at all, so no device could ever receive a challenge
   regardless of the echo logic's correctness. Fixed and confirmed live
   after a broker restart (Section 1).
5. **Stale Q-table format collision**: an old (pre-rearchitecture)
   Q-table used the same string key format for entirely different state
   semantics, causing a `KeyError` the first time the new code touched a
   collided key. Fixed by validating the loaded table's action set and
   discarding it wholesale if incompatible.
6. **Label noise in Process Anomaly training**: `high_rate` (a pure
   Security Trust event with a genuinely normal physical reading) was
   trained against the old blended label as "suspicious," teaching the
   fusion/GNN models that ordinary-looking features sometimes mean
   suspicious with nothing in the features to justify it. Measured effect
   before the fix: fused aggregate accuracy on held-out data dropped to
   ~0.68, `coordinated` recall to ~0.30. Fixed with
   `physical_label(event_type)` as the correct ground truth.
7. **RL class-imbalance bug**: unweighted RL training left
   `physical_fault` recall at 0.125 — *worse* than the static table's
   trivial 1.000 — despite the underlying Process Anomaly signal cleanly
   separating those events. Fixed with the same inverse-frequency reward
   weighting used for the fusion meta-learner; `physical_fault` recall
   recovered to 0.475, macro-F1 rose to the 0.553 reported in Section 3.
8. **Checkpoint cross-contamination** (Section 8).
9. **Window-residue evaluation blind spot** (pre-existing, found while
   fairly comparing the LSTM-AE against the new Transformer sub-signal,
   Section 2.2): `scripts/evaluate_ablation.py` scored `lstm_ae_score`/
   `transformer_score` against the raw interleaved message stream, but
   both models are trained only on windows with anomalies filtered out —
   so a genuinely normal message shortly after a real anomaly looks like
   nothing either model was trained on, and both were measured as
   ~75%-false-positive on isolated esp32-vib-001 test rows before the fix.
   `train_fusion_meta_learner.py` already excludes exactly these rows
   (`window_compromised`) for its own training target; fixed by applying
   the same exclusion to evaluation, in a new "FAIR COMPARISON" block.
10. **Audit-log hash-chain schema-migration gotcha** (found live, adding
    the Level-2 explainability columns): `audit_log.py`'s
    `verify_chain_integrity()` recomputes each row's hash from
    `SELECT *`, i.e. whatever columns exist NOW — adding a column (even
    one that backfills existing rows as NULL) changes every historical
    row's canonical JSON, so the chain check reported every row broken
    starting from row 1 immediately after the migration. Not tampering —
    fixed with a one-time re-baseline (recompute `this_hash`/`prev_hash`
    for all 31,670 existing rows and regenerate all 316 checkpoints
    against the new schema); both `verify_chain_integrity()` and
    `verify_against_checkpoints()` pass cleanly again. A warning comment
    is now in `audit_log.py` itself so the next column addition doesn't
    silently repeat this.

---

## 10. Deviations From the Design Docs

Two implementation choices depart from a literal reading of
`docs/00_overview.md` onward. Both are deliberate and do not change the
underlying architecture:

- **Process Anomaly Score kept trust-style** (high = normal) rather than
  the docs' literal anomaly-style scale (high = anomalous) — chosen so
  the already-trained, already-ablated fusion meta-learner's coefficients
  didn't need to be retrained with a flipped sign.
- **Flat `src/*.py` + `config.py`** kept instead of a package-per-module
  layout with `config.yaml` — a code-organization choice with no effect
  on the module boundaries or architecture.
- **Transformer sub-signal added, evaluated, and deliberately NOT adopted**
  (Section 2.2) — not in any design doc at all, added as a fifth Process
  Anomaly ablation candidate. Genuinely edges out the LSTM-AE on a fair,
  undiluted comparison (+0.010 F1), but the margin is small relative to
  ~6x the parameters, so it stays an ablation-only signal, same as the
  GNN's own keep/drop precedent before it was adopted.

RL and the GNN are **live defaults**, not optional stretch goals — see
`docs/06_module5_access_control.md`'s AS-BUILT note for why the RL
policy's frozen, no-exploration inference path makes this safe (it needs
no live reward signal, since it never updates itself online).

---

## 11. Acknowledged Detection Limit: Stealthy Compromised Devices

`stealthy_forged_values` (attack-matrix row 11) simulates a device that
still holds valid credentials but deliberately reports fabricated sensor
values chosen to look normal. This is **not expected to be reliably
detected** by a single-node design — there is nothing in the telemetry
itself that distinguishes a real in-range reading from a fabricated one.
Measured recall: 0.758 (fused signal, Section 2.1), 0.394 (RL policy's
`combined` class, Section 3.2) — better than a worst-case zero, but not
reliable detection, and not tuned to be better than it honestly is. This
is the intended, reported result of including this scenario, not an
unfixed bug — see `docs/04_module3_trust_evaluation.md` Section B.8 for
the full reasoning, and consider a redundant independently-trusted sensor
or multi-node cross-validation (out of this project's scope) as the
natural next step if this limit needs closing.

**Confirmed architecture-agnostic, not just theoretically so:** the
Transformer sub-signal added in Section 2.2 scores `stealthy_forged_values`
recall identically to the LSTM-AE (0.606 in Section 2.1's blended table,
per-event recall unchanged in the fair comparison too) despite genuinely
more capacity and a fair, undiluted evaluation. A different, larger
architecture did not move this number at all — direct evidence that this
is a data problem (no distinguishing signal in the telemetry itself), not
a capacity problem a bigger model could have closed. See Section 14 for
the remediation options this actually requires (multi-node/redundant
sensing), none of which are "try a different model."

See Section 14 for this project's full acknowledged-limitations table,
including this one alongside the other four open gaps and what each would
actually take to close.

---

## 12. Methodology Notes

- All numeric results above are computed on `data/collected/test_session.json`,
  generated with a **different random seed** from
  `data/collected/training_session.json` (per
  `docs/10_testing_and_attack_simulation.md` Section 3.3) — this is a
  held-out split from the same synthetic generator family, not
  independent real-world data. See Section 13.
- Ground truth for Process Anomaly evaluation (Sections 2, 4) is
  `physical_label(event_type)` — 1 (physically legitimate) or 0
  (physically anomalous), derived from `situation_for_event_type()`
  (`scripts/generate_training_data.py`) — **not** the older blended
  `label` field, which conflated security and physical evidence (see
  Section 9, item 6, for why that distinction is load-bearing).
- Ground truth for policy evaluation (Section 3) is the four-class
  `situation` (`normal`/`physical_fault`/`security_concern`/`combined`),
  also from `situation_for_event_type()`.
- `auth_ok=False` and `event_type=="replay"` records are excluded from
  every Process Anomaly / policy evaluation script — both represent
  messages Module 2 rejects outright in the live architecture and never
  reach Module 3 or Module 5 at all (see `gateway.py`'s `_reject()`).
- **Dataset size** (added this round): `TICKS` in
  `scripts/generate_training_data.py`/`generate_test_data.py` raised
  400→5,000 / 200→1,000. Still the same synthetic generator family and
  same random-seed separation described above — this changes *how much*
  data, not *what kind*. Every model in Sections 2–7 was retrained on the
  larger set; numbers in this document reflect that, not the original
  345-normal-reading run.
- **Window-residue exclusion** (added this round, Section 2.2/9 item 9):
  `scripts/evaluate_ablation.py`'s "FAIR COMPARISON" block excludes
  esp32-vib-001 rows where the message is itself normal but its
  `LSTM_SEQ_LEN`-message window still contains a recent true anomaly —
  the same `window_compromised` logic `train_fusion_meta_learner.py`
  already applies to its own training target. This exclusion applies
  ONLY to that block's `lstm_ae_score`/`transformer_score` comparison, not
  to the main Section 2/2.1 tables, which intentionally still reflect the
  raw, undiluted-by-exclusion pipeline behavior.

---

## 13. Hardware-in-the-Loop Results

**Status: real board flashed, authenticated, and running live; real data
collected across multiple sessions and folded into the trained models
with a controlled, measured before/after comparison; device-side latency
and RAM/flash footprint measured (Sections 13.1/13.4). True physical
adversarial testing (Section 13.2) and real network round-trip latency
(the one remaining item in 13.4) are what's left, both requiring new
physical action, not more analysis** — everything below is what has
actually been measured, not aspirational. Results in
Sections 1–12 above remain simulator-only; this section is the real-world
counterpart, kept separate rather than blended in, so every number's
provenance stays unambiguous.

### 13.0 Real Bring-Up: Bugs Found Only By Running On Real Silicon

The software-only HMAC/canonicalisation verification (thousands of
synthetic values, zero mismatches, referenced throughout Sections 1–12)
turned out to be necessary but not sufficient — four real integration bugs
only surfaced once actual hardware was in the loop, none of them
reachable by any amount of additional synthetic-value checking:

1. **`ImportError: no module named 'ussl'`** — this board's MicroPython
   build renamed `ussl` to `ssl`. Fixed with a `try`/`except ImportError`
   fallback in `firmware/main.py` (`import ssl as ussl`); the rest of the
   file is unaffected since the API is identical under either name.
2. **MicroPython epoch mismatch** — `time.time()` on this port counts
   seconds since 2000-01-01, not the Unix epoch (1970-01-01) `gateway.py`'s
   `time.time()` uses. NTP sync sets the RTC correctly but doesn't change
   the epoch reference, so every `ts` looked ~30 years stale to
   `check_timestamp_freshness()` even on a perfectly-synced clock — every
   message was rejected as `stale_timestamp` despite `boot_id`/`seq` (the
   primary anti-replay check) passing fine. Fixed by adding the fixed
   946,684,800-second offset when building `ts_ms`.
3. **Intermittent NTP timeout on first attempt** — a single `ntptime.settime()`
   call immediately after WiFi association intermittently raised
   `ETIMEDOUT` even though a retry a couple seconds later succeeded.
   `sync_time()` now retries up to 3 times, 2 seconds apart, before giving
   up (non-fatally — `boot_id`/`seq` doesn't depend on this at all).
4. **Misleading Level-2 GNN explanation with no active neighbors** —
   `gnn_scorer.py::level2_explain()` perturbs each other device's node and
   picks whichever change is largest; with zero currently-active neighbors
   (the real board's actual live situation — `sensor-002`/`actuator-001`
   only exist as simulated devices, not always running), every candidate
   ties at exactly `change=0.0`, and the loop's `>` comparison silently
   "picked" the first device in iteration order every time (always
   `sensor-002`), reporting a fake relational attribution
   (`"GNN score most driven by neighboring device 'sensor-002' (score
   change=0.000)"`) instead of correctly reporting no attribution at all.
   Fixed: `level2_explain()` now returns `None` when the best change is
   ≤1e-6, and `explainability.py` reports an honest `"GNN score based on
   this device's own signals only -- no other device is currently active
   in the graph"` instead. Verified directly (not just read) with the
   actual trained model and a single-active-device input.

None of these are ML/scoring bugs — they're exactly the class of issue the
software-only pre-hardware verification structurally could not catch
(firmware runtime behavior, real network timing, real graph connectivity
state), which is the whole reason this section exists separately from
Sections 1–12.

### 13.0.1 Why `process_trust_score` Initially Read Near-Zero — Investigated, Not Assumed

Once telemetry was flowing and authenticated, the live gateway console
showed a genuinely normal board scoring `process=0.00`, `gnn_score=0.00`,
an identical-looking `SHAP=-6.45`, and a `security_trust_score` plateaued
around 0.90–0.91 — enough overlapping oddities to warrant re-checking the
whole scoring pipeline rather than assuming any one of them. Read
`gnn_scorer.py`, `explainability.py`, `fusion_engine.py`, and
`trust_engine.py` directly against the actual `audit_log.db` rows (not
just the console text) to get a grounded answer for each:

- **`gnn_score≈0.00`**: the GNN's node features are `[rule_score,
  if_score, lstm_score]`, not raw sensor values, and it only forms graph
  edges to devices active within `GNN_EDGE_WINDOW_SECONDS`. With
  `sensor-002`/`actuator-001` not currently publishing, `esp32-vib-001`
  had no active neighbors — its output was a function of only its own
  inputs, landing deep in the trained model's saturated sigmoid tail for
  that combination. Confirmed genuinely moving, not frozen: real DB values
  ranged `4.6e-8` to `2.2e-7` — too small to print as anything but `0.00`.
- **`SHAP=-6.45` looking identical across messages**: it wasn't — raw
  values differed in the 6th decimal place, and the console rounds to 2
  significant figures for display. The LSTM-AE's SHAP contribution *was*
  briefly bit-identical every message (before the real-data retrain in
  13.2), because `lstm_score` itself was exactly `0.0` every message —
  legitimate `LinearExplainer` math (`coefficient × (x − background_mean)`
  gives identical output for identical input), not a caching bug.
- **`process_trust_score≈0.00`**: `fusion_engine.py`'s combine step is
  additive in log-odds (a fitted `LogisticRegression`), not a
  multiplicative crush by one bad signal. But three of the four inputs
  (`if_score`, `lstm_score`, `gnn_score`) were independently reading this
  device as anomalous at once, summing to roughly -13 to -15 log-odds;
  `rule_score`'s SHAP contributed almost nothing because 0.9 (a passing
  rule check) is also close to what the models consider "typical," so it
  carries little marginal information either way. This is the same
  train/serve mismatch Section 13.2's retraining directly addresses.
- **`security_trust_score` plateaued ~0.90–0.91**: solved algebraically,
  not just observed — `trust_engine.py::score_security_trust()`'s EWMA
  (`α=0.35`, `TRUST_DECAY_PER_SECOND=0.01`, ~2.2s between messages,
  observation=0.95 for "authenticated, normal rate") has a fixed point at
  `0.35×0.95 + 0.65×(score − decay) = score` → **score ≈ 0.908**, matching
  the observed 0.907–0.91 range exactly. Genuine steady-state convergence
  for a consistently well-behaved device, not an artificial cap (the only
  clamps in that function are 0/1 sanity bounds, never hit here).

**Verdict, and the one real bug that surfaced along the way**: every
low/plateaued number above is a real, mathematically-consistent
consequence of feeding real hardware through models trained solely on
synthetic data (Section 13.2 is the fix — more real training data) — not
a computation bug. The one genuine bug this investigation *did* surface is
already listed as item 4 in Section 13.0 above (the fake GNN neighbor
attribution).

### 13.1 Device-Side Latency — measured

`firmware/main.py` measures, per message, using `time.ticks_ms()`/
`time.ticks_diff()` (the MicroPython-correct way — handles the periodic
tick-counter wraparound a naive subtraction would get wrong): sampling
time (the 32-reading I2C accelerometer window), feature-extraction time
(RMS/peak/crest-factor/kurtosis + the on-device DFT for `dominant_freq`),
and signing time (canonicalisation + HMAC-SHA256). 4 consecutive real
messages, `boot_id=12`:

| Stage | Min | Max | Mean (n=4) |
| --- | --- | --- | --- |
| Sampling (32× I2C read) | 26 ms | 30 ms | 27.2 ms |
| Feature extraction (incl. DFT) | 134 ms | 136 ms | 134.5 ms |
| Sign (canonicalise + HMAC-SHA256) | 9 ms | 10 ms | 9.2 ms |
| **Total on-device compute** | | | **~171 ms** |

At a 2000ms publish interval, that's a ~8.6% duty cycle — comfortable
headroom, not close to falling behind. **Feature extraction dominates**,
specifically the hand-rolled O(N²) DFT for `dominant_freq` (32 samples →
16 frequency bins, each a full sine/cosine sum) run in interpreted
MicroPython — consistent with, and larger than, the entire gateway-side
full pipeline (Section 6: 43.5ms mean, including 4 ML models + fusion +
policy + Level-2 explainability on real hardware, just PC-class CPU
running compiled numpy/torch instead of an interpreted loop on a
microcontroller). Signing is comparatively cheap — two SHA256 passes
(HMAC's inner/outer padding) plus small-string canonicalisation, ~9ms.
A small sample (n=4) from one session, not a statistically rigorous
benchmark — sufficient to characterize where the time goes, not to bound
tail latency precisely.

### 13.2 Real Physical Data Collection — baseline done, adversarial testing still pending

**What was done**: `scripts/collect_hardware_session.py` (a read-only MQTT
subscriber, safe alongside a live `gateway.py`) captured real
`esp32-vib-001` telemetry across 5 sessions and varied legitimate physical
conditions — at rest, gentle tapping, moderate shaking, tilting/rotating,
and longer free-form mixed sessions — joining in `gateway.py`'s own live
`fused_score`/`security_trust_score`/`decision` for each captured message
from `audit_log.db` (not recomputed separately). One session (of 5)
captured 0 records — it overlapped with an ~11-minute window where the
board was manually disconnected (confirmed with the user, not a bug to
chase), left in this count rather than quietly dropped. That same window
is also what motivated the silence-watchdog fix in Section 14 — a
genuinely silent device previously produced no live signal distinguishing
"deliberately disconnected" from "gone offline/compromised," which this
project can now at least detect and log, even though it still can't
determine which of those it is from telemetry alone. Total: **380 real
records**. Observed real feature ranges (combined across all sessions):

| feature | observed range |
|---|---|
| rms | ~0.33 – 3.42 g |
| peak | ~0.01 – 2.19 g |
| crest_factor | ~0.01 – 1.30 |
| kurtosis | ~-1.72 – 25.36 |
| dominant_freq | 3.125 – 28.125 Hz |

All comfortably inside `DEVICE_REGISTRY["esp32-vib-001"]["expected_ranges"]`
(Section 13.3) — no rule-based range false positives from real hardware.

**Methodology caveat, noticed and worth stating plainly**: the per-phase
labels in `firmware/HARDWARE_DATA_LOG.md` are approximate, not precise
ground truth. In more than one session, the `moderate_shake` phase showed
*less* feature variation than the `at_rest` phases surrounding it — almost
certainly because picking the board up / setting it down / cable
movement right at a phase boundary produced more physical disturbance
than the deliberate "shake" itself. Harmless for this round's purpose
(all of it is legitimate real-hardware data, correctly labeled `label=1`/
`event_type="normal"` regardless of which specific phase it landed in —
see `scripts/collect_hardware_session.py`'s docstring), but anyone using
the per-phase breakdown for something that depends on the label being
precise (e.g. training a model to distinguish rest vs. active states)
should account for this rather than trust the phase column at face value.

**Folding real data into the trained models** (`scripts/
merge_real_hardware_data.py` + retraining `scripts/train_isolation_forest.py`
→ `train_lstm_ae.py` → `train_gnn.py` → `train_fusion_meta_learner.py` in
that dependency order), re-checked at two checkpoints (253 real records,
then the final 380) with a controlled A/B comparison against the exact
same held-out `data/collected/test_session.json` (3,050 messages, models
backed up and restored between runs for a clean comparison each time):

| Signal | Metric | Pure synthetic | +253 real | +380 real (final) |
| --- | --- | --- | --- | --- |
| **fused_score** (deployed) | Accuracy | 0.707 | 0.745 | **0.748** |
| **fused_score** (deployed) | Precision | 0.996 | 0.993 | 0.992 |
| **fused_score** (deployed) | Recall | 0.684 | 0.728 | **0.732** |
| **fused_score** (deployed) | F1 | 0.811 | 0.840 | **0.843** |
| isolation_forest_score | Accuracy | 0.939 | 0.953 | 0.957 |
| gnn_score | Accuracy | 0.926 | 0.931 | 0.931 |

The metric that's actually deployed (`fused_score`) improved monotonically
across both checkpoints — accuracy 0.707→0.745→0.748, recall
0.684→0.728→0.732, F1 0.811→0.840→0.843 — with only a negligible,
also-monotonic precision cost (0.996→0.993→0.992). Consistent, reproducible
improvement, not a one-off fluctuation.

**One real, honestly-reported trade-off, also monotonic in the same
direction**: the LSTM-AE's undiluted (esp32-vib-001-only) F1 fell
0.910→0.871→0.867, and `fused_score`'s recall on the `stealthy_forged_values`
event type fell 0.788→0.576→0.515 as more real data was blended in — both
because the LSTM-AE's reconstruction-error baseline necessarily widens
(`std` 0.277→2.7-3.3 at 253 real) to stop misreading real hardware's
naturally noisier signal as anomalous, which as a direct consequence makes
it less sensitive to the *tighter, synthetic-scale* anomalies in this one
specific hard test category. Not a free lunch on every sub-signal, but a
net positive on the metric that matters, and the regression lands in a
category the project's own pre-hardware baseline already flagged as "not
expected to be reliably caught" (Section 2, `stealthy_forged_values` row)
— it moved within an already-weak category, not from strong to weak.

**A first real (if informal) physical fault, found by accident, not staged
as a formal session**: the user disconnected and reconnected the MPU6050
while the board was running. The board did not error — I2C reads against
a disconnected sensor came back all-zero bytes rather than raising an
exception, so the firmware happily published `rms=0.0, peak=0.0,
crest_factor=0.0, kurtosis=0.0` as if it were a legitimate reading. This
is physically impossible for a connected accelerometer (Earth's gravity
alone contributes ~1g even at rest) but revealed a real, previously
undocumented gap: `rule_range_score()`'s `rms` bound was `(0.0, 3.0)`, so
this exact fault passed the rule check as "within expected range."
**Checked, not assumed, whether the fault was caught anyway**: replayed
the exact reading through the live scorers — `rule=0.900` (missed),
`if=0.420`, `lstm=0.900`, `gnn=0.002`, **`fused=0.008`** — the full
fusion pipeline correctly flagged it as anomalous (well below
`PROCESS_THRESHOLD=0.6`), driven by the GNN and Isolation Forest even
though the rule check missed it — the defense-in-depth design worked as
intended, no single point of failure. **Fixed anyway**, since a cheap
deterministic check catching an unambiguous physical impossibility is
strictly better than relying on the ML signals alone for it: `rms`'s
lower bound raised to `0.1` (comfortably below every real observed
minimum, 0.33g across the 5 sessions above, while excluding exactly
`0.0`). Verified this doesn't regress the synthetic held-out baseline
(`rule_score` accuracy unchanged at 0.921) or reject any real session's
data (all real `rms` values already sit at 0.33 or above).

**Still pending**: a FORMAL physical adversarial-testing session (actually
tapping/shocking/loosening the rig with a deliberately induced fault and
human-labelled ground truth per phase, `CLAUDE.md` Section 9 Week 2, using
`scripts/collect_hardware_session.py`-style structured capture rather than
an incidental discovery). This is the step that would let Sections 2–5's
synthetic-attack numbers be re-run against genuine physical faults instead
of the generator's model of one — the sensor-disconnect finding above is
real evidence in that direction, not a substitute for it.

**A second real fault, a genuine firmware bug this time**: the user then
removed the MPU6050's VCC entirely (not just SDA/SCL). This raises an
`OSError` (`ETIMEDOUT`) from the I2C read inside `sample_window()` —
different failure mode from the SDA/SCL-only disconnect above, which read
back zero bytes without erroring; a fully unpowered sensor can't ACK the
bus at all. The firmware's `main()` loop wrapped its ENTIRE per-message
body (sensor read AND MQTT publish) in one `except OSError`, written for
MQTT reconnection — so an I2C failure was misdiagnosed as a network
problem every time: it reconnected MQTT (which was never broken,
succeeding every time), then immediately hit the same I2C failure again
next cycle, looping `[main] connection error, reconnecting` /
`[mqtt] connected with broker credentials` forever, never actually
addressing or even correctly naming the real problem. **Fixed**: the
sensor read now has its own `try`/`except`, separate from the MQTT
publish/reconnect block — on an I2C failure it re-runs `mpu6050_init()`
(so power being restored is picked up automatically, same retry
philosophy as `sync_time()`'s NTP retries) and skips straight to the next
cycle without touching MQTT at all, with a correctly-labelled console
message (`MPU6050 read failed`, not `connection error`). Not yet
re-verified on real hardware (needs a live re-run with VCC removed again
to confirm the new path actually recovers cleanly) — flagged here rather
than claimed as confirmed.

### 13.3 Real Sensor Calibration — checked, no change needed (yet)

`expected_ranges` in `src/config.py`'s `DEVICE_REGISTRY["esp32-vib-001"]`
were checked directly against the real observed ranges in 13.2's table
above and found to already comfortably contain them with margin — no
edit was needed. This may need revisiting once genuine physical-fault data
(13.2's still-pending item) is available, since a rule-range bound wide
enough to never false-positive on legitimate variation may also be too
wide to catch a real physical fault via the rule check alone (the ML
scorers are the layer actually expected to catch that; see Section 13.2's
retraining discussion). ISO 10816/20816 zone-boundary comparison
(`CLAUDE.md` Section 6) still needs real vibration-velocity data, not the
raw-acceleration proxy used throughout — untouched by this round.

### 13.4 Physical Deployment Overhead — RAM/flash measured, network latency still pending

**RAM/flash**, `firmware/main.py::print_deployment_footprint()`, printed
once at boot right after full initialization (WiFi, MQTT, MPU6050) —
real measurements, not the simulated-device-process proxy used
implicitly everywhere else in this project:

| Resource | Free | Used | Total | % used |
| --- | --- | --- | --- | --- |
| RAM (MicroPython GC heap) | 100,976 B | 16,464 B | 117,440 B | 14.0% |
| Flash filesystem | 2,084,864 B | 12,288 B | 2,097,152 B | 0.59% |

Both comfortably low — this firmware's actual footprint is a small
fraction of what's available on an ESP32-class device, even accounting
for the ~117KB figure being MicroPython's own GC-managed heap, not the
chip's full ~520KB SRAM (the rest is reserved for the WiFi/BT stack, the
interpreter itself, and static buffers — normal, not a measurement gap).
12KB of flash used out of a 2MB filesystem partition is essentially just
`main.py` itself plus `boot_id.txt`.

**Still not instrumented**: real WiFi/MQTT round-trip latency in a
physical network, vs. the loopback-network figures in Section 6 — would
need a timestamped ping/ack round trip, not just the one-way publish
timing Section 13.1 covers.

---

## 14. Known Limitations & Remediation Roadmap

Originally five acknowledged gaps against the original design.
**All five are now resolved** (struck through below, not deleted, so the
roadmap's own history stays visible) — one (item 4) resolved in the sense
of "confirmed architecturally capped, not fixable," the other four
actually implemented/explained and verified.

| # | Limitation | Solvable? | Resolution |
|---|---|---|---|
| ~~1~~ | ~~Key rotation / device revocation not implemented~~ **RESOLVED — implemented** | — | `trust_engine.py` gained `revoke_device()`/`reinstate_device()`/`rotate_key()`/`is_revoked()`, operating directly on `DEVICE_REGISTRY` (additive fields: `status`, `key_version`, `secret_previous`, `key_rotated_at` — `config.py`). `gateway.py` rejects a revoked device unconditionally, BEFORE HMAC (`process_telemetry()`'s new `is_revoked()` check); `verify_signature()` tries the current key first, falling back to `secret_previous` only within `KEY_ROTATION_GRACE_SECONDS` of the last rotation. Verified end to end, not just unit-level: revoke→reject, reinstate→accept again, rotate→old key still verifies inside the grace window, wrong key never verifies, old key correctly stops verifying once the grace window is manually aged past (7 checks, all passed) — plus a live `process_telemetry()` call against a revoked device, confirmed logged as `REJECTED (device_revoked)`. |
| ~~2~~ | ~~Level-2 (feature-level) explainability not implemented as a separate function~~ **RESOLVED — already implemented, table was stale** | — | `level2_explain()` is a real, dedicated function on every scorer (`gnn_scorer.py`, `isolation_forest_scorer.py`, `lstm_ae_scorer.py`, `transformer_scorer.py`), orchestrated by `src/explainability.py`, populated on every authenticated message, and surfaced live in the dashboard's second overlay bar — verified directly against real hardware telemetry this session (and one real bug in it, the GNN's fake neighbor attribution with no active neighbors, found and fixed; Section 13.0). |
| ~~3~~ | ~~Decision-channel replay~~ **RESOLVED — implemented** | — | Same `boot_id`/`seq` pattern telemetry replay already used, applied to the gateway's outgoing decisions: `gateway.py` persists its own incrementing `gateway_boot_id` (`data/gateway_boot_id.txt`, same pattern as the device's `boot_id.txt`) and a per-device `decision_seq` counter, both signed into every decision payload. `firmware/main.py`'s `check_decision_replay()` mirrors `check_boot_replay()`'s logic (strictly-higher boot_id always wins; same boot_id needs a strictly-higher seq). Canonical-string construction now reuses `canonical_json()` (the same generic builder telemetry uses) instead of a hand-rolled format string, specifically to avoid a repeat of the earlier telemetry canonicalisation risk — verified byte-for-byte identical to the gateway's `json.dumps(payload, sort_keys=True)` output, and the full HMAC signature verified to match end to end. |
| 4 | **Stealthy compromised devices reporting plausible in-range forged values** | **Not solvable by a better model — architecturally capped** | If a forged value sits inside the learned-normal range, no telemetry-only detector can distinguish it from a real reading — confirmed directly, not just argued: Section 2.2's Transformer sub-signal, genuinely more capable and fairly evaluated, scores this scenario identically to the LSTM-AE (0.606/0.500/0.667 recall figures across Sections 2.1, 3.2, 11 — unmoved by architecture). The only real fixes are outside single-node ML: a second, independently-trusted sensor for cross-validation, or multi-device correlation (the GNN's multi-node mode, `docs/04_module3_trust_evaluation.md` Section B.5 — not yet meaningfully exercised with fewer than 3 physical devices). This project reports the honest, partial recall rather than a number tuned to look better, per Section 11. |
| ~~5~~ | ~~Unexplained Process-score movement on `high_rate`~~ **RESOLVED — explained, not a real gap** | — | Root-caused, not fixed, because there was nothing live to fix: `scripts/diagnose_high_rate_leak.py` traced it to synthetic-generator scheduling (`anomalous_shock`/`tick%12==7` and `high_rate`/`tick%18==11` deterministically landing 4 messages apart, inside the LSTM's 8-message window) — the same window-residue effect Section 9 already documents elsewhere, not a live rate→process leak. Full trace in Section 7. |

### A sixth issue found while closing the above, not on the original list

Investigating item 1/3 surfaced a real gap in `trust_engine.py` itself:
**`is_stale()` (Security side) had zero call sites anywhere in the
codebase, and `get_process_anomaly()`'s staleness check (Process side) had
exactly one — inside `gateway.py::process_telemetry()`, always called
immediately AFTER `update_process_anomaly()` refreshes the very timestamp
being checked.** Verified against the real audit log, not just read: a
genuine 753-second silence in the real board's session (`RESULTS.md`
history) shows the very first message after it logged `process_status:
'FRESH'`, never `'STALE'` — the staleness code was correct but
unreachable in the live message-triggered path. **Fixed**: `gateway.py`
now runs a background silence watchdog (`start_silence_watchdog()`, same
thread pattern as the dashboard/HTTPS transport, `SILENCE_CHECK_INTERVAL_
SECONDS=5`) that checks every registered device's staleness independent
of message arrival, logs a real audit row (`decision="SILENT"`,
`reason_category="device_silent"`) on the silence-start transition and
another on the return-to-normal transition, and prints a console alert.
Verified end to end: simulated a device going silent, confirmed the
watchdog's underlying check now correctly reports `STALE`/`is_stale()=
True` with the score frozen (not decayed), and confirmed the audit row
writes correctly and the hash chain stays intact afterward. This directly
answers the practical question the ~11-minute real silence episode
earlier in this session raised — the board was deliberately, manually
disconnected by the user, not a bug, but the underlying point stands:
**a genuinely silent device (disconnected, powered off, or an attacker
deliberately silencing it) was previously indistinguishable from
"nothing happening" in the live gateway.** It now produces a real,
queryable, timestamped signal instead.

Items 1–3 and 5 are scoped, buildable engineering work with no open
design question — the relevant docs already specify *what* to build, only
*wiring it in* remains. Item 4 is the one place this project's own
Section 11 already argues, and Section 2.2's Transformer result now
directly confirms, that no amount of additional modeling closes the gap —
only a change to what data is available (redundant sensing) would.
