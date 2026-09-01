# CLAUDE.md — Zero-Trust Security Framework for IoT-Based Cyber-Physical Systems

**v2 — updated to incorporate real hardware, full algorithm detail, industry
standards alignment, and a compressed 4-week timeline for a research-paper
deliverable.** This replaces the earlier version of this file. Place it at
the root of the repository (alongside `src/` and `docs/`) so Claude Code
reads it automatically every session.

---

## 1. What This Project Is

An academic research prototype and **industry-implementable reference
design** for a Zero-Trust Security Framework wrapping an IoT-based
Cyber-Physical System. The full academic grounding (37-source open-access
literature review, research gap, feasibility case) is in
`Zero_Trust_CPS_Project_Synopsis.docx` — read Sections 3, 4, 5, and 9 first
if that file is present. This CLAUDE.md is the working engineering brief;
the docx is the citable academic record. Keep both in sync as the project
evolves — if you change the architecture here, flag that the report needs
the same update.

**Physical use case (assumed from the hardware inventory below):**
condition-based / predictive-maintenance monitoring of rotating or
vibrating industrial equipment (a motor, pump, fan, or similar test rig),
secured end-to-end by the seven-module Zero-Trust pipeline. This is a
well-precedented CPS category (it's project #6, "Secure CPS-Based
Industrial Monitoring," in the original project list this work descends
from) and gives every module a concrete physical referent instead of an
abstract "sensor value." If the actual intended use case is different
(e.g. structural health monitoring on a building, vehicle vibration,
seismic sensing), the architecture below is unchanged — only the
domain-specific interpretation of "anomalous vibration" and the standard
you cite for severity thresholds (Section 6) would need to change. State
which one you're targeting explicitly in the paper's introduction.

The system has exactly **seven mandatory functional modules** — fixed
scope, do not change without the user explicitly asking:

1. CPS Device Identity
2. Authentication
3. Trust Evaluation
4. Continuous Verification
5. Access Control
6. Secure Communication
7. Monitoring

---

## 2. Hardware Inventory and Its Role in the System

| Component | Role | Notes |
|---|---|---|
| **ESP32** (dev board, WiFi + BLE, dual-core) | The physical CPS edge node — runs the device-side firmware for Modules 1, 2, 6 (identity, authentication, secure publish) and does on-device feature extraction from the two sensors below | Assume a standard ESP32-WROOM-32 dev board unless told otherwise. Has enough RAM/flash for MicroPython + TLS; does **not** run any ML model on-device (per the offline-training/gateway-inference split in Section 8) |
| **MPU6050** (3-axis accelerometer + 3-axis gyroscope, I2C) | Primary vibration/motion sensing — this is your main trust-evaluation feature source | I2C address `0x68` (default), connect `SDA`→GPIO21, `SCL`→GPIO22, `VCC`→3.3V, `GND`→GND on a typical ESP32 dev board. Confirm your board's actual default I2C pins before wiring — some dev board variants differ |
| **Vibration sensor** (assumed SW-420-style digital switch module, or an analog piezo — confirm which you have) | Secondary/confirmatory vibration signal, independent of the MPU6050 | If digital (SW-420): wire the `DO` pin to a GPIO configured as an interrupt input; treat readings as a binary event count per time window. If analog (piezo): wire to an ADC-capable GPIO and sample amplitude directly as a second continuous channel. **This second, independent sensor is deliberately useful for Zero Trust**, not just redundant — see the sensor-fusion-graph note in Section 5's GNN entry |

**One real device is enough to start.** The starter kit's existing
`device_simulator.py` already generates plausible telemetry for two
additional simulated devices (`sensor-002`, `actuator-001`). Recommended
approach for a 1-month, single-hardware-kit timeline: **run the one real
ESP32 alongside the existing Python-simulated nodes**, framed explicitly in
the paper as a hybrid testbed — "N simulated CPS nodes plus one physical
validation node" is a standard, defensible experimental design in CPS
research, not a compromise you need to apologise for. It also directly
supports the report's Section 5.2 claim that training happens offline and
only inference runs on constrained hardware: the real ESP32 is your proof
that the pipeline genuinely works on real constrained silicon, not just in
simulation.

**Do not attempt to fabricate additional device-to-device relationships
for the Graph Neural Network signal (Module 3) if you only have one
physical node.** Two legitimate options, pick one and state which in the
paper:
1. **Hybrid graph:** nodes = the one real ESP32 + the simulated devices
   already in the starter kit, edges = "communicated through the gateway
   in the same time window" (as originally designed in the
   implementation docs).
2. **Sensor-channel graph (recommended if you want the GNN result to say
   something about your *real* hardware specifically):** nodes = individual
   sensor channels on the one real device — accel-X, accel-Y, accel-Z,
   gyro-X, gyro-Y, gyro-Z, vibration-sensor — edges = statistical
   correlation between channels under normal operation. A GNN over this
   graph detects **coordinated cross-channel anomalies** (e.g. a vibration
   spike with no corresponding accelerometer signature, which is itself
   evidence of sensor spoofing or fault, not just "high vibration"). This
   is a genuinely interesting, real, single-device-compatible research
   contribution and is arguably a better fit for your actual hardware than
   forcing a multi-device graph.

---

## 3. Firmware: What to Build on the ESP32

**Language choice: MicroPython**, for three reasons specific to your
timeline — it lets the ESP32 firmware share almost identical logic
(HMAC construction, JSON message shape) with the existing Python gateway
and simulator code, it iterates far faster than a C/Arduino compile-flash
cycle during a 4-week build, and it's a completely legitimate, commonly
used choice for IoT research prototypes (note this choice explicitly in
your paper's implementation section, and note that a production
deployment would likely move to C/ESP-IDF for lower power draw and
smaller attack surface — say this once, in the paper's limitations or
future-work section, don't apologise for it repeatedly).

### Firmware responsibilities (map directly to Modules 1, 2, 3-feature-extraction, 6)

1. Read MPU6050 over I2C (raw accel + gyro).
2. Read the vibration sensor (digital event or analog sample).
3. Compute lightweight time-domain features on-device (Section 5 gives the
   exact feature list — RMS, peak, etc. This is cheap enough to run on the
   ESP32 itself; it is **not** the heavy ML inference, which stays at the
   gateway).
4. Sign the resulting feature payload with HMAC-SHA256 against the same
   shared-secret scheme already implemented in `src/device_simulator.py`
   and `src/gateway.py` (Modules 1/2 — reuse the existing design, don't
   invent a new one).
5. Publish over MQTT to the same `cps/telemetry` topic the gateway already
   subscribes to. **Your existing `gateway.py` needs zero changes to
   accept this** — MQTT already decouples the publisher's identity from
   the subscriber's logic; today `cps/telemetry` receives messages from a
   Python simulator, and it will accept messages from real firmware
   without any gateway-side code change, as long as the JSON envelope
   matches.

### Firmware skeleton (reference implementation — adapt as needed)

```python
# firmware/main.py -- runs on the ESP32 under MicroPython
import network, time, ujson, ubinascii, uhashlib
from machine import I2C, Pin, ADC
from umqtt.simple import MQTTClient

# ---- Config (mirror src/config.py's DEVICE_REGISTRY entry for this device) ----
DEVICE_ID = "esp32-vib-001"
SECRET = b"replace-with-a-real-shared-secret"   # provisioning: see Section 8
MQTT_HOST = "192.168.x.x"     # your gateway machine's LAN IP
MQTT_PORT = 1883               # switch to 8883 + TLS -- see docs/07_module6_secure_communication.md Section 3
                                # (NOTE: this whole sketch is superseded by the real, already-implemented
                                # firmware/main.py -- see that file, not this illustrative block, for the
                                # actual boot_id/seq/step-up/TLS-aware firmware)
TOPIC = b"cps/telemetry"

# ---- WiFi ----
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect("YOUR_SSID", "YOUR_PASSWORD")
while not wlan.isconnected():
    time.sleep(0.5)

# ---- MPU6050 (minimal register-level driver, no external lib needed) ----
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
MPU_ADDR = 0x68
i2c.writeto_mem(MPU_ADDR, 0x6B, b'\x00')   # wake the MPU6050 (PWR_MGMT_1 = 0)

def read_mpu6050():
    data = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)  # ACCEL_XOUT_H .. GYRO_ZOUT_L
    def s16(hi, lo):
        v = (hi << 8) | lo
        return v - 65536 if v > 32767 else v
    ax = s16(data[0], data[1]) / 16384.0   # g
    ay = s16(data[2], data[3]) / 16384.0
    az = s16(data[4], data[5]) / 16384.0
    gx = s16(data[8], data[9]) / 131.0     # deg/s
    gy = s16(data[10], data[11]) / 131.0
    gz = s16(data[12], data[13]) / 131.0
    return ax, ay, az, gx, gy, gz

# ---- Vibration sensor (adjust to digital-switch or analog, per Section 2) ----
vib_pin = ADC(Pin(34))          # example: analog piezo on GPIO34
vib_pin.atten(ADC.ATTN_11DB)

def read_vibration():
    return vib_pin.read()        # 0-4095 raw ADC; calibrate to a physical unit later

# ---- HMAC-SHA256, implemented manually for portability across MicroPython builds ----
def hmac_sha256(key: bytes, message: bytes) -> bytes:
    block_size = 64
    if len(key) > block_size:
        key = uhashlib.sha256(key).digest()
    key = key + b'\x00' * (block_size - len(key))
    o_pad = bytes(b ^ 0x5c for b in key)
    i_pad = bytes(b ^ 0x36 for b in key)
    inner = uhashlib.sha256(i_pad + message).digest()
    return uhashlib.sha256(o_pad + inner).digest()

def sign(payload: dict) -> str:
    # NOTE: must match src/device_simulator.py's canonicalisation exactly --
    # sorted keys, no extra whitespace -- or the gateway's HMAC check will
    # legitimately fail. Test this compatibility first, in isolation,
    # before wiring up the full sampling loop.
    canonical = ujson.dumps(payload, separators=(",", ":"), sort_keys=True)
    digest = hmac_sha256(SECRET, canonical.encode())
    return ubinascii.hexlify(digest).decode()

# ---- Feature extraction over a short window (see Section 5 for the full list) ----
def sample_window(n=32, dt_ms=10):
    accel_mags = []
    for _ in range(n):
        ax, ay, az, gx, gy, gz = read_mpu6050()
        accel_mags.append((ax**2 + ay**2 + az**2) ** 0.5)
        time.sleep_ms(dt_ms)
    rms = (sum(v**2 for v in accel_mags) / len(accel_mags)) ** 0.5
    peak = max(accel_mags)
    vib_raw = read_vibration()
    return {"device_id": DEVICE_ID, "rms_accel_g": round(rms, 4),
            "peak_accel_g": round(peak, 4), "vibration_raw": vib_raw, "ts": time.time()}

# ---- Main loop ----
client = MQTTClient(DEVICE_ID, MQTT_HOST, port=MQTT_PORT)
client.connect()

while True:
    payload = sample_window()
    signature = sign(payload)
    message = {"payload": payload, "signature": signature}
    client.publish(TOPIC, ujson.dumps(message))
    time.sleep(2)
```

**Before trusting this end to end:** verify the HMAC signature the ESP32
computes actually matches what `gateway.py`'s `verify_signature()` expects,
in isolation, by publishing one test message and checking the gateway logs
`auth=OK`. JSON canonicalisation mismatches (whitespace, key order,
float formatting) between MicroPython's `ujson` and CPython's `json` are
the single most likely first bug — budget real debugging time for this
specific integration point, don't assume it works on the first try.

### Registering the real device

Add it to `src/config.py`'s `DEVICE_REGISTRY` exactly like the simulated
devices, with an `expected_range` appropriate to the *feature* you're now
sending (e.g. `rms_accel_g` under normal operation, not a raw sensor
value) — you'll need a short baseline data-collection session (run the
device on your test rig under known-good conditions for a few minutes)
to set this sensibly rather than guessing.

---

## 4. Current State — Read Before Doing Anything Else

A working **core software implementation** (rule-based/static-threshold
version of all seven modules) already exists in `src/`, currently driven
by simulated telemetry only. Read, in this order, before writing new code:

1. `docs/00_overview.md` — the master as-built architecture overview
2. `docs/13_system_architecture_and_workflow.md` — the whole-system
   diagrams (layered architecture, message workflow, training pipeline,
   deployment topology) — read this before the per-module files if you
   want the shape of the system before its details
3. `docs/09_integration_and_data_flow.md` — the exact per-message call
   sequence, consolidated data schemas, and the module dependency graph
4. `docs/02_module1_device_identity.md` through
   `docs/08_module7_monitoring_and_audit.md` — one per module, each with
   Design Rationale, Failure Modes, Configuration Parameters, and
   Acceptance Criteria
5. `docs/12_model_validation_and_justification.md` — why each model
   (rule, Isolation Forest, LSTM-AE, Transformer, GNN, fusion, RL) earns
   its place, from a research-methodology standpoint, once you've read
   Module 3
6. The source itself: `src/config.py`, `src/trust_engine.py`,
   `src/policy_engine.py`, `src/gateway.py`, `src/device_simulator.py`,
   `src/audit_log.py`

The core system runs end-to-end today with simulated devices. Your
immediate task is (a) adding the real ESP32 as described in Section 3,
then (b) building out the advanced trust-evaluation and access-control
components described next.

---

## 5. Core Algorithms Reference — Full Detail

This section is the single place documenting every algorithm in the
system, the exact features it consumes, and why it's the right tool for
that job. Cite the bracketed reference numbers directly in the paper —
they correspond to the open-access journal sources in
`Zero_Trust_CPS_Project_Synopsis.docx`'s bibliography.

### 5.1 Feature Engineering (upstream of every algorithm below)

Raw signals available: `accel_x, accel_y, accel_z` (g), `gyro_x, gyro_y,
gyro_z` (deg/s), `vibration_raw` (ADC counts or binary event). Compute
these standard vibration-analysis features over a sliding window (industry
practice, not something specific to this project):

| Feature | Formula | What it captures |
|---|---|---|
| RMS acceleration magnitude | `sqrt(mean(ax²+ay²+az²))` over the window | Overall vibration energy — the primary severity indicator |
| Peak / peak-to-peak | `max(magnitude) - min(magnitude)` | Shock events, impacts |
| Crest factor | `peak / RMS` | Impulsiveness — high crest factor with normal RMS suggests early-stage bearing damage, a classic predictive-maintenance signature |
| Kurtosis | 4th standardised moment of the windowed signal | Sensitive to sharp, infrequent spikes that RMS alone smooths over |
| Dominant frequency / spectral energy | FFT of the windowed accel magnitude, take peak-magnitude frequency bin(s) | Frequency-domain fault signatures (unbalance ≈ 1× running speed, misalignment ≈ 2×, bearing defects at characteristic frequencies) — compute with `numpy.fft.rfft` at the gateway, not on the ESP32 |
| Vibration-sensor event rate | Count of trigger events per window (digital) or mean amplitude (analog) | Independent, lower-fidelity cross-check against the MPU6050-derived features — this is the second graph node for the sensor-channel GNN option in Section 2 |

Do the raw sampling and cheap features (RMS, peak) on the ESP32 (Section
3); do the FFT and anything needing more than a few dozen samples of
history at the **gateway**, consistent with the resource-constrained
design philosophy already established in the report.

**Honesty note for the paper's methodology/limitations section:** the
MPU6050 is a low-cost MEMS accelerometer, not an instrument calibrated to
industrial vibration-measurement standards. If you cite ISO 10816/20816
zone boundaries (Section 6), state explicitly that you're using the
standard's *zone concept* as an interpretive framework for a prototype,
not claiming certified-instrument compliance — reviewers respect this kind
of explicit scoping far more than an uncited or overclaimed comparison.
Also note: ISO 10816 zones are defined on vibration **velocity** (mm/s),
not acceleration — a fully standards-faithful pipeline would integrate the
accelerometer signal to velocity (with high-pass filtering to control
integration drift) before zone classification; using raw acceleration RMS
directly is a documented simplification, not an error, as long as you say
so.

### 5.2 Two-Score Architecture: Security Trust + Process Anomaly (shipped, Module 3/4/5 rearchitecture)

**Updated (see SESSION_LOG.md for the session that did this):** `src/trust_engine.py`
no longer produces one blended trust score. It now owns two permanently-separate
scores that are combined only inside `policy_engine.decide()`'s 2×2 table, never
before:

- **Security Trust Score** (`trust_engine.score_security_trust()`) — cyber-behaviour
  evidence ONLY: message rate/flood (`check_flood()`), step-up challenge outcomes,
  and time-decay for silence. EWMA over a per-message observation, same mechanism
  as the original rule-based engine, just with physical values and auth-failure
  counts removed from its inputs.
- **Process Anomaly Score** — physical sensor evidence ONLY, still exactly
  `fusion_engine.combine()`'s output (Sections 5.3–5.6 below, unchanged). Stored
  per device via `trust_engine.update_process_anomaly()`/`get_process_anomaly()`,
  retained exactly on silence (never decayed toward "normal" — only its
  `FRESH`/`STALE` status changes).

**Why this split exists — a real, fixed vulnerability, not a style preference:**
the single-score design let a failed-auth message (someone claiming a device's ID
without its secret) directly lower *that device's own* trust score — a
trust-poisoning attack. The fix (`trust_engine.IdentityTargetingRisk`) tracks
failed verification attempts per *claimed* device_id, completely separate from any
registered device's own state; a rejected message never reaches either score. See
`docs/03_module2_authentication.md` Section 5 for the full reasoning.

**Also fixed in the same pass:** anti-replay moved from a ts-size heuristic
(`REBOOT_TS_THRESHOLD_MS`, since removed) to a `boot_id`/`seq` scheme
(`trust_engine.check_boot_replay()`) that closes a real blind spot — a captured
pre-reboot message could previously be replayed after a legitimate reboot and
still be accepted. And `STEP_UP` is now a real gateway-issued-nonce/device-echo
challenge (`gateway.py::initiate_step_up()`/`trust_engine.check_step_up_response()`),
not just a policy label.

See `docs/04_module3_trust_evaluation.md`/`docs/05_module4_continuous_verification.md`
for the full walkthrough. Adapt the value-range rule to use `rms_accel_g` (or
whichever feature you settle on) instead of the generic `value` field once real
hardware is integrated — unchanged by this rearchitecture, still lives in the
Process Anomaly side (`rule_range_score()`).

### 5.3 Isolation Forest (Module 3, Phase 6a)

**Purpose:** unsupervised point-anomaly detection over the feature vector
`[rms, peak, crest_factor, kurtosis, dominant_freq]` — flags a single
reading that doesn't resemble the learned "normal operation" distribution,
without needing any labelled fault examples.
**Library:** `scikit-learn.ensemble.IsolationForest`.
**Why this algorithm specifically:** trains in milliseconds on a few
hundred samples, needs no GPU, and — critically for this project — needs
no labelled attack/fault data, which matters because you won't have a
large real-fault dataset in one month [17]–[20].
**Feasibility on your timeline:** trivial — this should be your first
working ML component, likely completable in under a day once real data is
flowing.

### 5.4 LSTM-Autoencoder (Module 3, Phase 6b)

**Purpose:** temporal anomaly detection — learns to reconstruct *sequences*
of the feature vector above under normal operation; a rising reconstruction
error signals the device's behaviour is drifting from its learned normal
pattern over time, which point-in-time models (rule-based, Isolation
Forest) cannot see by construction. This is a strong, natural fit for
vibration data specifically, since real mechanical degradation (e.g.
bearing wear) is a *gradual drift*, not a single anomalous reading — this
is arguably your single best real-data result opportunity given your
hardware.
**Library:** PyTorch or TensorFlow/Keras; a 1-2 layer LSTM encoder/decoder
over rolling windows of the feature vector is sufficient — do not over-
engineer the model size, a small model trained on your own collected data
is both more appropriate and more defensible in a viva than a large one.
**Update (real GPU became available, see SESSION_LOG.md):** this guidance
was written when the project ran CPU-only. Once a real GPU (RTX 5060) was
available, capacity was deliberately increased (8→16 hidden units, still
1 layer) — verified NOT to be over-engineering via `evaluate_ablation.py`
on held-out data: an initial, more aggressive attempt (32 hidden, 2
layers) measurably OVERFIT the ~345 training windows (held-out accuracy
and recall both got WORSE despite training loss dropping much further) and
was dialled back. The underlying principle this section states — model
size should be justified by what held-out data supports, not by what
hardware happens to be available — still holds; only the specific number
changed once there was real evidence supporting a modest increase.
**Grounded in:** [37].
**Feasibility on your timeline:** moderate — the real cost is *data
collection* (you need enough normal-operation time-series from your actual
rig to train on), not model complexity. Schedule a dedicated data-collection
session early (Week 2, see Section 10) specifically so this has time to
train before the deadline.

### 5.5 Graph Neural Network (Module 3, Phase 6c)

**Purpose:** relational anomaly detection — see Section 2 for the two
concrete graph-construction options given your hardware (hybrid
device-graph vs. sensor-channel graph). Catches anomalies that only show
up as a *pattern across multiple signals/devices simultaneously*, not in
any single signal alone.
**Library:** PyTorch Geometric (or DGL).
**Update (real GPU became available, see SESSION_LOG.md):** hidden size
and depth increased (8→32 hidden units, 2→3 GCN layers) once a real GPU
(RTX 5060) was available and the training loop was batched to actually
use it (the original per-snapshot Python loop was ~6.5x SLOWER on GPU than
CPU purely from kernel-launch overhead — see that log for the full
diagnosis and fix). Unlike the LSTM-AE above, this increase measurably
IMPROVED held-out generalisation (`coordinated`-attack recall for the GNN
signal alone: 0.870 → 1.000, verified via `evaluate_ablation.py`), not
overfitting — plausible given the GNN trains over all 1220 snapshots
(one per message) rather than the LSTM-AE's much smaller ~345-window
training set, giving it more data to support the added capacity.
**Grounded in:** [27]–[30].
**Feasibility on your timeline: this is your highest-risk component.**
Be honest with yourself and the user about this. If Weeks 1–3 run behind
schedule, this is the first component to scope down to "designed, with
architecture given, but evaluated on synthetic/simulated graph data only"
rather than fully evaluated on real hardware — that is a completely
standard, acceptable framing for a research paper's future-work section,
and is much better than rushing a broken implementation.

### 5.6 Stacking Meta-Learner Fusion (Module 3, Phase 7)

**Purpose:** combines the four signals above (rule-based, IF, LSTM-AE,
GNN) into the **Process Anomaly Score** by learning which signal to trust
more in which situation, rather than hand-tuned averaging. Updated (Section
5.2): this is no longer "the" trust score — it is one of two permanently-
separate scores, and never sees Security Trust's inputs (auth/rate/step-up)
at all. Ground truth for training is `physical_label(event_type)`
(`scripts/generate_training_data.py`), not the old blended `label` — a
`high_rate` record's features are genuinely normal, and training against
the blended label taught the meta-learner that ordinary-looking features
sometimes mean "suspicious," a real, measured regression caught and fixed
in the same session (see SESSION_LOG.md).
**Library:** `scikit-learn.linear_model.LogisticRegression` (or a shallow
`DecisionTreeClassifier` if you want the fused decision itself to be
directly human-readable, which is a nice property to have for the paper's
explainability discussion).
**Training data:** your own adversarial-testing sessions (Section 9) —
physically inducing anomalies on the real rig (tapping the sensor,
briefly loosening a mount, simulating a sensor fault by disconnecting a
wire momentarily) and labelling those windows, combined with the
simulator's software-injected anomalies for the simulated devices.
**Grounded in:** synthesis of [17]–[21] design pattern, novel combination
per the report's Section 4.1 Novelty Statement.

### 5.7 SHAP Explainability (Module 3, Phase 7)

**Purpose:** per-decision reason code — which feature (or which of the
four fused signals) drove a given trust score down, expressed in a form a
non-ML-expert reviewer (or governance auditor) can read.
**Library:** `shap.Explainer` over the meta-learner from 5.6 — this is
close to zero extra engineering once the meta-learner exists, since SHAP
works directly on scikit-learn models.
**Grounded in:** [33]–[36], which specifically found SHAP more consistent
than LIME for structured security/sensor telemetry — cite this as your
justification for choosing SHAP over LIME, don't just assert it.

### 5.8 RL-Adaptive Access Control (Module 5, Phase 8)

**Purpose:** replaces the static 2×2 table (Section 5.2 — ALLOW / ALERT /
STEP_UP / BLOCK, reading Security Trust + Process Anomaly together) with a
policy that learns better boundaries from the outcomes of its own past
decisions.
**Implementation:** an epsilon-greedy contextual bandit — state =
`(bucketed security_trust_score, bucketed process_trust_score)`, action =
`{ALLOW, STEP_UP, ALERT, BLOCK}`, reward = correctness against a
`(situation)` ground truth derived from `event_type`
(`normal`/`physical_fault`/`security_concern`/`combined` —
`docs/10_testing_and_attack_simulation.md` Section 4.1), weighted by
inverse class frequency (`scripts/train_adaptive_pdp.py::situation_weights()`,
the direct RL analogue of 5.6's `class_weight="balanced"` fix — needed for
the same underlying imbalance reason, verified empirically before adding
it) — see `src/adaptive_pdp.py` and `scripts/train_adaptive_pdp.py`.
**Why this is safe as the LIVE default, not just a stretch goal:**
`AdaptivePDP.greedy_action()` (the only method the live gateway calls) is
a frozen Q-table lookup with no exploration and no `update()` call — it
needs no live reward signal at all, since it never learns online; only
offline training (against known synthetic ground truth) ever calls
`update()`. This is the property that makes `USE_RL_POLICY=True` the safe
default (`src/config.py`), not a live-feedback-loop risk. Do not reach for
a full deep-RL framework (Stable-Baselines3, PPO, etc.) — the state/action
space here is small and simple enough that a hand-rolled bandit is both
sufficient and considerably easier to explain and defend than a deep-RL
black box would be.
**Grounded in:** [31], [32].
**Feasibility on your timeline:** straightforward once the fusion engine
(5.6) exists and you have labelled outcome data — plan for Week 4.

---

## 6. Industry Standards to Align With

Citing real standards (not just academic papers) is what makes this
"industry implementable" rather than purely academic, and gives you
concrete numeric thresholds to justify design choices in the paper instead
of arbitrary constants.

- **NIST SP 800-207** — Zero Trust Architecture. Already the project's
  governance backbone; every access decision should be traceable to a
  specific tenet (see `docs/08_module7_monitoring_and_audit.md` Section 5
  for the mapping table pattern).
- **IEC 62443** — the dominant industrial automation and control systems
  (IACS) security standard series. Specifically relevant: its
  zones-and-conduits security model maps naturally onto this project's
  Layer 1/2/3 architecture (Report Section 7), and its security-level
  concept (SL 1–4) gives you a vocabulary for stating what level of
  attacker sophistication your prototype is designed to resist. Cite this
  explicitly in the paper as the standard your architecture is compatible
  with — it substantially strengthens an "industry implementable" claim
  for reviewers who work in OT/ICS security specifically.
- **ISO 10816 / ISO 20816** — mechanical vibration severity evaluation
  (A/B/C/D zones based on RMS velocity). Use this to justify your
  rule-based trust engine's anomaly thresholds (Section 5.1's honesty
  note applies — state the acceleration-vs-velocity simplification
  explicitly). Representative verified figures you can cite: for
  medium-sized (Class II), rigidly-mounted machines under ISO 10816-3,
  roughly 1.4 mm/s RMS velocity or below is typical of a newly
  commissioned machine, ~2.8 mm/s is the acceptable/unsatisfactory (B/C)
  boundary, and ~4.5 mm/s is a commonly cited unsatisfactory/alarm
  reference point — confirm the exact boundary for your specific machine
  class and mounting from the standard itself before finalising paper
  figures, since exact values are class- and mounting-dependent.
- **MQTT Sparkplug B** (optional, mention as a discussion/future-work
  point) — the industrial-IoT-standard payload specification for MQTT,
  used for interoperability with real SCADA/MES systems. Worth one
  sentence in the paper noting your current custom JSON envelope could be
  migrated to Sparkplug B for industrial interoperability — you do not
  need to actually implement this given the timeline, just show awareness
  of the standard.

---

## 7. Phase Plan (What to Build, in Order)

| Phase | What | Primary doc |
|---|---|---|
| 0 (NEW) | Hardware bring-up: wire ESP32+MPU6050+vibration sensor, verify raw readings, write and test firmware per Section 3 | Section 3 above, `firmware/HARDWARE_SETUP.md` |
| 6a | Isolation Forest trust signal | `docs/04_module3_trust_evaluation.md` Section B.3; Section 5.3 above |
| 6b | LSTM-Autoencoder trust signal | Section 5.4 above |
| 6c | Graph Neural Network trust signal (scope per Section 2's two options; treat as highest-risk, first to descope if behind schedule) | Section 5.5 above |
| 7 | Stacking meta-learner fusion + SHAP | Section 5.6, 5.7 above |
| 8 | RL-adaptive Access Control | `docs/06_module5_access_control.md` Section 4; Section 5.8 above |
| 9 | Monitoring dashboard (Streamlit) + NIST 800-207 / IEC 62443 governance-mapping view | `docs/08_module7_monitoring_and_audit.md` Section 4-5 |

Do not skip ahead — each phase's output is another phase's input (the
fusion engine needs all four signals producing real output first; the RL
policy needs the fusion engine's confidence output to be worth upgrading
to).

---

## 8. Hard Constraints — Do Not Violate These

- **Interface contracts stay stable, but the two-score split (Section 5.2)
  was a deliberate, one-time exception to this rule, not a precedent for
  casual restructuring.** The load-bearing shapes now are
  `trust_engine.score_security_trust(device_id, is_flood, step_up_result)
  -> (security_trust_score, reason)` and `policy_engine.decide(security_trust_score,
  process_trust_score, process_status) -> decision`. This changed because
  the single-score design had two real, exploitable vulnerabilities (see
  Section 5.2) — that bar (a genuine, fixed vulnerability) is what
  justifies breaking an interface contract; a design preference does not.
- **A rejected message (unknown device, bad HMAC, boot/seq replay, stale
  timestamp) never touches a registered device's own Security Trust or
  Process Anomaly state.** It is routed to `trust_engine.IdentityTargetingRisk`,
  keyed by the *claimed* device_id, exclusively. Do not reintroduce a path
  where `auth_ok=False` (or a detected replay) feeds directly into a named
  device's own score — that is precisely the trust-poisoning vulnerability
  Section 5.2 fixed.
- **Every evaluation/training script that redirects `audit_log.AUDIT_DB_PATH`
  to a throwaway database must ALSO redirect `CHECKPOINT_STORE_PATH` and
  `AUDIT_KEY_PATH`.** Found live, not theorized: a script that redirected
  only `AUDIT_DB_PATH` left its checkpoint writes going to the real,
  shared checkpoint file, silently poisoning the live audit log's
  tamper-detection with checkpoints that describe an unrelated throwaway
  database (`scripts/evaluate_latency.py`'s comment documents the exact
  failure mode this caused).
- **Train offline, infer at the gateway.** GNN/LSTM-AE/meta-learner
  training happens in standalone scripts (`scripts/train_*.py`) producing
  saved model artifacts; `gateway.py` only ever loads and runs inference,
  never trains, in the live path. This is what keeps the "resource-
  constrained" claim true even on the real ESP32.
- **No external labelled attack/fault datasets.** Every model trains on
  data you actually generated — real physical anomaly-induction sessions
  on your hardware (Section 9), plus the existing simulator's injected
  anomalies. This is both a feasibility requirement and a genuine
  methodological strength worth stating explicitly in the paper: your
  results are grounded in your own testbed, not a possibly-unrepresentative
  public IDS dataset.
- **Secret provisioning.** For this prototype, hardcoding the shared
  secret in firmware (Section 3) is acceptable — but say so explicitly as
  a stated simplification in the paper, and note the IEC 62443-aligned
  production path (secure element, flash encryption, per-device
  provisioning at manufacture time) as future work rather than silently
  ignoring it.
- **Every new algorithm choice must cite a literature reference.** Section
  5 above gives you the reference numbers for each — use them.
- **Every decision still gets logged**, including ones produced by real
  hardware telemetry. Use a separate test database during offline
  training/evaluation runs so you don't pollute the live audit log.
- **Keep the seven-module scope fixed.**

## 9. Compressed 4-Week Timeline (Realistic, Prioritised)

Be honest with the user if any week starts slipping — better to descope
the GNN (Phase 6c) explicitly and say so in the paper than to submit a
rushed, broken version of everything.

**Week 1 — Hardware + core pipeline on real data**
Days 1–2: wire and bring up ESP32+MPU6050+vibration sensor, confirm raw
readings over serial. Days 3–4: firmware — sampling, feature extraction,
HMAC signing, MQTT publish (plaintext first). Days 5–7: register the
device in the gateway, confirm Modules 1/2/6/7 work end-to-end with real
hardware alongside the existing simulated nodes; run a baseline data
collection session on your test rig under normal operating conditions.

**Week 2 — Isolation Forest + adversarial data collection**
Adapt the rule-based engine's thresholds to your real vibration features
(Section 5.1/5.2). Implement and train Isolation Forest (5.3) on your
collected baseline data. **Schedule a dedicated adversarial-data session**:
physically induce several distinct anomaly types on the rig (tap/shock,
loosened mount, sensor disconnect, simulated imbalance) and label the
resulting windows — you need this labelled set for Phases 7 and 8, so
collecting it late is the single most likely cause of a Week 4 crunch.

**Week 3 — LSTM-Autoencoder, fusion, SHAP; GNN if time allows**
Train the LSTM-AE (5.4) on your normal-operation time-series. Build the
stacking meta-learner (5.6) and SHAP layer (5.7) using your labelled
adversarial data. Attempt the GNN (5.5) only if the above are solid —
otherwise document its architecture and defer evaluation to future work.

**Week 4 — RL policy, dashboard, evaluation, paper writing**
Implement the RL-adaptive PDP (5.8) if time allows, else keep the static
threshold and report it as the evaluated baseline with RL as designed-only.
Build the Streamlit dashboard and governance-mapping view (Phase 9). Run
the full evaluation suite (Section 10 below). Draft the paper — your
existing docx report already gives you most of the Abstract, Related Work,
and Methodology sections; Week 4 is primarily about writing Results,
Discussion, and Conclusion from your actual measured data, plus building
presentation slides.

---

## 10. Verification and Evaluation

**`RESULTS.md`** is the current, populated version of the deliverables
list below — every synthetic-data figure requested here has already been
produced, written up with explanations and caveats, and includes a
reserved Section 13 for the real-hardware items still outstanding.

Manual verification after every phase (run `gateway.py` +
`device_simulator.py` + the real ESP32, confirm no exceptions, confirm
trust scores react sensibly to both simulated and real physically-induced
anomalies, confirm audit log rows look right) — see the verification
steps in `docs/09_integration_and_data_flow.md` Section 3.1, now extended
to include the real device.

For the paper, per report Section 10, produce:
- Ablation: fused score vs. each individual signal's standalone accuracy
  on your labelled adversarial-test set.
- Authentication and gateway-inference latency, measured on the real
  ESP32 and the Pi-class (or laptop) gateway, compared against [22],
  [23], [24]'s published baselines.
- SHAP reason codes reviewed against your known ground-truth anomaly
  labels — do the top-ranked features make physical sense (e.g. does a
  physically-tapped sensor event get attributed to the acceleration/
  kurtosis features, not something spurious)?
- RL policy reward trend vs. the static-threshold baseline, if Phase 8 was
  completed.
- A NIST SP 800-207 + IEC 62443 tenet-mapping table generated from the
  audit log.

## 11. Repository Conventions

Same as before, plus:
- New top-level `firmware/` directory for the ESP32 MicroPython code
  (`firmware/main.py`, plus any driver helper modules).
- New `scripts/` directory for offline training scripts, one per model
  (`scripts/train_isolation_forest.py`, `scripts/train_lstm_ae.py`,
  `scripts/train_gnn.py`, `scripts/train_fusion_meta_learner.py`, plus
  `scripts/train_transformer.py` — a fifth, ablation-only Process Anomaly
  candidate, not part of the trained-model set `train_fusion_meta_learner.py`
  actually consumes; see `docs/04_module3_trust_evaluation.md` Section
  B.5b and `RESULTS.md` Section 2.2).
- New scorer files in `src/`: `isolation_forest_scorer.py`,
  `lstm_ae_scorer.py`, `gnn_scorer.py`, `transformer_scorer.py`,
  `fusion_engine.py`, `adaptive_pdp.py`, `dashboard.py` — one model, one
  file, matching the existing per-module file convention.
- Data collected from the real hardware (baseline + adversarial sessions)
  goes in a new `data/collected/` directory, checked into version control
  if small enough, or documented with a collection script if not — either
  way, this dataset is itself a citable artifact of your paper.

## 12. Definition of Done

The project is complete when every item in Section 10's evaluation list
can actually be produced from real measurements — not when the code merely
runs without errors. If a component (most likely the GNN) doesn't reach
that bar in the available time, that's an acceptable, common outcome for a
one-month timeline — document it honestly as implemented-but-not-fully-
evaluated or designed-but-not-implemented in the paper's future-work
section, rather than overclaiming or quietly hiding the gap.
