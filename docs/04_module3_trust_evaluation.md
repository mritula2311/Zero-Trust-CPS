# 04 — Module 3: Trust Evaluation

> **AS-BUILT NOTE:** Section A (Security Behaviour Engine) is implemented
> as `src/trust_engine.py::score_security_trust()` — rate/flood + step-up
> outcomes only, exactly per this file's attribution rule. Section B
> (Process Anomaly Engine) is `src/fusion_engine.py` + the four scorer
> files — kept in its original **trust-style scale (high = normal)**
> rather than inverted to "high = anomalous," specifically so the
> already-trained, already-ablated meta-learner's coefficients (verified
> positive-signed against real held-out data) didn't need to change sign;
> `policy_engine.py`'s 2×2 table is written for this scale. Section B.8's
> `stealthy_forged_values` limitation is implemented and measured (attack-
> matrix row 11, `device_simulator.py`/`scripts/generate_training_data.py`)
> — its honestly-low, non-zero detection rate is the real, reported result,
> not tuned toward zero or toward a target number. Section C's two-level
> SHAP is implemented in `fusion_engine.py` (Level 1: full per-signal SHAP
> vector, not just the top feature) — Level 2's per-signal feature
> attribution (perturbation-based for LSTM-AE/GNN, `TreeExplainer` for
> Isolation Forest) is now implemented as `src/explainability.py`
> (orchestration) plus a `level2_explain()` method added to each scorer,
> wired into the live gateway and logged to two new audit columns. Its
> Section C.4 validation, however, surfaces a genuine, honestly-reported
> result, not a clean win: 36% overall flip rate against the 70% target
> (100% for the GNN, 2%/0% for Isolation Forest/LSTM-AE) — see `RESULTS.md`
> Section 4.1 for the full breakdown and why it splits that way by
> architecture. This closes item 2 of `RESULTS.md` Section 14's
> remediation plan, though the C.4 validation result itself is a new,
> smaller finding worth reading before citing "Level 2 is done" as an
> unqualified win.
>
> **Two additions beyond this design doc, both verified, not assumed:**
> Section B.1's `ProcessFeatureVector` as actually implemented
> (`src/feature_engineering.py`) is 5 vibration-analysis features (rms,
> peak, crest_factor, kurtosis, dominant_freq) over a raw accel-magnitude
> window, not the 12-field raw-6-channel-plus-variance vector specified
> below — see B.1's own AS-BUILT note. Section B.5's Transformer sub-signal
> (B.5b below) was added, tuned, and fairly evaluated against the LSTM-AE
> — genuinely wins by a small margin (`RESULTS.md` Section 2.2) but is not
> adopted into the live fusion inputs, same keep/drop bar B.5's GNN
> decision already sets.

This is the largest and most important module. It produces the two scores the entire architecture is built around. Read `00_overview.md` Section 1 again before starting this file if the two-score rationale is not already clear — nothing in this module should ever combine security evidence and physical evidence into one number before the final policy step in Module 5.

## 1. Purpose and Structure

Module 3 has three internal parts, covered as Sections A, B, and C below:

- **Section A — Security Behaviour Engine:** produces the Security Trust Score from cyber-behaviour evidence.
- **Section B — Process Anomaly Engine:** produces the Process Anomaly Score from physical sensor evidence, itself built from up to four sub-signals fused together.
- **Section C — Two-Level Explainability:** explains both scores at two levels of abstraction.

**Literature grounding:** [13] (gateway-side Decision-Tree trust scoring), [14] (trust + CVSS-style severity combination), [15] (warns that any single ML method has a weak spot — the direct motivation for fusing several), [16], [17] (GNN for intrusion detection), [20], [21] (SHAP/LIME evaluation and validation methodology), [22] (LSTM-Autoencoder), [23] (accuracy/efficiency/explainability trade-off warning).

---

## Section A — Security Behaviour Engine

### A.0 Design Rationale — Why Rule-Based, Not Learned

The Security Behaviour Engine is kept as simple, fully-inspectable rules,
not machine learning, on purpose — three reasons that matter for both
engineering and research purposes:

1. It requires zero training data, so it works from message one — no
   cold-start problem, and no risk of the highest-stakes engine in the
   system (a false negative here means treating a compromised device as
   trustworthy) inheriting an ML model's opaque failure modes.
2. It's interpretable by construction — every score change traces to an
   explicit rule, valuable both for debugging and as the non-ML baseline
   the Process Anomaly Engine's ablation study (Section B, and
   `docs/10_testing_and_attack_simulation.md`) is measured against.
3. It de-risks the timeline — a working trust engine exists before any
   model training is attempted, so the rest of the pipeline (Modules 4-7)
   can be built and tested against it immediately.

### A.1 Inputs

**Only from `AuthenticatedBehaviourState` — never from raw rejection counts.** This is a direct consequence of the attribution fix in `03_module2_authentication.md` Section 5: a failed authentication attempt claiming a device's ID is evidence about whoever sent it, not about that device, and must not be allowed to lower that device's own score. The Security Behaviour Engine therefore only ever reads features computed from messages that already passed full verification.

```
SecurityFeatureVector (recomputed on every successfully-authenticated message,
rolling windows configurable, default 60s — sourced from AuthenticatedBehaviourState,
03_module2_authentication.md Section 5):
  message_rate_60s              : float     # accepted messages per second, last 60s
  expected_message_rate         : float     # this device's normal baseline rate (learned during Phase 4 baseline)
  seconds_since_last_authenticated_msg : float
  step_up_failures_total        : integer   # STEP_UP_TIMEOUT or STEP_UP_MISMATCH count, lifetime
```

Separately, and explicitly **not** part of this feature vector, `IdentityTargetingRisk` (`03_module2_authentication.md` Section 5) is tracked per claimed device_id from rejected attempts. It is surfaced on the dashboard (Module 7) as its own indicator and may trigger the gateway-level protective throttle in that section — but it is never read by `compute_security_trust_score()` below, and no future change to this engine should reintroduce that path without re-reading the attribution reasoning in Module 2 Section 5 first.

### A.2 Scoring Logic (Rule-Based, Deliberately Simple)

The Security Behaviour Engine is kept as simple rules, not machine learning, on purpose: it is responsible for the highest-stakes decisions (a false negative here means treating a compromised device as trustworthy), and a simple, fully-inspectable rule set is easier to audit and reason about than a learned model at this stage. Future work could add a learned layer, but this is explicitly out of scope for the initial build.

```
compute_security_trust_score(features: SecurityFeatureVector) -> float in [0, 1]:

    score = 1.0   # start clean

    rate_ratio = features.message_rate_60s / max(features.expected_message_rate, 0.01)
    if rate_ratio > 2.0:
        score -= 0.35 * min((rate_ratio - 2.0) / 3.0, 1.0)   # penalize flooding from a
                                                               # device we know is really
                                                               # the one it claims to be

    score -= 0.25 * min(features.step_up_failures_total / 2, 1.0)

    return clamp(score, 0.0, 1.0)
```

The exact weights above are starting defaults, not fixed constants — Phase 4/5 of the implementation plan tunes them against the validation split of the attack-matrix dataset (`10_testing_and_attack_simulation.md`). Document whatever final weights are chosen, and why, in code comments referencing the specific validation-set result that justified the choice.

### A.3 Output

```
SecurityTrustResult:
  device_id     : string
  score         : float in [0, 1]
  timestamp     : float
  contributing_features : dict   # e.g. {"auth_failures_60s": 4} — feeds Level-1 explanation (Section C)
```

---

## Section B — Process Anomaly Engine

### B.1 Inputs

> **AS-BUILT NOTE:** `src/feature_engineering.py` implements a 5-feature
> vibration vector (`rms`, `peak`, `crest_factor`, `kurtosis`,
> `dominant_freq`, computed over a raw accel-magnitude sampling window —
> `firmware/main.py`'s on-device equivalent), not the 12-field raw-6-
> channel-plus-per-axis-variance vector specified immediately below.
> Every scorer in this section (rule-based, Isolation Forest, LSTM-AE,
> Transformer, GNN's node features) consumes the AS-BUILT 5-feature
> vector, not the `ProcessFeatureVector` schema as originally specified —
> a genuine deviation, not an oversight, made to keep the on-device
> feature-extraction math (see `feature_engineering.py`'s docstring for
> why raw samples aren't shipped over the signed MQTT channel) reference-
> checked against one implementation rather than two competing schemas.

Raw `accel_x/y/z`, `gyro_x/y/z` from the current message, plus derived features computed over a short rolling window (default: last 20 messages):

```
ProcessFeatureVector:
  accel_x, accel_y, accel_z   : float          # current raw reading
  gyro_x, gyro_y, gyro_z      : float          # current raw reading
  rms_accel                    : float          # sqrt(mean(ax²+ay²+az²)) over the window
  peak_accel                   : float          # max magnitude over the window
  crest_factor                 : float          # peak / rms
  accel_variance_x/y/z         : float          # per-axis variance over the window
  gyro_variance_x/y/z          : float
```

### B.2 Sub-Signal 1 — Rule-Based Range Check

```
rule_based_score(features, expected_range: dict from device registry) -> float in [0, 1]:
    # expected_range = {"accel_x": (min, max), "accel_y": (...), ...}, learned from
    # the multi-day baseline in Phase 4 (see 10_testing_and_attack_simulation.md).
    violations = 0
    for channel in [accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z]:
        if value not in expected_range[channel]:
            violations += 1
    return violations / 6.0   # fraction of channels currently out of range
```

### B.3 Sub-Signal 2 — Isolation Forest

- **Library:** scikit-learn `IsolationForest`.
- **Training:** offline, on the training split of the multi-day baseline (normal-only data). One model per device, or one shared model across all simulated devices if data volume per device is too small early on — decide based on how much baseline data Phase 4 actually collects, and document the choice.
- **Features used:** the full `ProcessFeatureVector`.
- **Scoring:** use `.decision_function()` (not just `.predict()`), rescaled to `[0, 1]` where higher = more anomalous, so it is on the same scale as every other sub-signal.
- **Cold start:** until a device has enough baseline messages to train on (configurable minimum, e.g. 500 messages), this sub-signal returns a neutral `0.5` and is excluded from the fusion meta-learner's training data for that period — do not let an untrained model contribute noise to early scoring.
- **Retraining:** retrain on a schedule (e.g., every 10,000 new messages, or nightly in hardware-time) using an expanding or sliding window of recent normal data, so the model can adapt to slow legitimate drift.

### B.4 Sub-Signal 3 — LSTM-Autoencoder

- **Library:** PyTorch.
- **Architecture:** encoder LSTM (input size 12 — the six raw channels plus six derived features, or just the six raw channels if derived features prove redundant during experimentation — decide empirically) → small hidden state (e.g., 16–32 units) → decoder LSTM reconstructing the input window.
- **Input:** a sliding window of the last N raw readings (default N=20, matching the feature-window size in B.1).
- **Training:** offline, on the training split of normal baseline data, minimizing reconstruction error (MSE).
- **Scoring:** reconstruction error on the current window, rescaled to `[0, 1]` using the training-set error distribution (e.g., min-max or percentile-based scaling — document whichever is chosen and why).
- **Why this sub-signal exists specifically:** it is the only one of the four designed to catch *slow drift* — a trend that looks fine at any single instant but wrong over the trailing window. Verify this specifically during the ablation study (`10_testing_and_attack_simulation.md`): construct a test case where a slow drift scenario is caught by the LSTM-Autoencoder but missed by the rule-based check and Isolation Forest alone.

### B.5 Sub-Signal 4 — Graph Neural Network (Conditional)

**This sub-signal is not built unconditionally.** Refer to the project synopsis Section 7.4 for the full reasoning; the summary for implementation purposes:

- **Preferred graph construction (multi-node):** if 3+ simulated (or later, physical) devices are running, build a graph where each device is a node, edges represent communication/behavioural correlation between devices (e.g., correlated timing of anomalies, shared gateway, physical proximity if known), and node features are each device's current `ProcessFeatureVector`. This is the design the literature ([16], [17]) actually validates.
- **Fallback graph construction (single-node):** if only one device exists, build a graph from the six MPU6050 channels themselves — each channel is a node, edges represent expected correlation between channels (e.g., accel_x–accel_y, accel_z–gyro_z if the mounting orientation makes that physically meaningful), and node features are that channel's recent statistics. State explicitly in code comments that this is the weaker fallback case, not the target design.
- **Library:** PyTorch Geometric. A small 2-layer GCN or GraphSAGE model is sufficient — this is not a case that needs a large model.
- **The keep/drop decision:** after training, compare this sub-signal's contribution on the *validation* split against the three-signal combination (rule + Isolation Forest + LSTM-AE) using the ablation methodology in `10_testing_and_attack_simulation.md`. If it does not measurably improve F1-score or recall on the validation set, **do not include it in the live fusion meta-learner.** Record the comparison numbers regardless of outcome — a documented "we tried it, it did not help, here is the evidence" is a valid and expected result, not a failure.

### B.5b Sub-Signal 5 — Transformer (Ablation Candidate, Not in the Original Design)

Not part of the original design docs — added, tuned, and evaluated
against the same keep/drop bar B.5 sets for the GNN above, using
`10_testing_and_attack_simulation.md`'s ablation methodology (concretely
`scripts/evaluate_ablation.py`). See `RESULTS.md` Section 2.2 for the full
investigation and numbers; summarized here for architectural completeness.

- **Library:** PyTorch (`nn.TransformerEncoder`/`nn.TransformerEncoderLayer`).
- **Architecture:** encoder-only, full bidirectional multi-head self-attention
  (no causal mask, no decoder, no cross-attention — this is the BERT/ViT-
  encoder family, not a GPT-style decoder or a T5-style encoder-decoder
  seq2seq model). 2 layers, 4 heads, `d_model=32`, feedforward dim 64,
  dropout 0.2, learned absolute positional embeddings (not sinusoidal —
  the window length is fixed and short, so there's no variable-length-
  generalization need sinusoidal encodings exist for). 17,701 parameters.
- **Input:** the SAME sliding window as B.4 (`LSTM_SEQ_LEN`, shared, not a
  separate constant) over the AS-BUILT 5-feature vector (B.1's AS-BUILT
  note) — deliberately held identical to the LSTM-AE so the ablation
  comparison isolates architecture as the only variable.
- **Training objective: denoising, not plain reconstruction.** Gaussian
  noise is added to the normalized input window; the loss is
  reconstruction error against the CLEAN window
  (`scripts/train_transformer.py`). This is not a stylistic choice: full
  self-attention gives every position in the window direct access to
  every other position, so a *plain* reconstruction transformer can
  partially shortcut — attend to neighboring true values and copy them,
  under-scoring real anomalies — in a way an LSTM's recurrent bottleneck
  prevents by construction but self-attention does not. Denoising removes
  that shortcut without changing the task framing.
- **Scoring:** identical rescaling to B.4 — reconstruction error on the
  CLEAN current window (no noise at inference time), z-scored against the
  training-set error distribution.
- **Why forecasting/seq2seq was considered and rejected:** an encoder-
  decoder seq2seq model (predict future steps autoregressively) was
  considered but not built — at `LSTM_SEQ_LEN` this short, there is no
  long-range dependency for a decoder to exploit that a reconstruction
  encoder can't already capture, so the added complexity (and the
  decoder's own shortcut risks) isn't earned.
- **The keep/drop decision (same bar as B.5's GNN):** a 7-way
  hyperparameter sweep (pre-LN vs post-LN, ReLU vs GELU, ~6x more
  capacity, up to 400 epochs, varied noise/LR/weight decay) against a
  fair, undiluted held-out comparison found the Transformer genuinely
  outperforms the LSTM-AE, but only by +0.010 F1, with per-event recall
  on `anomalous_shock`/`coordinated`/`stealthy_forged_values` identical
  between the two architectures — see `RESULTS.md` Section 2.2 for the
  full numbers. **Not included in the live fusion meta-learner**: the
  margin is real but too small to justify ~6x the parameters and the
  downstream retraining cost (GNN's node features and the fusion
  meta-learner would both need retraining to accept a 5th input) for no
  measurable gain on the anomaly types that actually matter. Recorded here
  regardless, per this section's own stated principle for the GNN above.

### B.6 Fusion — Meta-Learner

```
Inputs to the meta-learner (one row per historical labelled message):
  [rule_score, isolation_forest_score, lstm_ae_score, gnn_score_or_omitted]

Model: sklearn.linear_model.LogisticRegression (or LogisticRegressionCV for
       automatic regularization strength selection)

Training data: the labelled training split from Phase 4/6 (physical anomalies
       + normal baseline; the meta-learner is trained on PROCESS signals only —
       it never sees Security Behaviour Engine features, keeping Section A and
       Section B's separation intact all the way through fusion).

Output: process_anomaly_score = meta_learner.predict_proba(X)[:, 1]   # in [0, 1]
```

### B.7 Output

```
ProcessAnomalyResult:
  device_id      : string
  score          : float in [0, 1]
  timestamp      : float
  sub_scores     : dict   # {"rule": 0.1, "isolation_forest": 0.6, "lstm_ae": 0.7, "gnn": None}
  # sub_scores feeds Level-1 explanation directly (Section C)
```

### B.8 An Acknowledged Detection Limit — Stealthy Compromised Devices

Every sub-signal in Section B works from the telemetry the device itself reports. A compromised device that still has valid credentials (it was never revoked, its HMAC still checks out, its sequence numbers are still well-formed) and deliberately reports fabricated sensor values that sit *inside* the range the Isolation Forest and LSTM-Autoencoder learned as normal will not reliably be caught by this design — there is nothing in the telemetry stream itself that distinguishes a real 0.31g reading from a fabricated 0.31g reading standing in for an actual 8.7g event. This project states that limitation honestly rather than implying every attack is detectable: **single-node telemetry, without an independent trusted measurement, cannot reliably detect a compromised device that reports plausible, in-range fabricated values.** The `"stealthy_forged_values"` scenario in `01_simulation_and_hardware_abstraction.md` Section 4.3 exists specifically to demonstrate and measure this limit during evaluation (`10_testing_and_attack_simulation.md`), not to claim it is solved. If multiple nodes or a redundant, independently-trusted sensor are available (Section 10.1 of the project synopsis), cross-validating one device's reported readings against another's is the natural next step — flagged here as future work, not part of this project's initial scope.

**Confirmed architecture-agnostic, not just theoretically so**: B.5b's Transformer sub-signal, genuinely more capable and fairly evaluated against the LSTM-AE, scores this exact scenario identically (0.606 recall, same as the LSTM-AE) — direct evidence this is a data problem (no distinguishing signal in the telemetry itself), not a model-capacity problem a different architecture could close. See `RESULTS.md` Section 14 for this limitation alongside four other acknowledged gaps and what each would actually take to close.

---

## Section C — Two-Level Explainability

### C.1 Why Two Levels

SHAP applied only to the meta-learner (Section B.6) can only ever explain that model's own inputs — the four sub-scores. It can correctly say *"the LSTM-Autoencoder score contributed most to this decision,"* but it cannot correctly say *"unusual acceleration variance caused this,"* because raw acceleration variance is not one of the meta-learner's inputs. Claiming the second kind of statement from Level-1 SHAP alone is the specific error the design review flagged, and this two-level structure is the fix.

### C.2 Level 1 — Fusion-Level SHAP

```
level1_explain(meta_learner, sub_scores_vector) -> dict:
    explainer = shap.Explainer(meta_learner)
    shap_values = explainer(sub_scores_vector)
    return {signal_name: shap_value for signal_name, shap_value in zip(
        ["rule", "isolation_forest", "lstm_ae", "gnn"], shap_values)}
    # Identify argmax(abs(shap_value)) as "the dominant signal" — this name is
    # what gets passed into Level 2.
```

### C.3 Level 2 — Feature-Level Explanation

Applied only to whichever sub-signal Level 1 identifies as dominant, using a method appropriate to that specific model:

```
if dominant_signal == "isolation_forest":
    use shap.TreeExplainer (or KernelExplainer if TreeExplainer is not compatible
    with the specific IsolationForest internals) on the ProcessFeatureVector inputs.

if dominant_signal == "lstm_ae":
    use a perturbation-based explanation: zero out or replace one input channel
    at a time in the window, re-run the autoencoder, measure the change in
    reconstruction error. The channel causing the largest change is "responsible."
    (This is simpler and more robust for a recurrent model than trying to force
    SHAP's standard tooling onto an LSTM, and produces an equally usable
    per-channel importance ranking.)

if dominant_signal == "gnn":
    use a perturbation-based explanation analogous to the above: mask one node's
    features at a time, measure the change in the GNN's output score.

if dominant_signal == "rule":
    trivial — the rule-based score already IS a per-channel violation count
    (Section B.2), so the "explanation" is just reporting which channel(s)
    violated their expected range. No additional model needed.
```

### C.4 Combined Output and Validation

```
TwoLevelExplanation:
  device_id        : string
  timestamp        : float
  level1_dominant_signal : string          # e.g. "lstm_ae"
  level1_contributions   : dict             # all four SHAP values
  level2_dominant_feature: string           # e.g. "accel_x_variance"
  level2_summary          : string           # human-readable, e.g.
                                              # "flagged mainly due to LSTM-Autoencoder
                                              #  reacting to abnormal X-axis acceleration
                                              #  variance over the last 20 samples"
```

**Validation procedure (directly reusing [21]'s method):** for a sample of flagged test-set messages, take `level2_dominant_feature`, deliberately perturb exactly that feature (replace it with a normal-range value, or with a different device's value for that feature), re-run the full Process Anomaly Engine, and check whether `process_anomaly_score` actually drops below the alerting threshold. Record the percentage of tests where it does. This percentage is a real evaluation metric (`10_testing_and_attack_simulation.md`), not a one-off sanity check — target at least 70%, matching the range [21] reports for an analogous test.

---

## 1.1 Failure Modes (Both Sections)

| Scenario | Section A behaviour | Section B (fusion) behaviour |
|---|---|---|
| New device, no history | Starts from a neutral baseline, converges as authenticated evidence accumulates | Every sub-signal defers to its own cold-start fallback (Sections B.2-B.5); fused output ≈ the rule-based sub-signal alone until enough baseline accumulates |
| One sub-signal unavailable (e.g. GNN model not yet trained/loaded) | N/A | Fusion treats a missing signal as a neutral input rather than crashing — a real, expected edge case, not hypothetical (`fusion_engine.py` handles this explicitly for any scorer that hasn't produced a value yet) |
| Sub-signals disagree by a large margin (e.g. rule says fine, GNN says anomalous) | N/A | This is precisely what the meta-learner is trained to arbitrate — cases where signals disagree sharply are a designated evaluation category in the ablation study (`docs/10_testing_and_attack_simulation.md`), not an error state |

## 2. Configuration Parameters

**AS-BUILT NOTE:** the yaml below is the ORIGINAL design-time spec, kept
for reference against the flat `src/config.py` this project actually
uses (per `docs/00_overview.md`'s AS-BUILT deviation #3) — the two have
drifted apart in real values as the GPU-scale-up experiments (Section
B.4/B.5) and the 5-feature AS-BUILT vector (B.1's AS-BUILT note) landed.
Actual live values, verified against `src/config.py` directly: `rms`/
`peak`/`crest_factor`/`kurtosis`/`dominant_freq` computed over a 32-sample
window (`FEATURE_WINDOW_SIZE`, not 20 — matches `firmware/main.py`'s real
sampling window); LSTM-AE `hidden_size=16`, `window_size` (`LSTM_SEQ_LEN`)
`=8` (not 24/20 — dialled back after a real, verified overfitting result
at 32-hidden/2-layer on the pre-scale-up dataset, see `SESSION_LOG.md`
entry 19); GNN `enabled: true` as a **live default**, not conditional
(`docs/00_overview.md` deviation #4) — 3-layer, 32-hidden, not the 2-layer
fallback below; `min_baseline_messages_before_training`/
`retrain_every_n_messages` are design-time parameters for a continuous-
retraining architecture this project doesn't use (training is offline,
once, per `CLAUDE.md` Section 8) — not implemented, not a gap, a
consequence of the offline-training deviation.

```yaml
trust_evaluation:
  security_behaviour:
    rolling_window_seconds: 60
  process_anomaly:
    feature_window_size: 20    # AS-BUILT: 32 (src/config.py FEATURE_WINDOW_SIZE)
    isolation_forest:
      min_baseline_messages_before_training: 500   # AS-BUILT: n/a, offline training
      retrain_every_n_messages: 10000               # AS-BUILT: n/a, offline training
    lstm_autoencoder:
      hidden_size: 24            # AS-BUILT: 16 (LSTM_HIDDEN_SIZE)
      window_size: 20            # AS-BUILT: 8  (LSTM_SEQ_LEN)
    transformer:                 # NOT in the original design -- ablation candidate, B.5b
      enabled: false              # ablation-only; not wired into fusion_engine.py's inputs
      d_model: 32
      nhead: 4
      num_layers: 2
      dim_feedforward: 64
      dropout: 0.2
      noise_std: 0.15             # denoising-objective training noise, see B.5b
    gnn:
      enabled: false   # AS-BUILT: true, live default (docs/00_overview.md deviation #4)
      graph_mode: "multi_node"   # or "single_node_fallback"  -- AS-BUILT: "multi_node" (hybrid device-graph)
```

## 3. Acceptance Criteria

- Security Trust Score visibly drops within a few messages of each simulated cyberattack scenario (Section A.1's attack matrix mapping) on the held-out test set, with recall ≥ 80% at the tuned threshold.
- Process Anomaly Score visibly drops within a few messages of each simulated physical anomaly scenario, recall ≥ 80% on the held-out test set.
- The fused Process Anomaly Score outperforms every individual sub-signal alone on the validation set (this is the ablation table result — see `10_testing_and_attack_simulation.md`).
- The GNN sub-signal's keep/drop decision is backed by a written-down validation-set comparison, not a judgement call.
- At least 70% of sampled Level-2 explanation-validation tests (Section C.4) flip the decision when the named dominant feature is perturbed.

Continue to `05_module4_continuous_verification.md`.
