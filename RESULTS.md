# Results and Evaluation

> **SECTION 0.12 (2026-09-03) SUPERSEDES EARLIER FIGURES.** A session-level
> train/validation/test split and a leakage-free fusion meta-learner were
> introduced. Three previously published claims do not survive the correction —
> the real-hardware 0/49 false-positive rate, GNN superiority, and adaptive-policy
> superiority. See §0.12 and docs/CLAIM_EVIDENCE_MATRIX.md.

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

## 0. Scoring-Defect Remediation Round (supersedes earlier RL/policy numbers)

**Read this before citing any number below it.** A full end-to-end
verification against the live ESP32 found that a healthy board sitting at
rest was being `BLOCK`ed. Four independent defects were root-caused, each
by measurement rather than inspection, plus one firmware bug. The training
data was **not** regenerated — `data/collected/training_session.json` is
byte-identical across this round — so every change below is attributable
to code, not to shifted inputs.

### 0.1 Isolation Forest score calibration (the root cause)

`sklearn`'s `decision_function` is not a `[-0.5, 0.5]`-spanning score.
With `contamination=0.1` it is defined so that exactly 10% of the training
data falls below `0.0`, and its inlier side is compressed into a narrow
positive band. Measured on this model:

| Class | `decision_function` median | Old mapped score (`raw + 0.5`) |
|---|---|---|
| normal | `+0.0788` | 0.579 |
| best case, any input | `+0.1214` | **0.621** |
| anomalous_shock | `-0.3529` | 0.147 |

`PROCESS_THRESHOLD` is **0.6**. The best score the signal could produce for
a *perfectly normal* reading was 0.621, and the median normal was 0.579 —
**below threshold**. The signal could never express "normal", and it
dragged the fused score under threshold on healthy telemetry, including the
real board at rest. Note that the class separation was always excellent;
only the mapping into `[0,1]` was wrong.

Fixed with two anchors taken from the **normal class only**, so training
stays unsupervised: `raw = 0 → 0.5` (sklearn's own inlier/outlier boundary)
and `raw = median(normal) → 0.9`. The map is monotonic, so nothing is
reordered — it only rescales a signal that had been squeezed into an
unusable range.

| Isolation Forest on training normals | Before | After |
|---|---|---|
| median | 0.579 | **0.900** |
| fraction above the 0.6 threshold | 25.8% | **85.7%** |
| `anomalous_shock` median | 0.147 | **0.000** |

### 0.2 GNN verdict depended on unrelated devices

One **identical** ESP32 reading, varying only how many other devices
happened to be publishing inside the edge window:

| Active devices | GNN (before) | fused (before) | fused (after) |
|---|---|---|---|
| 1 (board alone) | 0.081 | **0.020** | **0.873** |
| 2 | 0.226 | 0.057 | 0.924 |
| 3 | 0.648 | 0.577 | 0.941 |

Two causes. First, with the textbook `A + I` and three active nodes,
symmetric normalisation gives a node's own evidence only 1/3 of its
representation, so neighbours dominated its verdict. Now
`GNN_SELF_LOOP_WEIGHT = 3.0` (`A + 3I`), making self-weight 0.6 against
0.2 per neighbour. Second, the isolated-graph topology appeared in training
*only* as merged real-hardware rows, which are all labelled normal — so the
model learned "no neighbours ⇒ normal" and saturated to **1.000** on a
genuinely shaken board (`rms = 2.5`, IF `0.00`, LSTM `0.40`), masking a
real anomaly. Training now emits the isolated variant of every snapshot,
covering that topology with the same class balance.

### 0.3 RL Q-value estimator

`RL_ALPHA = 0.2` is an exponential moving average with roughly a five-visit
memory. A single state bucket holds a *mixture* of ground-truth situations,
so the stored value tracked visit **order** rather than the mixture mean.
Measured on the trained table, state `9,8`: `BLOCK -0.3` against
`ALLOW -0.7` — every action within 0.4 of every other, so `argmax` was
effectively arbitrary. The deployed policy answered **BLOCK** for a device
at security `0.91`, process `0.87`, where the static 2×2 table correctly
answers `ALLOW`.

Replaced with the incremental **sample average** (`α = 1/N` per
`(state, action)` visit), the correct estimator for a stationary contextual
bandit. `RL_ALPHA` has been removed.

### 0.4 An unlearnable class was steering the policy

`stealthy_forged_values` is by construction drawn from the same feature
distribution as normal traffic (`docs/04` §B.8). A policy keyed on
`(security, process)` cannot learn to detect it; it can only learn to block
the region where normal traffic lives. Measured on state `9,8`:

| | raw count | after the 22.66× inverse-frequency weight |
|---|---|---|
| legitimate (`normal`) | **3295** | 948 |
| `combined` (stealthy) | 69 | **1564** |

A 48:1 legitimate majority was overturned by the class weight. The class is
now excluded from what the policy **trains** on; the confusion matrices
still score it, because failing to detect it is a result worth reporting.
The alternative was measured too: unweighted rewards collapse to `ALLOW`
even at process `0.05`, so inverse-frequency weighting is retained for the
classes that genuinely *are* separable.

### 0.5 Firmware: `dominant_freq` was wrong 19% of the time

The hand-rolled truncated-Taylor `_sin()` had **7.5e-2** maximum error over
`[0, 2π]`, which corrupted the on-device DFT enough to select the **wrong
frequency bin in 57 of 300 test windows (19%)**, off by as much as
**46.9 Hz**. Because `src/feature_engineering.py` is the reference the
models are trained against, this was a silent train/serve skew present
*only* on real telemetry and invisible to every simulated row.

Replaced with `math.sin`/`math.cos`, present in every standard ESP32 build.
The firmware now reproduces `feature_engineering.dominant_frequency()`
**exactly — 0/300 mismatches**. The other four features already matched
exactly. A hardcoded `machine.RTC().datetime(...)` line was also removed:
it left a wrong-but-plausible clock whenever NTP failed, which is worse
than an obviously-wrong one.

#### 0.5b Clock handling: a regression this fix caused, and the proper repair

Removing the hardcoded `machine.RTC().datetime(...)` line was correct in intent
but wrong as executed, and it broke the board on the next flash: every message
was **REJECTED (stale_timestamp)**.

The measured cause: the board's clock sat **+19,784s** ahead of the gateway --
exactly **5h30m**, the IST offset. This deployment has no NTP route (an isolated
laptop hotspot; see `config.REPLAY_WINDOW_SECONDS`' own comment), so
`ntptime.settime()` always fails and the RTC holds whatever last set it. Thonny's
ESP32 backend runs with `local_rtc: True`, so it writes **local** time, not UTC,
while the firmware adds the 2000-to-1970 epoch gap assuming UTC. The deleted line
had been silently overwriting Thonny's local-time sync with an explicit UTC
value.

The repair is **not** a restored hardcoded date -- that genuinely was rotting,
pinned to one instant and drifting a day further out every day, failing with a
plausible-looking wrong time rather than an obvious one. Instead
`firmware/main.py` defines `RTC_LOCAL_UTC_OFFSET_SECONDS` and applies it **only
when NTP fails**: `sync_time()` now returns whether it succeeded, so a real NTP
sync gives a true UTC clock and a zero offset, while a failure means the RTC
holds local time and the offset converts it. An offset does not rot the way a
fixed date does, and enabling internet sharing on the hotspot bypasses it
automatically.

Verified against the exact observed failure: `19784.5 - 19800 = -15.5s` residual,
well inside the 600s window. Confirmed live after re-flashing -- clock delta
**+2.3s to +21.3s**, and **46 consecutive accepted rows (45 ALLOW, 1 ALERT)**
with zero `stale_timestamp` rejections.

#### 0.5c Did the frequency fix actually change real telemetry?

Comparing at-rest readings (`rms < 1.1`) before and after the re-flash:

| At-rest `dominant_freq` | Pre-fix (buggy `_sin`) | Post-fix (`math.sin`) |
|---|---|---|
| lowest bin, 3.125 Hz | 35.1% | **64.7%** |
| above 12.5 Hz | **17.4%** | **5.9%** |
| tail extends to | 50.0 Hz | 15.6 Hz |

(n=316 pre, n=34 post.) The spurious high-frequency tail largely disappears and
the distribution concentrates where a board at rest should sit, consistent with
the 19% wrong-bin rate measured offline. Stated honestly: **34 post-fix samples
is a small sample** and this comparison is directional corroboration, not proof
on its own -- the conclusive evidence remains the offline check, where the fixed
firmware reproduces `feature_engineering.dominant_frequency()` exactly across
300 windows (0 mismatches) while the old code missed 57.

### 0.6 Verified outcome, on live hardware

| Check | Before | After |
|---|---|---|
| Real board at rest | `process 0.18` → **BLOCK** | `process 0.85–0.88` → **ALLOW** |
| Board shaken (`rms > 1.2`) | — | **19/19 → ALERT, zero ALLOW** |
| Clean held-out normals, false positives at threshold | — | **0.0%** (n=84, fused median 0.888) |
| RL average reward (held-out) | 0.379 (static) | **0.515** |
| RL macro-F1 | 0.287 (static) | **0.550** |
| `security_concern` F1 | 0.000 | **0.997** |
| RL training reward | 3063 | **10094** |

Detection quality was preserved rather than traded away: `anomalous_shock`
recall **1.000**, `coordinated` **1.000** (GNN) and **0.974** (fused).

The live decision trace shows clean shake → `ALERT` → recovery-tail →
`ALLOW` cycles. The tail is the LSTM-AE's 8-sample rolling window flushing
the shaken samples, which is correct temporal behaviour rather than a false
positive.

### 0.7 Why the held-out ablation table barely moved

`evaluate_ablation.py` thresholds at **0.5**, while the calibration defect
only bites at the live `PROCESS_THRESHOLD` of **0.6**. That evaluation was
structurally blind to the defect, which is precisely why this shipped
looking healthy. Worth knowing before citing §2's aggregate accuracy as
evidence of correctness — the live-hardware and false-positive numbers in
§0.6 are the ones that actually exercise the deployed threshold.

### 0.8 Dashboard was serving stale renders

Not a scoring defect, but user-visible. The dashboard polls seven `/api/*`
endpoints every 2s; one full refresh cost **~1.99s of serial server time**
on a single-threaded `HTTPServer` once the audit log reached about 14k rows
(`/api/chain` alone re-verifies the entire hash chain — 0.66s, and growing
with every logged decision). At roughly 100% saturation, refreshes
overlapped, queued, and endpoints began returning **empty** responses, so
the page kept its last good render. That is what "the dashboard shows
static values" actually was.

Fixed with `ThreadingHTTPServer`, short-TTL caches on the three
audit-scanning endpoints, and tiered client polling.

| | Before | After |
|---|---|---|
| Full refresh cycle | 1990 ms | **~690 ms** |
| `/api/chain` | 0.66 s | **0.004 s** |

### 0.9 Level-2 explainability: why it still misses its target

The overall flip rate is **39%** (78/200) against a ≥70% target, split
**100% (GNN, 78/78)** and **0% (LSTM-AE, 0/122)**. There is no longer an
Isolation-Forest-dominant case, because after §0.1 the IF signal reports
"normal" correctly instead of sitting permanently near 0.58 and so stops
dominating SHAP on flagged windows.

The LSTM-AE 0% is now measured and mechanistically explained rather than
merely reported. A flagged window reconstructs with error ~46–62 (z = 20–27
above the normal baseline); recovering to a 0.5 score requires that error
to fall to **≤ 4.28**. An impulsive shock moves `rms`, `peak`,
`crest_factor` and `kurtosis` together — they are all functions of the same
spike — so the best possible single-channel repair only brings error from
~55.7 to ~33.7, an order of magnitude short.

Substituting a real normal *trajectory* for the channel, instead of its
flat training mean, was implemented and measured: it changed nothing
material (33.63 against 33.70 median, better in only 9/40 windows), so the
change was **reverted** rather than kept as complexity that buys nothing.
That experiment locates the limit in the single-channel restriction itself
rather than in the fill value. The **attribution** remains sound and useful
throughout: `kurtosis` is named in 110/122 of these cases, the physically
correct answer for an impulsive spike.

The flip test is a fair pass/fail for a point model — see the GNN's 100% —
but for a sequence model over correlated channels it asks the model to undo
an anomaly through a channel that carries only part of it.

## 0.10 Acquisition Chain Rebuild and First Labelled Hardware Evaluation

This round fixed the sensor acquisition chain end to end and produced the
project's first evaluation against **real hardware with trustworthy labels**.
Five defects, each of which only became visible once the previous one was fixed.

### 0.10.1 Three acquisition defects, in the order they surfaced

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | `sample_window()` had no delay: ~1231 Hz actual against a declared 100 Hz | 26 ms measured for 32 samples; a true 100 Hz window needs 320 ms | Deadline-scheduled pacing |
| 2 | Pacing moved Nyquist 615 Hz → 50 Hz, **below** the sensor's 260 Hz default bandwidth | `dominant_freq` collapsed onto 28–50 Hz, pinned to the top of the band | Enable the MPU6050 DLPF |
| 3 | DLPF at 44 Hz left only 6 Hz of margin under a 50 Hz Nyquist | 38% of samples still in the top 3 bins, 2× uniform | Raise the rate instead of narrowing the filter |

The ordering is the lesson. At ~1231 Hz, Nyquist was 615 Hz — comfortably above
the sensor's 260 Hz passband — so **there was no aliasing to observe**. Fixing
the sample rate is what *created* it. Rate, anti-alias filter and window size are
one decision, and treating them as three produced two successive regressions.

Final configuration — **500 Hz sampling, DLPF 184 Hz, 32-sample window**:

| | rate | Nyquist | filter | margin | window | usable BW |
|---|---|---|---|---|---|---|
| original | ~1231 Hz (declared 100) | 615 | none | — | 26 ms | axis 12.3× wrong |
| after fix 1 | 100 Hz | 50 | none | −210 | 320 ms | aliased |
| after fix 2 | 100 Hz | 50 | 44 Hz | 6 | 320 ms | marginal |
| **final** | **500 Hz** | **250** | **184 Hz** | **66** | **64 ms** | **184 Hz** |

500 Hz beats narrowing the filter on every axis: 11× the margin, 4× the usable
bandwidth, and a *shorter* window. The 100 Hz target was never a requirement —
it originated in a comment describing a sampling loop that did not exist.

Verified on the board: cycle time 2209 ms (predicted 2173), and the resting
spectrum now decays monotonically with frequency — 46% at 31.25 Hz, 23% at
15.625 Hz, **0% in the top 15% of the band**. That is the physically expected
signature for a board at rest, and it is the first time this project has had one.

### 0.10.2 Labels recorded at injection time

The four earlier hardware sessions were labelled by a fixed timetable, and the
labels did not match the physics — `at_rest_1` held a higher maximum rms
(3.416 g) than `moderate_shake` (1.050 g). `collect_hardware_session.py
--labelled` replaces the timetable: the operator marks the start and stop of
each action, only samples strictly inside a marked interval carry the label, and
**anything outside is discarded rather than guessed at**.

The first labelled run failed outright — 0 intervals marked, all 146 records
discarded — because the per-message console output buried the interactive
prompts. That is a UI defect with a data consequence, and it is worth recording
as such: a capture tool that talks over its own instructions cannot be driven.
Fixed by collapsing telemetry to one rewriting status line during a labelled
run, boxing each event prompt, and offering a **retry** on a too-short interval
instead of silently dropping it.

**114 records were recovered from that failed run's transcript**, which retained
both the readings and their position relative to each event prompt. Labels were
assigned by event block, leading handling transients trimmed (4 samples), and
at-rest windows containing a physical disturbance excluded (5 samples, peak
above 0.15 g against a resting median of 0.017 g). Provenance is recorded
honestly as `label_source: "transcript_reconstruction"` — not `operator_mark`.

The labels hold up against the physics, which the old sessions never did:

| phase | n | rms median | peak median | peak range |
|---|---|---|---|---|
| at_rest | 44 | 1.041 | 0.017 | 0.011 – 0.097 |
| gentle_tap | 16 | 1.034 | 0.380 | 0.020 – 3.108 |
| tilt_rotate | 24 | 1.034 | 0.524 | 0.012 – 2.491 |
| moderate_shake | 14 | 1.654 | 1.587 | 0.309 – 2.965 |
| sharp_impact | 16 | 2.372 | 0.909 | 0.150 – 2.263 |

`at_rest` medians agree across all **four separate occurrences** (1.0400,
1.0425, 1.0405, 1.0425) — the consistency check the timed sessions failed.
`moderate_shake` and `sharp_impact` have **zero** overlap with rest;
`gentle_tap` and `tilt_rotate` overlap by 3 samples each, which is expected
because intermittent actions have genuinely quiet moments between them.

### 0.10.3 Two simulator defects the real data exposed

The 500 Hz chain made the synthetic/real mismatch measurable for the first time.

**Spectrum.** The simulator's baseline was `random.gauss(1.0, 0.006)` — white
noise, whose dominant DFT bin is roughly uniform across the band. A real resting
board is low-frequency weighted. Measured: synthetic `dominant_freq` median
**140.6 Hz** against the real **78.1 Hz**, and the Isolation Forest scored
synthetic normals **0.900** while scoring the **real resting board 0.000** —
even with the real samples inside its own training set, because 44 real rows
against 3967 synthetic ones read as an isolated cluster. The baseline is now a
low-frequency drift term over a smaller white floor, with the drift frequency
drawn per window so the spread matches, and the resting DC drawn from a range
rather than pinned to exactly 1.0 g.

**Temporal continuity.** Every synthetic window was drawn independently, giving
the sequence ~zero temporal structure (lag-1 autocorrelation: rms 0.09, peak
−0.02) where a real board carries its state forward (rms 0.263, peak 0.161).
This can only reach one signal — the LSTM-AE is the sole scorer that models a
*sequence* — and that is exactly where it appeared. The state is now
mean-reverting between windows (autocorrelation 0.32 against the real 0.26); a
free random walk was tried first and rejected, being both unanchored (the mean
drifted and clamped) and far too persistent (0.89).

**Stated plainly: the temporal fix did NOT resolve the residual false
positives.** It moved the fused median from 0.869 to 0.881 and left the rate
unchanged at 6/16. It is kept because the simulator is supposed to stand in for
the real board and now matches it on a property it previously got wrong, not
because it fixed the symptom it was aimed at.

### 0.10.4 A stale constant, caught by the real data

`dominant_freq`'s expected range was still `(0.0, 50.0)` — set for the old
axis — while Nyquist had moved to 250 Hz. It marked **35 of 114** genuine
resting readings "out of range" purely as an artefact. The bound is now
**derived** from `FEATURE_SAMPLE_RATE_HZ / 2` rather than written as a literal,
so it can never drift from the acquisition chain again.

### 0.10.5 Result: real-hardware evaluation across three labelled sessions

> **Superseded by 0.10.10.** The figures in this section were computed with the
> permissive warm-up rule (drop `LSTM_SEQ_LEN-1`), which was later shown to leave
> each block's own settling disturbance inside its first scored windows. Under the
> corrected rule, and with the fourth (fault) session included, the headline was
> **1/29 (3.4%) false positives, 103/103 detection** — itself since withdrawn:
> under session-level splitting the leakage-free figure is **5/12 (41.7%) false
> positives, 30/30 detection** (§0.12.1). The numbers below are kept
> as recorded rather than rewritten.


Three operator-marked sessions now exist (313 records), not one. Sessions 2 and
3 were captured live with `label_source: operator_mark`; session 1 remains the
`transcript_reconstruction` recovered from the failed run. `scripts/evaluate_real_hardware.py`,
201 scored readings (window reset per `(session, phase)`, warm-up dropped):

| phase | n | rule | iso | lstm | gnn | fused | flagged |
|---|---|---|---|---|---|---|---|
| at_rest | 65 | 0.900 | 0.979 | 0.900 | 0.667 | **0.908** | 9% |
| gentle_tap | 30 | 0.900 | 0.000 | 0.000 | 0.021 | 0.000 | **100%** |
| moderate_shake | 33 | 0.900 | 0.000 | 0.000 | 0.021 | 0.000 | **100%** |
| sharp_impact | 31 | 0.900 | 0.000 | 0.000 | 0.021 | 0.000 | **100%** |
| tilt_rotate | 42 | 0.900 | 0.000 | 0.000 | 0.021 | 0.000 | **100%** |

- **Detection on real physical disturbance: 100% (136/136).**
- **False positives, split by label provenance — these are not averaged:**

| provenance | false positives | detection |
|---|---|---|
| `operator_mark` (sessions 2+3) | **0/49 (0.0%)** | 94/94 (100%) |
| `transcript_reconstruction` (session 1) | 6/16 (37.5%) | 42/42 (100%) |

The 37.5% figure previously reported as the headline was **largely measuring
label contamination, not model failure**, and the two clean sessions are what
established that. Resting `peak` distributions:

| session | provenance | n | median | p90 | max |
|---|---|---|---|---|---|
| 1 | reconstruction | 44 | 0.0170 | 0.0382 | 0.0970 |
| 2 | operator_mark | 59 | 0.0155 | 0.0223 | 0.0349 |
| 3 | operator_mark | 18 | 0.0159 | 0.0219 | 0.0341 |

The **medians agree** across all three — same board, same resting physics — while
session 1's tail runs ~3x fatter. Its windows were inferred from console
positions with no marks and no margin trimming, and the original transcript
carries readings such as `peak = 1.909 g` inside the "Event 1/8 at_rest" region.
Sessions 2 and 3 had real marks with `MARK_MARGIN_S` trimmed from each end and
never exceeded 4.8 sigma. Environment cannot be fully excluded as an alternative
explanation, but label provenance is the difference that can be pointed at, and
it is the one the operator-mark design exists to remove.

### 0.10.6 The window-warm-up hypothesis, tested and refuted

Section 0.10.5 previously carried a hypothesis: that short per-phase blocks deny
the autoencoder the steady run it stabilises over. Sessions 2 and 3 were
captured specifically to test it (120 s resting blocks against the old ~22 s,
~51 scoreable windows against ~4). **It is false.**

Pooling every resting window from all three sessions:

| worst input in window | n | lstm < 0.6 | | window # in block | n | lstm < 0.6 |
|---|---|---|---|---|---|---|
| 0–3 sigma | 43 | 0/43 | | 1–5 | 23 | 8/23 |
| 3–5 sigma | 7 | 0/7 | | 5–10 | 18 | 2/18 |
| 5–8 sigma | 4 | 3/4 | | 10–20 | 20 | 0/20 |
| 15+ sigma | 7 | 7/7 | | | | |

The position column looks like the predicted warm-up effect. It is a confound:
**control for sigma and it disappears — 0/50 windows below 5 sigma fail at every
block position, and 10/11 at or above 5 sigma fail.** Session 1's high-sigma
samples simply happened to land early in its short blocks.

The real mechanism is a hard cliff. `_error_to_score` is
`clip(0.9 - 0.25 * max(z, 0))`, so any window whose reconstruction error exceeds
z = 3.6 pins to exactly 0.000 — which is why the live signal is bimodal (0.000
or ~0.87, nothing between) rather than continuous. Under clean labels a resting
board never reaches the input sigma that triggers it, so **LSTM-AE false
positives on operator-marked resting data are 0/49**: a latent fragility, one
desk bump away, not an active failure.

### 0.10.7 Resting DC is not stable across sessions (ADR-18)

The most consequential finding of this round, and it invalidated a fix that had
already been made and measured.

Recentring the simulator's `REST_DC_CENTRE` from 1.035 to 1.053 — the median of
121 operator-marked resting samples — moved real-hardware false positives from
2/49 to **0/49** and lifted the resting `iso` median from 0.724 to 0.973. Both
remaining failures before that fix were Isolation-Forest-driven with the LSTM
healthy on the same samples (`iso` 0.061/0.000 against `lstm` 0.840/0.823), one
missing threshold by 0.002.

Then a live re-check of a genuinely resting board read **rms 1.011 g**, which
under the freshly-centred model sits at **-4.0 sigma**. Measured resting rms
medians on the *same board*:

| session 1 | sessions 2/3 | live re-check |
|---|---|---|
| 1.041 g | 1.056 g | 1.011 g |

A 0.045 g spread — **4.5x the within-session std of 0.009 g**. Accelerometer
bias and resting orientation both move it; `|a|` at rest is ~1 g by physics but
not the *same* ~1 g twice.

**Centring on the latest measurement optimises for the last session captured.**
The fix is a normal region wide enough to contain every session the board will
actually have: centre on the midpoint of the observed range (1.036) and widen
the stationary spread from 0.010 to 0.020 (`REST_DC_WALK` 0.010 to 0.019,
`REST_DC_MIN/MAX` 0.99/1.07 to 0.975/1.10). All three observed resting states
then sit within ±1.3 sigma.

Verified on both sides, because widening a normal region is exactly the change
that can quietly destroy detection:

| | before widening | after widening |
|---|---|---|
| real hardware FP (`operator_mark`) | 0/49 | **0/49** |
| real hardware detection | 94/94 | **94/94** |
| the live 1.011 g resting readings, `iso` | 0.000 | **0.343 – 0.696** |
| the same session's disturbed readings, `iso` | 0.000 | **0.000** |
| synthetic ablation, GNN accuracy | 0.907 | **0.915** |
| synthetic `anomalous_shock` recall | 1.000 | **1.000** |
| synthetic `coordinated` recall (fused) | 0.974 | **0.974** |
| **live board at rest, decision** | **ALERT** (wrong) | **ALLOW (17/17)** |
| **live board shaken, decision** | ALERT | **ALERT (16/16)** |

Detection has enormous headroom to pay for this: a disturbed board reconstructs
at 7,000–62,000 sigma of baseline error, so doubling the resting tolerance is
invisible there. *Do not re-tune `REST_DC_CENTRE` onto a single session's median.*

**Verified live on hardware, not in replay.** Read from the gateway's own
hash-chained audit log, 33 consecutively scored messages plus the watchdog row:

```
   t+ decision    rule    iso   lstm    gnn     proc    sec
    0 ALLOW      0.900  0.140  0.900  0.712  0.74914  0.909
   ...  17 resting messages, all ALLOW  ...
   35 ALLOW      0.900  0.188  0.829  0.714  0.66972  0.909
   38 ALERT      0.900  0.000  0.000  0.021  0.00001  0.909   <- board picked up and shaken
   ...  16 disturbed messages, all ALERT  ...
   73 ALERT      0.900  0.000  0.000  0.021  0.00001  0.909
   94 SILENT        --     --     --     --       --  0.701   <- silence watchdog
```

- **Detection 16/16 with no marginal calls** -- `iso`, `lstm` and `gnn` collapse
  together and `proc` reads 0.00001. Widening the resting region (ADR-18) cost
  nothing measurable here.
- **The transition takes one message**: t+35 `ALLOW` 0.670 -> t+38 `ALERT`
  0.00001.
- **Security Trust held 0.895-0.909 for the entire disturbance.** A violently
  shaken board moved the Process axis and left the Security axis alone -- the
  two-score separation demonstrated on real hardware rather than on synthetic
  injections. It falls to 0.701 only on the `SILENT` row, which is the silence
  penalty behaving correctly.
- The silence watchdog fired live, 21 s after the last message, when shaking the
  board knocked it off the network.

One resting message (t+27) dipped to `proc` 0.474 -- `iso` 0.000 while `lstm`
held 0.780 -- without changing the decision. Resting is therefore **0/17 at the
decision level and 1/17 at the score level**, and both are reported: quoting only
the decision figure would hide a real dip, and the Isolation Forest is where the
remaining fragility sits.

**A methodological note on how these were scored.** The LSTM-AE's rolling
window is reset at each `(session, phase)` boundary and the first
`LSTM_SEQ_LEN-1` records of each block are dropped. Keying on phase alone left
no reset at the seam between two capture files — every session both starts and
ends with `at_rest`, so the last resting block of one capture and the first of
the next, hours apart, were joined into windows that never existed. Without the
reset at all, a continuous window scored the LSTM **0.000 even on at_rest**,
while the same samples fed as their own sequence reconstruct at error 0.725
(z = 0.0, a 0.9 score) — measuring transitions, not the model. That transition
behaviour is real and matters live (it is the ALERT recovery tail), but it
answers a different question than "given the board is in state X, does the
pipeline score X correctly".

Finally, what this does **not** measure: no attack was performed, so this is
physical anomaly discrimination, not attack detection. Security Trust is
untouched throughout — which is the two-score separation behaving exactly as
designed.

### 0.10.8 The two open flags, worked

Both flags raised at the end of the previous round were investigated. One
produced a real finding; the other produced a fix that was measured and thrown
away. Both outcomes are recorded.

**Flag 1 -- the Isolation Forest is the weakest signal.** It swings from 0.000 to
1.000 across physically near-identical resting samples (28/121 below 0.6), and it
produced the one live resting dip (`proc` 0.474 with `lstm` healthy at 0.780).
Three hypotheses were tested and **two were wrong**:

| hypothesis | test | result |
|---|---|---|
| one feature drives it | Spearman rho of `iso` vs each feature | **wrong** -- all abs(rho) <= 0.19 |
| estimator variance | sweep `n_estimators` 100-1000, `max_samples` 256-4088 | **wrong** -- IQR stays ~0.37 throughout |
| `contamination=0.1` misplaces the threshold | sweep 0.1 -> 0.005 and `auto` | **real but not fixable this way** |

The contamination sweep is worth keeping because it shows a genuine trade-off
rather than a defect. The forest trains on **pure normal examples**, so
`contamination=0.1` does tell it to declare 10% of clean training data anomalous.
But lowering it compresses the whole score range upward:

| contamination | real resting below 0.6 | real resting min | real disturbed MISSED | held-out anomalous median |
|---|---|---|---|---|
| 0.1 (deployed) | 28/121 | 0.000 | **8/192** | **0.307** |
| 0.02 | 13/121 | 0.099 | 13/192 | 0.591 |
| 0.005 | 8/121 | 0.338 | 15/192 | 0.683 |

Fewer resting dips, more missed anomalies. `0.1` is the best of these for
detection, so it stays -- now with the measurement written down rather than as an
unexamined sklearn default.

**A fix that was tried, measured and reverted.** The resting dips do cluster by
frequency: the 0-30 Hz bucket scores `iso` median 0.666 (7/17 below threshold)
against 0.974 for the well-covered 30-80 Hz bucket, and the simulator
under-produces low-frequency resting windows (19% below 40 Hz against the real
27%). Refitting the drift parameters to match (`REST_DRIFT_HZ_MIN/CENTRE`
15/52 -> 10/40, distribution-match error 1.91 -> 0.74) and retraining the full
chain **made the system worse**: real-hardware false positives went
**0/49 -> 3/49** while resting `iso` barely moved (28 -> 25 below 0.6). Reverted.
Better marginal calibration of the noisiest axis is not the same as a better
decision, and only the fused number distinguishes them.

**Flag 2 -- Level-2 explainability at 36%.** The single-channel number stands and
is unchanged. What was added is the measurement that explains it, on 136 real
operator-labelled disturbance windows:

| channels repaired | recovered to >= 0.5 | median reconstruction error after |
|---|---|---|
| none (baseline) | 0/136 | 26825.17 |
| best 1 of 5 | 0/136 | 7156.90 |
| best 2 of 5 | 1/136 | 311.89 |
| **best 3 of 5** | **132/136 (97%)** | **0.31** |
| best 4 of 5 | 136/136 | 0.03 |

A flip requires error <= 2.76. Single-channel repair achieves a 3.7x reduction
where ~9700x is needed; **three-channel repair clears it, and the minimal set is
`{peak, rms, crest_factor}` in 132/132 cases.** Those three are all amplitude
functions of the same spike -- `crest_factor` is literally `peak/rms` -- so no
one of them can carry the repair alone. The anomaly has **rank ~3 in channel
space, and a rank-1 instrument cannot undo it.** `gnn_score` passes the same test
at 100% precisely because its anomaly IS single-source: a neighbour's evidence.

So the 36% is measuring channel correlation and only incidentally explainability.
Both numbers are now printed by `evaluate_explainability_level2.py`, the
single-channel one first and still against its 70% target, because it is the
literature-comparable figure and swapping it for one the signal passes is exactly
what this project does not do.

One correction this produced: the script previously claimed the anomaly moves
"rms, peak, crest_factor and kurtosis TOGETHER". The measurement says three
channels suffice and **kurtosis is not among them** -- although kurtosis remains
the channel most often *attributed*. Attribution names the most diagnostic
channel; repair needs the sufficient set. They are different questions, and the
text now says so.

### 0.10.9 Three improvements: two applied, one refuted by its own measurement

**1. The ablation suite now evaluates at the deployed threshold.**
`evaluate_ablation.py` defaulted to 0.5 while `gateway.py` decides at
`PROCESS_THRESHOLD` = 0.6. That gap was already proven dangerous once: an
Isolation Forest calibration defect that made a signal structurally incapable of
scoring above 0.621 -- so a healthy board was BLOCKed live -- moved this script's
headline accuracy by **0.003**. The suite was blind to a bug that made the system
unusable. Now aligned; the numbers moved slightly and are now about the system
that actually ships:

| signal | accuracy @0.5 (old) | accuracy @0.6 (deployed) |
|---|---|---|
| isolation_forest_score | 0.931 | 0.916 |
| gnn_score | 0.915 | 0.909 |
| fused_score | 0.719 | 0.717 |

**2. Leave-one-out ablation: what the 121 real rows actually buy.**
The real hardware data is only **3.0%** of the 4,088 esp32 normal training
examples, which invites the obvious question. Answered by withholding it
(`merge_real_hardware_data.py --synthetic-only`) and retraining the entire chain:

| training normals | operator-marked FP | detection |
|---|---|---|
| 15,250 synthetic only | **13/49 (26.5%)** | 94/94 (100%) |
| + 121 real at-rest rows (3.0%) | **0/49 (0.0%)** | 94/94 (100%) |

*Both arms of this ablation were measured under the permissive warm-up rule on
the three-session corpus, before 0.10.10 corrected it. The comparison is
internally valid -- same rule, same data, only the training set differs -- but the
absolute figures are not comparable to the 1/29 headline. The conclusion is
unaffected: withholding the real rows costs 13 false positives that adding them
removes.*


**3% of the training data removes 100% of the false positives, at zero cost to
detection.** The per-phase resting flag rate goes 31% -> 9%, and resting `lstm`
median 0.859 -> 0.900. Synthetic data alone cannot place the normal region where
the real board actually sits, however well calibrated -- which is the empirical
case for hardware-in-the-loop training rather than simulation alone.

**3. Graded severity -- proposed, measured, and NOT implemented.**
The stated limitation was that `_error_to_score` pins to exactly 0.000 at
z >= 3.6, so a gentle tap and a violent shake are indistinguishable; the proposed
fix was a compressive map to make severity rankable. **The measurement refuted
the premise.** Reconstruction-error z by phase on real hardware:

| phase | n | median z | max peak (g) | fraction of samples quiet (<= 0.035 g) |
|---|---|---|---|---|
| at_rest | 65 | -0.1 | 0.097 | 0.96 |
| gentle_tap | 30 | 18745 | 3.108 | 0.05 |
| tilt_rotate | 42 | 22155 | 2.491 | 0.02 |
| moderate_shake | 33 | 23092 | 2.965 | 0.00 |
| sharp_impact | 31 | **10392** | 2.968 | **0.29** |

`sharp_impact` -- the most violent event, max peak 2.968 g -- has the **lowest**
median z of the four disturbance classes. It is not ordered by severity at all.
The reason is duty cycle: sharp impacts are brief impulses with pauses, so 29% of
their samples are physically indistinguishable from rest, against 0% for
continuous shaking. **Reconstruction error over an 8-message window measures how
much of the window is disturbed, not how violently.**

Two consequences, both kept rather than papered over:

- A compressive map would produce a number that *looks* like severity and is not.
  On this data there is nothing to grade anyway -- resting sits at z ~ 0 and every
  real disturbance at z = 4,200-48,000, with the middle entirely empty.
- The limitation is therefore **restated, not fixed**: the pipeline cannot rank
  severity, and the obstacle is the window-averaged error itself, not the score
  mapping. Ranking severity would need a peak-aware statistic alongside the
  sequence model. Recorded as future work.

The Spearman rank correlation of z against an ordinal severity label is +0.614
(p = 3e-22), but that is carried almost entirely by rest-versus-everything, not by
ordering within the disturbance classes -- an example of a healthy-looking
aggregate statistic concealing the thing it was computed to test.

### 0.10.10 A sustained-fault session, and a warm-up rule that contradicted itself

A fourth session (`--fault`, 116 records, all `operator_mark`, 116/116 joined to
live gateway decisions) captured a **sustained fault with no hand contact**: a
phone on continuous vibrate sharing the board's desk surface, at two coupling
distances. Every previously captured event was violent hand manipulation, so this
is the first event class that is continuous, operator-untouched, and transmitted
through the mounting surface rather than applied to the board.

**It also exposed a defect in the evaluation itself, which matters more.**

`score_all` dropped `LSTM_SEQ_LEN-1` records per block -- enough to FILL the
rolling window, not enough to keep the block's own settling disturbance out of
it. A window scored at index 7 still *contains* messages 0..7, and those are the
seconds right after the operator pressed ENTER and stepped away. Measured on this
session's baseline block:

```
  i      rms     peak   <- the block's own warm-up, still inside every scored window
  4   1.0287   0.0768      2.5x the block median of 0.0195
  6   1.0229   0.0436
  7   1.0274   0.0246   <- first SCORED window: contains i=0..7, including both spikes
```

All 6 scored windows in that block failed, with `lstm` 0.000 while `iso` read
0.265-1.000 on the same samples -- the one-bad-sample-poisons-eight-windows
mechanism, now seen at a block boundary. This directly contradicted the reset's
own stated rationale ("every window straddling a boundary contains two different
physical states"). **Corrected to drop `2*LSTM_SEQ_LEN-1`**, so no scored window
contains any of the block's first `LSTM_SEQ_LEN` messages, and
`MIN_EVENT_SECONDS` raised from 20 s to 36 s to match.

Both conventions, on the full four-session corpus, because the correction
improves the headline and that deserves scrutiny rather than a silent swap:

| warm-up drop | operator-marked resting windows | false positives | detection |
|---|---|---|---|
| `LSTM_SEQ_LEN-1` = 7 (fills window) | 83 | **10/83 (12.0%)** | 140/140 (100%) |
| `2*LSTM_SEQ_LEN-1` = 15 (excludes block start) | 29 | **1/29 (3.4%)** | 92/92 (100%) |

The cost is real: resting sample size falls from 83 to 29, and the reconstructed
session now contributes **zero** resting windows because its blocks are too short
to survive the stricter rule -- which incidentally removes the tail-contaminated
data automatically rather than by judgement.

**The previously reported 0/49 was under the permissive rule on three quieter
sessions.** The fault session was genuinely noisier -- a phone on the desk and an
operator moving around it -- and adding it takes the permissive figure to 12.0%.
The honest deployed headline is now **5/12 (41.7%) false positives, 30/30
detection** on the untouched test session under session-level splitting (§0.12.1).
The 1/29 in the table above was measured before session-level splitting was
enforced -- the test session's own at-rest rows were still in the training set --
and is superseded.

#### Detection on the sustained fault

| phase | n | rule | iso | lstm | gnn | fused | flagged |
|---|---|---|---|---|---|---|---|
| at_rest | 29 | 0.900 | 0.923 | 0.900 | 0.671 | 0.904 | 3% |
| fault_weak | 22 | 0.900 | 0.000 | 0.000 | 0.021 | 0.000 | **100%** |
| fault_strong | 8 | 0.900 | 0.000 | 0.000 | 0.021 | 0.000 | **100%** |

30/30 detected. The pipeline generalises to a fault class it was never trained
on and never previously tested against.

#### What this did NOT establish, and why

The experiment was designed to find the **detection floor** -- a fault whose
amplitude never leaves the resting band, which is the realistic profile of a worn
bearing and the case the LSTM-AE exists for. It did not reach it. Phone vibrate
couples strongly through a desk and is *intermittent* rather than continuous:

- `fault_weak` peak median **0.2557 g** against a target band of 0.05-0.20 g and
  a resting p99 of 0.0411 g -- 6x the intended ceiling.
- 11% of its samples do sit at or below the resting ceiling, but **0 of 30 scored
  windows have all 8 messages there**. Every window catches at least one buzz.

So detection on this class is real, but it is still being carried by amplitude
that exceeds rest, not by sequence structure invisible to a threshold. **The
detection floor remains unmeasured.** Reaching it needs a continuous
low-amplitude source (a small DC motor with an unbalanced mass, or a much weaker
coupling), not a phone.

### 0.10.11 Seed sensitivity: which numbers are properties and which are draws

Every training script pins its RNG, which makes a rebuild reproducible — and
reproducible is not the same as stable. A single seed reports one draw from the
distribution of models the pipeline can produce, with no indication of spread.
`TRAINING_SEED` (env `ZTCPS_SEED`, default 0) now threads through all five
models, and the full chain was retrained across seeds 0–4:

| metric | per-seed | mean ± sd |
|---|---|---|
| `isolation_forest_score` acc | 0.916 0.914 0.916 0.918 0.916 | **0.916 ± 0.001** |
| `lstm_ae_score` acc | 0.753 ×5 | **0.753 ± 0.000** |
| `transformer_score` acc | 0.694 ×5 | **0.694 ± 0.000** |
| `gnn_score` acc | 0.909 0.886 0.912 0.900 0.914 | **0.904 ± 0.011** |
| `fused_score` acc | 0.717 0.711 0.716 0.715 0.717 | **0.715 ± 0.002** |
| RL macro-F1 | 0.538 0.534 0.538 0.535 0.538 | **0.537 ± 0.002** |
| static macro-F1 | 0.279 0.277 0.278 0.278 0.279 | **0.278 ± 0.001** |
| real-hardware FP | 1 2 1 1 1 (of 29) | **1.2/29 ≈ 4.1%**, sd 0.45 |
| real-hardware detection | 103/103 on every seed | **100%, sd 0** |

Three things worth reading off this:

**The bandit beats the *deployed* static table across seeds.** 0.537 ± 0.002
against 0.278 ± 0.001 — separated by ~130 standard deviations, a property of the
method, not of seed 0. But that is only the *deployed* table: a static table with
thresholds selected on validation scores 0.588 and beats the bandit (§0.13.6), so
this is not a superiority claim. The policy is a contextual bandit, not
reinforcement learning (C6).

**`lstm_ae` and `transformer` reaching ±0.000 was checked, not assumed.**
Identical accuracy to three decimals across five seeds looks like broken seed
plumbing. It is not: training seeds 11 and 12 produce weights differing by up to
1.40 per tensor (9.05 summed). The models land on the same held-out accuracy from
genuinely different initialisations — their decision behaviour is fixed by the
data, not the init.

**The GNN is the seed-sensitive component**, at ±0.011 with a 0.028 range —
roughly ten times the fused model's spread. It is also the heaviest-weighted
fusion input (coefficient 9.922), so it is simultaneously the most influential
and the least stable signal. Worth stating plainly rather than hiding inside a
mean.

Sampling uncertainty is now reported alongside, via Wilson score intervals
(chosen over the normal approximation, which misbehaves at small *n* near 0 or 1):

```
FALSE POSITIVE RATE:  3.4% (1/29)     95% CI [0.6%, 17.2%]
DETECTION RATE:     100.0% (103/103)  95% CI [96.4%, 100.0%]
```

**The false-positive rate cannot be quoted to one decimal.** Anything from 0.6%
to 17% is consistent with 29 samples. Detection is genuinely tight because
n = 103. Quoting "3.4%" bare would be the first thing a reviewer attacks.

### 0.10.12 The GNN's non-monotonicity, finally justified rather than noted

Carried for several rounds as "directionally correct, but unexplained rather than
justified". Measured properly it is worse than recorded — **25 violations across a
51-point neighbour sweep**, not one — and confined to the saturated regions:

```
neighbours 0.00 -> 0.20   gnn 0.158 -> 0.119   both "bad"    ripple 0.04
neighbours 0.20 -> 0.70   gnn 0.119 -> 0.667   transition    correct, steep
neighbours 0.70 -> 1.00   gnn 0.667 -> 0.637   both "good"   ripple 0.03
```

That mattered more than it looked, because the GNN carries the largest fusion
coefficient (9.922 against rule 0.071). So the decision-level question was asked
directly:

```
gnn monotonicity violations (51 points):  25
fused monotonicity violations:            25
  worst fused decrease:                   0.00295
decision changes along the sweep:          1  (ALERT -> ALLOW at nb=0.26, correct direction)
NON-MONOTONIC DECISIONS:                 none
```

**The ripple is three thousandths of fused score against a threshold margin of
0.3+, and never once makes a verdict stricter as a neighbourhood improves.** So
this is ripple inside regions where the answer is already saturated, not a defect.
It is not being "fixed": the only available fix is fabricating neighbour training
data to cover input combinations the live system does not produce, which adds
risk for no decision-level benefit. What is added instead is a test pinning the
property that matters — improving a neighbourhood must never make the decision
stricter — so if a future change makes the ripple decision-relevant, it fails.

### 0.10.13 Transformer into fusion: measured, and rejected

`stealthy_forged_values` is the attack class this design acknowledges it cannot
see, and the ablation table contains an apparent answer: `transformer_score`
recalls it at **0.970** where the deployed fusion manages 0.606 — yet the
transformer is not a fusion input. A signal that is poor overall but excellent on
the one class the others miss is the textbook case for a weighted meta-learner.

Tested offline first, before touching production code, both meta-learners fit
identically on the same replay:

| | accuracy | FP on normal | anomalous_shock | coordinated | **stealthy** |
|---|---|---|---|---|---|
| 4 inputs (deployed) | 0.686 | 0.310 | 1.000 | 0.983 | 0.636 |
| 5 inputs (+transformer) | 0.645 | 0.373 | 1.000 | 0.974 | **0.970** |

+33 points of stealthy recall for +6.3 points of false positives on synthetic
normals. Arguably a good trade — which is why the acceptance criterion, set
*before* running it, required real hardware to hold. It does not:

| model | resting FP | detection |
|---|---|---|
| 4 inputs (deployed) | **5/29** | **92/92** |
| 5 inputs (+transformer) | **15/29** | **87/92** |

Ten extra false positives *and* five lost detections. **Rejected.** Production
code was reverted before any of it shipped.

**The explanation first given for this rejection was wrong, and the correction is
the more useful result.** It was attributed to the Transformer keying on an
artefact of how `stealthy_forged_values` is generated. The actual cause was
simpler and worse: **the Transformer artifact was stale**, trained the previous
day against data superseded by ADR-18 and the merged real-hardware rows, because
the documented training order omitted it. Its 0.970 stealthy recall was not a
capability at all — retrained on current data it reads **0.606**, identical to the
LSTM-AE.

Re-run with a freshly trained Transformer, the fusion experiment comes out
differently and far less interestingly:

| | accuracy | FP on normal | shock | coordinated | stealthy |
|---|---|---|---|---|---|
| 4 inputs (deployed) | 0.686 | 0.310 | 1.000 | 0.983 | 0.636 |
| 5 inputs (+fresh transformer) | 0.687 | 0.310 | 1.000 | 0.983 | 0.667 |

and on real hardware the two are **identical** — FP 5/29 both, detection 92/92
both. The meta-learner splits weight roughly evenly between the LSTM-AE (0.365)
and the Transformer (0.341) because they correlate at 0.998; the fifth input is
redundant, not harmful. **Still rejected**, now for the right reason: +0.031
synthetic stealthy recall and zero real-hardware movement does not justify a
fifth model on the deployment path.

The lesson worth keeping is about evaluation hygiene, not architecture: a
comparison is only valid if every arm was trained on the same data, and nothing
in the pipeline enforced that until a test was written for it.

*(Caveat on the 5/29 above: the offline harness refits both meta-learners with a
simplified pipeline, so its 4-input arm reads 5/29 where the deployed model reads
1/29. The comparison is internally valid — both arms identical but for the fifth
feature — but the absolute figures are not the deployed ones.)*

### 0.10.14 The detection floor, measured — by accident

`0.10.10` closed with the detection floor unmeasured: every detected event,
including the engineered phone-vibrate fault, exceeded the resting band by a wide
margin, so detection was carried by amplitude rather than by structure a threshold
would miss. Reaching the floor was listed as future work needing a continuous
low-amplitude source.

**One appeared unplanned.** During a routine live check the board was found
reading `peak` 0.032–0.050 g — roughly 2.3x the resting median of 0.0172 — with
`proc = 0.00001` and a continuous ALERT. The board was not stuck (28 distinct
readings) and `rule` stayed 0.900, so the values were in range. What identified it
was the spectrum:

| | distinct `dominant_freq` bins | top bin share |
|---|---|---|
| operator-marked at rest (n=132) | 15 | 21% (15.625 Hz) |
| live, this condition (n=40) | 2 | **96% (93.75 Hz)** |

At rest the argmax DFT bin scatters, because a resting board has no dominant
excitation and the bin is essentially noise. **A single bin holding 96% is a
periodic mechanical source**, not noise — some continuously running machine
coupled into the bench.

#### The controlled measurement

The question that matters is whether the pipeline is detecting this through
amplitude, which a simple threshold would also catch, or through structure it
would not. Windows were built from **only those samples at or below the
operator-marked resting ceiling** (p99 = 0.0411 g) — so a per-sample amplitude
threshold set at that ceiling classifies every window below as "rest":

| window source | n | `lstm` median | flagged | `iso` median | flagged |
|---|---|---|---|---|---|
| live periodic source | 14 | **0.0000** | **14/14** | 0.0000 | 14/14 |
| operator-marked at rest | 14 | **0.9000** | **0/14** | 0.9545 | 1/14 |

**Perfect separation on windows an amplitude threshold cannot separate at all.**
This is the first evidence in this project that the sequence model earns its place
— that the pipeline detects a sustained disturbance whose per-sample amplitude
never leaves the resting band.

#### The caveat, stated because it bounds the claim

Amplitude is **not fully controlled**, only capped. Within the below-ceiling band
the live windows still carry roughly double the amplitude of the resting ones
(max-peak-in-window median 0.0403 against 0.0190). So the correct claim is
**detection below the amplitude decision boundary**, not detection with amplitude
held equal. Separating those two would need a source tuned to sit at the resting
*median* rather than near its p99 — still future work, but a much narrower gap
than before.

The unplanned nature is itself worth recording. A source that could not be
engineered on demand with a phone appeared from ordinary bench conditions, which
is a reminder that the deployment environment supplies disturbances the test plan
does not.

### 0.10.15 Per-device predictions: the real board versus the simulated ones

The ablation table blends all three devices, which hides the only comparison that
matters for a hardware-in-the-loop claim. Split by device on the held-out
synthetic set:

| device | kind | n | rule | iso | lstm | gnn | fused | accuracy |
|---|---|---|---|---|---|---|---|---|
| esp32-vib-001 | **real**, feature_vector | 1050 | 0.900 | 0.884 | 0.000 | 0.730 | 0.042 | **0.401** |
| sensor-002 | simulated, scalar | 1000 | 0.900 | 0.900 | 0.900 | 0.734 | 0.952 | 0.854 |
| actuator-001 | simulated, scalar | 933 | 0.900 | 0.900 | 0.900 | 0.733 | 0.952 | 0.848 |

Read naively this says the models are catastrophically worse on the real device.
**They are not.** Splitting the normal class by window residue — a message that is
itself normal but sits within `LSTM_SEQ_LEN` of a recent injected attack, so its
window straddles the attack:

| device | all normals | residue-contaminated | **clean normals** |
|---|---|---|---|
| esp32-vib-001 | 580/794 (73.0%) | 580/754 (76.9%) | **0/40 (0.0%)** |
| sensor-002 | 92/907 (10.1%) | 49/527 (9.3%) | 43/380 (11.3%) |
| actuator-001 | 88/840 (10.5%) | 46/481 (9.6%) | 42/359 (11.7%) |

**Every one of the real device's 580 false positives is window residue, and on
genuinely clean normals it is 0/40 — perfect.** The simulated devices show no
residue effect at all (9.3% against 11.3%), because they have no sequence model:
they mirror `rule_score` into the IF/LSTM slots, and a scalar has no window to
contaminate.

The cause is dataset design, not modelling. **95.0% of esp32's "normal" test rows
are residue-contaminated**, because `generate_test_data.py` injects
`anomalous_shock`/`coordinated`/`stealthy`/`high_rate` every 12-30 ticks against
an 8-message window. Most nominally-normal esp32 messages are therefore
recovery-period messages, not steady-state baseline.

Three consequences worth stating plainly:

1. **The blended fused accuracy of 0.717 is dominated by this artefact**, not by
   model quality. It is a property of the attack-injection schedule.
2. **The real-hardware result is the trustworthy one**: its then-measured 1/29
   false positives on operator-labelled data agreed with the 0/40 clean-normal
   figure and disagreed with 73% only because the synthetic set has almost no
   clean rows. (That 1/29 is pre-split and withdrawn — the leakage-free rate is
   5/12, §0.12.1; the methodological point, real hardware over synthetic-blended,
   stands.)
3. **Any future dataset extension must keep injection density low relative to the
   sequence window**, or the pool of genuinely clean normals collapses and
   per-signal evaluation measures the schedule instead of the model.

### 0.10.16 Governance: the seventh falsifier, previously excluded in error

The falsifiability self-test injected each tenet's own falsifier and reported
**6/6**, with Tenet 5 excluded on the stated grounds that "its falsifier is
missing data, not a bad row, which cannot be constructed".

That reasoning was wrong. T5 asks whether every device in `DEVICE_REGISTRY`
produced at least one audit row, so its falsifier is **a row set covering fewer
devices than the registry** — an ordinary row list, not an absence. Injected as
one row for one registered device, the check correctly returns FAIL.

**Now 7/7 tenets validated and 7/7 falsifiers demonstrably rejected.** The case is
built from the live registry rather than a hardcoded device id, so it cannot drift
out of step with it.

Worth recording as more than a bookkeeping fix. The claim this project makes about
governance is that its compliance checks are falsifiable rather than asserted, and
a check excluded from the falsifiability test on a mistaken premise is exactly the
kind of quiet gap that claim exists to prevent. Finding one is the self-test
working.

### 0.10.17 Live adversarial testing — and the vulnerability it found

Until now every attack in this project was synthetic, injected into an evaluation
harness. `scripts/attack_live_gateway.py` fires genuinely hostile MQTT messages at
a running gateway and reads its own audit log back to confirm each was rejected.
Threat model: the attacker holds the broker credentials (insider / stolen laptop)
but **not** the per-device HMAC secret — the exact threat this design targets.

Five attacks over a live transport, against the running board:

| attack | threat | outcome |
|---|---|---|
| forged_signature | broker creds, guessed HMAC key | rejected (`hmac_mismatch`) |
| tampered_payload | signature over different values | rejected (`hmac_mismatch`) |
| unregistered_device | an id never registered | rejected (`unknown_device_id`) |
| stale_forged | old timestamp + forged key | rejected |
| captured_replay | a real past envelope re-sent | rejected (boot/seq anti-replay) |

**5/5 rejected at Module 1/2, before any model ran.** But the first run exposed a
real vulnerability, which is the point of doing this live.

#### The vulnerability: a rejected message could mutate device state

The gateway's order was `HMAC → check_boot_replay → check_timestamp_freshness`.
`check_boot_replay` **advanced** the stored `last_seen_boot_id` as a side effect of
its check. A validly-signed message with an inflated `boot_id` (999) therefore:

1. passed HMAC,
2. advanced the stored boot baseline to 999 inside `check_boot_replay`,
3. was **then** rejected by the freshness gate.

A rejected message had mutated the device's anti-replay state — directly violating
the invariant *"a rejected message must never touch the claimed device's state"*.
The consequence was live and total: the real board, on `boot_id 34`, now read as
`replay_of_superseded_boot_session` (34 < 999) on every subsequent message and was
**locked out entirely**. This is a denial-of-service against a legitimate device.

This specific exploit needed the HMAC secret (to pass step 1), so it is not
remotely triggerable — but the same ordering fires on any validly-signed message
that later fails freshness, which a real device hits during the exact clock-skew
condition this project has seen before. The invariant existed precisely to prevent
this class, and it had a hole.

#### The fix

`check_boot_replay` is now a **pure predicate** — it reads state and returns a
verdict, mutating nothing. A new `commit_boot_seq()` advances the baseline, and the
gateway calls it **only after every authentication gate has passed**. State can no
longer advance on a message that is ultimately rejected, regardless of check order,
and the commit is monotonic so an accepted-but-late message cannot lower it.

Verified live: after the fix, the same attack class was re-run against the board
and the board **stayed at ALLOW (14/20 decisions)** through it — the stale/replay
messages left its state untouched. Guarded by `TestBootReplayStateIsolation`
(3 tests): the predicate does not mutate, a rejected stale high-`boot_id` message
does not lock out the real device, and the commit is monotonic.

This is the strongest single argument in the project for hardware-in-the-loop
adversarial testing: the bug was invisible to every synthetic evaluation because
those never sent a validly-signed-but-stale message with an inflated boot id at a
live gateway holding real per-device state.

### 0.10.18 GNN seed stability, severity ranking, and the FP interval — three items reframed by measurement

All three were on the "solvable" list. Measured, two are non-problems dressed as
problems and one is blocked by the bench environment. Recording the reframing
rather than forcing a fix is the honest outcome.

**GNN seed variance is in the wrong metric.** The concern was accuracy sd 0.011
across seeds. A learning-rate sweep (3 seeds each, GNN retrained standalone):

| lr | accuracy sd | coordinated recall |
|---|---|---|
| 0.05 (deployed) | 0.0138 | 0.974 / 1.0 / 0.974 (sd 0.015) |
| 0.01 | 0.0213 (worse) | 1.0 / 1.0 / 1.0 (sd 0.000) |

Lowering the lr does **not** cut accuracy variance — it raises it, from
under-convergence at 150 epochs. What it does is make **coordinated recall
perfectly stable**. That is the tell: the GNN exists for `coordinated` detection,
and that metric is stable at deployed settings (never below 0.974) and rock-solid
at lower lr. The accuracy variance lives in classes the GNN does not own, and
0.10.12 already proved it changes **zero** decisions across a neighbour sweep. The
fix is to report the metric the GNN is responsible for, not to tune away a
decision-irrelevant wobble — which would trade real convergence for a cosmetic
number. The lr/epochs are now env-overridable (`ZTCPS_GNN_LR`) for reproducibility;
the deployed default is unchanged.

**Severity ranking is ill-posed, not unbuilt.** 0.10.9 attributed the LSTM-AE's
inability to rank severity to window-averaging. Tested directly: a peak-aware
statistic (max per-timestep error instead of mean) does **not** fix it — Spearman
rho against ordinal intensity *drops*, 0.781 → 0.723, and `sharp_impact` still
scores lowest. The raw peak feature within disturbance classes reaches only
rho 0.245. The reason is that "severity" is not a scalar here: `sharp_impact` is
high-rms / low-peak (impulsive), `moderate_shake` is high-peak / high-rms
(sustained). They differ on **orthogonal physical axes**, so no single statistic —
reconstruction error, peak, or rms — can totally order them. The system already
exposes all five features per message, which *is* the severity information,
per-axis; collapsing it to one rank is the ill-posed step. Recorded as a
correction to 0.10.9, whose window-averaging explanation was incomplete.

**The false-positive interval cannot be tightened under current bench conditions.**
n=29 gives [0.6%, 17.2%]; halving the half-width needs ~120 clean resting samples.
A 5-minute capture collected 133 — but they are **not reference rest**: the
`dominant_freq` concentrates 51% in one bin (31.25 Hz) against 21% scattered for
operator-marked rest, i.e. a variable low-frequency source is coupled into the
bench (the same class of disturbance as 0.10.14, milder). Scored, they flag 21.2%
— which is **not a false-positive rate**, for exactly the reason the 93.75 Hz
capture was not: the board is not at reference rest, so the pipeline is correctly
flagging an ambient disturbance. The capture was discarded rather than reported as
FP. Tightening the interval requires a genuinely quiet bench, which this
environment does not currently provide — itself a reminder that a false-positive
rate is only defined relative to a controlled resting condition (ADR-18).

### 0.10.19 Level-2 explainability: the rank-aware metric, promoted to a reported result

0.10.14 established that the standard single-channel Level-2 test is a rank-1
instrument on a rank-3 anomaly, and buried the rank-aware recovery figure as a
diagnostic. It is now a **first-class reported metric**, printed beside the
single-channel number by `evaluate_explainability_level2.py`:

| Level-2 metric | result | vs 70% target |
|---|---|---|
| single-channel ([21]'s method, kept for comparability) | 80/219 = **37%** | does not meet |
| **rank-aware (proposed): repair the minimal sufficient channel set** | 178/182 = **98%** | **meets** |

The minimal sufficient set is rank 3, `{peak, rms, crest_factor}` in 173/178 of
recovering windows — the three amplitude functions of one spike.

**Why the 98% is honest and not goalpost-moving.** The rank-aware test matches the
instrument's rank to the anomaly's rank; it does not simply relax the pass
condition. The proof is the control: applied to `gnn_score`, whose anomaly is
genuinely single-source, the rank-aware test still passes at **rank 1** (the GNN
already scores 100% single-channel). A test that passed everything by loosening
would have promoted the GNN to rank 3 too; it does not. The 37% single-channel
number is retained and printed alongside — this project does not delete a metric
it misses.

**What is NOT claimed.** This does not make the single-channel test pass. Doing
that would require a feature representation in which the physical anomaly is
genuinely rank-1 (a single learned severity channel), which is a
model-architecture change and remains future work. The contribution here is
methodological: the single-channel perturbation test is the wrong instrument for
correlated multi-channel physical anomalies, and the minimal-repair-set / anomaly-
rank metric is the corrected one.

### 0.10.20 Future work, with the measurement that motivates each

Not a wish list. Each item below is here because a specific measurement in this
document reaches a limit and names what would move it.

**1. Measure the detection floor with amplitude fully controlled** (partly closed by 0.10.14, which measured it below the amplitude *threshold* but not at equal amplitude).
Every detected event in this corpus -- including the sustained phone-vibrate
fault -- exceeds the resting band by a wide margin. `fault_weak` came out at peak
median **0.2557 g** against a resting p99 of **0.0411 g**, and of 30 scored fault
windows **zero** have all 8 messages at or below the resting ceiling. So the
136/136 and 103/103 detection figures are carried by amplitude, not by sequence
structure a plain threshold would miss, and the LSTM-AE's stated purpose --
gradual drift near the noise floor, the profile of a worn bearing -- is still
untested. Phone vibrate cannot probe it: it couples strongly through a desk and is
intermittent rather than continuous, so every window catches a buzz. What is
needed is a **small DC motor with an unbalanced mass**, run at a supply voltage
low enough to sit in the 0.05-0.20 g band, for long enough to capture gradual
onset. Until that exists, the honest claim is "detects disturbance well above the
noise floor", not "detects faults".

**2. A second MPU6050, to establish whether the resting-DC spread is a sensor
property or this unit's quirk.** ADR-18 sizes the resting normal region on the
cross-session spread of one board (1.011 / 1.041 / 1.056 g, a 0.045 g range
against a 0.009 g within-session std) and attributes it to accelerometer bias and
resting orientation. That attribution is an assumption. One 90-second resting
capture from a second board resolves it, and the two outcomes fork the design: if
its resting DC lands in the same band, the calibration generalises and
`REST_DC_CENTRE` is a sensor-class constant; if it does not, the constant is
per-device and the whole calibration approach needs rethinking. **A single unit
cannot distinguish these**, and no amount of additional data from it will.

**3. Bound the audit chain's full-scan cost before it matters.** Measured at
78,546 rows: the incremental tail verification runs in **46.7 ms** on every
request, while the full O(rows) scan takes **2,539 ms** (32.3 microseconds/row)
and is cached for 300 s -- a 0.85% duty cycle, and the scan interval IS the
naive-tamper detection latency, so it is deliberate rather than wasteful. The
projection is the useful number: **~32 s at 1M rows**, at which point a 300 s
cache no longer hides it and a checkpoint-anchored partial scan becomes worth
building. Recorded as a budget with a trigger rather than a vague concern.

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

---

## 0.12 Leakage-free re-measurement (2026-09-03)

A session-level train/validation/test split was introduced
(`data/splits/session_split.json`, reviewer concern E). Before it,
`merge_real_hardware_data.py` folded the at-rest rows of **every** labelled
session into training while `evaluate_real_hardware.py` scored the disturbance
rows of **those same sessions** — one physical acquisition session feeding both
sides. The fusion meta-learner was likewise trained on the session its own base
models were fitted on (concern H).

**Three previously published claims do not survive the correction.** They are
withdrawn here rather than quietly restated. Reproduce everything below with the
commands in `docs/EXPERIMENTAL_PROTOCOL.md` §7.

### 0.12.1 Real hardware — the withdrawn 0/49

**OBSERVATION.** On the untouched TEST session (`20260902_221217`):

| | detection | false positives on a resting board |
|---|---|---|
| TEST split | **30/30 (100%)**, 95% CI [88.6%, 100%] | **5/12 (41.7%)**, 95% CI [19.3%, 68.0%] |
| VALIDATION split (`20260902_173108`) | 14/14 (100%) | 0/3, 95% CI [0%, 56.2%] |

Per phase (TEST, median scores): `at_rest` fused 0.701 (42% flagged),
`fault_weak` 0.000 (100% flagged), `fault_strong` 0.000 (100% flagged).

**INTERPRETATION.** Detection is unaffected by the correction — real physical
disturbance, including the sustained low-amplitude `fault_weak` condition, is
detected in every scored window. The false-positive rate is not: it moves from
**0/49 to 5/12**.

**ALTERNATIVE EXPLANATION.** Is the test session simply unusual? Its resting rms
median (1.0485) sits *inside* the training range (1.0410–1.0571), so it is not
out-of-distribution by centre. But its spread is wider (sd 0.0134, min 1.0172)
than either training session (sd 0.0025 and 0.0106). The learned normal region
appears narrower than the true cross-session spread — which is what ADR-18
warned about, reached from the other direction.

**LIMITATION.** Twelve resting windows. The interval runs 19–68%. This does not
establish that the false-positive rate *is* 42%; it establishes that 0/49 was an
artefact of the leak and that the true rate is not near zero.

**IMPLICATION.** The mounting/orientation experiment (concern D) becomes the
highest-value outstanding capture — it is what would tell us whether the normal
region is session-specific.

**The 0/49 figure is withdrawn.** So is the `13/49 vs 0/49` synthetic-only
ablation magnitude (§0.10.9): its direction stands, its baseline was the leaky
number, and it needs re-measurement.

### 0.12.2 Fusion meta-learner — the leak was visible in the coefficients

Trained on the session its base models were fitted on, the meta-learner learned

```
[rule, iso, lstm, gnn] = [?, +4.41, -0.46, +5.51]
```

The **LSTM-AE coefficient was negative** — the wrong sign for a signal whose
whole purpose is to fall on anomalies. Retrained on a held-out validation
session (SIM_SESSION_VAL_001, seed 4242) with the base models frozen:

```
[rule, iso, lstm, gnn] = [-0.003, +2.972, +5.966, +8.332]
```

All three ML signals now carry the correct sign, and the LSTM-AE is the
second-strongest contributor rather than a negative one.

### 0.12.3 GNN vs same-information baselines — claim withdrawn

`results/gnn_baselines/metrics.json`. Five comparators, byte-identical inputs
(per-node `[rule, iso, lstm]` for all ten nodes), fit on TRAIN, all selection on
VALIDATION, TEST read once.

**Task 1 — per-node anomaly detection (test):**

| model | precision | recall | F1 | FPR | event recall |
|---|---|---|---|---|---|
| B2 concat MLP | 0.9727 | 0.9980 | **0.9852** | 0.0045 | 1.000 |
| B0 single-device | 0.9583 | 0.9967 | 0.9771 | 0.0070 | 1.000 |
| **GNN** | 0.8000 | 0.8800 | **0.8381** | 0.0355 | **0.733** |
| B1 concat logistic | 0.6560 | 0.9573 | 0.7785 | 0.0810 | 1.000 |
| B3 coordinated rule | 0.4629 | 0.9187 | 0.6156 | 0.1719 | 1.000 |

**Task 2 — network coordination pattern, 4-way (accuracy):**

| model | validation | test |
|---|---|---|
| B2 concat MLP | 0.6475 | **0.6567** |
| B1 concat logistic | 0.6592 | 0.6433 |
| **GNN node embeddings** | 0.5792 | **0.6058** |
| B0 anomalous-node count | 0.4592 | 0.4142 |

Self-loop weight swept `{1, 2, 3, 5}` on validation; 5.0 selected (validation
F1 0.8254). **The GNN loses at its own best swept setting**, and is the only comparator whose EVENT recall falls below 1.000 (0.733).

**INTERPRETATION.** Cross-device information clearly helps: on task 2, which a
single-node view cannot answer even in principle, accuracy rises 0.4142 → 0.6567.
Graph structure does not — the GNN is beaten by a concatenated MLP on both tasks.

**ALTERNATIVE EXPLANATION.** On task 1, B0 (one node) nearly matches B2 (ten
nodes), because a node's own label is largely determined by its own sub-scores.
That is a property of the *target*, not evidence about graphs — which is why
task 2 was declared alongside it rather than after seeing task 1.

**LIMITATION.** One topology, one graph size, one GCN architecture, one testbed,
and `esp32-vib-002` contributed no rows. This shows the GNN did not help *here*,
not that graph learning cannot help.

**IMPLICATION.** Any claim of GNN necessity or superiority is withdrawn. The
defensible claim concerns cross-device information.

### 0.12.4 Policy comparison — the adaptive policy loses to a tuned static table

> **SUPERSEDED BY §0.13.6.** Re-measured on the consistent chain; P2, P3 and P5
> all moved. The conclusion (the bandit loses to a tuned static table) survives.

`results/policy_comparison/metrics.json`, untouched test split, 2933 decisions.

| policy | 2933 | 0.0083 | 0.0127 | 0.0060 | 0.0146 | 0.0223 | 0.5192 |
|---|---|---|---|---|---|
| P2 static optimised | **0.8936** | **0.5879** | 0.8995 | 0.0048 | 0.0014 |
| P3 decision tree | 0.4722 | 0.5834 | 0.6183 | **0.5272** | 0.0000 |
| P5 adaptive bandit | 0.7300 | 0.5329 | 0.7896 | 0.0000 | 0.0007 |
| P4 multiclass LR | 0.6502 | 0.4355 | 0.7284 | 0.0755 | 0.0483 |
| P1 static (deployed) | 0.6577 | 0.2744 | 0.7029 | 0.0000 | 0.0000 |

**P5 is a contextual bandit with sample-average action-value estimation, not
reinforcement learning** — no discount factor, no next-state bootstrapping,
reward a fixed function of (state, action).

**Rare combined class (BLOCK), support 33 — reported, not hidden:**

| policy | tp | fp | fn | precision | recall |
|---|---|---|---|---|---|
| P1 static | 0 | 0 | 33 | 0.0000 | 0.0000 |
| P2 static optimised | 0 | 14 | 33 | 0.0000 | 0.0000 |
| P3 decision tree | 33 | **1529** | 0 | **0.0211** | 1.0000 |
| P4 multiclass LR | 1 | 219 | 32 | 0.0045 | 0.0303 |
| P5 adaptive bandit | 0 | 0 | 33 | 0.0000 | 0.0000 |

Recall on the combined class is effectively zero for every policy that keeps a
usable false-block rate. The one policy achieving full recall does so at 2.1%
precision and a 52.7% false-block burden — not deployable. The class is
`stealthy_forged_values`, whose `(s_sec, s_proc)` state is by construction
indistinguishable from normal, so no policy over those two inputs can separate
it. A known architectural blind spot, not a tuning failure.

### 0.12.5 Common vs separate thresholds (concern J)

Both selected on VALIDATION by macro-F1, reported on TEST:

| configuration | test macro-F1 |
|---|---|
| A — common `θ = 0.7` | 0.4876 |
| B — separate `θ_sec = 0.7`, `θ_proc = 0.05` | 0.5879 |

Separate scored higher, **but the selected `θ_proc = 0.05` would make the
deployed system nearly blind to process anomalies.** It maximises macro-F1 on a
class mix dominated by normal and security-concern examples. The selection
objective is not the deployment objective; deployed thresholds remain 0.6/0.6
and the gap is reported as the finding rather than adopted.

### 0.12.6 Per-stage latency (concern P)

`results/latency/latency.json`. Warm, `time.perf_counter_ns`, host in
`docs/ENVIRONMENT.md`. Cold start 1268 ms, reported separately, never amortised.

| stage | n | mean | sd | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| authentication | 2933 | 0.0192 | 0.0137 | 0.0142 | 0.0354 | 0.0546 | 0.3471 |
| security_trust | 2933 | 0.0109 | 0.0993 | 0.0067 | 0.0167 | 0.0266 | 5.3754 |
| rule_detector | 2933 | 0.0038 | 0.0050 | 0.0030 | 0.0073 | 0.0101 | 0.2446 |
| isolation_forest | 1000 | 5.1201 | 2.3546 | 4.1168 | 8.9815 | 10.6815 | 20.7264 |
| lstm_ae | 1000 | 1.3823 | 2.7923 | 1.1738 | 2.4624 | 3.1695 | 85.8246 |
| gnn | 2933 | 0.9104 | 3.3473 | 0.8608 | 1.5682 | 1.9930 | 180.9994 |
| fusion | 2933 | 0.2723 | 0.1531 | 0.2018 | 0.5383 | 0.7931 | 1.5842 |
| policy | 2933 | 0.0083 | 0.0127 | 0.0060 | 0.0146 | 0.0223 | 0.5192 |
| explainability | 2933 | 0.0157 | 0.0109 | 0.0108 | 0.0277 | 0.0547 | 0.1683 |
| audit_logging | 2933 | 0.0254 | 0.0186 | 0.0182 | 0.0498 | 0.0754 | 0.3398 |
| **total_pipeline** | 2933 | **3.4891** | 5.3890 | **1.4540** | 11.3009 | **13.8442** | **201.3477** |

All values in milliseconds. **Max is ~138× the median** — a mean alone
materially misrepresents this pipeline, which is exactly why percentiles are now
reported. `audit_logging` is the hash-chain link computation only; the SQLite
write is I/O-bound and excluded (stated, not omitted).

10-node hybrid network tick: mean 70.67 ms, p50 67.65, p95 100.34, p99 112.95,
max 129.15 → ~14.1 network ticks/s ≈ **141 messages/s sustained**. Ten nodes is not
evidence of industrial scalability and is not presented as such.

### 0.12.7 What changed in the data

Enforcing the split removed 18 real at-rest rows from training (121 → 103) and
withheld two entire sessions from evaluation that had previously contributed to
both sides.

---

## 0.13 Chain-consistency re-measurement and the cross-device architecture study (2026-09-04)

Every number in §2, §2.1 and §0.12.4 was produced while the training chain was
**internally inconsistent**: Isolation Forest and LSTM-AE artifacts were written
at 23:32, while the Transformer (22:32), GNN (22:32), fusion meta-learner (22:33)
and RL Q-table (22:36) all pre-dated them by an hour. Steps 3–6 therefore
described base models that no longer existed.

`test_no_model_artifact_is_older_than_its_training_data` passed throughout,
because it only compares each artifact against `training_session.json` (22:28).
It has no notion of the chain being a dependency order.
`test_chain_artifacts_are_not_older_than_the_artifacts_they_replay` now closes
that gap, and its falsifier was injected and verified: advancing the Isolation
Forest mtime by two hours fails it with
`lstm_ae is older than isolation_forest`.

Steps 3–6 were retrained in order. Everything below is measured on the
consistent chain.

### 0.13.1 The deployed GNN does not survive a clean retrain

| `gnn_score` (ablation, 3050 held-out messages) | stale chain | consistent chain |
|---|---|---|
| accuracy | 0.901 | **0.281** |
| precision | 0.985 | 0.984 |
| recall | 0.906 | **0.223** |
| F1 | 0.944 | **0.364** |
| `coordinated` recall | 0.974 | 1.000 |
| `stealthy_forged_values` recall | 0.000 | 0.697 |

The per-class recalls rise because the model now flags roughly 78% of legitimate
traffic. `train_gnn.py` weights the suspicious class at 24.4× the normal class
(347,220 normal against 7,260 suspicious node-targets), and on the current data a
fresh fit answers "anomalous" to almost everything. This is the invariant in
CLAUDE.md §4 doing exactly what it says: a number going up is not the model
improving.

**This is a TRAINING result, not an architectural one, and the two must not be
cited together.** The architectural evidence is §0.13.3, where a GCN trained in
the same loop, with the same class weighting and the same epoch count as six
other models, still fails on isolated anomalies.

Fusion coefficients on `[rule, iso, lstm, gnn]`, refitted on the held-out
validation session with the base models frozen:

```
stale chain      [-0.003, +2.972, +5.966, +8.332]
consistent chain [-0.018, +2.979, +4.500, +6.062]
```

The `rule` coefficient is ≈0 in both. The deployed fusion is effectively
`iso + lstm + gnn`, and describing it as a four-signal fusion without that
number beside it overstates what the rule input contributes.

### 0.13.2 Corrected ablation (supersedes §2 and §2.1)

`scripts/evaluate_ablation.py`, 3050 held-out messages, 117 excluded
(`auth_ok=False`, rejected at Module 2 and never scored). 2700 legitimate,
233 suspicious. Deployed threshold 0.6.

| Signal | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| rule_score | 0.921 | 0.921 | 1.000 | 0.959 |
| isolation_forest_score | 0.919 | 0.960 | 0.951 | 0.956 |
| lstm_ae_score | 0.753 | 0.957 | 0.766 | 0.851 |
| transformer_score | 0.754 | 0.957 | 0.768 | 0.852 |
| gnn_score | **0.281** | 0.984 | **0.223** | **0.364** |
| **fused_score** | 0.704 | 0.993 | 0.684 | 0.810 |

Per-event-type recall:

| Signal | anomalous_shock | coordinated | high_rate | stealthy_forged_values |
|---|---|---|---|---|
| rule_score | 0.000 | 0.000 | n/a | 0.000 |
| isolation_forest_score | 1.000 | 0.316 | n/a | 0.212 |
| lstm_ae_score | 1.000 | 0.308 | n/a | 0.606 |
| transformer_score | 1.000 | 0.308 | n/a | 0.606 |
| gnn_score | 1.000 | 1.000 | n/a | 0.697 |
| **fused_score** | 1.000 | 0.983 | n/a | 0.667 |

**`rule_score`'s 0.959 F1 must never be cited as detection performance.** It
scores 0.000 recall on all four attack types; its headline number is entirely the
label mix, because none of the four attacks produce a physically out-of-range
reading. It is the correct free first gate and nothing more.

LSTM-AE vs Transformer on the fair, undiluted comparison (esp32-vib-001 only,
254 rows after excluding window-residue): **identical at 0.945 / 0.878 / 1.000 /
0.935**. §0.10.13's rejection of the Transformer as a fifth fusion input stands.

### 0.13.3 Cross-device architecture benchmark, seven models

`scripts/benchmark_crossdevice_models.py`, `results/crossdevice_benchmark/`.
Ten-node network, 10,800 scoreable test rows (1500 anomalous: 150 isolated,
1350 coordinated) across 15 events. Fit on TRAIN, every threshold and the GCN
self-loop weight selected on VALIDATION, TEST read once. All seven receive the
identical per-node `[rule, iso, lstm]` sub-scores for all ten nodes.

| model | macro-F1 | detection | FPR | event rec | **isolated rec** | coord rec | params | infer ms |
|---|---|---|---|---|---|---|---|---|
| M1 concat MLP | **0.9914** | 0.9980 | 0.0045 | 15/15 | 0.9800 | 1.0000 | 1857 | **0.0591** |
| M2 grad boosting | 0.9906 | 0.9993 | 0.0052 | 15/15 | 0.9933 | 1.0000 | n/a | 1.3069 |
| M5 GATv2 | 0.9896 | 0.9933 | 0.0047 | 15/15 | 0.9400 | 0.9993 | **881** | 1.5086 |
| M6 set transformer | 0.9876 | 0.9973 | 0.0066 | 15/15 | 0.9800 | 0.9993 | 2593 | 1.1235 |
| M7 NP-ST | 0.9872 | 0.9973 | 0.0068 | 15/15 | 0.9800 | 0.9993 | 3746 | 1.8629 |
| M3 deep sets | 0.9799 | 1.0000 | 0.0115 | 15/15 | **1.0000** | 1.0000 | 2097 | 0.7395 |
| M4 GCN | 0.9052 | 0.8800 | 0.0355 | **11/15** | **0.0067** | 0.9770 | 1217 | 0.7637 |

**Six of the seven sit inside 0.011 macro-F1.** On one split with one seed that
is not a ranking, and no architectural claim may rest on it. The accuracy table
is at ceiling and the informative results are the structural probes below.

A second operating point is reported per model: isotonically calibrated on one
half of validation, threshold read off the ROC of the disjoint other half at a
declared 1% false-positive budget. Calibration and threshold selection use
disjoint halves, cut contiguously per scenario, because neighbouring ticks share
LSTM windows and events.

| at FPR ≤ 1% | detection | achieved test FPR | budget held | precision |
|---|---|---|---|---|
| M1 concat MLP | 1.0000 | 0.0097 | **yes** | 0.9434 |
| M6 set transformer | 1.0000 | **0.0209** | **no** | 0.8855 |
| M7 NP-ST | 0.9973 | 0.0075 | yes | 0.9553 |

Isotonic calibration made the Brier score **worse** for M1, M2 and M3
(M1: 0.00310 → 0.00506). It helped only M4 (0.05415 → 0.03043), the model that
is not being adopted. Reported because the calibration step was expected to help
and did not.

### 0.13.4 Neighbourhood-induced anomaly dilution (the primary finding)

One anomalous device among n−1 healthy ones, 400 trials per cell, feature vectors
drawn from real scored test rows rather than synthesised. Recall on the anomalous
node at each model's own validation-selected threshold:

| model | n=2 | n=3 | n=5 | n=10 | n=20 |
|---|---|---|---|---|---|
| M4 GCN | 0.8625 | 0.7550 | 0.1700 | 0.0025 | **0.0000** |
| M5 GATv2 | 0.9950 | 0.9425 | 0.7675 | 0.2225 | **0.2025** |
| M6 set transformer | 0.9650 | 0.9700 | 0.9900 | 1.0000 | 0.9950 |
| M7 NP-ST | 1.0000 | 0.9950 | 0.9975 | 0.9925 | 0.9950 |
| M3 deep sets | 0.9925 | 0.9975 | 1.0000 | 1.0000 | 1.0000 |

**A defect in the first version of this probe, recorded because it changed two
published cells.** The declared 15-edge topology exists only at ten nodes, so the
first run used it at n=10 and a complete graph everywhere else. The n=10 cell was
therefore drawn from a different graph than its neighbours, and GATv2 showed a
non-monotone bump (0.7675 → 0.8775 → 0.2025) that read as a property of device
count and was an artifact of the adjacency changing. With a complete graph at
every n both graph models decay monotonically. The superseded cells were GCN
n=10 = 0.0400 and GATv2 n=10 = 0.8775.

**The confound, once controlled, became the strongest single result.** Holding
the device count fixed at ten and changing only the adjacency:

| model | complete graph (9 neighbours) | declared topology (avg degree 3) |
|---|---|---|
| M4 GCN | 0.0025 | 0.0600 |
| M5 GATv2 | **0.2225** | **0.8725** |
| M6 set transformer | 1.0000 | 0.9925 |
| M3 deep sets | 1.0000 | 0.9975 |

GATv2's isolated recall changes roughly four-fold at a fixed device count when
only the neighbour count changes. The mechanism is therefore
**healthy-neighbour aggregation degree**, not network size. The set models are
unaffected because they never aggregate over a neighbourhood.

The mirror experiment, k of 10 devices anomalous at once, confirms nothing was
traded away:

| model | k=1 | k=2 | k=3 | k=5 | k=10 |
|---|---|---|---|---|---|
| M4 GCN | 0.0400 | 0.6150 | 0.9500 | 1.0000 | 1.0000 |
| M5 GATv2 | 0.8650 | 0.9725 | 0.9900 | 0.9750 | 1.0000 |
| M6 set transformer | 1.0000 | 0.9975 | 0.9975 | 0.9975 | 1.0000 |
| M3 deep sets | 0.9975 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

Devices relabelled, adjacency deliberately NOT permuted with them; max absolute
score difference:

```
M3 deep sets        0.000000    invariant
M6 set transformer  0.000000    invariant
M7 NP-ST            0.000000    invariant
M5 GATv2            0.124339    order-dependent
M4 GCN              0.755786    order-dependent
```

**Stated precisely, because the loose form is wrong:** GCN and GATv2 are
permutation-equivariant when node features and adjacency are permuted together.
What is measured here is that under a FIXED deployment topology indexed to
slots, the verdict depends on which physical device occupies which graph
position. That is a deployment property, not a deficiency of graph learning.

M1 and M2 are absent from every probe: their input is a fixed 10·3+10 vector and
cannot be evaluated at any other device count. That inability is the scaling
result, not a missing row.

**LIMITATION, load-bearing — since addressed, see §0.13.11.** Every model in
this table was trained at n=10 only, so all n ≠ 10 columns are extrapolation for
all seven — which is why M3 reads 0.2555
mean P(anomaly) at n=2, its worst cell. The neighbour-degree comparison above is
the part of this section that holds n fixed and is therefore not subject to it.

### 0.13.5 NP-ST: proposed, measured, not adopted

A Node-Preserving Set Transformer (set attention plus a gated local residual the
context can modulate but not replace) was implemented as the candidate novel
architecture. It is **not adopted**, on its own numbers: 7th of 7 on macro-F1,
tied with the plain Set Transformer at n=20 dilution (0.9950 vs 0.9950), 3746
parameters against 2593, and the highest inference latency in the field.

The reason is visible in M3. Deep Sets already concatenates each node's own
un-aggregated embedding with the pooled context before its head — a protected
local path by another name — and already scores 1.000 isolated recall. The idea
NP-ST was built to contribute was already present in a baseline.

Recorded here rather than dropped silently, per CLAUDE.md §7: a fix that was
built, measured and rejected is worth more than its absence.

### 0.13.6 Policy comparison on the consistent chain (supersedes §0.12.4)

`results/policy_comparison/metrics.json`, untouched test split, 2933 decisions.

| policy | accuracy | macro-F1 | weighted F1 | false-block | false-step-up | ALERT recall |
|---|---|---|---|---|---|---|
| P3 decision tree | 0.7770 | **0.6453** | 0.8398 | **0.1510** | 0.0000 | 0.9850 |
| P2 static optimised | **0.8646** | 0.5614 | **0.8797** | 0.0076 | 0.0014 | **0.5850** |
| P5 adaptive bandit | 0.7238 | 0.5271 | 0.7846 | 0.0000 | 0.0022 | 0.9600 |
| P4 multiclass LR | 0.6679 | 0.4410 | 0.7408 | 0.0669 | 0.0483 | 0.5900 |
| P6 static constrained | 0.6662 | 0.2777 | 0.7088 | 0.0000 | 0.0000 | 0.9900 |
| P1 static (deployed) | 0.6577 | 0.2744 | 0.7029 | 0.0000 | 0.0000 | 0.9900 |

Superseded §0.12.4 values: P2 0.8936/0.5879, P3 0.4722/0.5834 with false-block
0.5272, P5 0.7300/0.5329. P3's false-block rate improved from 0.5272 to 0.1510
and its macro-F1 now leads the table — but 15.1% of legitimate traffic blocked
is still not deployable.

Common vs separate thresholds (concern J): A common θ = 0.7 → test macro-F1
0.4865; B separate (0.7, 0.05) → 0.5614.

### 0.13.7 Deployment-constrained policy selection (P6)

P2 shows what unconstrained selection does: it picks `theta_proc = 0.05`, which
maximises macro-F1 by declaring nearly every reading physically healthy. That is
not a tuning accident — macro-F1 over a class mix dominated by normal and
security examples genuinely is maximised by ignoring the rare physical class.

P6 uses the same grid and the same objective under bounds declared before the
search: ALERT recall ≥ 0.90 (ALERT is the physical-fault action, so its recall
is process-anomaly recall at the policy layer) and false-block rate ≤ 0.01.
130 of 361 grid points were feasible.

| | θ_sec | θ_proc | macro-F1 | ALERT recall | false-block |
|---|---|---|---|---|---|
| P2 unconstrained | 0.7 | **0.05** | 0.5614 | **0.5850** | 0.0076 |
| **P6 constrained** | 0.05 | 0.5 | **0.2777** | **0.9900** | 0.0000 |

Constraints held on test. **P2's entire macro-F1 advantage was purchased by
going blind to physical faults**: enforcing a deployment-valid process recall
drops 0.5614 to 0.2777, barely above the deployed P1's 0.2744. §0.12.5 reported
the gap as a finding about the metric; this quantifies what closing it costs.

The deployed thresholds remain 0.6 / 0.6.

### 0.13.8 What is withdrawn

**The claim that the GNN is an architecturally necessary relational layer is
withdrawn.** §0.12.3 already withdrew GNN superiority against same-information
baselines; §0.13.3 and §0.13.4 go further and identify the mechanism. Under a
controlled comparison the GCN scores 0.0067 isolated recall, and a fixed-n
intervention shows the cause is healthy-neighbour aggregation degree.

What survives is narrower and better supported:

> Cross-device relational information helps. Conventional graph message passing
> is not an appropriate mechanism for it in this setting, because neighbourhood
> aggregation suppresses isolated anomalies as healthy-neighbour degree rises.
> Graph attention substantially reduces but does not eliminate the effect.
> Set-based relational modelling avoids it while preserving coordinated-anomaly
> detection.

### 0.13.10 Two dilution mechanisms, separated by intervention

> Both tables here are **seed 0**. §0.13.14 repeats both probes over ten
> training seeds; the direction of every effect below reproduces, the magnitude
> of the GATv2 one does not, and one wording in this section is corrected there.

§0.13.4 established that isolated-anomaly recall falls as healthy context grows,
but the dilution sweep confounds two variables: as n rises, so does the target's
neighbourhood degree. Two interventions at **fixed n = 10** separate them.

**D. Target degree.** The healthy population 1..9 is complete among itself in
every condition; only the number of those peers node 0 connects to varies.

| model | d=1 | d=2 | d=3 | d=5 | d=9 |
|---|---|---|---|---|---|
| M4 GCN | 0.9100 | 0.8125 | 0.5875 | 0.0675 | **0.0175** |
| M5 GATv2 | 0.1875 | 0.2050 | 0.2125 | 0.2150 | 0.2225 |
| M6 set transformer | 0.9925 | 0.9925 | 0.9925 | 0.9925 | 0.9925 |
| M3 deep sets | 0.9975 | 0.9975 | 0.9975 | 0.9975 | 0.9975 |

**E. Peer density.** Node 0's own degree is held at 3; what varies is how densely
the nine healthy peers are wired to *each other* (36 edges = complete).

| model | 0 edges | 4 | 9 | 18 | 36 |
|---|---|---|---|---|---|
| M4 GCN | 0.3775 | 0.4075 | 0.4200 | 0.3875 | 0.5875 |
| M5 GATv2 | **0.9925** | 0.8950 | 0.6950 | 0.2125 | **0.2125** |
| M6 set transformer | 0.9925 | 0.9925 | 0.9925 | 0.9925 | 0.9925 |
| M3 deep sets | 0.9975 | 0.9975 | 0.9975 | 0.9975 | 0.9975 |

**The two graph models fail for different reasons, and only one of them is the
mechanism originally hypothesised.**

- **GCN — direct dilution.** Driven by the target's own degree (0.9100 → 0.0175),
  essentially unaffected by peer density (0.3775 → 0.5875, non-monotone).
  Fixed averaging over more healthy neighbours erases the node's own evidence.
- **GATv2 — propagated dilution.** Essentially unaffected by the target's own
  degree (0.1875 → 0.2225 across d=1..9), driven instead by peer density
  (0.9925 → 0.2125). Attention successfully protects the node from its own
  neighbourhood; it does not protect it from neighbours that have already
  homogenised one hop away.
- **Set models — neither.** Flat at 0.9925 / 0.9975 in every cell of both
  interventions, because they have no neighbourhood to aggregate over. Their
  rows are flat by construction and are a reference line, not a result.

This resolves the apparent contradiction in §0.13.4, where GATv2 read 0.8725 on
the sparse declared topology and 0.2225 on a complete graph at the same device
count: the declared graph has average degree 3, so its peers are not homogenised,
while a complete graph's are.

**A wrong turn, recorded.** The first version of probe D left nodes 1..9 isolated
(self-loops only) instead of complete among themselves. With nothing else to
attend to, node 0's neighbours absorbed its anomaly and reflected it straight
back, so GATv2 read a flat 0.99 at every degree — while reading 0.2225 on a
complete graph at the same n. The probe was measuring the peers' isolation, not
the target's degree. The contradiction is what exposed it.

**Correct statement of the finding**, replacing "attention delays dilution":

> Graph message passing suppresses isolated anomalies through two separable
> channels. Fixed neighbourhood averaging dilutes a node in proportion to its own
> degree. Learned attention removes that direct channel but not the propagated
> one: the anomaly is still erased when the node's neighbours have themselves
> aggregated a homogeneous healthy population. Set-based relational modelling is
> subject to neither.

### 0.13.11 Mixed-cardinality training (M8)

§0.13.4's stated limitation was that every model was fitted at n=10, making all
other cardinalities extrapolation. M8 is the same Set Transformer architecture
and the same optimiser, learning rate, epoch count and class weighting as M6,
trained with the cardinality cycling over n ∈ {2, 3, 5, 10}.

**The subsets are real.** A size-k network is k of the ten real scored node
streams at a real tick — never a synthesised or duplicated device. n = 10 is
therefore the ceiling here; going above it requires the virtual-device generator,
not a resampling trick that would quietly reuse one physical device as several.

| | macro-F1 | detection | FPR | isolated rec | coord rec | params |
|---|---|---|---|---|---|---|
| M6 (n=10 only) | 0.9876 | 0.9973 | 0.0066 | 0.9800 | 0.9993 | 2593 |
| **M8 (mixed n)** | 0.9761 | 0.9993 | 0.0137 | **1.0000** | 0.9993 | 2593 |

Dilution recall, the measurement mixed-cardinality training was meant to fix:

| model | n=2 | n=3 | n=5 | n=10 | n=20 |
|---|---|---|---|---|---|
| M6 set transformer | 0.9650 | 0.9700 | 0.9900 | 1.0000 | 0.9950 |
| **M8 mixed n** | **1.0000** | **1.0000** | 0.9975 | 0.9975 | **1.0000** |
| M3 deep sets | 0.9925 | 0.9975 | 1.0000 | 1.0000 | 1.0000 |

Mean P(anomaly) is where the effect is clearest, because recall was already near
ceiling: M3's worst cell was **0.2555 at n=2**, and M8 reads **0.9975** there.
M8's curve is the flattest in the study (0.9975 → 0.9490 across n=2..20).

**This retires the extrapolation limitation and confirms it was one.** M3's odd
small-n behaviour was an artifact of being fitted only at n=10, not a property of
Deep Sets. M8 is also exactly permutation-invariant (max |Δ| = 0.000000) and
holds 1.0000 recall across every cell of probes D and E.

The cost is real and reported: **−0.0115 macro-F1 and roughly double the FPR**
(0.0066 → 0.0137) against M6, and M8's 1% alarm budget does not transfer to test
either (achieved 0.0127, cap not held; detection 0.9993, precision 0.9270).
Cardinality robustness is bought, not free.

### 0.13.12 What was NOT done

Stated so the gap is not mistaken for a result.

- **No hardware validation of any of this.** The testbed has two physical devices
  (`esp32-vib-001`, and `esp32-vib-002` which has no capture and contributes
  `PENDING_REAL_HARDWARE_DATA` rows only). Every cross-device number in §0.13.3
  through §0.13.11 comes from the ten-node hybrid network, eight of whose nodes
  are simulated. No claim of physical validation at n = 10 or above is supported.
- **No real-derived virtual device generator.** Training above n = 10 needs
  telemetry synthesised from real-device distributions with per-device bias,
  noise and drift, then replayed through the Isolation Forest and LSTM-AE
  scorers. Not built. M8's ceiling of n = 10 is a consequence.
- **The Set Transformer is not wired into the deployed fusion.** `gnn_score` in
  `fusion_engine.py` comes from `src/gnn_scorer.py` over **three** devices, while
  every model in §0.13.3 is the ten-node network. Substituting it is not a
  drop-in: it needs a three-device variant, then a retrain of fusion and the
  policy layer (chain steps 5-6). Until that runs, the fusion coefficient that
  would show whether set-based relational context adds information the Isolation
  Forest and LSTM-AE do not already carry is unmeasured.
- **Repeated seeds cover the two dilution probes only.** §0.13.14 re-runs
  probes D and E under ten training seeds. Every other number in §0.13.3
  through §0.13.11 is one seed on one split, and all of them are one split. The
  six models inside 0.011 macro-F1 in §0.13.3 are not separated by this
  experiment and are not claimed to be.

### 0.13.13 Reproduction

```
python scripts/train_transformer.py                # steps 3-6, in order
python scripts/train_gnn.py
python scripts/train_fusion_meta_learner.py
python scripts/train_adaptive_pdp.py
python scripts/evaluate_ablation.py                # 0.13.1, 0.13.2
python scripts/benchmark_crossdevice_models.py     # 0.13.3, 0.13.4, 0.13.5
python scripts/benchmark_crossdevice_models.py --selfcheck
python scripts/evaluate_policy_comparison.py       # 0.13.6, 0.13.7
# the benchmark run above also produces 0.13.10 (probes D, E) and 0.13.11 (M8)
python scripts/benchmark_crossdevice_models.py --seeds 10   # 0.13.14, ~6 min
python -m unittest discover -s tests               # 65 tests
```

### 0.13.14 The two mechanisms under ten training seeds

§0.13.10 separated direct from propagated dilution on **one** seed. Both probes
were re-run under ten training seeds, refitting M3/M4/M5/M6 *and each model's
decision threshold* per seed. The GCN self-loop weight is held at the 5.0 it won
on validation in the main run — re-sweeping it per seed would turn a seed study
into a second hyperparameter search. The interval is over training seeds at a
fixed dataset: it answers "does this reproduce on a refit", not "does this hold
on another split".

**D. Target degree**, mean ± 95% CI over ten seeds:

| model | d=1 | d=2 | d=3 | d=5 | d=9 |
|---|---|---|---|---|---|
| M4 GCN | 0.837 ±0.033 | 0.802 ±0.006 | 0.577 ±0.076 | 0.086 ±0.031 | **0.021 ±0.006** |
| M5 GATv2 | 0.726 ±0.195 | 0.716 ±0.202 | 0.716 ±0.205 | 0.686 ±0.197 | 0.660 ±0.201 |
| M6 set transformer | 0.995 ±0.004 | 0.995 ±0.004 | 0.995 ±0.004 | 0.995 ±0.004 | 0.995 ±0.004 |
| M3 deep sets | 0.996 ±0.002 | 0.996 ±0.002 | 0.996 ±0.002 | 0.996 ±0.002 | 0.996 ±0.002 |

**E. Peer density**, same:

| model | 0 edges | 4 | 9 | 18 | 36 |
|---|---|---|---|---|---|
| M4 GCN | 0.387 ±0.060 | 0.442 ±0.069 | 0.430 ±0.090 | 0.406 ±0.111 | 0.577 ±0.076 |
| M5 GATv2 | **0.989 ±0.005** | 0.946 ±0.033 | 0.885 ±0.075 | 0.733 ±0.206 | **0.716 ±0.205** |
| M6 set transformer | 0.995 ±0.004 | 0.995 ±0.004 | 0.995 ±0.004 | 0.995 ±0.004 | 0.995 ±0.004 |
| M3 deep sets | 0.996 ±0.002 | 0.996 ±0.002 | 0.996 ±0.002 | 0.996 ±0.002 | 0.996 ±0.002 |

**The per-level intervals are the wrong statistic for this claim, and reading
them as if they were the claim understates the result.** GATv2's d=1 cell spans
0.19 to 0.91 across the ten seeds — but that spread is a *level* offset, how
detectable a given refit finds an isolated anomaly at all, and it is present
almost identically at every level of both probes. The mechanism claim is not
about the level, it is about the *change* across an intervention. Pairing each
seed against itself cancels the offset.

**Per-seed change between each intervention's extreme levels**, paired,
two-sided 95%, t critical 2.262 at nine degrees of freedom:

| model | intervention | mean Δ | 95% CI | t | seeds down |
|---|---|---|---|---|---|
| M4 GCN | target degree 1→9 | **−0.8160** | [−0.850, −0.782] | −53.90 | 10/10 |
| M4 GCN | peer density 0→36 | **+0.1895** | [+0.140, +0.239] | +8.74 | 0/10 |
| M5 GATv2 | target degree 1→9 | −0.0655 | [−0.265, +0.134] | −0.74 | 4/10 |
| M5 GATv2 | peer density 0→36 | **−0.2733** | [−0.477, −0.069] | −3.03 | 10/10 |
| M6, M3 | either | 0.0000 | — | — | flat by construction |

**Not a double dissociation — the GCN is significantly affected by both
interventions**, negatively by its own degree and *positively* by peer density
(+0.19, t=+8.7). "Each architecture responds to one intervention and not the
other" is false as stated and is not claimed. What the table supports is:

> The two architectures exhibit distinct and directionally opposed topology
> sensitivities.

**The interaction is tested directly, not inferred from the intervals above.**
Two separate intervals, one excluding zero and one including it, do not establish
that two effects differ; that is the difference-of-significance error, and this
study is unusually exposed to it because GATv2's degree interval is wide. Each
quantity below is formed inside a seed before averaging, so the between-seed
level offset cancels in the contrast as well as in the effects:

| contrast | mean | 95% CI | t | seeds down |
|---|---|---|---|---|
| GCN: degree effect − density effect | **−1.0055** | [−1.073, −0.938] | −33.72 | 10/10 |
| GATv2: degree effect − density effect | +0.2078 | [−0.131, +0.546] | +1.39 | 2/10 |
| **interaction**: (GCN − GATv2) of that contrast | **−1.2132** | [−1.583, −0.843] | **−7.42** | 10/10 |

The interaction clears comfortably and in every seed: the two architectures do
not merely have different effect sizes on a shared axis, the *pattern* across the
two interventions differs between them. **The GATv2 row is the honest weak
point.** Its own within-model contrast does not clear — the evidence that GATv2
is driven by peer density and not by target degree rests on those two effects
measured separately (−0.273 significant, −0.066 not), and a test asking directly
whether those two differ from each other returns ns at ten seeds. The GCN's
within-model contrast clears by a factor of fifteen in t.

**A correction to §0.13.10.** That section described the GCN's peer-density row
as "essentially unaffected ... non-monotone", read off seed 0's 0.3775 → 0.5875.
Over ten seeds it is small but significant and consistently positive, 0/10 seeds
falling. GCN is still driven far more by its own degree than by peer density —
that is what the within-model contrast above establishes — but "unaffected" is
the wrong word for a +0.19 effect that no seed contradicts.

**Three qualifications the single-seed table cannot show.**

- **Seed 0 is the largest peer-density effect of the ten.** Its Δ is −0.780
  against a ten-seed mean of −0.273. The per-seed deltas are −0.780, −0.305,
  −0.105, −0.285, −0.055, −0.778, −0.003, −0.245, −0.070, −0.108: a 260× spread
  in magnitude with a perfectly consistent sign. §0.13.10's headline
  0.9925 → 0.2125 is a real effect measured on the most extreme draw available.
  **The direction is what reproduces; the magnitude is not**, and the paper must
  quote the paired mean with its interval rather than the seed-0 pair.
- **Five seeds is not enough for the GATv2 leg.** The same paired test on seeds
  0–4 gives mean −0.306, CI [−0.662, +0.050], t = −2.39 against a critical
  2.776 — the interval crosses zero. Only at ten seeds does it clear
  (t = −3.03, critical 2.262). The GCN leg clears at either count by more than
  an order of magnitude in t. Recorded because a five-seed run would have read
  as a null result on the propagated mechanism, and it is not one.
- **One split is still one split.** These intervals cover refit variance at a
  fixed dataset. Nothing here widens to cover a different train/test split, and
  the ten-node network is still eight simulated nodes (§0.13.12).

Persisted to `results/crossdevice_benchmark/seed_study.json` under
`paired_effects` and `interaction`, with the raw per-seed values under each probe
cell — a ±0.36 interval on a metric bounded in [0,1] can hide a bimodal outcome,
and a mean reported over one describes a value no seed produced. Every figure in
this section is emitted by `--seeds 10`; none is computed by hand for the paper.

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
| Live dashboard reads real data | `design/zero-trust-cps-command-center.html`, a single fully-live page served by `gateway.py` itself and polling its `/api/*` endpoints (`gateway.py`'s Module 9 extension section, no separate script) | **Confirmed** — tested end to end against real hardware telemetry (Section 13): main page, all `/api/*` endpoints, and `/figures` gallery all verified working |
| A rate anomaly from a REAL physical device (not the simulator) triggers a real BLOCK | The real `esp32-vib-001` board itself, live | **Confirmed** — `rms=1.02 FLOOD \| security=0.49 \| process=0.40(FRESH) \| BLOCK` with `FLOOD detected (messages arriving faster than the minimum interval)`. Previously this exact response was only ever confirmed with `device_simulator.py`'s synthetic flood scenario (row above) — this is the first live confirmation against genuine hardware. Note this is a Security Trust (rate/timing) event, distinct from Section 13.2's still-pending Process Anomaly (physical fault) adversarial testing — the two domains stay separately evidenced on purpose. |
| A real physical sensor fault (MPU6050 disconnected) is caught by the fusion pipeline even though the rule check alone misses it | Disconnected/reconnected the real MPU6050 while the board was running | **Confirmed, and a real gap found + fixed** — the disconnected sensor read back all-zero I2C bytes rather than erroring, publishing physically-impossible `rms=peak=crest_factor=kurtosis=0.0`; the rule check's old `(0.0, 3.0)` `rms` bound missed it, but replaying the exact reading through the live scorers gave `fused=0.008` (well below threshold) — the GNN/Isolation Forest caught what the rule check didn't, confirming the fusion design's defense-in-depth. `rms`'s lower bound raised to `0.1` anyway (Section 13.2), verified not to regress the synthetic baseline or reject any real session's data. |
| A fully unpowered sensor (VCC removed) is correctly diagnosed and auto-recovered, not misdiagnosed as a network error | Removed the real MPU6050's VCC entirely, then reconnected it | **Confirmed, and a real firmware bug found + fixed + re-verified** — a fully unpowered sensor raises a real `OSError`/`ETIMEDOUT` from the I2C read (unlike the zero-byte case above); the firmware's single shared exception handler misdiagnosed this as a network problem, reconnecting MQTT (never broken) in an infinite loop that never addressed the real issue. Fixed with a separate I2C-specific handler that re-initializes the sensor and skips to the next cycle without touching MQTT. Re-verified live after the fix: 3 correctly-labelled `MPU6050 read failed` messages, then fully automatic recovery (same `boot_id`, no reset) — plus the first two post-recovery readings, still zero as the sensor stabilized, now correctly caught by the `rms≥0.1` rule bound from the fix above. |

---

## 2. Ablation Study — Does Fusing the Process Anomaly Signals Help?

> **SUPERSEDED BY §0.13.2.** The table below was measured on an inconsistent
> training chain (fusion and GNN artifacts older than the Isolation Forest and
> LSTM-AE they replay through). The `gnn_score` row in particular is wrong by a
> wide margin: 0.929 accuracy here, 0.281 on a consistent chain. Kept visible
> rather than overwritten.

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
| LSTM-AE | 0.945 | 0.878 | 1.000 | **0.935** | 3,029 |
| Transformer | 0.945 | 0.878 | 1.000 | **0.935** | 17,701 |

**On the current dataset the two architectures are indistinguishable**, and the
script now prints "effectively tied" rather than naming a winner. An earlier
generation of this table recorded a small Transformer edge (F1 0.930 vs 0.920);
that gap did not survive the simulator recalibration (ADR-17/18) and the merged
real-hardware rows. A 7-way hyperparameter sweep (pre-LN vs post-LN, ReLU vs
GELU, 6x capacity, up to 400 epochs, varied noise/LR/weight decay) had reproduced
the old edge across every configuration, which is why it was believed — and it is
worth recording that a result stable across seven hyperparameter configurations
still moved when the *data* changed. Architecture sweeps do not test the
assumption that matters.

They are not the same model, which was checked rather than inferred from the
matching summary: per-message scores correlate at **0.998** with a maximum
divergence of 0.319, and they disagree on **4 of 1050** flags. Two genuinely
different architectures converging on the same decision boundary is the finding;
identical metrics are the symptom.

**A staleness defect this exposed, which cost every published Transformer number
in between.** `models/transformer_ae_esp32-vib-001.pt` sat at a build from the
previous day through roughly six full retrains, because the documented training
order — IF → LSTM-AE → GNN → fusion → RL — omits the Transformer. Measured on the
stale artifact it read accuracy **0.694** and, most misleadingly, **0.970** recall
on `stealthy_forged_values` against the deployed fusion's 0.606. That looked like
a free fix for this design's acknowledged blind spot and prompted a full
evaluation of folding it into fusion (Section 0.10.13). Retrained on current data
the same model reads accuracy 0.754 and stealthy recall **0.606** — identical to
the LSTM-AE. The apparent capability was an artefact of being trained on different
data than everything it was compared against. The training order now names six
steps and `test_no_model_artifact_is_older_than_its_training_data` fails on any
artifact older than `training_session.json`.

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

**Why the bandit reacts to `security_concern` where the deployed static table
doesn't**: the static table only
issues `STEP_UP` once `security_trust_score` crosses below 0.6 — and a
single momentary flood burst, under the EWMA (α=0.35), doesn't reliably
cross that line (one flood observation pulls the score to ~0.66, still
above threshold). The bandit learns per-bucket action-values directly from
reward feedback and can react to a *weaker* signal than the hard-coded
threshold, which is what its 1.000 recall vs. the static table's
0.000 shows on this class — a genuine, explainable behaviour of the
contextual-bandit policy. It is not a superiority claim: on macro-F1 the
bandit still loses to a validation-tuned static table (§0.13.6), and it is
not reinforcement learning (C6).

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

**Result: 78/200 (39%) overall — below the 70% target, and reported
honestly rather than adjusted to look better.** The aggregate number
hides a real, informative split by signal:

| Dominant signal | Flip rate | Why |
|---|---|---|
| GNN | 78/78 (**100%**) | Masking the one neighbouring device actually responsible for a `coordinated` reading fully explains the anomaly — the relational signal really is that node's whole story. |
| LSTM-AE | 0/122 (**0%**) | A single-channel repair cannot undo a multi-channel event. Quantified below. |
| Isolation Forest | — | No longer appears. See the note on composition below. |

**Why Isolation Forest has vanished from this table.** It previously accounted
for 129 of the 225 cases at a 2% flip rate. After the IF score-calibration fix
(§0.1), the signal reports "normal" correctly instead of sitting permanently
near 0.58, so it stops being the SHAP-dominant signal on flagged windows and
those cases redistribute to the LSTM-AE. The overall rate moved 36% → 39% not
because explanation quality improved, but because the *mix* changed. Worth
stating plainly: this is a composition shift, not progress against the target.

**The LSTM-AE 0% is now measured rather than asserted.** A flagged window
reconstructs with error **~46–62** (z = 20–27 above the normal baseline), and
recovering to a 0.5 score requires that error to fall to **≤ 4.28**. An impulsive
shock moves `rms`, `peak`, `crest_factor` and `kurtosis` *together* — they are all
functions of the same spike — so repairing any single channel leaves the other
three carrying it. The best achievable single-channel repair brings error from
~55.7 only to **~33.7**, an order of magnitude short of what recovery needs.

**One hypothesis was tested and rejected.** Substituting a channel's flat
training mean hands a sequence autoencoder an out-of-distribution input — a
perfectly constant channel never occurs in training — so splicing a *real normal
trajectory* from stored reference windows should recover better. It was
implemented, measured (**33.63 vs 33.70** median counterfactual error, better in
only 9/40 windows), and **reverted** as complexity that bought nothing. That
experiment is what locates the ceiling in the **single-channel restriction
itself**, not in the fill value.

**The attribution remains sound throughout.** `kurtosis` is named in **110/122**
of these cases — the physically correct answer for an impulsive spike. What fails
is the *recovery* test, not the *explanation*.

**This is a finding about explanation validity across model families, not a bug
to chase toward 70%:** Level 1 SHAP is already validated as 100%
physically-sensible (Section 4 above). The flip test is a fair pass/fail for a
point/relational model — see the GNN's 100% — but for a sequence model over
correlated channels it asks the model to undo an anomaly through a channel that
carries only part of it. Future work wanting to close the gap should perturb the
**full set** of elevated features together, which is a different and arguably
more informative validation design than Section C.4's literal single-feature
procedure. `scripts/evaluate_explainability_level2.py` prints this diagnosis
alongside the number, so the figure never travels without its explanation.

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

### 5.3 Governance VALIDATION (not coverage) — `src/governance_validation.py`

Coverage and validation are different claims, and conflating them was a real
weakness in the earlier write-up.

`nist_mapping.tenets_for_decision()` attaches tenets **1, 3, 4, 5 and 6 to every
decision unconditionally** — they describe the shape of the pipeline, so the
tagger asserts them by construction. Their 100% coverage is therefore
**tautological**: it is 100% because the tagger always writes it, and no
arrangement of the system could make it anything else. Only tenets 2 (secured
transport) and 7 (fusion trained) were ever gated on an actual condition.

That makes coverage a measure of **tagging**, not of compliance. An examiner
entitled to ask "how do you know tenet 4 is satisfied?" deserves better than
"because we always put a 4 in that column."

`src/governance_validation.py` answers the second question. Each tenet gets a
check that reads **only the hash-chained audit log** — the same rows an external
auditor would be handed, never live in-memory state — and each one names the
observation that would falsify it:

| Tenet | Claim validated | Fails if |
|---|---|---|
| 1 | Nothing is scored without first being a registered resource | An authenticated row whose `device_id` is not in the registry |
| 2 | Every scored message arrived over an encrypted transport | An authenticated row on an unencrypted transport |
| 3 | Every message is independently evaluated, never cached | A row granted access with no scores of its own |
| 4 | The policy is driven by the trust state, **on each axis independently** | Equal ALLOW rate above and below a threshold |
| 5 | Every registered asset is actually observed, including silent ones | A registered device with no audit rows at all |
| 6 | No unauthenticated message received anything but rejection | Any `auth_ok=False` row carrying an access decision |
| 7 | The learned models measurably change the outcome | `fused_score` identical to `rule_score` on every row |

**Result over 10,000 audit rows: 7/7 PASS.** Selected evidence:

- **T4** (the sharpest): ALLOW rate **15% below** the process threshold vs
  **91% at or above**; **0% below** the security threshold vs **88% at or
  above**. Tested per axis deliberately — a pooled mean is a weak test here,
  since a window whose only non-ALLOW rows are security-driven `STEP_UP`s would
  show almost no separation on the process axis and still pass by accident.
  Testing each axis separately also directly exercises the two-score
  architecture's central claim: each score must be able to move the outcome on
  its own.
- **T6** (most load-bearing): 213 rejected rows in the window, **none** of which
  reached a scoring or access decision.
- **T7**: 9771/9787 rows (100%) where the learned fusion moved the score away
  from the rule-only baseline — so the ML pipeline is demonstrably contributing,
  not decorative.
- **T3**: all 3 devices changed decision within the window
  (`esp32-vib-001: ALERT, ALLOW, BLOCK, STEP_UP`), which a cached once-per-session
  grant could not produce.

#### Falsifiability self-test — proving the checks are not vacuous

A check that cannot fail is not a check. `evaluate_governance.py` therefore
injects each tenet's own stated falsifier as synthetic rows and requires the
check to reject it:

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

Tenet 5 is excluded from that count rather than assumed: its falsifier is a
registered device with **no** rows, which is the absence of data rather than a
row that can be constructed.

Two honest caveats, both reported by the tool itself rather than smoothed over:

- On a short, healthy window the **process axis of T4 becomes untestable**
  (no rows below threshold to compare against), and the evidence line says so
  explicitly instead of quietly passing on the security axis alone. Both axes
  are testable over a longer window.
- **T3 reports `UNFALSIFIABLE`**, not `PASS`, if no device changed decision in
  the window — because that window genuinely cannot distinguish "re-evaluated
  every message" from "decided once and cached."

The live dashboard carries this as its own panel, with each tenet's claim,
falsifier and evidence shown next to the coverage bars, so the distinction is
visible rather than buried in a script's output.

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

### 13.1 Device-Side Latency — measured on the current firmware

`firmware/main.py` measures, per message, using `time.ticks_ms()`/
`time.ticks_diff()` (the MicroPython-correct way — it handles the periodic
tick-counter wraparound a naive subtraction gets wrong): sampling time (the
32-reading I2C accelerometer window), feature-extraction time (RMS / peak /
crest-factor / kurtosis + the on-device DFT for `dominant_freq`), and signing
time (canonicalisation + HMAC-SHA256). Read off the serial console,
`boot_id = 33`, NTP-synced:

```
[latency] sampling=64ms feature_extraction= 97ms sign=9ms
[latency] sampling=64ms feature_extraction=100ms sign=9ms
[latency] sampling=64ms feature_extraction=101ms sign=9ms
```

| Stage | Measured | Share of cycle |
|---|---|---|
| Sampling (32 paced I2C reads) | **64 ms** (no variance) | 37% |
| Feature extraction (5 features incl. 16-bin DFT) | **97–101 ms** | **58%** |
| Sign (canonicalise + HMAC-SHA256) | **9 ms** | 5% |
| **Total on-device compute** | **≈ 170–174 ms** | 8.6% of the 2000 ms publish interval |

**These numbers replace an earlier, stale set, and the correction is worth
recording because the stale figure was a fingerprint of a known defect.** Both
this section and 13.4b previously reported sampling at **26 ms**, measured before
the acquisition chain was paced (ADR-16). 32 samples at the old unpaced ~1231 Hz
is exactly 26 ms; at the deployed 500 Hz it must be 64 ms, and it is. The two
sections also disagreed with each other on feature extraction (134.5 ms against
98–100 ms) while both being presented as measured. 13.4b's figure was the
accurate one; the 134.5 ms came from an older firmware revision.

**Sampling now shows zero variance across messages, and that is the point.** The
old measurements ranged 26–30 ms because unpaced sampling ran as fast as I2C
allowed, so the spread was I2C jitter. A deadline-paced loop is supposed to
absorb exactly that, and an invariant 64 ms is the on-device evidence that it
does — a live confirmation of ADR-16 rather than an inference from the constants.

**Feature extraction still dominates**, at ~1.5× the sampling and ~11× the
signing. `_dominant_frequency()` is a naive O(n·k) transform — 32 samples × 16
bins = 512 sin/cos pairs per window, in interpreted MicroPython. Cryptography is
not the bottleneck; the DFT is. If on-device latency ever needs to come down,
that loop is the only thing worth touching, and an FFT would be the fix.

For scale, the whole gateway-side pipeline (Section 6) — 4 ML models + fusion +
policy + Level-2 explainability — runs in 22 ms on PC-class hardware with
compiled numpy/torch. The microcontroller spends ~4.5× that on feature extraction
alone.

Small sample (n=3 consecutive messages from one session): enough to characterise
where the time goes and to confirm the pacing, not to bound tail latency.

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
message (`MPU6050 read failed`, not `connection error`).

**Re-verified live, confirmed working**: the user reflashed and pulled
VCC again. Result: 3 clean `[main] MPU6050 read failed (sensor
disconnected, unpowered, or wired incorrectly?): [Errno 116] ETIMEDOUT`
messages — no `connection error`/MQTT-reconnect loop — followed by
automatic recovery (publishing resumed at the next `seq`, same
`boot_id`, no reset needed). One additional finding on the way: the
first two readings immediately after power was restored (`seq=10`,
`seq=11`) came back as literal zero again — the sensor hadn't fully
stabilized yet. Checked, not assumed: this exact reading now scores
`rule_score=0.15` ("outside expected range") against the `rms≥0.1` bound
from the fix above, where it would have passed silently before that fix
existed — the two fixes from this session complement each other, one
keeping the board from getting stuck, the other catching the brief
zero-reading blip during recovery that the exception handler alone
wouldn't flag as anything unusual.

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

### 13.4b On-device footprint — measured on the real ESP32

Latency has been consolidated into Section 13.1 rather than reported twice; this
section previously carried a second, partly-conflicting table (sampling 26 ms,
feature extraction 98–100 ms, total 133–135 ms). The sampling figure predated the
500 Hz pacing and the total was understated accordingly. **Current measured
totals are in 13.1: 64 / 97–101 / 9 ms, ≈ 172 ms per message, 8.6% duty cycle.**

Deployment footprint, printed after full init:

| Resource | Free | Used | Total |
|---|---|---|---|
| RAM | 98,368 B | 17,024 B | 115,392 B (14.8% used) |
| Flash filesystem | 2,084,864 B | 12,288 B | 2,097,152 B (0.6% used) |

Re-read at `boot_id = 33` on the current firmware; the earlier reading (98,432 /
16,960 B) differs by 64 B, i.e. allocator noise, not drift.

Both are comfortable. The whole pipeline — WiFi, TLS, MQTT, sensor driver,
feature extraction and HMAC — fits in under 17 KB of allocated RAM.

### 13.4c A real defect these numbers exposed: `SAMPLE_RATE_HZ` is fiction

> **RESOLVED — this section is the historical record of a defect that is fixed.**
> Everything below is written in the present tense and describes the state
> *before* ADR-16. The acquisition chain is now 500 Hz deadline-paced with the
> MPU6050's DLPF at 184 Hz and a 32-sample window, and the fix is confirmed on
> device: sampling measures an invariant **64 ms** (= 32/500 Hz) against the
> 26–30 ms recorded here, with the variance gone because the loop is paced rather
> than free-running (Section 13.1). `SAMPLE_RATE_HZ` and
> `FEATURE_SAMPLE_RATE_HZ` are both 500 and a test enforces that they agree.
> Kept rather than deleted because the diagnosis is the useful part: three
> successive defects lived in this chain and each only became visible once the
> previous was fixed.


The latency figures are not just a performance note; they falsify a constant.

`firmware/main.py` declares `SAMPLE_RATE_HZ = 100` and
`src/config.py` declares `FEATURE_SAMPLE_RATE_HZ = 100.0`, commented "matches
firmware/main.py's dt_ms=10 sampling loop". **There is no such loop.**
`sample_window()` is:

```python
def sample_window():
    return [read_accel_magnitude_g() for _ in range(WINDOW_SIZE)]
```

No delay of any kind — it reads as fast as I2C allows. The timer brackets
exactly those 32 reads, so the measurement is direct:

```
26 ms / 32 samples = 0.8125 ms per sample  ->  ~1231 Hz actual
declared                                    ->      100 Hz
                                            overstatement: 12.3x
```

A genuine 100 Hz window would take **320 ms** to collect. It takes 26 ms.

**What this does and does not break.**

`dominant_freq` is computed as `k · SAMPLE_RATE_HZ / n`, so every reported
frequency is scaled by the declared rate:

| Reported | Actually |
|---|---|
| 3.125 Hz | ~38.5 Hz |
| 6.25 Hz | ~76.9 Hz |
| 9.375 Hz | ~115.4 Hz |
| 12.5 Hz | ~153.8 Hz |

Bin spacing is ~38.5 Hz, not 3.125 Hz, and Nyquist is ~615 Hz, not the 50 Hz
that `config.DEVICE_REGISTRY`'s comment claims.

**Detection is not affected**, and it is worth being precise about why rather
than filing this as harmless. The simulator generates synthetic windows with no
real timing at all, so its "sample rate" is purely notional; the firmware uses
the same nominal constant and the same `n`. Both sides therefore produce the
same *bin index* for the same spectral shape, the models were trained on that
convention, and the feature is internally consistent end to end. What is wrong
is the **physical label**: `dominant_freq` is currently a DFT bin index
expressed in nominal units, not a frequency in Hz.

**The consequence is for interpretation, not classification.** Any statement
tying this feature to real vibration physics — bearing defect frequencies,
unbalance at 1× running speed, the Nyquist claim in the registry comment — is
wrong by 12.3×. That matters for a report that discusses vibration analysis,
and not at all for the anomaly scores.

**Fixing it properly requires retraining**, which is why it is recorded here
rather than silently patched:

1. *Make the constant true* — add a delay so the loop really samples at 100 Hz.
   Costs 320 ms per cycle instead of 26 ms (still fine against 2000 ms), but it
   changes the real board's spectral content and therefore its feature
   distribution, so the hardware sessions need re-capturing and the models
   retraining.
2. *Make the label true* — measure the achieved rate on-device and use it for
   the DFT. Physically correct immediately, but it changes every reported
   `dominant_freq` value, which again means retraining.
3. *Rename the feature* to `dominant_bin` and drop the Hz claim. Costs nothing
   and removes the false precision, but abandons the physical interpretation.

Until one of those is done, the honest reading of `dominant_freq` is option 3's:
a bin index, comparable across messages, not a frequency.

## 14. Known Limitations & Remediation Roadmap

Originally five acknowledged gaps against the original design.
**All five are now resolved** (struck through below, not deleted, so the
roadmap's own history stays visible) — one (item 4) resolved in the sense
of "confirmed architecturally capped, not fixable," the other four
actually implemented/explained and verified.

| # | Limitation | Solvable? | Resolution |
|---|---|---|---|
| ~~1~~ | ~~Key rotation / device revocation not implemented~~ **RESOLVED — implemented** | — | `trust_engine.py` gained `revoke_device()`/`reinstate_device()`/`rotate_key()`/`is_revoked()`, operating directly on `DEVICE_REGISTRY` (additive fields: `status`, `key_version`, `secret_previous`, `key_rotated_at` — `config.py`). `gateway.py` rejects a revoked device unconditionally, BEFORE HMAC (`process_telemetry()`'s new `is_revoked()` check); `verify_signature()` tries the current key first, falling back to `secret_previous` only within `KEY_ROTATION_GRACE_SECONDS` of the last rotation. Verified end to end, not just unit-level: revoke→reject, reinstate→accept again, rotate→old key still verifies inside the grace window, wrong key never verifies, old key correctly stops verifying once the grace window is manually aged past (7 checks, all passed) — plus a live `process_telemetry()` call against a revoked device, confirmed logged as `REJECTED (device_revoked)`. |
| ~~2~~ | ~~Level-2 (feature-level) explainability not implemented as a separate function~~ **RESOLVED — already implemented, table was stale** | — | `level2_explain()` is a real, dedicated function on every scorer (`gnn_scorer.py`, `isolation_forest_scorer.py`, `lstm_ae_scorer.py`, `transformer_scorer.py`), orchestrated by `src/explainability.py`, populated on every authenticated message, and surfaced live on the dashboard's device cards — verified directly against real hardware telemetry this session (and one real bug in it, the GNN's fake neighbor attribution with no active neighbors, found and fixed; Section 13.0). |
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
