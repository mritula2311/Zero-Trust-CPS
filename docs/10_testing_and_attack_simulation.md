# 10 — Testing and Attack Simulation

> **AS-BUILT NOTE:** the attack matrix (Section 2) is implemented with two
> additions beyond this file's original rows: `high_rate` (a pure
> Security Trust event, `simulated_flood` in generated data / a real
> rapid-fire burst live in `device_simulator.py`) as the concrete
> representative of "abnormal message rate," and `stealthy_forged_values`
> (row 11) fully implemented, not hypothetical. Section 4.1's multi-class
> confusion matrix is implemented in `scripts/evaluate_rl_policy.py`
> (situation classes: `normal`/`physical_fault`/`security_concern`/`combined`,
> derived from `event_type` via `situation_for_event_type()` in
> `scripts/generate_training_data.py`). Real measured results (held-out
> test set, re-measured after the dataset scale-up, `RESULTS.md` Section
> 12): static-table macro-F1 = 0.269, RL(greedy) macro-F1 = 0.583 — RL's
> `security_concern` recall (1.000) and `combined`/stealthy recall (0.394)
> both meaningfully beat the static table's 0.000 on both, at a real
> precision cost from the aggressive inverse-frequency reward weighting
> needed to catch any `combined` cases at all (see
> `06_module5_access_control.md`'s AS-BUILT note and `RESULTS.md` Section
> 3 for the full numbers and the honest trade-off). Section 5's ablation
> table is implemented in
> `scripts/evaluate_ablation.py`, using `physical_label(event_type)` as
> ground truth (not the old blended label — see `04`'s AS-BUILT note for
> why that distinction matters).

## 1. Purpose

Define exactly how test data is generated, split, and used to evaluate the system, so that every metric reported later is measured honestly — on data the system was never tuned against — rather than accidentally reusing training data for evaluation.

## 2. The Attack Matrix

| # | Scenario | Simulator Trigger (from `01`, Section 4.3) | Should Be Caught By |
|---|---|---|---|
| 1 | Unknown device ID | `set_scenario(device, "forged_id")` | Module 1, feeding `IdentityTargetingRisk` (Module 2, Section 5) — never the legitimate device's own Security Trust Score |
| 2 | Incorrect HMAC | `set_scenario(device, "bad_hmac")` | Module 2, feeding `IdentityTargetingRisk` — see the trust-poisoning acceptance test in `03_module2_authentication.md` Section 9 |
| 3 | Payload altered after signing | `set_scenario(device, "altered_payload")` | Module 2 |
| 4 | Replayed valid packet | `set_scenario(device, "replay")` | Module 2 (boot-aware sequence/timestamp check) |
| 5 | Abnormal message rate (from a genuinely authenticated device) | `set_scenario(device, "high_rate", multiplier=5)` | Module 3, Security Behaviour Engine — this one legitimately affects that device's own Security Trust Score, since the messages are genuinely authenticated |
| 6 | Repeated auth failures in a short window, claiming a real device's ID | `set_scenario(device, "auth_failure_burst", count=5, window_s=10)` | `IdentityTargetingRisk` for that claimed ID (Module 2, Section 5) and the optional gateway-level throttle (Section 5.1) — explicitly **not** that device's own Security Trust Score |
| 7 | Physical spike (tap/shock equivalent) | `set_scenario(device, "physical_spike", magnitude=3.0, duration_s=2)` | Module 3, Process Anomaly Engine (rule + Isolation Forest) |
| 8 | Physical slow drift | `set_scenario(device, "physical_drift", drift_rate=0.01)` | Module 3, Process Anomaly Engine (LSTM-Autoencoder specifically) |
| 9 | Coordinated multi-node abnormal readings | Trigger `physical_spike` simultaneously across 3+ simulated devices | Module 3, GNN sub-signal (only if kept per its ablation decision) |
| 10 | Message/connection flooding | `set_scenario(device, "high_rate", multiplier=20)` on multiple devices at once | Module 5/6 (rate enforcement) |
| 11 | Stealthy compromised device: valid credentials, deliberately plausible in-range forged sensor values | `set_scenario(device, "stealthy_forged_values", target_value={...})` | **Explicitly acknowledged as not reliably detectable from this project's single-node design** — see `04_module3_trust_evaluation.md` Section B.8. This row exists to measure and document that limit, not to claim it is solved. Record the actual detection rate (likely near 0%) honestly in the results, rather than omitting this scenario because it makes the numbers look worse. |
| 12 | Device reboot mid-operation | `set_scenario(device, "reboot")` | Not an attack — a robustness test. Module 2's boot-aware anti-replay check (Section 4.1) must accept the new session, not reject it. |

## 3. Baseline and Dataset Generation

### 3.1 Baseline Collection

Using the simulator's `time_scale` parameter (`01`, Section 4.5), generate the equivalent of at least **3 simulated days** of normal-only telemetry across all active simulated devices, before injecting any anomaly. This directly replaces the too-short 2-hour baseline flagged in the project's design review — the point is capturing enough natural variation (simulated slow drift, varying message timing) that the rule-based ranges and the Isolation Forest/LSTM-Autoencoder training are not fit to an artificially narrow slice of behaviour.

### 3.2 Attack/Anomaly Data Generation

For each row in Table 2 above, generate a labelled batch: run the scenario for a defined duration, record exact start/end timestamps as ground truth, then return the device to `"normal"`. Repeat each scenario multiple times (recommend at least 20 separate occurrences per scenario) with the exact trigger parameters varied slightly each time (different magnitudes, different durations) so the resulting dataset is not just 20 copies of an identical event.

### 3.3 Train / Validation / Test Split

**This split must be decided and fixed before any model training or threshold tuning begins**, and the test portion must not be looked at again until final evaluation. This directly addresses the dataset-leakage risk flagged in review.

```
Recommended split, applied independently to the normal baseline data and to
each attack-scenario batch (so all three splits contain a representative
mix of normal and every scenario type):

  Training set    : 60%  — used to fit Isolation Forest, LSTM-Autoencoder,
                            GNN (if built), and the fusion meta-learner.
  Validation set   : 20%  — used to tune rule-based thresholds, the
                            Security Behaviour Engine's rule weights, the
                            Module 5 policy thresholds, and to make the
                            GNN keep/drop decision.
  Test set          : 20%  — touched only during final evaluation
                            (10_testing_and_attack_simulation.md Section 4).
```

## 4. Evaluation Metrics

Computed separately for the Security Trust Score, the Process Anomaly Score, and the final Module 5 decision, always on the test set:

```
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)         # a.k.a. detection rate
F1        = 2 * Precision * Recall / (Precision + Recall)
FPR       = FP / (FP + TN)          # false positive rate
FNR       = FN / (FN + TP)          # false negative rate
```

Also compute PR-AUC and ROC-AUC by sweeping the decision threshold across its full range, rather than reporting a single-threshold precision/recall pair as if it were the only possible operating point.

### 4.1 The Final Policy Decision Needs Multi-Class Evaluation, Not Just Binary Metrics

Section 4's Precision/Recall/F1/FPR/FNR are binary metrics (anomalous vs. not), and they are the right tool for evaluating each individual signal inside Module 3. They are the wrong tool, used alone, for evaluating Module 5's final decision, because that decision has four possible outputs (`ALLOW`, `STEP_UP`, `ALERT`, `BLOCK`) mapped against four different ground-truth situation types, not just "attack" vs. "normal." Build a confusion matrix instead:

| Actual Situation \ Predicted Outcome | Allow | Alert | Step-Up | Block |
|---|---|---|---|---|
| Normal operation | | | | |
| Physical fault only (attack matrix rows 7–9) | | | | |
| Suspicious security behaviour only (rows 5–6, 10) | | | | |
| Combined: compromised device + abnormal data (row 11, and any row-5/6-plus-row-7/8/9 combination deliberately staged together) | | | | |

Populate each cell with the count of test-set messages falling into that (actual, predicted) pair, then compute macro-F1 across the four situation classes (average the per-class F1, where each class's "positive" is that row matching its intended column — e.g., "Normal" is correctly handled when predicted `Allow`, "Physical fault only" is correctly handled when predicted `Alert`, and so on). Report macro-F1 alongside the ablation table in Section 5, not as a replacement for it — the ablation table answers "did fusing help," this confusion matrix answers "does the final four-way decision actually work across every situation type it needs to handle."

## 5. Ablation Study

The specific question this answers: **does combining models actually help, or would a single simpler model have done just as well?** Fill in Table 3 using the test set, once per configuration:

| Configuration | F1-score | False Positive Rate | Detection Latency |
|---|---|---|---|
| Rules only | | | |
| Isolation Forest only | | | |
| LSTM-Autoencoder only | | | |
| GNN only (if built) | | | |
| Rules + Isolation Forest | | | |
| Rules + Isolation Forest + LSTM-AE | | | |
| All signals fused (final design) | | | |

The GNN keep/drop decision referenced throughout `04_module3_trust_evaluation.md` is made directly from this table (on the validation set first, then confirmed on the test set): if "All signals fused" only meaningfully beats "Rules + IF + LSTM-AE" when the GNN is included, keep it; otherwise, drop it from the live system and report this table as the evidence either way.

## 6. Per-Attack-Type Detection Table

A second table, using the same test set, records detection rate broken out by the individual attack-matrix row (Section 2 above) rather than one pooled number — a system could score well on average while consistently missing one specific, important scenario, and pooled metrics alone would hide that.

## 7. Explanation Validation

Following `04_module3_trust_evaluation.md` Section C.4: on a random sample (recommend at least 50) of test-set messages that were correctly flagged as anomalous, perturb the named `level2_dominant_feature` and re-run scoring. Record the percentage of cases where the decision actually flips. Target ≥ 70%.

## 8. Resource and Performance Overhead

Measured on whichever hardware is available at the time (simulation-only machine now; the real ESP32 once it arrives):

- Authentication + encryption latency, including p95, not just mean.
- RAM/flash used by firmware (once hardware exists) or by the simulated device process (for now, as a proxy).
- Gateway-side inference latency, per sub-signal and for the fused result.
- Sustained throughput (maximum message rate before the gateway falls behind).

## 9. Acceptance Criteria for This Document's Process

- The train/validation/test split is generated once, saved to disk, and never regenerated mid-project in a way that could leak test data into training (e.g., re-running the whole pipeline from scratch with a different random seed after having already looked at test-set results).
- Every number in Sections 4–8 above is computed from the test set exclusively, and the code that computes them is kept separate from the code that does any tuning.

Continue to `11_project_structure_and_config.md`.
