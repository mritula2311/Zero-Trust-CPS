# Hardware Setup — `esp32-vib-002` (ESP32 + SW-420)

> **Audit qualification (2026-09-05):** MPU6050 captures exist; SW-420
> captures remain pending. SW-420 is another modality, not another MPU6050.
> Firmware peer-certificate verification is not established; see
> [Astra audit](../docs/ASTRA_AUDIT.md) before relying on deployment claims.

Second physical node. Read `HARDWARE_SETUP.md` first for the shared parts
(flashing MicroPython, Thonny, the hotspot, Mosquitto/TLS) — this document
covers only what differs.

---

## 1. What this sensor is, and what it is not

The SW-420 is a **vibration switch**, not an accelerometer.

A spring-and-pin contact inside the module closes when it is disturbed past a
threshold set by the onboard potentiometer. An LM393 comparator squares that
into a logic level on the `D0` pin. There is no amplitude output, no axis, and
no calibrated unit.

**Consequences that are not negotiable:**

- `rms`, `peak`, `crest_factor`, `kurtosis`, `dominant_freq` **do not exist**
  for this device. They are not published, not stored, and not in its
  `expected_ranges`. Computing them from a bit stream would produce five
  numbers that look like the MPU6050's and mean nothing physical.
- What a binary event stream genuinely supports is event statistics. This node
  publishes four features, defined in `src/feature_engineering_sw420.py`:

  | Feature | Meaning | Units |
  |---|---|---|
  | `trigger_rate` | rising edges per second | Hz |
  | `duty_cycle` | fraction of the window with the contact closed | 0–1 |
  | `burst_max_ms` | longest single closure | ms |
  | `inter_event_cv` | std/mean of gaps between edges — regularity | dimensionless |

- Therefore the two-node experiment is **heterogeneous multi-sensor
  validation**, not same-model MPU6050 sensor-to-sensor replication. The
  manuscript must say so.

---

## 2. Wiring

| SW-420 pin | ESP32 pin |
|---|---|
| `VCC` | `3.3V` |
| `GND` | `GND` |
| `D0`  | `GPIO4` |

`A0`, if your module has it, is left unconnected — the analog output of a
comparator module is the raw piezo/spring voltage before thresholding, and
mixing it in would mean two different sensing modalities on one node.

`GPIO4` is configured `PULL_DOWN`. This matters: a floating ESP32 input picks up
enough ambient noise to fabricate a convincing vibration trace, which would be
indistinguishable from real activity in the captured data.

---

## 3. Setting the potentiometer — this is part of the acquisition chain

The trimpot sets the comparator threshold. It is not a convenience knob; it
determines what counts as an event, so **a session captured at one setting is
not comparable to one captured at another.**

Procedure:

1. Put the board flat on the desk, hands off.
2. Turn the pot until the module's D0 LED is **steadily OFF** at rest.
3. Tap the desk lightly. The LED should flicker.
4. Back off very slightly from the point where resting noise starts triggering.
5. **Do not touch it again**, and record in your notes that it was set on this
   date. If you must re-adjust, treat everything captured before as a different
   configuration.

Verify with the live sanity check the firmware prints on boot: tap the board and
watch `trigger_rate` move off `0`.

---

## 4. The failure mode you must actively check for

The MPU6050 has a free integrity check: gravity alone is ~1 g, so an
all-zero reading is physically impossible and `expected_ranges` catches a
disconnected sensor with an `rms` floor of 0.1.

**The SW-420 has no such signature.** A disconnected D0 wire, a mis-set
potentiometer, and a genuinely still board all read exactly the same:
`trigger_rate=0, duty_cycle=0, burst_max_ms=0, inter_event_cv=0`.

There is no way to tell them apart from the feature vector. So the check has to
happen at capture time, by a person:

> **Before every session, tap the board and confirm the counters move.**

`collect_hardware_session.py` prints this reminder. Do not skip it — a whole
session of zeros looks like a beautifully quiet baseline right up until you try
to use it.

---

## 5. Acquisition chain

`SW420_SAMPLE_RATE_HZ = 1000`, `SW420_WINDOW_SIZE = 256` → a **256 ms window**.
Both are in `src/config.py` and in `firmware/main_sw420.py`, and
`tests/test_invariants.py::TestSW420SamplingContract` fails if they disagree.

These are chosen for this sensor, not copied from the MPU6050 node:

- **256 ms**, not the MPU6050's 64 ms, because an SW-420 fires as a sparse train
  of brief closures. A 64 ms window would frequently contain zero edges even
  during genuine shaking, and the feature set would be mostly silence.
- **1 kHz**, because a contact closure lasts on the order of 1–30 ms and needs
  to resolve into tens of samples, not one or two.

Sampling is **deadline-scheduled**, exactly as the MPU6050 firmware's is. A
fixed sleep after each read adds the read's own duration to every interval and
accumulates across the window; that exact defect produced a 12.3× rate
overstatement on the other node (`RESULTS.md` 13.4c) and is not repeated here.

Changing either constant requires retraining this device's models.

---

## 6. Flashing

1. Open `firmware/main_sw420.py`.
2. Fill in `DEVICE_SECRET` and `MQTT_PASSWORD` from `src/secrets_local.py`
   (`esp32-vib-002` entries). **The committed copy keeps placeholders** — same
   convention as `firmware/main.py`, so the working copy shows as permanently
   modified locally and that is the intended steady state.
3. Upload it to the board **as `main.py`** (each ESP32 boots its own `main.py`;
   the two boards hold different files under the same on-device name).
4. Add the broker credential and ACL entry on the host:

```bash
mosquitto_passwd -b certs/mosquitto_passwd esp32-vib-002 '<MQTT_PASSWORD>'
# then append to certs/mosquitto_acl, mirroring the esp32-vib-001 block:
#   user esp32-vib-002
#   topic write cps/telemetry
#   topic read cps/decisions/esp32-vib-002
#   topic read cps/challenge/esp32-vib-002
```

5. Restart Mosquitto, then power the board.

---

## 7. Why the plumbing is duplicated from `main.py`

`main_sw420.py` repeats `main.py`'s WiFi, MQTT, HMAC, `canonical_json`,
boot_id/seq and decision-verification code rather than importing it.

Each ESP32 boots its own `main.py`, so two files are needed regardless; and
`main.py` is currently flashed, working, and producing the project's only real
telemetry. Adding a sensor-selection branch to it would mean re-flashing and
re-validating that node.

The duplication is real and carries a real risk: **if you change
canonicalisation, the HMAC scheme, or the replay logic in one file, change it in
the other.** `tests/test_invariants.py` checks both firmware files against
`src/`, rather than only the first, so a divergence fails the suite rather than
silently producing messages the gateway rejects.
