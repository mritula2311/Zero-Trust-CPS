# Proposed Methodology — Zero-Trust Gateway for a Cyber-Physical System

This document states the method: what is computed, the mathematics behind each
step, **why each expression is required rather than an arbitrary choice**, and
what is novel. Measured results live in `RESULTS.md`; architectural decisions and
their rejected alternatives live in `ZERO_TRUST_CPS_KB.md`. Nothing here is
aspirational — every constant quoted is the deployed one, and every claim of
effect points at the measurement that established it.

---

## 1. Problem and scope

A cyber-physical system exposes two failure surfaces that look identical to a
conventional intrusion detector and demand opposite responses:

| | example | correct response |
|---|---|---|
| **Cyber** | a device with forged credentials reporting perfectly normal vibration | deny access, challenge, revoke |
| **Physical** | a correctly-authenticated device whose bearing is failing | **pass the data through** and alert operations |

A single "trust score" cannot express the difference. Averaging a high identity
score with a low physical score yields a middling number that is wrong in both
directions: it under-reacts to a compromised device and over-reacts to a genuine
mechanical fault, taking the machine offline for a maintenance problem.

**The proposed method keeps the two axes separate all the way to the decision.**

The deployment is one real ESP32 + MPU6050 accelerometer (`esp32-vib-001`)
publishing over TLS MQTT, alongside two simulated devices that provide graph
context. Scope is deliberately bounded: this addresses *authentication and
anomaly attribution*, not confidentiality of the physical process, and it claims
IEC 62443 **SL-2**, not higher.

---

## 2. Architecture

```
telemetry ──▶ identity ▶ revocation ▶ HMAC-SHA256 ▶ replay(boot_id,seq) ▶ freshness
                                  │
                    any failure = REJECTED (never reaches a model,
                    and never touches the CLAIMED device's own state)
                                  │
                                  ▼
        ┌─────────────────────────┴─────────────────────────┐
        │                                                   │
  SECURITY TRUST  s_sec                            PROCESS ANOMALY  s_proc
  rate, step-up outcome, silence            rule ▸ IsolationForest ▸ LSTM-AE ▸ GNN
  (cyber evidence only)                              └────▶ fusion ────┘
        │                                                   │
        └───────────────▶  2×2 POLICY LOOKUP  ◀─────────────┘
                        ALLOW / ALERT / STEP_UP / BLOCK
                                  │
                                  ▼
                    hash-chained audit record
```

The two axes meet **only** at the policy lookup. This is enforced by test, not by
convention: `decide()` accepts the two scores plus a staleness flag and nothing
else, and a third evidence input fails `TestTwoScoreSeparation`.

---

## 3. Mathematics

### 3.1 On-device feature extraction

The board samples accelerometer magnitude `a = √(aₓ² + a_y² + a_z²)` into a window
**x = (x₁ … x_N)**, with **N = 32** at **f_s = 500 Hz** (64 ms). Five features are
computed *on-device*, and only those five are transmitted.

**Why extract on-device at all?** Transmitting raw windows would be 32× the
payload and would put the feature definition on the gateway, where it could drift
from what the sensor actually measured. Extracting at the source makes the
message self-describing and keeps the signed payload small enough that
HMAC-SHA256 costs 9 ms.

| # | expression | why this one |
|---|---|---|
| 1 | **RMS** = √( (1/N) Σ xᵢ² ) | Total vibration energy. The primary severity indicator, and the only feature with a direct physical unit (g). Insensitive to brief spikes, which is why it cannot stand alone. |
| 2 | **Peak** = max(x) − min(x) | Peak-to-peak amplitude. Captures shocks and impacts that RMS averages away. Peak-to-peak rather than max-absolute because a DC offset (gravity, ~1 g) would otherwise dominate. |
| 3 | **Crest factor** = Peak / RMS | Impulsiveness, dimensionless. **The diagnostic that RMS and peak cannot give separately**: a high crest factor at *normal* RMS is the classic early-stage bearing-damage signature — the energy has not risen yet, but it has become spiky. |
| 4 | **Excess kurtosis** = (1/N) Σ ((xᵢ − μ)/σ)⁴ − 3 | Fourth standardised moment. The −3 makes a Gaussian read 0, so the number is directly interpretable as "heavier-tailed than noise". Sensitive to sharp, infrequent events that all three amplitude features smooth over. |
| 5 | **Dominant frequency** = argmaxₖ \|Xₖ\| · f_s / N, k = 1 … N/2 | Frequency-domain fault signature. Rotating machinery faults appear at characteristic frequencies — unbalance at 1× running speed, misalignment at 2×, bearing defects at computable defect frequencies. The amplitude features cannot distinguish *which* fault. |

**The acquisition chain is one decision, not three.** f_s = 500 Hz, N = 32, and
the MPU6050's internal low-pass filter at 184 Hz are chosen together:

- Nyquist = f_s/2 = **250 Hz**, giving **66 Hz of margin** above the anti-alias
  filter's corner so its gradual roll-off does not fold content back into band.
- Bin spacing = f_s/N = **15.625 Hz**, window duration = N/f_s = **64 ms**.

Every `dominant_frequency` the models learned is scaled by f_s, so changing any
of the three requires retraining all of them. This is recorded as ADR-16 because
three successive defects lived here, each invisible until the previous was fixed;
the deployed chain is confirmed on-device by an invariant 64 ms sampling time
(`RESULTS.md` 13.1).

### 3.1b What each model trains on, and why

The same five features feed every Process Anomaly model, but each consumes them
in a different **shape**, and that shape is the reason the ensemble is not
redundant. A signal that cannot represent a pattern will never learn it, however
much data it sees.

| model | input shape | trains on | what that shape can represent | what it cannot |
|---|---|---|---|---|
| **Rule** | 1 vector (5 values) | nothing — fixed expected ranges from `config.DEVICE_REGISTRY` | physical implausibility (a disconnected sensor, an out-of-range reading) | anything statistical; it has no notion of "unusual but in range" |
| **Isolation Forest** | 1 vector (5 values) | 4,088 **normal** esp32 vectors, unsupervised | a point far from the normal cloud in 5-D | anything about *order* — it sees one message at a time |
| **LSTM-AE** | 8 × 5 window | 4,081 windows built from **normal** rows only | how the five features **evolve together over ~16 s** | cross-device patterns; each device is scored alone |
| **Transformer-AE** | 8 × 5 window | same windows, trained as a **denoiser** | same as LSTM-AE, via self-attention instead of recurrence | same limits; measured statistically identical (r = 0.998) |
| **GNN** | 3 nodes × 3 features (`rule`, `iso`, `lstm`) + adjacency | 29,576 graph snapshots, **supervised** per node | **simultaneous** anomalies across devices | single-device subtlety — it sees summaries, not raw features |
| **Fusion** | 4 scores | 11,036 examples, `class_weight='balanced'` | which signal to trust in which regime | nothing new — it only weights what it is given |

**Why train the autoencoders on normal data only?** Because the fault you care
about has not happened yet. A supervised classifier needs labelled examples of
the failure mode; an autoencoder needs only examples of health, and flags
whatever it cannot reconstruct. That is the realistic condition for a deployment
where the bearing has not worn out during the study.

**Why does the GNN take the other models' scores as node features rather than raw
features?** Two reasons. Raw features are device-specific — a vibration vector
means nothing on a scalar device — while `[rule, iso, lstm]` is a common
vocabulary every device speaks, so the graph can mix device types. And it keeps
the graph layer's job to *relational* reasoning rather than re-learning point
anomaly detection that the Isolation Forest already does well.

**Why only `at_rest` real hardware rows become training data.** The 192 captured
disturbance records are deliberately excluded: folding a shaken board in as
"normal" would teach the models a fault is healthy. They are held out as the
labelled test set, which is what makes real-hardware detection (30/30 on the
untouched test session under session-level splitting; C4) a result rather than
recall of memorised data.

**Measured evidence that the shapes are not redundant**, on `coordinated` — a
simultaneous multi-device anomaly:

| signal | input shape | recall |
|---|---|---|
| Isolation Forest | one vector | 0.316 |
| LSTM-AE | one device's window | 0.308 |
| Transformer-AE | one device's window | 0.308 |
| **GNN** | **the graph** | **1.000** |

The three single-device models are not undertrained. They **cannot see** the
pattern — no amount of data about one device reveals that three moved together.
So detecting it needs **cross-device information**, and this is the only event
class where cross-device information pays. It does *not* follow that graph
structure is necessary: given the same multi-device information a concatenated-input
model matches or beats the GNN, so no claim of GNN necessity or superiority is made
(C3). The GNN's 1.000 recall here also comes with badly collapsed precision — on a
consistent retrain it flags most traffic (overall accuracy 0.281, §0.13.2) — so the
recall figure alone overstates it; the defensible claim is that cross-device
information helps (task-2 accuracy 0.414 → 0.657, C2).

### 3.2 Security Trust  `s_sec ∈ [0,1]`

Computed from cyber evidence only — message rate, step-up challenge outcomes,
silence — and **never** from a sensor reading.

Time decay between messages:

> `s ← max(0, s − min(0.3, λ·Δt))`,  λ = 0.01 s⁻¹

**Why the `max(0, ·)` and the `min(0.3, ·)`?** Both are load-bearing rather than
defensive. Without the outer clamp, a backward wall-clock step (NTP correction)
makes Δt negative, so the decay term becomes negative and *inflates* trust —
a device would gain security trust for a reason unrelated to its behaviour.
**Trust may decay with time; it must never grow from it.** The inner clamp bounds
how much a single long gap can cost, so a device returning from a legitimate
outage is not instantly untrusted.

Failed authentication does **not** touch the claimed device's score. It
increments a separate `IdentityTargetingRisk` counter against the *claimed*
identity. **Why this matters:** penalising the claimed device on auth failure is
a trust-poisoning denial of service that requires no secret — an attacker simply
spams a victim's device ID with garbage signatures. This is also load-bearing
outside the attack model: during a clock misconfiguration the real board was
rejected hundreds of times and its trust score correctly never moved.

### 3.3 Process Anomaly — four sub-signals

All four map to `[0,1]` where **1 = looks normal**. That orientation is a
convention worth stating: these are *trust* scores, not anomaly scores, so they
compose with the policy in the same direction as `s_sec`.

#### (a) Rule-based range score

Each feature has an expected range; the score falls as features leave it. Its job
is not detection — it is a **physical-plausibility floor**. `rms`'s lower bound is
0.1, not 0, because a disconnected MPU6050 returns all-zero bytes over a
responsive I²C bus rather than raising an error, and `rms = 0` is physically
impossible for a connected accelerometer since gravity alone contributes ~1 g.
That bound catches a fault class no learned model would.

#### (b) Isolation Forest — point anomaly

Trained on normal feature vectors only (unsupervised). scikit-learn's
`decision_function` returns a raw score whose sign is the inlier/outlier boundary
but whose *scale* is compressed and contamination-dependent. It must be
calibrated before it can be composed with other signals:

> `s_iso = clip( 0.5 + (0.9 − 0.5) · (raw / m), 0, 1 )`,  m = median raw over the normal training set

**Why two anchors, and why these two?**

- `raw = 0 ↦ 0.5` — sklearn's own decision boundary maps to the neutral point, so
  the model's notion of "borderline" and the pipeline's agree by construction.
- `raw = m ↦ 0.9` — the median normal maps to this codebase's "looks normal"
  convention, shared with the other scorers' fallback value.

Both anchors come from the **normal class only**, so calibration consults no
anomalous example and the signal stays unsupervised.

**Why this is not cosmetic.** The previous mapping was `raw + 0.5`. Measured on
this model, the inlier side occupies a narrow positive band (normal median
+0.073), so a *perfectly normal* reading capped at **0.62** and the median normal
sat at **0.58** — both under the deployed threshold of 0.6. The signal was
structurally incapable of expressing "normal", and a healthy physical board was
BLOCKed live. Class separation had always been excellent; only the mapping was
broken.

#### (c) LSTM Autoencoder — sequence anomaly

Encoder–decoder over a window of **T = 8** consecutive feature vectors
(≈16 s of device history at the 2 s telemetry cadence). Inputs are per-feature
standardised using training mean and standard deviation.

Reconstruction error and its mapping to a score:

> `e = (1/(T·D)) Σ_t Σ_d ( x̂_{t,d} − x_{t,d} )²`
> `z = (e − μ_e) / σ_e`
> `s_lstm = clip( 0.9 − 0.25 · max(z, 0), 0, 1 )`

**Why an autoencoder rather than a classifier?** It trains on normal data only,
so it needs no labelled attacks — which is the realistic condition for a
deployment where the fault you care about has not happened yet.

**Why `max(z, 0)`?** Reconstructing *better* than the training baseline is not
evidence of health; the one-sided term stops an unusually easy window from
inflating trust.

**Why the 0.25 slope — and its known consequence.** It places the 0.5 crossing at
z = 1.6 and saturates to exactly 0 at z ≥ 3.6. That saturation is a real
limitation, honestly stated: real disturbances measure z = 4,200–48,000, so **the
signal is binary in practice and cannot rank severity**. A compressive map was
proposed to fix this and *rejected on measurement*: `sharp_impact` (max peak
2.968 g) produces a *lower* median z than `gentle_tap`, because 29% of its
samples are quiet — brief impulses with pauses — and error is averaged across the
window. **Window-averaged error measures how much of the window is disturbed, not
how violently.** The mapping was never the obstacle (`RESULTS.md` 0.10.9).

#### (d) Graph Neural Network — relational anomaly

A 3-layer graph convolution over the device graph. Devices publishing within the
same time window are connected; the normalised adjacency is

> `Â = D^(−1/2) (A + w·I) D^(−1/2)`,  **w = 3**
> `H^(l+1) = σ( Â H^(l) W^(l) )`

with node features `[rule, iso, lstm]` per device.

**Why a self-loop weight of 3 instead of the textbook `A + I`?** With three
active devices, `A + I` gives a node's own evidence weight 1/3 — so an identical
reading scored 0.020, 0.057 or 0.577 depending only on how many *unrelated*
devices happened to be publishing. A device's verdict must be dominated by its
own evidence, with neighbours as context. `w = 3` restores that.

**Why a cross-device signal exists at all.** Only a signal with access to more
than one device can see cross-device co-occurrence. Measured: on the `coordinated`
attack class, per-event recall is **1.000 for the GNN against 0.308–0.316** for
every single-device signal (§0.13.2). Those single-device signals cannot represent
the pattern by construction, not by undertraining. The GNN is one such cross-device
model, but graph structure is not what produces the benefit — given the same
multi-device information a concatenated-input MLP matches or beats it, so no claim
of GNN necessity or superiority is made (C3).

**A recorded trap.** Raising isolated-device scores once made the model saturate
to 1.000 on a genuinely shaken board, *masking a real anomaly* — because the only
isolated-topology examples in training were merged real-hardware rows, all
labelled normal, so the model learned "alone ⇒ normal". The fix was both the
self-loop weight *and* emitting the isolated variant of every training snapshot.
The metric improved before the model did.

#### (e) Fusion

A logistic-regression meta-learner over the four sub-signals:

> `s_proc = σ( β₀ + Σᵢ βᵢ sᵢ )`,  `σ(u) = 1 / (1 + e^(−u))`

**Why logistic regression and not something larger?** Three reasons, in order of
weight. It is **monotone in each input given a positive coefficient**, so "a
signal improved" can never make the fused verdict worse for a reason nobody can
explain. It admits an **exact** SHAP decomposition (§4.1) rather than an
approximation. And with four inputs and ~11k training examples, capacity is not
the binding constraint — under leakage-free held-out stacking (fusion fit on a
validation session disjoint from the base models', concern H) the coefficients are
`[rule −0.003, iso +2.97, lstm +5.97, gnn +8.33]`, which are themselves a finding:
the GNN carries the most weight and is also the least seed-stable signal
(±0.011 against the fused model's ±0.002). The leak was visible in the sign —
fitted in-sample the LSTM-AE coefficient came out **−0.46**, the wrong sign for a
signal whose whole purpose is to fall on anomalies; the clean fit restores it to
**+5.97** (`docs/CLAIM_EVIDENCE_MATRIX.md` C13, `RESULTS.md` §0.12.2).

**Trained with `class_weight='balanced'`, deliberately at a cost.** Unweighted,
the numerous easy examples dominate and the GNN's contribution on the rare
`coordinated` class is effectively discarded — measured, unweighted fused recall
on `coordinated` was **0.261, worse than the GNN alone at 0.870**. Balancing
recovers it, at the price of lower aggregate accuracy. Aggregate accuracy is the
wrong objective for a security system where a missed rare attack costs more than
a false alarm on a common one.

### 3.4 Policy

With thresholds `θ_sec = θ_proc = 0.6`:

| | `s_proc ≥ θ` | `s_proc < θ` |
|---|---|---|
| **`s_sec ≥ θ`** | ALLOW | **ALERT** |
| **`s_sec < θ`** | STEP_UP | BLOCK |

**The ALERT cell is the entire argument for the architecture.** Valid
credentials, abnormal physics — likely a real mechanical problem, so the data is
passed through and operations are flagged rather than the device being silently
cut off. A blended score cannot reach this cell distinctly: 0.909 and 0.000
average to ~0.45, which is indistinguishable from a moderately suspicious device
that is mechanically fine.

Verified on live hardware: shaking the board drove `s_proc` to 0.00001 across 16
consecutive messages while `s_sec` held at **0.895–0.909**, and the transition
took **one message**.

### 3.5 Adaptive policy (contextual bandit — not reinforcement learning)

**Terminology, corrected.** This is a **contextual bandit with sample-average
action-value estimation**, not reinforcement learning: there is no discount
factor and no next-state bootstrapping, and the reward is a fixed function of
`(state, action)`. (`RL_*` config names are retained only to avoid a ~20-site
rename; the method is described correctly everywhere it is discussed.)

The 2×2 table is a fixed prior. An optional learned policy discretises
`(s_sec, s_proc)` into a state and learns an action value by **incremental sample
average**:

> `Q(s,a) ← Q(s,a) + (1 / N(s,a)) · ( r − Q(s,a) )`

**Why 1/N rather than a fixed learning rate?** A fixed α = 0.2 is an exponential
moving average with a ~5-visit memory. Because a discretised state bucket holds a
*mixture* of underlying situations, such an estimator tracks recent visit
**order** rather than the mean — measured, every action in the high-trust states
sat within 0.4 of every other, making `argmax` effectively arbitrary, and the
deployed policy answered BLOCK at security 0.91 / process 0.87 where the static
table correctly answers ALLOW. The reward target here is **stationary**, and for
a stationary bandit the sample average is the correct estimator.

Training excludes `stealthy_forged_values`, which this design documents as
undetectable from single-node telemetry. **Why exclude an attack class?** State
`(9,8)` holds 3,295 legitimate messages against 69 stealthy ones; the 22.66×
inverse-frequency weight flips the reward mass to 1,564 against 948, so the
policy learns to block a 48:1 legitimate majority chasing something the evidence
cannot distinguish. It is still *scored* in the confusion matrices — excluded
from learning, not from reporting.

**Never on the live path.** All training is offline and produces artifacts;
`gateway.py` only runs inference. An online-learning policy decision point is an
attack surface: anyone who can generate traffic can move the model.

**What the comparison actually shows — a reported negative result.** On the
untouched test split, five policies on identical inputs give macro-F1:
static-optimised **0.5879**, decision tree 0.5834, **adaptive bandit 0.5329**,
multiclass LR 0.4355, deployed static 0.2744. The bandit clearly beats the
*deployed* static table (0.533 vs 0.274) but is **beaten by the same table with
thresholds selected on validation** (0.588). The honest claim is therefore that
the adaptive policy improves on the deployed configuration, **not** that it
outperforms a well-tuned static baseline (`docs/CLAIM_EVIDENCE_MATRIX.md` C6,
`RESULTS.md` §0.13.6).

### 3.6 Tamper-evident audit

Every decision appends a row whose hash chains to its predecessor:

> `h_i = H( h_{i−1} ‖ canon(row_i) )`,  H = SHA-256, `h₀` = fixed genesis

**Why a chain rather than signed rows?** Independently signed rows detect
*modification* but not *deletion* or *reordering* — an attacker who removes the
row recording their own BLOCK leaves a set of individually valid rows. Chaining
makes any deletion break every subsequent link.

Verification is two-tier because full verification is O(n):

- **Incremental tail** — verified on every request. Measured **46.7 ms** at
  78,546 rows.
- **Full scan** — O(n), measured **2,539 ms** (32.3 µs/row), cached 300 s.

**The full scan's interval *is* the detection latency for naive tampering**, so it
is deliberate rather than wasteful, at a 0.85% duty cycle. Projection: ~32 s at
1M rows, the point at which a checkpoint-anchored partial scan becomes necessary.
The checkpoint store that attests the database lives in a **different directory**
from the database, so a single deletion cannot remove both the evidence and its
witness.

### 3.7 Reporting uncertainty

Proportions are reported with **Wilson score intervals**:

> `( p̂ + z²/2n ± z·√( p̂(1−p̂)/n + z²/4n² ) ) / ( 1 + z²/n )`

**Why Wilson and not the normal approximation?** The normal ("Wald") interval
misbehaves in exactly this regime — small *n*, proportions near 0 or 1 — where it
produces intervals extending outside [0,1] and badly wrong coverage. Both
conditions hold here.

**Why report intervals at all?** Because the headline is otherwise misleading:
under session-level splitting the resting false-positive rate on the untouched
TEST session is **41.7% (5/12)** with a 95% CI of **[19.3%, 68.0%]** — a 12-window
denominator cannot be quoted to one decimal place, and the interval is what makes
that legible. (The earlier tight-looking **1/29 (3.4%)** was measured with the
test session's own at-rest rows in the training set and is withdrawn —
`docs/CLAIM_EVIDENCE_MATRIX.md` C4.) Detection, at 100% (30/30), remains the
better-supported number: **[88.6%, 100%]**.

---

## 4. Explainability

### 4.1 Level 1 — which signal decided

Because fusion is linear, SHAP values are exact, not approximated:

> `φᵢ = βᵢ · ( sᵢ − E[sᵢ] )`,  and  `Σᵢ φᵢ = margin − E[margin]`

Every decision logs a complete attribution across all four signals with the sum
reconstructing the model's margin. Measured: **200/200 (100%)** of top-feature
attributions matched the physically-sensible feature set for the injected anomaly
type.

### 4.2 Level 2 — which feature within the signal

Perturbation-based: replace one input channel with its training mean, re-score,
and check whether the verdict returns to legitimate.

> `Δᵢ = e(x) − e(x with channel i set to its training mean)`

Measured: **GNN 80/80 (100%)**, **LSTM-AE 0/139 (0%)**, overall **37%** against a
70% target. The single-channel test is retained for literature comparability; §4.3
gives the corrected, rank-aware metric that meets the target.

### 4.3 Anomaly rank — the diagnosis, and a proposed method

The Level-2 failure is not a property of the model. It is a property of the
**instrument**, and this is measurable. Define the **minimal repair set**: the
smallest set of channels whose joint repair restores a legitimate verdict.

> `k* = min { k : ∃ S ⊆ channels, |S| = k, score( x with S repaired ) ≥ τ }`

Measured on 136 real operator-labelled disturbance windows:

| channels repaired | recovered | median error after |
|---|---|---|
| none | 0/136 | 26825.17 |
| best 1 of 5 | 0/136 | 7156.90 |
| best 2 of 5 | 1/136 | 311.89 |
| **best 3 of 5** | **178/182 (98%)** | **0.31** |
| best 4 of 5 | 136/136 | 0.03 |

A flip requires error ≤ 2.76. Single-channel repair achieves a 3.7× reduction
where ~9,700× is needed; **three-channel repair clears it, and the minimal set is
`{peak, rms, crest_factor}`** — the three amplitude functions of
one spike, since `crest_factor` *is* `peak/rms`.

**So the anomaly has rank ≈ 3 and the standard instrument has rank 1. **Reported as a
first-class metric: rank-aware Level-2 recovery is 98% (178/182), meeting the same
70% target the single-channel test is held to.** This is not the single-channel
test relaxed until it passes — applied to `gnn_score`, whose anomaly is genuinely
single-source, the rank-aware test still passes at rank 1. The instrument's rank
is matched to the anomaly's; single-source anomalies are unaffected.** It cannot
pass, structurally. The GNN scores 100% on the identical test precisely because
its anomaly genuinely is single-source — a neighbour's evidence. The 37% is
measuring channel correlation and only incidentally explainability.

Note kurtosis is **not** in the minimal repair set although it is the channel most
often *attributed*. Attribution names the most diagnostic channel; repair needs
the sufficient set. They are different questions.

---

## 5. Evaluation methodology

The measurement protocol carries as much of this method's contribution as the
architecture, because several results changed sign when the protocol was fixed.

**Labels are recorded, never inferred.** Timed phase labels were shown not to
match physics — `at_rest_1` held a *higher* maximum RMS (3.416 g) than
`moderate_shake` (1.050 g). Ground truth now comes from operator marks taken at
the moment of each action, with a margin trimmed from each end, and **anything
outside a marked interval is discarded rather than guessed at**.

**Provenance never averages away.** `operator_mark` and
`transcript_reconstruction` are different grades of evidence and are reported
separately. Reconstructed labels are tail-contaminated in a detectable way:
resting medians agree across sessions (0.0170 / 0.0155 / 0.0159) while the
reconstructed session's tail runs ~3× fatter.

**Filling a sequence window is not clearing it.** A model with window length T
must drop **2T−1** records per block, not T−1. Dropping only enough to fill the
window leaves the block's own settling disturbance inside it — one 0.0768 g spike
in a baseline block failed all 6 of its scored windows.

**Evaluate at the deployed threshold.** A defect that made a signal incapable of
scoring above 0.621 — so a healthy board was BLOCKed live — moved the ablation
suite's headline accuracy by **0.003**, because the suite thresholded at 0.5 while
deployment decides at 0.6.

**Every arm of a comparison must be trained on the same data.** A stale
Transformer artifact — omitted from the documented training order — reported
accuracy 0.694 and an apparent **0.970** recall on the one attack class this
design cannot see. Retrained on current data: 0.754 and **0.606**, statistically
indistinguishable from the LSTM-AE. The capability was an artefact of staleness.

**A number going up is not the model improving.** Every fix is re-run on the case
that motivated it *and* the opposite case.

---

## 6. Novelty

The ML pipeline is not the contribution. Isolation Forest + LSTM-AE + GNN +
meta-learner is competent ensemble engineering, and zero-trust for CPS is a
crowded field. The contributions are methodological.

**1. Anomaly rank versus instrument rank in perturbation-based explainability.**
Single-channel perturbation is a standard Level-2 method. This work shows it is
**structurally invalid** for sequence models on correlated multi-channel physical
anomalies, with a controlled comparison inside one system: rank-1 repair achieves
3.7× where 9,700× is required, rank-3 repair recovers 98%, and a second signal in
the same pipeline passes the identical test at 100% because its anomaly is
single-source. A replacement diagnostic — the minimal repair set — is proposed
and measured.

**2. Falsifiable compliance rather than a mapping table.** Each NIST SP 800-207
tenet is validated against the hash-chained audit log, and then **each tenet's own
falsifier is injected to prove the check can fail** — **7/7 rejected**. Tenet 5
was for a long time excluded from that count as "not injectable, its falsifier is
missing data rather than a bad row". That was wrong: the check compares the
devices present in the rows against `DEVICE_REGISTRY`, so a row set covering
fewer devices falsifies it, and that is an ordinary row list. Finding and
correcting a wrongly-excluded case is precisely what a falsifiability self-test is
for. *If a validation check
cannot fail, it is not a check.*

**3. Hardware-in-the-loop training, quantified.** Real hardware is **3.0%** of the
training normals. Withholding it and retraining the whole chain **materially
increases** operator-marked false positives with detection unchanged — synthetic
data alone cannot place the normal region where the board actually sits, however
well calibrated. ⚠ The previously quoted magnitude (0/49 → 13/49) was measured
under the pre-split regime and its 0/49 baseline is the withdrawn leaky figure
(novelty #6 below); the *direction* is unaffected, but the exact synthetic-only
magnitude must be re-measured under session-level splitting before it is quoted
again (`docs/CLAIM_EVIDENCE_MATRIX.md` C14).

**4. Sim-to-real calibration that survives contact with a second session.** The
same board's resting DC measured 1.041 / 1.056 / 1.011 g — a 0.045 g spread
against a 0.009 g within-session std. Centring the simulator on the newest median
passed *every* offline test and then put the next live resting board at **−4.0σ**.
The method is to size the normal region on **cross-session spread**, not on the
latest median, and the negative result is the transferable part: offline
evaluation over captured sessions cannot detect over-fitting to captured
sessions.

**5. Detection below the amplitude decision boundary, on real hardware.** A
sustained periodic disturbance whose per-sample amplitude never leaves the resting
band is separated 14/14 against 0/14 from genuine rest — windows on which a
threshold set at the resting p99 has, by construction, no discriminative power at
all. This is the evidence that the sequence model contributes something an
amplitude rule cannot, and it came from an unengineered bench source rather than
an injected fault.

**6. Leakage-free re-measurement that withdrew the project's own headline
numbers.** Enforcing session-level train/validation/test splitting exposed that
several previously published figures rested on overlap between training and test
data, and each was re-measured and, where it changed, withdrawn rather than the
result being discarded: (a) the real-hardware resting false-positive rate moved
from a leaky **0/49** to an honest **5/12 (41.7%)** on the untouched test session,
detection unaffected at 30/30; (b) against five comparators on byte-identical
inputs the **GNN did not beat simpler models** (Task 1 test F1: concat MLP 0.985
vs GNN 0.838 at its own best swept self-loop weight), so the defensible claim is
about cross-device *information* (0.4142 → 0.6567), not graph structure; (c) a
**validation-tuned static policy beat the adaptive contextual-bandit policy**
(macro-F1 0.588 vs 0.533), which itself only beats the deployed static table
(0.274). A framework that withdraws its own overstated results under a stricter
protocol is the honest-reporting principle applied to itself
(`docs/CLAIM_EVIDENCE_MATRIX.md` C2/C3/C4/C6, `RESULTS.md` §0.12–§0.13).

**7. Live adversarial testing that found a real vulnerability.** Five hostile
messages delivered over the actual MQTT transport against a running gateway, all
rejected — and the exercise exposed a state-mutation bug invisible to every
synthetic evaluation: `check_boot_replay` advanced the anti-replay baseline as a
side effect, so a validly-signed but stale message with an inflated boot id could
mutate a rejected message's device state and lock the real board out entirely
(a denial of service). Fixed by making the check a pure predicate and committing
state only after all gates pass; verified by re-running the attack live with the
board staying authenticated. This is the concrete case for hardware-in-the-loop
adversarial testing over injected-label evaluation.

**8. The two-score separation, demonstrated on real hardware rather than argued.**
A violently shaken board moved `s_proc` to 0.00001 while `s_sec` held 0.895–0.909
across 16 consecutive messages, with a one-message transition.

---

## 7. Limitations

Stated because a method's boundaries are part of it.

- **The detection floor is measured below the amplitude threshold, not at equal
  amplitude.** An unplanned periodic source (96% of `dominant_freq` in one bin
  against 15 scattered bins at rest) allowed the controlled test: windows built
  only from samples at or below the resting p99 separate **14/14 flagged against
  0/14**, i.e. perfect separation where a per-sample amplitude threshold has none.
  Bounded claim — within that band the live windows still carry ~2× the amplitude,
  so amplitude is capped rather than held equal (`RESULTS.md` 0.10.14).
- **One board, one sensor, three operators-marked sessions.** ADR-18 assumes the
  resting-DC spread is a sensor property; a single unit cannot distinguish that
  from this unit's quirk.
- **Adversarial testing is now live, not synthetic** (§6 novelty #7): five hostile
  MQTT attacks over a real transport, 5/5 rejected — and it found a
  state-mutation vulnerability (a rejected message could advance anti-replay state
  and lock out the real device), now fixed and regression-guarded. Physical
  *fault* injection on hardware remains future work; a controlled attacker over
  the transport is done.
- **`stealthy_forged_values` is undetectable** from single-node telemetry by
  design, and the transformer's apparent solution was a staleness artefact.
- **Level-2 explainability**: the single-channel test is 37% (a structural rank-1
  limit, §4.3); the proposed rank-aware metric meets the 70% target at 98%.
- **The GNN's seed variance is in aggregate accuracy, not in its job.** ±0.011
  across seeds, but `coordinated` recall — the metric it exists for — is stable
  (0.974–1.0, sd 0.015) and never changes a decision. Lowering the learning rate
  makes coordinated recall perfectly stable but does not reduce accuracy variance;
  the wobble is decision-irrelevant and reported rather than tuned away.

- **Severity cannot be reduced to a single rank** because the physical states
  differ on orthogonal axes (impulsive vs sustained). A peak-aware statistic does
  not order them; the five-feature vector per message is the severity
  information, per-axis. The system detects *whether* a disturbance is present
  (binary, reliable) but not a scalar *how severe*.

---

## 8. Reproducing

```bash
# full training chain — SIX steps, in order; each replays through the previous
python scripts/merge_real_hardware_data.py      # fold real at-rest rows into synthetic
python scripts/generate_test_data.py
python scripts/train_isolation_forest.py
python scripts/train_lstm_ae.py
python scripts/train_transformer.py             # omitted once; cost every Transformer result
python scripts/train_gnn.py
python scripts/train_fusion_meta_learner.py
python scripts/train_adaptive_pdp.py

# evaluation
python scripts/evaluate_real_hardware.py        # operator-labelled hardware
python scripts/evaluate_ablation.py             # per-signal, at the deployed threshold
python scripts/evaluate_governance.py           # 7/7 tenets + 6/6 falsifier injections
python -m unittest discover -s tests            # 46 invariant tests
```

`ZTCPS_SEED` (default 0) sets the training seed for every model, so the
seed-sensitivity analysis in `RESULTS.md` 0.10.11 is reproducible.
