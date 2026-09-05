# 12 — Model Validation and Research Justification

This file exists for one reason: every other doc in this set describes
*what* each model is; this one argues, from a research-methodology
standpoint, *why each model belongs in the pipeline*, what evidence
supports keeping it, and what evidence would make a reviewer skeptical.
Every number below is reproducible by running the named script against
this repository's real trained models on `data/collected/test_session.json`
— nothing here is asserted without a script that can regenerate it. Read
`RESULTS.md` for the raw numbers; this file is the argument for why those
numbers matter and whether they're strong enough evidence.

**Scope note**: this project makes no claim of inventing a new model
architecture. Its research contribution is the *system*: a two-score,
never-blended Zero-Trust architecture for a CPS gateway, a multi-signal
fusion strategy with a documented, falsifiable ablation methodology, and
an honest accounting of where that system's own limits are (`RESULTS.md`
Section 14). Each model below is evaluated against that standard — does
it earn its place in *this* system, not "is it a good model in the
abstract."

---

## 1. Methodology Standard Applied to Every Model Below

Before the per-model sections, the standard every one of them is held to,
stated once:

1. **Held-out evaluation only.** Every number cites `test_session.json`
   (different random seed from `training_session.json`,
   `docs/10_testing_and_attack_simulation.md` Section 3.3), never
   training data. A number computed on training data is not a validation
   result and is never cited as one anywhere in this project's docs.
2. **A model earns its place by a measured comparison, not by
   assumption.** The GNN, and later the Transformer, were both added
   under an explicit keep/drop bar (`docs/04_module3_trust_evaluation.md`
   Section B.5): beat the existing combination on held-out data, or don't
   ship it. Both decisions — one keep, one archive-as-ablation-only — are
   documented with the numbers that produced them.
3. **A negative or underwhelming result is reported as-is.** This
   project's own history (`SESSION_LOG.md`) contains multiple cases where
   a measured result came back worse than hoped (the Transformer's tie
   with the LSTM-AE before the residue-exclusion fix; the Level-2
   explainability validation's 39% vs. a 70% target) and the response was
   to report the number and explain it, not adjust the target or hide the
   run. That standard applies to every model in this file.
4. **Synthetic data, honestly labeled as such.** Every number in this
   file comes from a synthetic generator (`device_simulator.py`,
   `scripts/generate_training_data.py`) that knows its own ground truth
   because it injected the anomalies itself. This is a genuine limit on
   generalization claims (Section 13 of `RESULTS.md`), not a hidden one —
   every per-model section below repeats it rather than letting a reader
   forget it three sections later.

---

## 2. Rule-Based Range Check (Security Behaviour Engine + Process Anomaly Sub-Signal)

**File**: `src/trust_engine.py` (`score_security_trust()`,
`rule_range_score()`). No training, no learned parameters.

### 2.1 Purpose and Need

Two separate rule-based checks exist in this system, and conflating them
is a common misreading worth heading off:

- **Security Behaviour Engine** (`score_security_trust()`): rate/flood
  detection + step-up outcomes. Pure cyber-behaviour evidence.
- **Process Anomaly rule check** (`rule_range_score()`): is each reported
  sensor feature inside its device's learned-normal range. Pure physical
  evidence, one of the four (now five, with the ablation-only Transformer)
  Process Anomaly sub-signals.

**Why a rule, not a model, for either**: this project's research
argument here is that the highest-stakes, earliest-available signal in a
Zero-Trust pipeline should be the one with the *fewest* ways to fail
silently. A rule has zero cold-start period (works from message one,
before any training data exists), a 100% inspectable failure mode (every
score change traces to one `if` branch), and — this is the load-bearing
research point — it exists specifically to serve as the **non-learned
baseline** every learned signal in Section B is measured against. Without
it, the ablation study in Section 3 below would have no floor to compare
learned signals to, and "the GNN improves on baseline" would be an
unfalsifiable claim.

### 2.2 Validation

`scripts/evaluate_ablation.py`, Section 2 of `RESULTS.md`:

| Metric | Value |
|---|---|
| Accuracy | 0.921 |
| Precision | 0.921 |
| Recall | 1.000 |
| Per-event recall: `anomalous_shock` / `coordinated` / `stealthy_forged_values` | 0.000 / 0.000 / 0.000 |

**Reading this honestly**: 1.000 recall on the *positive* (legitimate)
class and 0.000 on every physical-anomaly event type is not a
contradiction — it's the expected signature of a rule that only fires on
out-of-range values, and every anomaly scenario in this attack matrix is
deliberately *in-range* (`device_simulator.py`'s module docstring: the
whole point of `anomalous_shock`/`coordinated`/`stealthy_forged_values` is
to be undetectable by range alone). **This is the rule doing its job
correctly, not failing** — it is the explicit control condition the
ablation study needs, and its 0.000 recall on every anomaly type is the
exact evidence that motivates every learned signal below.

### 2.3 Threats to Validity

A rule this simple is trivially evadable by any adversary who knows the
expected range — which the `stealthy_forged_values` and `coordinated`
scenarios explicitly simulate. This isn't a flaw discovered in
validation; it's the documented, intended reason the other four signals
exist (`docs/04_module3_trust_evaluation.md` Section A.0).

---

## 3. Isolation Forest (Unsupervised ML)

**File**: `src/isolation_forest_scorer.py` /
`scripts/train_isolation_forest.py`. `sklearn.ensemble.IsolationForest`,
`contamination=0.1`, trained on normal-only esp32-vib-001 data.

### 3.1 Purpose and Need

**Research motivation**: an unsupervised density/isolation-based
detector is the correct first ML signal to add specifically because it
requires **no labelled anomaly examples** — only normal baseline data,
which is the one thing this project can collect in volume (via the
synthetic generator standing in for a real baseline-collection session,
`docs/01_simulation_and_hardware_abstraction.md` Section 5.2). This
matters for the stated research problem (a CPS gateway that must work
from early deployment, not after months of labelled-attack data
accumulate) — Isolation Forest's cold-start story is "500 normal
messages," not "500 labelled attacks of every kind you expect to see."

**Why Isolation Forest specifically, not e.g. a one-class SVM or local
outlier factor**: literature grounding [15] warns that any single ML
method has a systematic weak spot — the direct motivation for this
project's whole fusion strategy, not just this one model's choice.
Isolation Forest's specific strength (fast, works well in the moderate-
dimensional, non-linear feature space this project's 5-feature vibration
vector sits in, no distance-metric sensitivity the way LOF/SVM have) makes
it a strong FIRST opinion to fuse, not a claim that it's uniquely correct.

### 3.2 Validation

| Metric (blended, Section 2) | Value | Metric (own, Section 2.1 per-event) | Value |
|---|---|---|---|
| Accuracy | 0.937 | `anomalous_shock` recall | 1.000 |
| Precision | 0.960 | `coordinated` recall | 0.316 |
| Recall | 0.972 | `stealthy_forged_values` recall | 0.121 |
| F1 | 0.966 | | |

**Reading this honestly**: highest raw aggregate accuracy of any single
signal, including the fused output (`RESULTS.md` Section 2's own
callout on this). But this is a case where aggregate accuracy is the
wrong single number: 0.316 on `coordinated` shows Isolation Forest,
looking at one device's features in isolation, structurally cannot see a
cross-device correlated pattern — a real, validated, expected weak spot,
not a modeling failure (Section 4.1's Level-2 explainability result adds
a second, independent confirmation: SHAP correctly attributes the
dominant feature, but a *tree ensemble's* isolation depth depends on many
features jointly, which is exactly why a single-node, single-feature
signal caps out here).

### 3.3 Threats to Validity

`ISOLATION_FOREST_CONTAMINATION=0.1` is a hyperparameter choice, not
learned from data — a different contamination fraction would shift the
precision/recall trade-off; not swept in this round (a real, scoped
follow-up, not a hidden gap).

---

## 4. LSTM-Autoencoder (Deep Learning — Sequential)

**File**: `src/lstm_ae_scorer.py` / `scripts/train_lstm_ae.py`.
Encoder-decoder LSTM, `hidden_size=16`, `num_layers=1`,
`LSTM_SEQ_LEN=8`-message window, self-supervised reconstruction (MSE).

### 4.1 Purpose and Need

**Research motivation**: every signal above (rule, Isolation Forest)
scores ONE message at a time — neither can see a trend that looks fine
at any single instant but wrong over a trailing window (a slowly
worsening bearing fault is the canonical physical example,
`docs/04_module3_trust_evaluation.md` Section B.4). An autoencoder over a
short sequence is the correct model FAMILY for this specific gap: it
learns a compressed representation of "normal sequences" and flags
anything that doesn't reconstruct well from the training-time-normal
manifold — sequence in, no external label needed, same self-supervision
property as Isolation Forest (synopsis Section 5.3), but sequence-aware
where Isolation Forest is not.

**Why LSTM specifically, not e.g. a GRU or 1D-CNN**: an LSTM's recurrent
hidden state creates a genuine information bottleneck between encoder and
decoder — this matters more than it sounds like a footnote: Section 5's
Transformer comparison below exists specifically because this bottleneck
property (or its absence) turned out to be architecturally consequential
for this exact task.

### 4.2 Validation — Two Numbers, Because One Is Misleading

**Blended (Section 2, includes rule_score standing in for the two scalar
devices)**: accuracy 0.753, F1 0.851 — diluted by 66% of rows being an
unrelated signal (`RESULTS.md` Section 2.2 explains the dilution
mechanism in full).

**Fair, esp32-vib-001-only, window-residue-excluded (Section 2.2)**:

| Metric | Value |
|---|---|
| Accuracy | 0.933 |
| Precision | 0.875 |
| Recall | 0.970 |
| F1 | 0.920 |

**This second number is the one that actually measures the LSTM-AE's own
quality** — the first is dominated by an unrelated signal for most rows.
Citing 0.753/0.851 as "the LSTM-AE's accuracy" without this caveat would
be a real, avoidable misrepresentation; this file states which number
means what specifically so that mistake isn't repeated elsewhere.

**A real methodological bug was found and fixed in the course of
producing this number**: the raw isolated-esp32 evaluation, before the
fix, showed ~75% false-positive rate on genuinely normal messages —
traced to a train/inference mismatch (training windows exclude any
window containing an anomaly; inference sees the real interleaved
stream) and fixed by applying the same residue-exclusion
`train_fusion_meta_learner.py` already used for its own target
(`RESULTS.md` Section 2.2 / Section 9 item 9). Reported here because a
model validation section that doesn't mention a bug that inflated its own
apparent error rate by ~40x would be an incomplete validation.

### 4.3 Threats to Validity

`LSTM_HIDDEN_SIZE`/`LSTM_NUM_LAYERS` were explicitly tested at 2x-4x
current capacity and found to OVERFIT the (then-345-reading) training set
— held-out accuracy regressed from 0.762 to 0.734 (`SESSION_LOG.md` entry
19). The current 16-hidden/1-layer configuration is the result of that
verified-not-assumed capacity search, not an arbitrary default — but a
capacity search on a since-enlarged dataset (12.5x more data, this
session) has not been re-run; the current size may now be conservative
relative to the larger dataset. Flagged as a real, scoped follow-up.

---

## 5. Transformer Encoder — Denoising Autoencoder (Deep Learning — Attention-Based, Ablation Candidate)

**File**: `src/transformer_scorer.py` / `scripts/train_transformer.py`.
Encoder-only (`nn.TransformerEncoder`), full bidirectional self-attention,
2 layers, 4 heads, `d_model=32`, 17,701 params. NOT in the original
design; added, tuned, and evaluated this round; NOT wired into the live
fusion inputs.

### 5.1 Purpose and Need

**Research motivation, stated precisely**: this model was not added
because the LSTM-AE was failing — it was added to test a specific,
falsifiable hypothesis: *does self-attention's ability to weigh every
position in the window against every other position directly (rather
than through a recurrent bottleneck) improve reconstruction-based anomaly
detection on this exact task*, holding window length, input features, and
evaluation methodology fixed. This is the correct research design for
introducing a second architecture into an existing ablation study — one
variable changed (attention mechanism vs. recurrence), everything else
held constant, per Section 1's methodology standard above.

**Why a denoising objective, not plain reconstruction — a specific,
falsifiable architectural risk this project identified and mitigated,
not a stylistic choice**: full self-attention gives every position direct
access to every other position, so a *plain* reconstruction transformer
can partially shortcut — attend to neighboring true values and copy them,
under-scoring real anomalies — in a way an LSTM's recurrent bottleneck
prevents by construction. Training against Gaussian-noise-corrupted input
(loss against the clean target) removes that shortcut without changing
the task framing. This risk was reasoned about BEFORE training, not
discovered as a failure after the fact — the kind of foresight a
methodology section should be able to point to.

**Why NOT a seq2seq/forecasting variant, considered and rejected
explicitly**: an encoder-decoder that predicts future steps
autoregressively was considered. At an 8-step window, there is no
long-range dependency for a decoder to exploit that a reconstruction
encoder can't already capture — the setting transformers most clearly win
in (long sequences, large data) is not the setting this task presents.
Building the more complex variant anyway would have been architecture
shopping without a hypothesis behind it.

### 5.2 Validation

**Fair, undiluted comparison against the LSTM-AE** (`RESULTS.md` Section
2.2, esp32-vib-001-only, residue-excluded):

| Metric | LSTM-AE | Transformer | Δ |
|---|---|---|---|
| Accuracy | 0.933 | 0.941 | +0.008 |
| Precision | 0.875 | 0.877 | +0.002 |
| Recall | 0.970 | 0.990 | +0.020 |
| F1 | 0.920 | 0.930 | **+0.010** |
| Parameters | 3,029 | 17,701 | 5.8x |

**The hypothesis is confirmed, but the effect size is small — and this
project treats that as the actual result, not a disappointment to
downplay.** A 7-configuration hyperparameter sweep (pre-LN vs. post-LN,
ReLU vs. GELU, ~6x more capacity, up to 400 epochs, varied noise/LR/weight
decay) reproduced the identical +0.010 F1 gap across every configuration
— the reproducibility across a wide sweep is itself evidence this is a
genuine, if modest, architectural effect rather than training-run noise.
Per-event recall on `anomalous_shock`/`coordinated`/`stealthy_forged_values`
is identical between the two architectures, meaning the attention
mechanism's advantage shows up in aggregate discrimination, not in
catching any additional anomaly *type* the recurrent model missed.

### 5.3 The Keep/Drop Decision, and Why It's "Drop" Despite a Positive Result

A positive, reproducible result is not automatically an adoption
decision — this is the section that makes that distinction explicit as a
research judgment, not an oversight. Adopting the Transformer into live
fusion would mean: (1) retraining the GNN, whose node features currently
include `lstm_score` (`gnn_scorer.py`'s docstring), (2) retraining the
fusion meta-learner to accept a 5th input, (3) shipping 5.8x the
parameters for a signal with structurally identical recall to what's
already deployed. **A +0.010 F1 gain does not clear that integration
cost.** This is recorded as a validated-but-not-adopted result, following
the exact same keep/drop precedent the GNN itself had to clear
(`docs/04_module3_trust_evaluation.md` Section B.5) before being folded
into the live pipeline.

### 5.4 Threats to Validity

The training-data scale-up (400→5,000 ticks) was done specifically
because a higher-capacity model needs more data to be evaluated fairly —
but 12.5x more synthetic data from the SAME generator family is not
equivalent to more real-world diversity; the effect size measured here is
still bounded by how expressive that one generator's normal/anomalous
distributions are.

---

## 6. Graph Neural Network (Deep Learning — Relational)

**File**: `src/gnn_scorer.py` / `scripts/train_gnn.py`. Hand-rolled GCN
(not `torch-geometric` — a deliberate dependency-risk decision, not a
capability gap, see that file's docstring), hybrid device-graph, 3 layers,
32 hidden units.

### 6.1 Purpose and Need

**Research motivation**: this is the one signal in the entire Process
Anomaly Engine structurally capable of seeing a **cross-device**
correlated pattern — the specific gap every single-device signal above
(rule, Isolation Forest, LSTM-AE, Transformer) cannot close by
construction, no matter how well-tuned. `coordinated` (attack-matrix row:
all three devices drift simultaneously, individually in-range) exists
specifically to give this signal a scenario only it can plausibly catch —
and per Section 3.2's numbers, that's exactly what happens.

**Why a graph, not e.g. concatenating all devices' features into one
larger feature vector for a non-relational model**: a graph's edges
encode WHICH devices' co-occurrence is meaningful (a `GNN_EDGE_WINDOW_SECONDS`
communication-recency edge, `gnn_scorer.py`), and message passing
propagates each node's evidence to its neighbors in a way a flat
concatenation can't — the model literally cannot ignore that device B's
current state is relevant context for scoring device A, which is the
exact property `coordinated` detection needs.

### 6.2 Validation

| Metric (blended, Section 2) | Value | Metric (Section 2.1 per-event) | Value |
|---|---|---|---|
| Accuracy | 0.929 | `anomalous_shock` recall | 1.000 |
| Precision | 0.987 | `coordinated` recall | **1.000** |
| Recall | 0.935 | `stealthy_forged_values` recall | 0.000 |
| F1 | 0.960 | | |

**The 1.000 `coordinated` recall is the load-bearing validation result
for this model's entire justification** — no other single signal comes
close (Isolation Forest 0.316, LSTM-AE/Transformer 0.308, rule 0.000).
This is not a coincidence of tuning: the GNN's own keep/drop decision
(Section B.5) was made BEFORE this result was known, on the explicit
criterion that it must measurably improve `coordinated` handling over the
rule+IF+LSTM-AE combination alone — it did, decisively, and that's the
documented reason it's a live default rather than an ablation-only signal
like the Transformer.

**0.000 on `stealthy_forged_values` is expected, not a failure**: this
scenario is deliberately engineered so every device's reading looks
normal individually AND the correlation pattern looks normal too — there
is no relational signal for a GNN to see when nothing about the situation
is actually correlated across devices. `RESULTS.md` Section 11 covers why
this is architecturally capped for every signal, GNN included.

### 6.3 Threats to Validity

The "hybrid device-graph" (3 nodes: the two scalar devices plus
esp32-vib-001) is a much smaller graph than the literature this model is
grounded in ([16], [17]) actually validates against (typically dozens to
hundreds of nodes). `docs/04_module3_trust_evaluation.md` Section B.5
states plainly this is a demo-scale graph, and the `coordinated` result
above, while real, is measured on a 3-node graph from the same synthetic
generator as training (different seed) — a narrower generalization claim
than "detects coordinated attacks on an arbitrary sensor network."

---

## 7. Fusion Meta-Learner (Stacking, Classical ML)

**File**: `src/fusion_engine.py` / `scripts/train_fusion_meta_learner.py`.
`sklearn.linear_model.LogisticRegression`, `class_weight="balanced"`, 4
inputs (rule, Isolation Forest, LSTM-AE, GNN scores).

### 7.1 Purpose and Need

**Research motivation, and why NOT a hand-tuned weighted average**: [15]'s
warning (any single ML method has a systematic weak spot) is the
motivating citation for the whole fusion strategy, but the specific
choice to LEARN the combination rather than hand-set weights is a
separate, additional research decision: a learned stacking model can
discover that, e.g., GNN evidence should dominate specifically for
`coordinated`-shaped inputs, in a way a fixed linear blend tuned by hand
could not adapt to. Logistic regression specifically (over a more complex
stacker) is chosen for the SAME interpretability argument Section A.0
makes for the rule-based Security Engine — its coefficients are directly
inspectable (`train_fusion_meta_learner.py` prints them every run) and
SHAP has an exact, closed-form explanation for a linear model
(`fusion_engine.py`'s `_explain()` docstring) that a nonlinear stacker
(e.g. a small MLP or gradient-boosted stacker) would not offer without
sampling-based approximation.

### 7.2 Validation

| Metric | Value |
|---|---|
| Accuracy | 0.703 |
| Precision | 0.996 |
| Recall | 0.681 |
| F1 | 0.809 |
| `coordinated` recall | **1.000** |
| `stealthy_forged_values` recall | 0.758 |

**This is the single most important "read the number correctly" case in
this whole document.** 0.703 aggregate accuracy is LOWER than Isolation
Forest's 0.937 alone — a naive reading would call this a regression. It
is not: `class_weight="balanced"` is a deliberate, verified trade-off
(`RESULTS.md` Section 2's own explanation, with the counter-experiment
already run: an UNWEIGHTED fit measured `coordinated` recall at 0.261,
*worse* than the GNN alone at 1.000 — meaning an unweighted fusion would
have been actively discarding the one signal built to catch the rarest,
highest-value attack class). The correct comparison for a security system
is not "which number is bigger" but "which policy costs less when it's
wrong" — missing a `coordinated` attack is categorically more expensive
than a few extra false positives on already-well-caught `normal`
messages, and this fusion configuration is the one that reflects that
priority, verified with the counterfactual experiment that shows what the
alternative actually costs.

### 7.3 Threats to Validity

The 4 inputs are themselves each imperfect (Sections 3–6 above); fusion
cannot manufacture information none of its inputs contain — the
architecturally-capped `stealthy_forged_values` ceiling (Section 11 of
`RESULTS.md`) applies to the fused output too (0.758, a real improvement
over any single input's 0.000–0.606, but still not "reliable detection").

---

## 8. Adaptive PDP — Contextual Bandit (sample-average action values)

> **Terminology, corrected (`docs/CLAIM_EVIDENCE_MATRIX.md` C6, concern N).**
> This is a **contextual bandit with sample-average action-value estimation**,
> **not reinforcement learning and not Q-learning**: the update is
> `Q(s,a) ← Q(s,a) + (1/N(s,a))·(r − Q(s,a))` with **no discount factor and no
> next-state bootstrapping**, and the reward is a fixed function of
> `(state, action)`. The `RL_*` config names and the "Q-learning" wording below
> are retained only to avoid a ~20-site rename; read them as the bandit described
> here. Prose in this section that argues "why an RL formulation belongs here"
> should be read as "why an *adaptive/contextual-bandit* formulation belongs here".

**File**: `src/adaptive_pdp.py` / `scripts/train_adaptive_pdp.py`.
Tabular action-value estimation, epsilon-greedy training, state = (security_bucket,
process_bucket) — a 2D discretized state space, 4 actions
(ALLOW/ALERT/STEP_UP/BLOCK).

### 8.1 Purpose and Need

**Research motivation, and the specific gap this closes that the static
table cannot**: `policy_engine.decide()`'s static 2x2 table issues
`STEP_UP` only once `security_trust_score` crosses a hard-coded 0.6
threshold. A momentary flood, under the EWMA smoothing (`α=0.35`), pulls
the score to ~0.66 — above that hard line, so the static table does
nothing. A Q-learning policy that has seen many (state, reward) pairs can
learn a *softer, more sensitive* decision boundary than any single
hand-picked threshold, directly from reward feedback, without anyone
having to guess the right cutoff. This is the correct problem shape for
RL among the models in this pipeline: **the earlier five models produce
evidence (a score); this model consumes two pieces of evidence and
decides an ACTION** — a genuinely different task (sequential decision
under a reward signal) that a classifier can't directly express, which is
the actual justification for why an RL formulation belongs here at all,
not just "RL is a modern technique."

**Why tabular Q-learning specifically, not a deep RL method (DQN, policy
gradient)**: the state space here is small and fully enumerable (10x10
discretized buckets), and the action space is 4 actions. A deep function
approximator would add capacity and training instability this problem
does not need — the same "not a case that needs a large model" reasoning
`docs/04_module3_trust_evaluation.md` Section B.5 applies to the GNN
applies here with even more force, since the state space is provably
small enough for an exact tabular representation.

**Why the LIVE policy never learns online — a safety property, not a
limitation**: `adaptive_pdp.py`'s `greedy_action()` is a frozen,
no-exploration Q-table lookup; `choose_action()` (epsilon-greedy,
training-only) and `update()` (training-only) are never called by the
live gateway. This is a deliberate research and engineering choice,
stated explicitly in `docs/00_overview.md` deviation #4: a policy that
never updates itself live has no live-reward-signal-integrity problem to
solve (an adversary can't poison the policy by feeding it bad live
rewards, because there are no live rewards).

### 8.2 Validation

`scripts/evaluate_rl_policy.py`, `RESULTS.md` Section 3:

| Policy | Avg reward | macro-F1 (4-class) | `security_concern` recall |
|---|---|---|---|
| Static 2x2 table (deployed) | 0.282 | 0.269 | 0.000 |
| **Bandit (greedy, deployed)** | **0.606** | **0.583** | **1.000** |

> ⚠ **Leakage-free re-measurement qualifies this (C6, `RESULTS.md` §0.13.6).** On
> the untouched test split with five policies on identical inputs, macro-F1 is:
> **static-optimised 0.5879 > decision tree 0.5834 > adaptive bandit 0.5329 >
> multiclass LR 0.4355 > deployed static 0.2744.** The bandit beats the *deployed*
> static table but is **beaten by a validation-tuned static table**. The
> "beats static" claim therefore holds only against the deployed configuration, not
> against a well-tuned static baseline — and the rare `combined`
> (`stealthy_forged_values`) class stays effectively undetectable for every policy
> with a usable false-block rate (C8). The mechanistic `security_concern` result
> below is unaffected.

**The 0.000 → 1.000 jump on `security_concern` is the single clearest,
most mechanistically-explained result in this whole document**: it is
not a black-box improvement — `RESULTS.md` Section 3.2 traces the EXACT
reason (the static table's hard 0.6 threshold vs. the RL policy's learned
sensitivity to the same ~0.66 post-flood score) and confirms it's not
overfitting the reward function (Section 3.3's convergence trend shows
stable, noisy-but-not-diverging learning across independent training
runs).

**The `combined` class result is the necessary honest counterweight**:
0.394 recall on the rarest class (33/2,933 messages) comes at 0.071
precision — the reward weighting that makes RL sensitive enough to catch
some `combined` cases also makes it BLOCK many `normal`/`physical_fault`
messages it shouldn't (163 and 6 false positives respectively,
`RESULTS.md` Section 3.2). This is priced in and reported, not hidden:
`situation_weights()`'s ~22x inverse-frequency upweighting of the
rarest class is a deliberate precision-for-recall trade specific to a
security context, following the same "missing a rare attack costs more
than a false positive" argument Section 7.2 makes for the fusion
meta-learner — the same research principle applied at two different
layers of the same system.

### 8.3 Threats to Validity

A tabular Q-table's generalization is bounded by how many training
messages land in each of the 100 state buckets — sparsely-visited buckets
fall back to the static table's own seeded action
(`adaptive_pdp.py::_get_q()`), meaning the RL policy's real advantage is
concentrated in well-visited regions of the state space, not uniform
everywhere. Not measured directly in this round (a real, scoped
follow-up: report per-bucket visit counts alongside the confusion matrix).

---

## 9. Cross-Model Summary — What Each Model's Validation Actually Establishes

| Model | Type | What it uniquely validates | What it does NOT establish |
|---|---|---|---|
| Rule-based range check | Rule (non-ML) | The non-learned floor every learned signal is measured against | Anything about in-range anomalies, by design |
| Isolation Forest | ML (unsupervised) | Best raw single-signal accuracy; works from normal-only data | Cross-device patterns; SHAP-ranked features don't linearly control its score (Section 4.1, RESULTS.md) |
| LSTM-Autoencoder | DL (sequential, recurrent) | Slow-drift/window-based detection with a genuine information bottleneck | An advantage over the Transformer on this task at this scale (Section 5.2) |
| Transformer | DL (sequential, attention) | A measurable, reproducible +0.010 F1 over the LSTM-AE from removing the recurrent bottleneck | That the gain justifies production adoption (Section 5.3) |
| GNN | DL (relational) | The ONLY signal that reliably catches `coordinated` (1.000 recall) | Generalization beyond a 3-node demo-scale graph |
| Fusion meta-learner | ML (stacking) | A principled, verified precision/recall trade favoring rare-attack recall | Recovery from an architecturally-capped scenario (`stealthy_forged_values`) no input signal can see |
| Adaptive PDP (bandit) | Contextual bandit (sample-average action values — **not RL/Q-learning**, §8) | A learned, more sensitive decision boundary than the *deployed* static table, safely frozen at inference | Beating a *validation-tuned* static table (it does not — C6); uniform reliability across sparsely-visited state buckets |

**The overall research claim this file supports**: not that any one
model here is individually novel, but that a disciplined, falsifiable
keep/drop methodology — applied consistently across a rule, three
distinct ML/DL paradigms, a graph model, a stacking ensemble, and a
reinforcement-learning policy — produces a system where every component's
presence is backed by a specific, reproducible, held-out measurement, and
where a negative or underwhelming result (the Transformer's marginal
gain, the Level-2 explainability's 39% flip rate, Isolation Forest's
`coordinated` blind spot) is reported as data, not smoothed over. That
discipline, not any single model, is this project's actual research
contribution.
