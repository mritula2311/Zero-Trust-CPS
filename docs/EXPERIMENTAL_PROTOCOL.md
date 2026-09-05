# Experimental Protocol — ZT-Duo 20-Node Hybrid CPS Testbed

> **2026-09-05 audit update:** Two physical identities are configured; Device 001 (MPU6050) contributes TRAIN/VALIDATION/TEST observations, Device 002 (SW-420) contributes TRAIN observations only (first capture, session `20260905_162002` — see §0.13.18). The network was grown from 10 to 20 configured slots the same day to equalise sensor-type representation (§1 below). VALIDATION/TEST still use a pending context placeholder for Device 002; this is not 20 independently observed streams or source-independent calibration.
> Current evidence and limitations: RESULTS §0.13.17, then §0.13.18–§0.13.22
> (§0.13.19 fixed a pending-node masking bug and corrected §0.13.18.2's
> diagnosis; §0.13.20 covers a separate `evaluate_gnn_baselines.py`
> regression; §0.13.21 found the M9 virtual-only-vs-hybrid comparison did not
> reproduce at 20 nodes).

Authoritative description of what is measured, on what, and how. Every number
in the manuscript traces to a run described here.

---

## 1. Testbed composition

```
1 CAPTURED PHYSICAL SOURCE (TRAIN/VAL/TEST) + 1 PARTIALLY-CAPTURED PHYSICAL SOURCE (TRAIN only, PENDING in VAL/TEST)
+
18 SIMULATED ESP32 STREAMS (9 MPU6050-type + 9 SW-420-type, equalising the two real sensor types)
=
20 CONFIGURED HYBRID SLOTS
```

| Node | device_id | source_type | Hardware | Features |
|---|---|---|---|---|
| 01 | `esp32-vib-001` | REAL | ESP32 + MPU6050 (I²C) | 5: rms, peak, crest_factor, kurtosis, dominant_freq |
| 02 | `esp32-vib-002` | REAL in TRAIN, PENDING_REAL_HARDWARE_DATA in VALIDATION/TEST | ESP32 + SW-420 vibration switch (GPIO4) | 4: trigger_rate, duty_cycle, burst_max_ms, inter_event_cv |
| 03–10 | `esp32-sim-03` … `esp32-sim-10` | SIMULATED | none | parameterised from real telemetry (`config/simulated_nodes.json`), original 8 |
| 11–20 | `esp32-sim-11` … `esp32-sim-20` | SIMULATED | none | added 2026-09-05 (§0.13.18) to equalise sensor-type counts (10 MPU6050-type / 10 SW-420-type total); the 7 new SW-420-type profiles are calibrated against Device 002's real measured stats, not the sensor datasheet |

**The required wording, and the only accurate one:**

> The evaluation used twenty configured slots: one fully-captured MPU6050
> source (all three splits), one partially-captured SW-420 source (TRAIN
> only), and eighteen simulated streams. Pending targets (Device 002 in
> VALIDATION/TEST) are excluded from metrics and, as of RESULTS §0.13.19,
> from every model's pooling/attention as well — an earlier measurement
> (§0.13.18.2, superseded) attributed a concrete recall degradation to the
> placeholder remaining in model context; §0.13.19 found and fixed a
> separate masking bug that was the actual cause, and the degradation does
> not reproduce once fixed.

The captured MPU6050 supplies empirical physical values across every split;
the SW-420 supplies them for TRAIN only; the eighteen simulated nodes provide
controlled network-scale relational context. Full-network results are
**hybrid testbed evidence, not physical replication across twenty
independent ESP32 devices**, and are never described as twenty physical
devices.

Because the two configured physical nodes use **different sensors**, the planned experiment after Device 2 capture
evaluates cross-device and heterogeneous-sensor behaviour, **not** same-model
MPU6050 sensor-to-sensor replication. An SW-420 cannot reproduce an MPU6050's
measurements even in principle — see `firmware/HARDWARE_SETUP_SW420.md` §1.

---

## 2. Acquisition chains

Rate, filter and window move together and are one decision per sensor. Both are
enforced across the firmware/host boundary by
`tests/test_invariants.py` (`TestSamplingContract`, `TestSW420SamplingContract`).

| | Node 01 (MPU6050) | Node 02 (SW-420) |
|---|---|---|
| Sample rate | 500 Hz nominal | 1000 Hz |
| Window | 32 samples (64 ms) | 256 samples (256 ms) |
| Anti-alias | `MPU6050_DLPF_CFG=1` (184 Hz) | n/a — comparator output |
| Threshold | n/a | onboard potentiometer, fixed per session |
| Telemetry interval | 2 s | 1 s |

Current MPU6050 firmware paces 32 samples at nominal 500 Hz (64 ms), with
184 Hz DLPF and 15.625 Hz DFT bins. The 12.3× mismatch belongs to the old
unpaced 100 Hz declaration in RESULTS 13.4c; it is historical. The short window
and uncalibrated excitation still limit physical spectral interpretation.

---

## 3. Labels

**Labels are recorded, never inferred.** Only `--labelled` operator-marked
captures are ground truth. An operator presses ENTER at the start and end of
each physical action, `MARK_MARGIN_S = 2.0 s` is trimmed from each end (the
keypress and the action are not simultaneous), and samples outside a marked
interval are **discarded, not guessed at**.

This is not caution for its own sake. The four earlier timed-schedule sessions
were shown not to match physics — `at_rest_1` held a higher maximum rms
(3.416 g) than `moderate_shake` (1.050 g).

`MIN_EVENT_SECONDS` is **derived, not chosen**:

```
MIN_EVENT_SECONDS = 2·MARK_MARGIN_S + 2·LSTM_SEQ_LEN·TELEMETRY_INTERVAL_S = 36 s
```

Below that an event cannot yield a single scoreable window.

Two grades of label provenance exist and are **reported separately, never
averaged**: `operator_mark` (recorded live) and `transcript_reconstruction`
(recovered from a failed capture's console output). Reconstructed labels are
tail-contaminated — resting `peak` p90 runs ~3× fatter.

---

## 4. Splits

`data/splits/session_split.json` is the manifest.

**Invariant: every physical acquisition session belongs to exactly one split.**
Enforced by `tests/test_invariants.py::TestSessionSplit`.

| Split | Real sessions | Simulated sessions |
|---|---|---|
| TRAIN | `20260902_171313`, `20260902_102448` (MPU6050), `20260905_162002` (SW-420, first capture) | `SIM_SESSION_TRAIN_001` (seed 42) |
| VALIDATION | `20260902_173108` (MPU6050 only — no SW-420 session yet) | `SIM_SESSION_VAL_001` (4242), `SIM_SESSION_VAL_002` (4243) |
| TEST | `20260902_221217` (MPU6050 only — no SW-420 session yet) | `SIM_SESSION_TEST_001` (999) |

Excluded from every split: the four `20260901_*` sessions — captured on the old
unpaced acquisition chain, sitting on a different frequency axis.

**Two validation sessions, not one**, because two stages are fitted above the
base models: the fusion meta-learner (VAL_001) and the threshold/policy layer
(VAL_002). Sharing one session would leave the policy reading in-sample fusion
scores.

TEST is untouched by model fitting, normalization, threshold selection,
hyperparameter tuning, fusion training, reward design and model selection.

**Stage assignment:**

```
TRAIN       -> Isolation Forest, LSTM-AE, Transformer, GNN
VALIDATION  -> fusion meta-learner; thresholds; policy; self-loop sweep
TEST        -> read once, at the end, by evaluation only
```

---

## 5. Physical conditions

### 5.1 Coordinated two-node conditions (C1–C4)

Requires both boards publishing.

| Condition | Node 01 | Node 02 |
|---|---|---|
| C1 | NORMAL | NORMAL |
| C2 | PHYSICAL_ANOMALY | NORMAL |
| C3 | NORMAL | PHYSICAL_ANOMALY |
| C4 | PHYSICAL_ANOMALY | PHYSICAL_ANOMALY |

C4 uses **genuine simultaneous measurements from both physical nodes**. It is
not simulated while hardware is available.

### 5.2 Intensity sweep

`intensity_low` / `intensity_medium` / `intensity_high`, plus the `fault_weak` /
`fault_strong` sustained low-amplitude conditions already captured.

**These are NOT calibrated.** There is no shaker table and no reference
accelerometer; the amplitude knob is how hard a person moves the board. They are
reported as *operator-controlled low/medium/high intensity*, with the actual
observed rms / peak / crest / dominant_freq of each block published alongside.

Purpose: the **detection floor**. Existing sessions detect 136/136 disturbances,
but every one is violent hand manipulation (peak 0.4–3.1 g against a 0.035 g
resting maximum — a 10–90× margin), so 100% says very little.

### 5.3 Mounting and orientation robustness

Run the same schedule once per physical configuration, with the configuration
passed on the command line so it lands in the data:

```
MOUNT_A / ORIENTATION_A     baseline
MOUNT_A / ORIENTATION_B     rotated 90 degrees, same mounting
MOUNT_B / ORIENTATION_A     detached and remounted
```

The sensor is **never randomly repositioned** — each change is deliberate and
recorded. The question is whether the learned normal region is specific to one
mounting configuration. **Report the actual result; do not assume robustness.**

This matters more than it looks: with session leakage removed, the false-positive
rate on the untouched TEST session is 5/12, against 0/49 when that session's own
at-rest rows were in training. That is direct evidence the learned normal region
may be session- and mounting-specific.

### 5.4 Authenticated physical anomaly

A legitimate, correctly authenticated board (valid identity, HMAC, boot_id, seq,
timestamp, TLS) deliberately producing abnormal physical telemetry.

Expected: Security Trust stays acceptable, Process Anomaly goes abnormal,
policy candidate is ALERT. **The outcome is measured, never hard-coded** — the
point is to demonstrate that anomalous physical data can remain *available*
while the device is correctly authenticated.

---

## 6. Metrics — three levels, reported separately

Window-level numbers alone would treat 500 overlapping windows from one
disturbance as 500 independent physical experiments. They are not.

**Window / message level.** total, TP, TN, FP, FN, precision, recall, F1,
false-positive rate, detection rate.

**Event level.** An event is one physical disturbance occurrence — one marked
operator interval — not a window. Detection criterion, stated explicitly:

> An event counts as detected if at least one scoreable window strictly inside
> its trimmed interval produces an anomaly decision.

Reported: total events, detected, missed, event recall, false event alarms.

**Session level.** Per independent run: `session_id`, devices, `source_type`,
condition, mounting condition, event count, window metrics, event metrics.

**Statistical treatment.** Windows from one disturbance are correlated.
Window-level intervals are labelled as window-level; cluster bootstrap over
sessions is used where an aggregate is needed. Narrow window-level intervals are
never presented as evidence of hardware generalization.

---

## 7. Reproduction commands

Compute environment (CPU/GPU/RAM/package versions) and measured wall-clock
training times for every step below: `docs/ENVIRONMENT.md` §1/§1a. The full
six-step chain runs in ~2.4 minutes on that hardware; the two network-scale
scripts (`evaluate_gnn_baselines.py`, `benchmark_crossdevice_models.py`) take
tens of minutes each at the current 20-node network size, dominated by the
CPU-bound sklearn fits (M1/M2), not the GPU torch models.

### 7.1 Software-only (no hardware required)

```bash
# Splits and data
python src/splits.py                                   # verify disjointness
python scripts/generate_training_data.py
python scripts/generate_validation_data.py             # both validation draws
python scripts/generate_test_data.py
python scripts/merge_real_hardware_data.py             # TRAIN sessions only

# Training chain -- SIX steps, in this order, all on TRAIN except where noted
cd scripts
python train_isolation_forest.py
python train_lstm_ae.py
python train_transformer.py
python train_gnn.py
python train_fusion_meta_learner.py    # VALIDATION (SIM_SESSION_VAL_001)
python train_adaptive_pdp.py           # VALIDATION (SIM_SESSION_VAL_002)

# Evaluation
python evaluate_real_hardware.py --split validation    # while tuning
python evaluate_real_hardware.py --split test          # once, at the end
python evaluate_ablation.py

python -m unittest discover -s tests                   # from repo root
```

### 7.2 Hardware acquisition

Prerequisites: Mosquitto running with TLS, both boards flashed and on the
hotspot, `python src/gateway.py` up.

**Before every SW-420 session: tap the board and confirm `trigger_rate` moves
off 0.** A disconnected D0 wire reads identically to a still board.

```bash
cd scripts

# --- Node 01 only (MPU6050) ---
python collect_hardware_session.py --labelled --device esp32-vib-001 \
       --mount MOUNT_A --orientation ORIENTATION_A

# --- Node 02 only (SW-420) ---
python collect_hardware_session.py --labelled --device esp32-vib-002 \
       --mount MOUNT_A --orientation ORIENTATION_A

# --- C1..C4 coordinated, BOTH physical nodes ---
python collect_hardware_session.py --coordinated --labelled \
       --devices esp32-vib-001,esp32-vib-002 \
       --mount MOUNT_A --orientation ORIENTATION_A

# --- Intensity sweep (low / medium / high) ---
python collect_hardware_session.py --intensity --labelled --device esp32-vib-001

# --- Sustained low-amplitude fault (phone on vibrate) ---
python collect_hardware_session.py --fault --labelled --device esp32-vib-001

# --- Mounting / orientation robustness: one run per configuration ---
python collect_hardware_session.py --mount-check --labelled --device esp32-vib-001 \
       --mount MOUNT_A --orientation ORIENTATION_A
python collect_hardware_session.py --mount-check --labelled --device esp32-vib-001 \
       --mount MOUNT_A --orientation ORIENTATION_B
python collect_hardware_session.py --mount-check --labelled --device esp32-vib-001 \
       --mount MOUNT_B --orientation ORIENTATION_A
```

Every capture records `session_id`, `device_id`, `source_type`, `sensor_type`,
`mounting_condition`, `orientation`, `phase`, `label_source` and
`network_experiment_id` on **every record**. No source-code edit is needed
between sessions.

**After capturing**, add each new session id to `data/splits/session_split.json`
deliberately. `tests/test_invariants.py::TestSessionSplit` fails on any session
that is neither allocated nor explicitly excluded — a new capture cannot
silently land in TRAIN.

---

## 8. What this protocol does not establish

- Only **two** physical ESP32 devices exist. Twenty-node results are hybrid,
  not physical replication.
- The two physical sensors are **heterogeneous**, so no same-model MPU6050
  sensor-to-sensor replication is possible here.
- Disturbances are **laboratory operator actions**, not industrial bearing
  degradation. Validation on rotating machinery and naturally developing faults
  remains future work.
- Session count is small (five labelled sessions at time of writing — four
  MPU6050, one SW-420), so the test denominator is small and its intervals
  are wide. This is reported, not smoothed over.
- The SW-420 device has **no held-out VALIDATION or TEST session** — its one
  capture is TRAIN only. Every SW-420-specific number (its deployed
  per-device model, its slot in the 20-node network) is currently unvalidated
  against held-out real data. (§0.13.18.2 originally claimed a concrete,
  measured cost of this gap; §0.13.19 found that specific measurement was
  actually a masking bug, now fixed, and the claimed cost did not
  reproduce — the split gap itself remains real and unvalidated.)
- Simulator-to-real domain shift is measured (`RESULTS.md` 0.10.9) but not
  eliminated.
