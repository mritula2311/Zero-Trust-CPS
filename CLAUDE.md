# CLAUDE.md — Zero-Trust CPS

> **Current status:** read RESULTS §0.13.17, then §0.13.18–§0.13.23 in order.
> Keep archived artifacts/results intact when rebuilding the corrected
> temporal chain. M9 is experimental, with no persisted n=15 test; LOW
> validation is TRAIN residual consistency only. The virtual-only advantage
> stays visible. Device 2 (SW-420) has its first real capture (TRAIN split
> only, session 20260905_162002) — a held-out VALIDATION/TEST SW-420 session
> is still pending. The cross-device network is now 20 nodes (2 captured-real
> + 18 LEGACY_SIMULATED, equalised 10 MPU6050-type + 10 SW-420-type), grown
> from 10. §0.13.18.2's original M1/M2 diagnosis is SUPERSEDED — §0.13.19
> found and fixed a pending-node masking bug (a validity feature was appended
> but never actually excluded invalid nodes from pooling/attention), which
> was the real cause, not a training-distribution gap. §0.13.20 flagged a
> separate regression in `evaluate_gnn_baselines.py`'s Task 1/2 numbers
> (novelty claim #3) and its own B1/B2/B3 concat baselines as possibly
> sharing the same unmasked-placeholder issue; §0.13.24 confirmed and fixed
> it (masking correction only, no hyperparameter/threshold/split changes).
> The fix barely moved Task 2's headline cross-device delta (0.3958 → 0.5267,
> was 0.3958 → 0.5283 pre-fix) but changed Task 1's concat-MLP F1 materially
> (0.9662 → 0.9174) — GNN still loses to every simple baseline either way.
> Novelty claim #3 remains SUPPORTED.

Guidance for coding agents working in `zt-cps-starter`. Read `METHODOLOGY.md` for the
method and its mathematics, `ZERO_TRUST_CPS_KB.md` for architecture decisions,
`RESULTS.md` for measured numbers; this file is the short list
of things not to break, and every entry has already cost real debugging time.

---

## 1. What this is

A Zero-Trust gateway for a cyber-physical system. One real ESP32 + MPU6050
(`esp32-vib-001`) publishes vibration telemetry over TLS MQTT alongside two
simulated devices (`sensor-002`, `actuator-001`). The gateway authenticates
every message, scores it on two independent axes, decides via policy, and
writes a hash-chained audit record.

**The two scores are the whole architecture:**

| | Security Trust | Process Anomaly |
|---|---|---|
| Evidence | identity, HMAC, freshness, rate | the physical reading only |
| Answers | "are these papers real?" | "is the machine behaving?" |
| Signals | rule-based trust engine | rule + Isolation Forest + LSTM-AE + GNN → fusion |

They meet **only** in the 2×2 policy lookup (`policy_engine.decide`).

---

## 2. Repo map

```
src/          gateway.py, trust_engine.py, policy_engine.py, fusion_engine.py,
              feature_engineering.py, config.py, audit_log.py,
              governance_validation.py, device_simulator.py,
              {isolation_forest,lstm_ae,transformer,gnn}_scorer.py,
              secrets_local.py (gitignored)
firmware/     main.py (MicroPython, on-device), HARDWARE_SETUP.md
scripts/      train_*.py, evaluate_*.py, generate_*.py,
              collect_hardware_session.py, merge_real_hardware_data.py
models/       trained artifacts + *_meta.json calibration
data/collected/  training_session.json, test_session.json, *_labelled.json
tests/        invariant, generator and audit regression suites (stdlib unittest)
docs/         00_overview.md … 13_system_architecture_and_workflow.md
```

`METHODOLOGY.md` states the method, its mathematics and the novelty claims.
`ZERO_TRUST_CPS_KB.md` is the architectural source of truth. `RESULTS.md` holds
measured numbers. `SESSION_LOG.md` is the chronological record of why things
are the way they are — including fixes that were tried, measured and reverted.

Figures: `generate_evaluation_graphs.py` produces 17 covering pipeline behaviour
on synthetic data; `generate_paper_figures.py` produces the four that carry the
claims (real hardware, two-score separation, anomaly rank, seed sensitivity).

---

## 3. Running it

```bash
cd src/
python gateway.py            # terminal 1
python device_simulator.py   # terminal 2
# gateway.py also serves the dashboard at http://localhost:8600
```

Tests: `python -m unittest discover -s tests` (baseline 70 tests; see RESULTS.md §0.13.17 for the current count).

With real hardware: Mosquitto running, board flashed and on the hotspot,
gateway up, then `python scripts/collect_hardware_session.py --labelled`.

---

## 4. Invariants — do not "fix" these

### Never blend the two scores
Averaging makes "forged papers, normal cargo" indistinguishable from "valid
papers, machine shaking" — opposite responses. `decide()` takes the two scores
plus staleness and nothing else; a third evidence input means the separation
has leaked. Enforced by `TestTwoScoreSeparation`.

### Never train on the live path
`scripts/train_*.py` produce artifacts; `gateway.py` only runs inference. No
`.fit()`, no `update()`. An online-learning PDP is an attack surface — anyone
who can generate traffic can move the model.

### Training order is not optional — and it has SIX steps, not five
**IF → LSTM-AE → Transformer (ablation) → GNN → fusion → contextual bandit.** Each replays through the
previous models. Retrain all six, in order, after any change to features, the
simulator, or the merged dataset.

This list previously omitted the Transformer, and that omission cost real
results: it sat at a build from the previous day through ~6 full retrains, so
every number published about it was measured against superseded data. Its
accuracy read 0.694 where a current build reads 0.754, and an apparent 0.970
recall on `stealthy_forged_values` — which looked like a free fix for this
design's acknowledged blind spot — evaporated to 0.606 once retrained.
`test_no_model_artifact_is_older_than_its_training_data` now fails on any stale
artifact.

### A rejected message must never touch the claimed device's state
Failed auth updates `IdentityTargetingRisk` for the *claimed* ID only.
Penalising the claimed device is a trust-poisoning DoS needing no secret.
Load-bearing beyond attacks: during a clock misconfiguration the real board
was rejected hundreds of times and its trust score correctly never moved.

### `feature_engineering.py` is a reference implementation
The firmware computes the same five features on-device and the models train
against *this* file. Changing a formula without re-verifying the firmware
creates train/serve skew **no offline evaluation can detect**. Verify by
differential test over randomised windows, not by reading the code.

### The acquisition chain is one decision
`SAMPLE_RATE_HZ=500`, `WINDOW_SIZE=32`, `MPU6050_DLPF_CFG=1` (184 Hz) — rate,
anti-alias filter and window size move together, and `config.FEATURE_SAMPLE_RATE_HZ`
must match the firmware exactly (tests enforce it). Every `dominant_freq` the
models learned is scaled by the rate, so changing any of the three requires a
full retrain. Three successive defects lived here, each invisible until the
previous was fixed (ADR-16).

### The resting normal region is sized by spread, not by the latest median
The same board's resting rms measured 1.041 / 1.056 / 1.011 g on three
occasions — a 0.045 g spread against a 0.009 g within-session std. Centring
`REST_DC_CENTRE` on the newest median was implemented, measured (real-hardware
false positives 2/49 → 0/49 — pre-split figures now withdrawn as leaky, cited only
for the *movement*), and then the next live resting board landed at
**−4.0σ**. Centre on the midpoint of the observed range and widen the spread to
span it. Do not re-tune it onto one session (ADR-18).

### Evaluate at the deployed threshold
`PROCESS_THRESHOLD = 0.6`, and `evaluate_ablation.py` now defaults to it (it
used to threshold at 0.5) — a defect
that made a signal incapable of scoring above 0.621 moved its headline
accuracy by 0.003 while making the system reject a healthy physical board.
Prefer per-class score *distributions* over aggregate accuracy.

### Filling the LSTM window is not the same as clearing it
`evaluate_real_hardware.py` drops `2*LSTM_SEQ_LEN-1` records per block, not
`LSTM_SEQ_LEN-1`. Dropping only enough to FILL the window leaves the block's own
settling disturbance inside it — the first scored window still contains messages
0..7, i.e. the seconds right after the operator pressed ENTER and stepped away.
Measured: one 0.0768 g spike in a baseline block failed all 6 of its scored
windows with `lstm` 0.000 while `iso` read 0.265–1.000 on the same samples.
`MIN_EVENT_SECONDS` is derived from the same `2*LSTM_SEQ_LEN` (36 s, not 20 s).

### Real hardware is 3% of training and carries the result
Withholding the real at-rest rows and retraining the whole chain **materially
increases** operator-marked false positives, detection unchanged. Do not treat
them as a rounding error because they are 3% of the count, and do not "clean up"
`merge_real_hardware_data.py` in a way that drops them (`RESULTS.md` 0.10.9).
⚠ The old "13/49 vs 0/49" magnitude is pre-split and its 0/49 baseline is the
withdrawn leaky figure — the *direction* holds, the magnitude needs re-measuring
under session-level splitting (`docs/CLAIM_EVIDENCE_MATRIX.md` C4/C14). The honest
deployed resting FP is **5/12 (41.7%)** on the untouched test session, not 0/49.

### Window-averaged error is not severity
`sharp_impact` (max peak 2.968 g) scores a LOWER reconstruction-error z than
`gentle_tap`, because 29% of its samples are quiet — brief impulses with pauses —
against 0% for continuous shaking. The score mapping is not the obstacle and a
compressive map will not fix it; it would produce a number that looks like
severity and is not. Ranking severity needs a peak-aware statistic.

### A number going up is not the model improving
Re-run the case that motivated the fix **and** the opposite case. A GNN fix
that raised isolated-device scores from 0.020 to 0.929 also made the model
saturate to 1.000 on a genuinely shaken board, masking a real anomaly.

---

## 5. Hardware and labels

### Pinout (`firmware/HARDWARE_SETUP.md` §2)
`VCC→3.3V` (not 5V), `GND→GND`, `SDA→GPIO21`, `SCL→GPIO22`, `AD0→GND` (I2C
address `0x68`). Swapped SDA/SCL is the most common first-time fault.

Two sensor failure modes to recognise: `ETIMEDOUT` (loose/unpowered — firmware
re-inits I2C and self-recovers), and **all features exactly `0.0`** (bus
responsive but returning zero bytes; physically impossible for a connected
accelerometer since gravity alone is ~1g, which is why `expected_ranges` has an
`rms` floor of 0.1).

### Labels are recorded, never inferred
Timed-schedule phase labels were shown not to match physics (`at_rest_1` held a
higher max rms than `moderate_shake`). Only `--labelled` operator-marked
captures are ground truth; samples outside a marked interval are **discarded,
not guessed at**, with `MARK_MARGIN_S` trimmed from each end.

`MIN_EVENT_SECONDS` is *derived*, not chosen:
`2·MARK_MARGIN_S + 2·LSTM_SEQ_LEN·TELEMETRY_INTERVAL_S`. Below that an event
cannot yield a single scoreable window — a hardcoded 16s once meant a
minimum-length event was silently worth nothing downstream.

### Merging real data
Only `*_labelled.json` merges, and only `at_rest` rows become NORMAL training
data — folding a shaken board in as "normal" teaches the models that a fault is
healthy. The 20260901 sessions are permanently excluded: they used the old
unpaced acquisition chain and sit on a different frequency axis.

`score_all` resets the LSTM window per `(session, phase)`, not per phase —
every session starts and ends with `at_rest`, so keying on phase alone joins
two captures taken hours apart into windows that never existed.

### Provenance never averages away
`operator_mark` and `transcript_reconstruction` are different grades of
evidence and must be reported separately. Reconstructed labels are
tail-contaminated: medians agree across sessions, but the reconstructed one's
resting `peak` p90 runs ~3× fatter because it inferred windows from console
positions rather than real marks.

### Calibrate the simulator against measured reality
The simulator is ~97% of training data, so its constants set what "normal"
means. `REST_DC_CENTRE` is the midpoint of the observed resting range (ADR-18), not a guess — centring it ~1.8σ low put every real resting sample at
the edge of the learned normal region, which is what the Isolation Forest was
reporting when it scored clean resting windows 0.000. Prefer an offset
correction backed by a measurement over widening a distribution.

---

## 6. Security

`src/secrets_local.py` and `firmware/device_secrets.py` are gitignored.
Both firmware entry points import the separate secret module; tracked firmware
does not need embedded credentials. Never stage a credential file or print key
material. The gateway refuses insecure startup and template device keys; actual
firmware certificate verification remains a deployment blocker in the audit.

`.gitignore` must cover rotated artifacts (`*.archived-*` — `*.db` does not
match `audit_log.db.archived-…`).

The audit log is hash-chained: rows cannot be deleted to tidy up. Tests that
write audit rows **must** redirect `audit_log.AUDIT_DB_PATH` to a temp
directory — 25 test-written rows once turned a 7/7 governance validation
into 5/7, and could not simply be removed afterwards.

---

## 7. Reporting standards

**Report what you measured, including when it fails.** Where the system
underperforms — Level-2 explainability at 37% against a 70% target,
`stealthy_forged_values` recall — the number stays in the figures with its
explanation. Never swap a metric for one the system happens to pass.

**If a validation check cannot fail, it is not a check.** State its falsifier
and inject it (`docs/10` §7.1). `governance_validation.py` proves 7/7 of its
tenets reject their own falsifier (Tenet 5 was previously excluded on a mistaken
premise; corrected).

**Verify the surface a user actually touches.** Endpoint checks verify an API,
not the page consuming it. A dashboard fix was confirmed by `curl` while the
page rendered nothing, because the same edit introduced a JavaScript
`SyntaxError`. Use `node --check` on the extracted script, then load the page.

**Record wrong turns.** A fix that was tried, measured and reverted is worth
more in `SESSION_LOG.md` than silence — it stops the next reader repeating it.

---

## 8. Working style

**Think before coding.** State assumptions; if two readings of a request
differ materially, ask instead of guessing. Name what's confusing rather than
silently picking one.

**Simplicity first.** Minimum code that solves the problem — no abstraction
for a single use, no configurability nobody asked for, no error handling for
states that can't occur. If it could be a one-liner, make it one.

**Surgical diffs.** Touch only what the request needs. Don't improve adjacent
code, don't refactor what isn't broken, match existing style. Mention dead
code you notice; don't delete it unless asked. Every changed line should
trace back to the request.

**Goal-driven execution.** Turn the task into a verifiable check before
starting:
```
1. [step] → verify: [check]
2. [step] → verify: [check]
```
Non-trivial logic leaves one runnable check behind — a test in
`tests/test_invariants.py` that fails if the logic breaks. Every test there
guards a property that has **already been broken once** (§4); a test with no
corresponding incident is mostly maintenance cost.

**Spend Claude Code's usage limit like it's scarce, because it is.**
Subagent-heavy sessions and long, high-context sessions are what burn through
the 5-hour and weekly limits fastest.
- Default to direct `Grep`/`Glob`/`Read` for anything scoped to one or two
  files or a single symbol. Reach for an Explore/general-purpose subagent
  only when a search genuinely has to span many files or unknown naming
  conventions — most questions about this repo resolve with one or two greps.
- Don't spawn a subagent to parallelize work that isn't actually independent,
  and don't spawn one "just in case" it finds more.
- `/compact` when a task's context is done growing but the session continues;
  `/clear` when switching to an unrelated task. A session sitting above
  ~150k tokens costs more per turn even with caching.
- This project does not use the `graphify` skill or its subagents — prefer
  the repo map above, `docs/`, and targeted grep/read over building or
  querying a knowledge graph.

**These guidelines are working if:** diffs trace line-by-line to the request,
fewer rewrites from overcomplication, questions arrive before implementation
rather than after the mistake, and sessions stay light on subagents and
context.
