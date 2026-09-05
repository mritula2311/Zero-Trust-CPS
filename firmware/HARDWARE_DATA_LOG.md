# Hardware Data Log — `esp32-vib-001` (real ESP32 + MPU6050)

> **Audit qualification (2026-09-05):** MPU6050 captures exist; SW-420
> captures remain pending. SW-420 is another modality, not another MPU6050.
> Firmware peer-certificate verification is opt-in and untested on real
> hardware — do not rely on it for deployment claims.

Captured with `scripts/collect_hardware_session.py` against one physical
MPU6050 over I2C — there is no separate vibration sensor; the accelerometer
*is* the vibration sensor (see `HARDWARE_SETUP.md`). Raw records live in
`data/collected/hardware_session_*.json`.

---

## READ THIS BEFORE USING THE SCORES BELOW

The **feature** columns (rms, peak, crest_factor, kurtosis, dominant_freq) are
real measurements of a real board and remain valid, with one correction noted
in §3.

The **score and decision** columns are not. They were produced by a gateway
carrying four defects since fixed (`RESULTS.md` §0), and they are kept here as
a historical record of what the system used to do, not as evidence of what it
does now. Two of those defects are visible directly in this table if you know
to look:

- `hardware_session_20260901_113103` records **93 ALLOW decisions with a mean
  fused score of 0.000**. A fused Process Anomaly score of 0.000 against a
  `PROCESS_THRESHOLD` of 0.6 should never produce ALLOW. Both halves were
  broken at once: the Isolation Forest calibration made the fused score
  meaningless (`RESULTS.md` §0.1), and the RL policy's Q-values were so close
  together that `argmax` was effectively arbitrary and happened to land on
  ALLOW (`RESULTS.md` §0.3). Those ALLOWs were accidents that looked like
  correct behaviour.
- `hardware_session_20260901_125402` shows the opposite tail — 36 ALERT and 3
  BLOCK on a board that was mostly being handled normally.

**Do not cite these decisions as system performance.** For current numbers see
`RESULTS.md` §0.6 (live hardware, post-fix) and §2 (held-out evaluation).

---

## 1. Sessions captured

| Session | n | rms (g) | peak (g) | dominant_freq (Hz) | Phases |
|---|---|---|---|---|---|
| `20260901_112219` | 56 | 1.033 – 1.097 | 0.011 – 0.195 | 3.13 – 50.00 | moderate_shake 15, tilt_rotate 20, at_rest_2 21 |
| `20260901_113103` | 95 | 0.334 – 3.152 | 0.011 – 2.187 | 3.13 – 21.88 | at_rest_1 19, gentle_tap 20, moderate_shake 21, tilt_rotate 20, at_rest_2 15 |
| `20260901_115152` | 102 | 0.870 – 3.416 | 0.010 – 1.492 | 3.13 – 28.13 | at_rest_1 21, gentle_tap 20, moderate_shake 20, tilt_rotate 21, at_rest_2 20 |
| `20260901_125402` | 127 | 0.780 – 3.439 | 0.009 – 2.806 | 3.13 – 43.75 | free_form_mixed 127 |

**380 real readings total.** All four are merged into the training set as
additional normal `esp32-vib-001` examples by
`scripts/merge_real_hardware_data.py`, where they make up **8.7%** of the
esp32 normal class (380 of 4347) — the rest is synthetic.

Historical gateway decisions recorded alongside each session (pre-fix, see the
warning above):

| Session | Decisions | Mean fused |
|---|---|---|
| `20260901_113103` | ALLOW 93, ALERT 2 | 0.000 |
| `20260901_115152` | ALLOW 90, ALERT 11, STEP_UP 1 | 0.006 |
| `20260901_125402` | ALLOW 88, ALERT 36, BLOCK 3 | 0.110 |

---

## 2. Phase labels are NOT reliable ground truth

The `phase` field records what the operator was *asked* to do, not what the
board physically experienced, and the two do not line up:

| Phase | n | median rms | **max rms** |
|---|---|---|---|
| `moderate_shake` | 56 | 1.046 | **1.050** |
| `at_rest_1` | 40 | 1.062 | **3.416** |
| `gentle_tap` | 40 | 1.047 | **3.152** |
| `at_rest_2` | 56 | 1.046 | **1.577** |
| `tilt_rotate` | 61 | 1.047 | 2.359 |

`at_rest_1` contains a **higher maximum rms than `moderate_shake`** — the
opposite of what the labels claim. The likely cause is that the operator's
handling did not align with the timed phase boundaries (picking the board up,
or the act of touching it to start a phase, registers as a larger transient
than a steady shake).

**Consequence:** do not build labelled training or evaluation data on the
`phase` field. It was considered as a supervision source and rejected for this
reason. This is also why `merge_real_hardware_data.py` folds every real row in
as a single undifferentiated *normal* class rather than trying to derive
per-phase labels from it.

Note the honest tension this creates, stated rather than hidden: 62 of the 380
real rows (16.3%) sit at or above the synthetic `anomalous_shock` class's rms
floor of 1.117, so some rows labelled normal are physically shock-like. On the
features that actually separate the classes the overlap is far smaller — only
**3 of 380** exceed the synthetic shock `peak` floor of 2.018 — so the
contradiction is real but narrow.

---

## 3. The `dominant_freq` column, before and after the firmware fix

Every session above was captured with firmware whose hand-rolled `_sin()`
Taylor approximation carried up to **7.5e-2** error, which selected the wrong
DFT bin in **57 of 300** test windows (19%), by as much as 46.9 Hz
(`RESULTS.md` §0.5). **The `dominant_freq` ranges in §1 are therefore inflated
at the top end** — the 50.0 Hz and 43.75 Hz maxima on a hand-held board are
substantially artefacts of that bug, not physics.

`rms`, `peak`, `crest_factor` and `kurtosis` are unaffected: those four match
`src/feature_engineering.py`, the reference implementation, exactly.

After re-flashing with `math.sin`/`math.cos`, at-rest readings (`rms < 1.1`):

| At-rest `dominant_freq` | Pre-fix (n=316) | Post-fix (n=34) |
|---|---|---|
| lowest bin, 3.125 Hz | 35.1% | **64.7%** |
| above 12.5 Hz | **17.4%** | **5.9%** |
| tail extends to | 50.0 Hz | 15.6 Hz |

The spurious high-frequency tail largely disappears and the distribution
concentrates where a resting board belongs. Stated honestly: n=34 post-fix is
a **small sample**, so this is directional corroboration rather than proof on
its own. The conclusive evidence is offline — the fixed firmware reproduces
`feature_engineering.dominant_frequency()` exactly across 300 windows (0
mismatches) where the old code missed 57.

**A re-capture is worth doing.** The sessions above predate the fix, so the
merged training data still carries the inflated frequency tail. Re-running
`collect_hardware_session.py` and `merge_real_hardware_data.py` on the current
firmware, then retraining, would remove it. That has not been done yet.

---

## 4. Physically-observed faults that shaped the code

Two real faults were found by manipulating the board live, and both produced
code changes rather than just notes:

1. **A disconnected MPU6050 reads all-zero bytes over I2C** rather than
   raising an error, producing `rms = peak = crest_factor = kurtosis = 0.0`.
   That is physically impossible for a connected accelerometer — gravity alone
   contributes ~1 g at rest — but it satisfied the original `rms` lower bound
   of 0.0 trivially. The bound in `config.DEVICE_REGISTRY` was raised to
   **0.1**, which sits well below the real observed minimum across all sessions
   (0.334 g) while catching this exact fault. `peak`, `crest_factor` and
   `kurtosis` were deliberately **not** given the same floor: unlike rms they
   can legitimately approach zero during genuinely quiet operation (observed
   real minimum `peak` was 0.0087 g), so a similar bound there would cause
   false positives.

2. **I2C read failures were being misdiagnosed as MQTT/network errors**, which
   sent the firmware into a reconnect loop instead of reporting a sensor fault.
   Now separated, and re-verified live: pulling VCC produces three correctly
   labelled `MPU6050 read failed ... ETIMEDOUT` messages and then fully
   automatic recovery when power returns — same `boot_id`, resuming at the next
   `seq`, no reset needed.

The two fixes turned out to be complementary in practice: the exception
handling keeps the board from getting stuck, and the `rms >= 0.1` bound catches
the brief zero-reading blip during recovery that an exception handler cannot
see, because a slow read that *succeeds* raises no `OSError`.

---

## 5. Clock handling — the non-obvious bring-up trap

This board has **no NTP route** (it sits on an isolated laptop hotspot), so
`ntptime.settime()` always fails and the RTC holds whatever last set it.
Thonny's ESP32 backend runs with `local_rtc: True`, meaning it writes **local**
time, while the firmware adds the 2000→1970 epoch gap assuming UTC. Left
uncorrected, every message lands exactly one timezone offset in the future and
the gateway rejects it as `stale_timestamp` — measured at **+19,784 s**, which
is precisely IST's +5:30.

`firmware/main.py` handles this with `RTC_LOCAL_UTC_OFFSET_SECONDS`, applied
**only when NTP fails** (`sync_time()` returns whether it succeeded). Set it to
0 if your board has a real NTP route or your IDE syncs UTC.

Post-fix, the clock delta against the gateway is **+2.3 s to +21.3 s**, well
inside the 600 s freshness window, with zero `stale_timestamp` rejections
across 46 consecutive rows.

---

## 6. Deployment footprint

Printed by `print_deployment_footprint()` at every boot, after full init:
RAM free/allocated and flash filesystem free/used. See `RESULTS.md` §13.4 for
the recorded values and what they imply about headroom on the ESP32.

---

## 7. Still outstanding

A **formal, structured adversarial capture with human-labelled ground truth**
has not been done. Two real faults (§4) were found by informal live
manipulation, and the two-score pipeline has been exercised end to end against
the physical board — but a deliberate, scripted fault-injection session, with
labels recorded at injection time rather than inferred afterwards, remains the
main gap in the hardware evidence. §2 is the reason it matters: without labels
captured at the moment of injection, phase annotations cannot be trusted as
ground truth after the fact.
