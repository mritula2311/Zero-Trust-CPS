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
> test set, leakage-free re-measurement, `docs/CLAIM_EVIDENCE_MATRIX.md`
> C6 / `RESULTS.md` §0.13.6): the adaptive policy — **a contextual bandit,
> not reinforcement learning** — scores macro-F1 **0.5329**, beating the
> *deployed* static table (**0.2744**) but **losing to a validation-tuned
> static table (0.5879)**. The bandit's `security_concern` recall meaningfully
> beats the deployed table's, at a real precision cost from the aggressive
> inverse-frequency reward weighting needed to catch any `combined` cases at
> all — and the rare `combined` (`stealthy_forged_values`) class remains
> effectively undetectable for any policy with a usable false-block rate, an
> architectural blind spot reported in full (C8). (see
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

## 7.1 Validating a *validation* — the falsifiability self-test

A check that cannot fail is not a check. Every metric in this document is
vulnerable to a specific, quiet failure: the measurement can be constructed so
that it always passes, at which point it stops carrying information while still
looking like evidence.

This was not hypothetical here. The NIST governance figure was **100% coverage
across all 7 tenets** — and it was tautological. `nist_mapping.tenets_for_decision()`
attaches tenets 1, 3, 4, 5 and 6 to *every* decision unconditionally, so those
five read 100% because the tagger always writes them, and no arrangement of the
system could have produced any other number. Coverage measured **tagging**, not
compliance (see `08_module7_monitoring_and_audit.md`).

The remedy generalises beyond governance, and is the method this document now
prescribes for any claimed validation:

1. **State the falsifier.** For each check, write down the specific observation
   that would make it FAIL. If you cannot name one, the check is not a check.
2. **Inject the falsifier.** Construct synthetic input exhibiting exactly that
   observation and confirm the check rejects it.
3. **Report an untestable check as untestable.** If the available data cannot
   exercise a check, report that state explicitly rather than defaulting to
   PASS.

`scripts/evaluate_governance.py` implements all three. Its self-test injects
each tenet's own stated falsifier as synthetic audit rows:

```
T1 inject an authenticated row from an unregistered device          -> FAIL (correctly rejected)
T2 inject an authenticated row over an unencrypted transport        -> FAIL (correctly rejected)
T3 inject a row granted access with no scores of its own            -> FAIL (correctly rejected)
T4 inject a policy that ALLOWs equally above and below thresholds   -> FAIL (correctly rejected)
T5 inject rows covering fewer devices than the registry            -> FAIL (correctly rejected)
T6 inject an UNauthenticated row that was granted ALLOW             -> FAIL (correctly rejected)
T7 inject a pipeline whose fused score never differs from the rule  -> FAIL (correctly rejected)

7/7 checks demonstrably reject their own falsifier.
```

Tenet 5 is **excluded from that count rather than assumed**: its falsifier is a
registered device with *no* rows, which is the absence of data rather than a row
that can be constructed. Counting it as a seventh pass would be exactly the
overclaiming this section exists to prevent.

Two checks additionally report non-PASS states that are not failures:

- **`UNFALSIFIABLE`** — T3 returns this when no device changed decision within
  the window, because such a window genuinely cannot distinguish "re-evaluated
  every message" from "decided once and cached."
- **`INSUFFICIENT_DATA`** — T4 reports an axis as untestable when the window
  contains rows on only one side of its threshold.

## 7.2 An evaluation that was structurally blind — and the lesson

`scripts/evaluate_ablation.py` thresholds at **0.5**. The live gateway's
`config.PROCESS_THRESHOLD` is **0.6**. A calibration defect that made the
Isolation Forest incapable of scoring above 0.621 — so a *perfectly normal*
reading sat at a median of 0.579, below the live threshold — therefore produced
**almost no change** in this document's headline ablation table (fused accuracy
0.744 → 0.747 before and after the fix), while making the system reject a
healthy physical board outright.

The evaluation was not wrong. It was measuring something adjacent to what the
deployment does, and the gap between the two was exactly where the bug lived.

**Three practices follow, and they apply to any metric in this document:**

1. **Evaluate at the deployed decision boundary.** If the live system decides at
   0.6, a metric computed at 0.5 is not evidence about the live system.
2. **Aggregate accuracy hides threshold defects.** Report the score
   *distribution* per class, not just a pass/fail count — the defect was
   instantly visible as "normal median 0.579, best achievable 0.621" and
   invisible as "accuracy 0.744".
3. **Offline metrics do not substitute for live observation.** The definitive
   evidence that anything was wrong came from watching a real board at rest be
   BLOCKed, not from any script here.

## 7.3 Verification scenarios that define correctness

Concrete cases, each with the observation that decides pass or fail. These
complement the aggregate metrics in §4 — an aggregate can stay healthy while any
individual one of these breaks.

| # | Scenario | Correct behaviour | Measured |
|---|---|---|---|
| 1 | Healthy board at rest | ALLOW | fused median **0.888**, **0.0%** false positives at threshold (n=84 clean normals) |
| 2 | Board physically shaken | ALERT/BLOCK, never ALLOW | **19/19** readings with `rms > 1.2` caught, zero ALLOW |
| 3 | Recovery after disturbance | Returns to ALLOW, with a short tail | Clean shake → ALERT → tail → ALLOW cycles; the tail is the 8-sample LSTM window flushing |
| 4 | Neighbour degrades, own evidence unchanged | Only the GNN may move | GNN `0.647 → 0.316`; IF and LSTM-AE structurally cannot move |
| 5 | Coordinated multi-device anomaly | Detected | GNN recall **1.000**; IF 0.316, LSTM-AE 0.222 |
| 6 | Rate anomaly from a valid device | Security axis only | `high_rate` moves Security (3.21 msgs to break), Process untouched |
| 7 | Physical anomaly from a valid device | Process axis only | `anomalous_shock`/`coordinated` move Process (0.00/0.10), Security untouched |
| 8 | Unauthenticated message | REJECTED, and the *claimed* device's own score untouched | 0 violations across 10,000 rows (governance T6) |
| 9 | Gateway→device decision | Device can verify it | **10/10** HMAC-valid recomputed with the device's own secret |
| 10 | Cross-device decision leakage | None | 0 leaked; broker ACL refuses the subscription |
| 11 | Device with no active neighbour | Scored on its own evidence, not saturated | fused **0.873** at 1 active device vs **0.941** at 3 (was 0.020 vs 0.577) |
| 12 | Audit tampering | Detected by both checks | Hash chain + independent checkpoint, both PASS over 34,067 rows |

Scenarios 6 and 7 together are the operational test of the two-score
architecture: if either event type moved *both* axes, the separation has a leak
and every downstream claim about the 2×2 policy is unsound.

Scenario 11 is included because it once failed in **both** directions — first
scoring a healthy isolated board at 0.020, then, after a naive fix, saturating a
genuinely shaken one to 1.000 and masking a real anomaly. A metric moving in the
desired direction is not the same as the model getting better; scenario 2 is
what catches the second failure, and it must be re-run whenever 11 changes.

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
