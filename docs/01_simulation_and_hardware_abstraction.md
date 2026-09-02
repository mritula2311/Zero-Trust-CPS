# 01 — Simulation and Hardware Abstraction Layer

> **AS-BUILT NOTE:** the message schema below (Section 2) is implemented
> exactly, including `boot_id`/`seq` and the optional `step_up_nonce_echo`
> field. The device fleet is hybrid, not uniform: `esp32-vib-001` publishes
> a 5-feature vibration vector (`rms, peak, crest_factor, kurtosis,
> dominant_freq`, computed on-device) rather than raw 6-channel accel+gyro,
> alongside two legacy scalar devices (`sensor-002`, `actuator-001`) —
> `src/config.py`'s `DEVICE_REGISTRY`. `firmware/main.py` implements
> Section 5's firmware spec (boot_id persisted to a local file as the
> flash-equivalent, NTP time sync, step-up echo) and **has since been
> flashed to a real ESP32 + MPU6050, authenticated, and run live** — no
> longer software-only. Real bring-up surfaced bugs no amount of
> synthetic-value checking could (a MicroPython epoch mismatch, an
> `ussl`/`ssl` module rename, intermittent NTP timeouts, and — from
> physically manipulating the board — an I2C-vs-MQTT exception-handling
> bug and a missing `rms` rule-check floor), all found and fixed; see
> `RESULTS.md` Section 13 for the full real-hardware results and
> `firmware/HARDWARE_SETUP.md` for the current bring-up guide. See
> `00_overview.md`'s AS-BUILT callout for the full list of deviations and
> `SESSION_LOG.md` for the narrative.

**Read this before implementing any of Modules 1–7.** This is the layer that makes the entire project buildable and testable today, with zero hardware, and lets the real ESP32 + MPU6050 slot in later without touching any downstream module.

## 1. Purpose

Every module from Device Identity through Monitoring must be written against one interface: a stream of already-formed, already-signed telemetry messages arriving over MQTT. It must not matter to any of those modules whether the message originated from a MicroPython ESP32 or from a Python process pretending to be one. This document defines that interface and the two implementations that satisfy it.

## 2. The Message Schema (the actual contract)

This is the one schema every downstream module receives, regardless of source. Field names and types are fixed; do not vary them between simulation and hardware.

```
TelemetryMessage:
  device_id      : string            # e.g. "esp32-node-01"
  boot_id        : integer           # increments by exactly 1 each time the device boots,
                                      # persisted in flash and written once per boot (not
                                      # once per message) — see Section 5.1 point 3 and
                                      # 03_module2_authentication.md Section 4 for why this exists
  seq            : integer           # strictly increasing WITHIN a boot_id, starts at 1 on every boot
  timestamp      : float             # Unix epoch seconds, device clock
  accel_x        : float             # g
  accel_y        : float             # g
  accel_z        : float             # g
  gyro_x         : float             # deg/s
  gyro_y         : float             # deg/s
  gyro_z         : float             # deg/s
  key_version    : integer           # which registry key this HMAC was computed with
  hmac           : string (hex)      # HMAC-SHA256 over the canonical payload (see 03_module2)
```

### 2.1 Why `boot_id` Exists

A device that reboots restarts its in-memory `seq` counter. Without something to distinguish boot sessions, a gateway that simply enforces "seq must strictly increase" would reject every message after a legitimate reboot, since the new session's `seq=1` looks smaller than whatever the previous session last reached (e.g., 10493). `boot_id` fixes this cleanly: it is a small counter persisted in flash and incremented exactly once per boot (one flash write per reboot, not per message — far gentler on flash wear than persisting `seq` itself would be). The gateway's rule (fully specified in `03_module2_authentication.md` Section 4) is: a strictly higher `boot_id` always starts a fresh, trusted `seq` count at 1; a repeated `boot_id` must still have a strictly increasing `seq`. This also closes a replay variant the reviewed design initially missed: an attacker who captured an entire old boot session (old `boot_id` and its sequence of messages) cannot replay it, because that `boot_id` has already been superseded by a higher one and is permanently rejected from that point forward.


Canonical serialization rule (must match exactly between simulator, hardware firmware, and gateway, or HMAC verification will fail): fields serialized as JSON with keys sorted alphabetically, no extra whitespace, `hmac` field itself excluded from the signed payload. This exact rule is documented again in `03_module2_authentication.md` since Module 2 owns HMAC verification — it is repeated here because the simulator must also produce it correctly.

## 3. The Abstract Interface

```
interface DeviceDataSource:
    def start(self) -> None
        # Begin producing telemetry (spawns a thread/process/async task per device)

    def stop(self) -> None
        # Cleanly stop all devices

    def list_devices(self) -> list[str]
        # Device IDs currently active in this source

    # Messages are not pulled from this interface directly — both implementations
    # publish to MQTT topics (Module 6), and everything downstream subscribes there.
    # This keeps the abstraction boundary at the transport layer, not inside application code.
```

The key design decision: **the abstraction boundary is the MQTT broker itself.** Modules 1–5 and 7 never import or reference `DeviceDataSource`, `SimulatedDevice`, or `HardwareDevice` at all — they only ever subscribe to `cps/telemetry/+` and receive `TelemetryMessage`-shaped JSON. This is stronger and simpler than a shared Python interface: it means hardware integration later requires zero changes to any Python module, only flashing firmware that publishes correctly-shaped, correctly-signed JSON to the same broker.

## 4. Implementation A — Simulated Device

### 4.1 Responsibilities

- Generate realistic MPU6050-shaped readings at a configurable rate (default: 1 message every 2 seconds, matching the real sensor's expected polling rate).
- Maintain its own `seq` counter and current `key_version`, exactly as real firmware would.
- Compute a real HMAC using the device's registered secret (read from the same device registry Module 1 uses — the simulator is a client of Module 1's registry, not a separate identity source).
- Publish to the same MQTT topics real hardware will use.
- On command, inject any scenario from the attack matrix (`10_testing_and_attack_simulation.md`) — this is what makes labelled test-data generation possible without hardware.

### 4.2 Normal-Data Generation Model

Resting/idle MPU6050 behaviour (used as the "normal" baseline):

```
accel_x, accel_y ~ Normal(mean=0.0, std=0.02)     # g, small noise around level
accel_z           ~ Normal(mean=1.0, std=0.02)     # g, gravity dominates one axis
gyro_x, gyro_y, gyro_z ~ Normal(mean=0.0, std=0.5)  # deg/s, near-zero when still
```

Add a slow-varying component to each channel (a random walk with small step size) so the baseline is not pure white noise — this matters for the LSTM-Autoencoder in Module 3, which is specifically designed to catch *drift*, and needs a simulator that actually produces mild, realistic drift to be meaningfully testable.

### 4.3 Configurable Scenario Injection

The simulator must expose a control surface (a small local HTTP/CLI/function-call interface is fine — this is a test tool, not part of the production message path) to switch each device into a named scenario:

```
set_scenario(device_id, scenario, **params)

Scenarios (map directly to the attack matrix):
  "normal"                 — baseline behaviour, no injection
  "physical_spike"         — inject a burst of high accel/gyro values (params: magnitude, duration_s)
  "physical_drift"         — slowly shift baseline over time (params: drift_rate)
  "forged_id"              — publish using a device_id not in the registry
  "bad_hmac"               — compute HMAC with a wrong/garbage secret
  "altered_payload"        — sign one payload, then mutate a field before publishing
  "replay"                 — re-publish a previously captured valid message verbatim
  "high_rate"              — publish at N times the normal rate (params: multiplier)
  "auth_failure_burst"     — repeatedly send bad_hmac messages in a short window (params: count, window_s)
  "reboot"                 — increment this device's boot_id, reset its in-memory seq to 1,
                              and resume publishing — used to test that Module 2 accepts the
                              new boot session instead of rejecting it as a replay
  "stealthy_forged_values" — a compromised-device simulation: publish otherwise fully valid,
                              correctly-signed messages (real device_id, correct boot_id/seq,
                              real key) whose sensor values are deliberately fabricated to sit
                              inside the learned normal range, rather than reflecting whatever
                              the simulator's underlying physical model actually computed for
                              that moment (params: target_value per channel). This exists to
                              test the explicitly-acknowledged detection limit described in
                              04_module3_trust_evaluation.md Section B.8 and
                              10_testing_and_attack_simulation.md Section 2, row 11 — it is not
                              expected to be reliably caught by this project's single-node design.
```

### 4.4 Multi-Node Simulation

The simulator must support running several devices concurrently (recommend 3–5, matching the project's stated preference for multi-node testing wherever possible — see `04_module3_trust_evaluation.md` Section on the GNN). Each simulated device is independent: its own `seq` counter, its own key, its own scenario state. This is what allows the GNN component to be developed and tested against a genuine multi-device graph *before* physical hardware exists, rather than being stuck with the weaker single-device six-channel fallback from day one.

### 4.5 Time Acceleration for Baseline Collection

The project synopsis calls for a multi-day baseline collection to avoid the short-baseline problem the design review flagged. In simulation, this does not require literally waiting multiple days: the simulator should support a `time_scale` parameter (e.g., `time_scale=100` compresses 100 simulated seconds into 1 real second) so a "3 simulated days" baseline can be generated in minutes. Record simulated timestamps (not wall-clock) in the `timestamp` field so downstream time-of-day/drift features remain meaningful.

## 5. Implementation B — Hardware Device (specification for later)

This section specifies what the ESP32 firmware must do to be a drop-in replacement for the simulator.

> **AS-BUILT:** the firmware exists (`firmware/main.py`), is flashed, and has
> been running against the live gateway. The contract below held up — see §5.2's
> AS-BUILT note for how it was verified and for a second, subtler equivalence
> risk that this specification did not anticipate and that turned out to matter
> more than the one it did.

### 5.1 Firmware Responsibilities

1. On boot, read `device_id`, `secret_key`, and `key_version` from on-device flash storage (provisioned once, per `02_module1_device_identity.md` Section on provisioning). Read the persisted `boot_id` counter from flash, increment it by 1, and write the new value back to flash immediately — this is the only per-boot flash write this scheme requires.
2. Read the MPU6050 over I2C (SDA → GPIO21, SCL → GPIO22 on standard ESP32 boards; wake the sensor via `PWR_MGMT_1` register, read 14 bytes starting at `ACCEL_XOUT_H`).
3. Maintain an in-memory `seq` counter starting at 1 for this boot session (it does **not** need to be persisted across reboots — `boot_id` already handles the reboot case, so `seq` can safely reset to 1 every time, which is exactly what makes this scheme cheap on flash wear compared to persisting `seq` itself).
4. Build the canonical JSON payload exactly as Section 2 specifies, compute HMAC-SHA256 using MicroPython's `uhashlib`/`hmac`, and publish over MQTT/TLS using `umqtt.simple`.
5. Subscribe to its own challenge topic (`cps/challenge/{device_id}`) to support step-up authentication (Module 2, Module 5).

### 5.2 The One Integration Risk to Test First

MicroPython's `ujson` and the gateway's CPython `json` can serialize floats or key ordering slightly differently. **The very first hardware integration test, before anything else, must be:** publish one real message from the ESP32, and confirm the gateway's independently computed HMAC matches the one the firmware sent. If it does not, the canonicalization rule (Section 2) needs a firmware-side fix before any other module can be trusted against real hardware.

> **AS-BUILT — this risk was real, and the mitigation was to stop trusting the
> JSON encoder at all.** `firmware/main.py` does *not* call `ujson.dumps()` to
> build the signed payload. It constructs the canonical string by hand
> (`canonical_json()` + `format_py_float()`): every value is pre-rendered as a
> JSON literal, keys are sorted explicitly, and the separators (`", "` between
> pairs, `": "` within one) match CPython's `json.dumps(payload, sort_keys=True)`
> defaults exactly. `format_py_float()` renders with 4 decimals then strips
> trailing zeros, restoring a single `.0` so that `1.0` does not become `1.`.
> This means the firmware never depends on a MicroPython JSON encoder matching
> CPython's float formatting — it sidesteps the entire class of risk rather than
> hoping the two agree.
>
> **The verification is stronger than the one-message test specified above.**
> Hundreds of consecutive messages have been accepted with **zero
> `hmac_mismatch`**. That is a continuous proof, not a one-off: the HMAC covers
> the canonical string byte-for-byte, so a single mismatched float rendering — in
> any field, on any message — would reject that message immediately. Sustained
> acceptance across varied readings (values spanning `0.0087` to `3.4386`, both
> signs of kurtosis, and the optional `step_up_nonce_echo` field appearing and
> disappearing) is what actually establishes equivalence.

### 5.2b The Second Equivalence Risk — the one this spec missed

Canonicalisation equivalence is necessary but **not sufficient**. A message can
be perfectly signed and still carry a *numerically wrong* feature, because the
five features are computed **on-device** (§5.1 item 2) while every model is
trained against `src/feature_engineering.py`. Those are two independent
implementations of the same maths, and nothing in the message format can detect
a disagreement between them — the HMAC signs whatever number the device
computed, correct or not.

This was not hypothetical. Re-implementing the firmware's extraction in CPython
and diffing it against `feature_engineering.py` over 300 windows in three signal
regimes found:

| Feature | Agreement with reference |
|---|---|
| `rms` | exact |
| `peak` | exact |
| `crest_factor` | exact |
| `kurtosis` | exact |
| **`dominant_freq`** | **wrong bin in 57/300 windows (19%), by up to 46.9 Hz** |

The cause was a hand-rolled truncated-Taylor `_sin()` with up to **7.5e-2**
error over `[0, 2π]`, which corrupted the on-device DFT's bin selection. Because
the models train on the reference implementation, this was a **silent train/serve
skew that existed only on real telemetry** — invisible to every simulated row and
to every offline evaluation script. Replacing it with `math.sin`/`math.cos`
(present in every standard ESP32 MicroPython build) reproduces the reference
exactly: **0/300 mismatches**. See `RESULTS.md` §0.5.

**The generalisable lesson for this layer:** when features are computed on the
device, the hardware/simulation abstraction has *two* contracts, not one — the
message format, and the feature mathematics. Only the first is enforced by the
protocol. The second needs its own differential test, and the cheap version is
what was used here: re-implement the device maths in CPython and diff it against
the reference over randomised windows. That test now belongs in §6's acceptance
criteria.

### 5.2c A third integration point: wall-clock time

Also not anticipated here. The gateway's secondary freshness check
(`check_timestamp_freshness`) compares the device's self-reported `ts` against
the gateway's own clock, so the two clocks must agree to within
`config.REPLAY_WINDOW_SECONDS`. Two device-side corrections are required and
neither is obvious:

1. MicroPython's `time.time()` counts from **2000-01-01**, not the Unix epoch,
   so a fixed `946684800` s must be added or every message looks ~30 years stale.
2. If NTP is unreachable — which is the case on an isolated hotspot — the RTC
   holds whatever last set it. Thonny syncs it with `local_rtc: True`, i.e.
   **local** time, so an uncorrected clock lands exactly one timezone offset in
   the future. Measured at **+19,784 s**, precisely IST's +5:30, and every
   message was rejected as `stale_timestamp`.

`firmware/main.py` applies `RTC_LOCAL_UTC_OFFSET_SECONDS` **only when
`sync_time()` reports NTP failed**, so a working NTP route bypasses it
automatically. See `firmware/HARDWARE_DATA_LOG.md` §5.

### 5.3 Switching Modes

```
config.yaml:
  device_mode: simulation   # or: hardware

# When device_mode = simulation:
#   the simulator process (Section 4) is started, publishing to the broker.
# When device_mode = hardware:
#   the simulator process is not started; real ESP32 firmware publishes instead.
# No other module reads this config key. Modules 1–7 are identical in both modes.
```

## 6. Acceptance Criteria for This Layer

- A simulated device publishes a valid, correctly-signed message that Module 2's verifier accepts.
- **The hardware device's on-device feature maths matches `src/feature_engineering.py`** — the reference implementation the models are trained against — verified by a differential test over randomised windows, not by inspection. Signature validity does not imply numerical equivalence (§5.2b).
- Each attack-matrix scenario in Section 4.3 can be triggered on command and produces a message that Module 2 or Module 3 correctly flags.
- At least 3 simulated devices can run concurrently with independent state.
- Switching `device_mode` in config requires editing exactly one value, and no code in Modules 1–7 references `device_mode` directly.

Continue to `02_module1_device_identity.md`.
