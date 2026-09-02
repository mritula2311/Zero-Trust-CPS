# Hardware Setup — ESP32 + MPU6050

A complete, zero-to-running guide for flashing `firmware/main.py` onto a
real ESP32 and getting it publishing real, HMAC-signed, boot-aware
telemetry into this project's gateway. No command-line `esptool`/`mpremote`
needed — everything here uses **Thonny**, a free MicroPython-focused IDE
with a built-in firmware flasher and file uploader.

**Status as of writing**: this firmware has been run end-to-end on real
hardware — a real ESP32 + MPU6050, authenticated (HMAC/boot_id/seq/
timestamp all passing), scored live by `gateway.py`, and folded back into
the trained models via `scripts/collect_hardware_session.py` (see Section
12). The board publishes **one physical sensor's worth of data**: a
MPU6050 over I2C. There is no separate vibration sensor in this design —
an earlier draft of this guide described one, but all 5 Section-5.1
features (`rms`, `peak`, `crest_factor`, `kurtosis`, `dominant_freq`) are
derived from the MPU6050's accelerometer alone (see
`firmware/main.py::extract_features()`).

---

## 0. What You'll End Up With

One physical ESP32 board, running MicroPython, reading a real MPU6050 over
I2C, computing the same 5-feature vibration vector (`rms`, `peak`,
`crest_factor`, `kurtosis`, `dominant_freq`) the rest of this project
already expects, signing it with HMAC-SHA256, and publishing it over
MQTT/TLS to your existing gateway — alongside (or eventually instead of)
`device_simulator.py`'s simulated `esp32-vib-001`. Nothing on the gateway
side changes; `gateway.py` cannot tell the difference between a real board
and the simulator, by design (see
`docs/01_simulation_and_hardware_abstraction.md`).

---

## 1. Parts List

| Part | Notes |
|---|---|
| ESP32 dev board | Any standard ESP32-WROOM-32 board. Needs WiFi (built in). |
| MPU6050 breakout | 3-axis accelerometer + 3-axis gyroscope, I2C. ~$2-5, widely available. |
| USB cable | Data-capable (not charge-only) micro-USB or USB-C, matching your board. |
| Jumper wires | Female-to-female if your MPU6050 breakout has pin headers — no breadboard required, see Section 2. |
| A computer with a USB port | To run Thonny and flash the board. |

---

## 2. Wiring

Five connections total, all to the MPU6050 — no breadboard needed if your
jumper wires can plug directly onto both boards' headers.

| MPU6050 pin | ESP32 pin | Notes |
|---|---|---|
| VCC | 3.3V | **Not 5V** — most MPU6050 breakouts are 3.3V-only; check yours. |
| GND | GND | |
| SDA | GPIO21 | Default I2C data pin on most ESP32 dev boards. |
| SCL | GPIO22 | Default I2C clock pin. |
| AD0 | GND | Ties the I2C address to `0x68` (the default `firmware/main.py` expects). Tying AD0 to VCC instead gives address `0x69` — if you do this, change `MPU6050_I2C_ADDR` in `firmware/main.py`. |

**Only one ESP32 GND pin is required** — AD0 doesn't need its own separate
ground pin on the ESP32; daisy-chain it off the MPU6050's own GND pin (or
a shared ground rail if you are using a breadboard) instead of running two
wires back to the board.

### 2.1 Double-Check Before Powering On

- Confirm VCC goes to 3.3V, not 5V or VIN.
- Confirm SDA/SCL aren't swapped (a swapped I2C bus is the most common
  first-time wiring mistake — if Step 9 shows an I2C error, check this
  first).

---

## 3. Install Thonny

1. Download Thonny from **https://thonny.org** (Windows/macOS/Linux
   installers available) and install it.
2. Open Thonny once so it finishes its first-run setup.

---

## 4. Flash MicroPython Onto the ESP32

1. Plug the ESP32 into your computer via USB.
2. In Thonny: **Tools → Options → Interpreter**.
3. Set the interpreter dropdown to **MicroPython (ESP32)**.
4. Select the correct **Port** (if unsure which COM port / `/dev/tty*` is
   your board, unplug it, check the list, plug it back in, and see which
   one appears).
5. Click **Install or update firmware** (the exact wording varies slightly
   by Thonny version — look for a firmware-flashing link/button in this
   same dialog).
6. Choose the latest stable **ESP32** MicroPython `.bin` from the list (or
   point it at a `.bin` you downloaded from
   [micropython.org/download/ESP32_GENERIC/](https://micropython.org/download/ESP32_GENERIC/)
   if Thonny's built-in list doesn't have what you want).
7. Click **Install**. This erases the flash and writes MicroPython — takes
   a minute or two. Wait for it to finish before touching the board.
8. Once done, click **OK**, then check Thonny's **Shell** panel at the
   bottom — you should see a MicroPython REPL prompt (`>>>`). If you type
   `print("hello")` and press Enter, it should print `hello`. If this
   works, MicroPython is installed correctly.

**Note on MicroPython build differences**: `firmware/main.py` imports
`ussl` with a fallback to `ssl` (newer MicroPython builds dropped the `u`
prefix on several modules) — no action needed either way, it self-selects
the right one at boot.

---

## 5. Confirm Your Gateway Is Reachable

The board needs your gateway machine's **LAN IP address** (not
`localhost` — that means something different on the board itself).

- On the gateway machine (Windows): open PowerShell, run `ipconfig`, and
  note the `IPv4 Address` under your active network adapter (e.g.
  `192.168.1.42`). If the ESP32 will join a Windows Mobile Hotspot hosted
  by this same machine, that's the adapter named something like `Local
  Area Connection* N`, and its address is almost always `192.168.137.1`
  (Windows' standard default for that feature).
- Confirm the ESP32 and the gateway machine will be on the **same WiFi
  network** — the board can't reach a gateway on a different subnet or
  behind client-isolation (some guest WiFi networks block device-to-device
  traffic; use your main network or a hosted mobile hotspot, not a guest
  network, for this).
- Confirm the broker is actually listening (from the gateway machine):
  `netstat -an | findstr "1883 8883"` should show both ports `LISTENING`.

---

## 6. Provision the Device's Secret

This device (`esp32-vib-001`) already has a slot in `src/config.py`'s
`DEVICE_REGISTRY`, reading from `src/secrets_local.py` (gitignored — see
`src/secrets_local.example.py` for the template if you haven't created it
yet). You need the **same** secret and MQTT password in two places: the
gateway's `secrets_local.py`, and the firmware you're about to flash.

1. If `src/secrets_local.py` doesn't exist yet, copy the example and fill
   in real random values:
   ```bash
   cd src
   cp secrets_local.example.py secrets_local.py
   python -c "import secrets; print(secrets.token_hex(16))"          # -> DEVICE_SECRETS["esp32-vib-001"]
   python -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"   # -> MQTT_PASSWORDS["esp32-vib-001"]
   ```
2. If `certs/mosquitto_passwd` already exists (broker auth is enabled),
   regenerate the `esp32-vib-001` line to match the new MQTT password:
   ```bash
   mosquitto_passwd -b certs/mosquitto_passwd esp32-vib-001 <the-MQTT-password-you-just-generated>
   ```
   Then restart the Mosquitto service (admin PowerShell:
   `Restart-Service -Name mosquitto`) so it picks up the change.
   `certs/mosquitto_acl` already has `esp32-vib-001`'s topic rules — no
   change needed there.
3. Write down both values (the HMAC secret and the MQTT password) — you'll
   paste them into the firmware in Step 7.

---

## 7. Configure `firmware/main.py`

Open `firmware/main.py` in Thonny (or any text editor) and edit the
**`==================== CONFIGURE BEFORE FLASHING ====================`**
block near the top:

```python
WIFI_SSID = "YOUR_WIFI_SSID"                  # your real WiFi network name
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"          # your real WiFi password
MQTT_HOST = "192.168.x.x"                     # the gateway machine's LAN IP from Step 5

MQTT_TLS_PORT = 8883
MQTT_USE_TLS = True                           # keep True; see Section 13 for the plaintext-debugging exception

DEVICE_ID = "esp32-vib-001"                   # leave as-is unless you also update DEVICE_REGISTRY
DEVICE_SECRET = "..."                         # paste the secret from Step 6, exactly
MQTT_USE_AUTH = True                          # keep True if certs/mosquitto_passwd exists
MQTT_USERNAME = "esp32-vib-001"               # leave as-is
MQTT_PASSWORD = "..."                         # paste the MQTT password from Step 6, exactly
```

**Type these values by hand rather than pasting where practical** —
copy/paste (especially from a rich-text source) can silently introduce a
trailing space or a smart-quote that looks identical on screen but breaks
authentication. If you do hit an auth failure, the fastest way to check is
a temporary `print(len(MQTT_PASSWORD))` / `print(len(DEVICE_SECRET))` right
before they're used, comparing against the actual length of the value you
generated in Step 6 — a length mismatch means a typo, not a deeper bug.

**Never commit real values here to git** — `firmware/main.py` itself is
tracked, so if you're contributing back, revert these four lines to their
placeholder values before committing, the same way `src/secrets_local.py`
(a separate, gitignored file) is what actually holds the gateway-side
secrets.

If your wiring differs from Section 2 (different I2C pins, AD0 tied to VCC
instead of GND), also update `MPU6050_I2C_ADDR` accordingly.

---

## 8. Upload `firmware/main.py` to the Board

1. In Thonny, with the ESP32 still selected as the interpreter (Section 4),
   open `firmware/main.py` (**File → Open**, browse to this repo's
   `firmware/main.py`).
2. **File → Save As...** → choose **MicroPython device** (not "This
   computer") → save it as exactly **`main.py`** (MicroPython
   auto-runs a file named `main.py` on every boot — this is what makes the
   board start publishing automatically without you needing to run
   anything manually each time).
3. Thonny will show the file now living on the device's filesystem (check
   the **Files** panel — it should show a device-side pane alongside your
   computer's files, with `main.py` listed).

**Careful with File → Save (not Save As)**: if you use the plain "Save"
shortcut/toolbar button rather than "Save As... → MicroPython device", it
can save back to **this computer's copy** of `firmware/main.py` instead of
(or in addition to) the board — which is how real credentials end up
sitting in the git-tracked file. Always use Save As and explicitly pick
the device target.

---

## 9. First Boot — What You Should See

Press the ESP32's **EN/RST** button (or unplug/replug USB), then watch
Thonny's **Shell** panel. A working boot looks like:

```
[wifi] connecting to YOUR_WIFI_SSID
[wifi] connected, ip= 192.168.1.xxx
[time] synced via NTP
[mqtt] connecting over TLS to 192.168.1.xxx 8883
[mqtt] connected with broker credentials
[footprint] RAM: ... bytes free, ... bytes allocated (... total)
[footprint] Flash filesystem: ... bytes free, ... bytes used (... total)
[main] boot_id = 1 -- publishing esp32-vib-001 telemetry every 2000 ms
[publish] {"payload": {"boot_id": 1, "crest_factor": ..., ...}, "signature": "..."}
[latency] sampling=...ms feature_extraction=...ms sign=...ms
```

The `[footprint]` lines print once at boot (RESULTS.md Section 13.4);
`[latency]` prints every message (Section 13.1) — both are real
on-device measurements, not the simulated-device-process proxy used
elsewhere in this project. If you're recording numbers for RESULTS.md,
copy a few representative lines back.

If you see this, the board is publishing. Check the gateway's own console
(a separate terminal running `python src/gateway.py` — **not** Thonny's
Shell; Thonny only shows the board's own console, the gateway is a
completely separate process on your PC that subscribes to the MQTT broker
independently) — you should see a new `esp32-vib-001` line appear roughly
every 2 seconds, with real `security=`/`process=` scores, **not** a
`REJECTED (hmac_mismatch)` line. If you see the latter, stop and go to
Step 10 before doing anything else.

**Common first-boot problems:**

| Symptom in Thonny's Shell | Likely cause |
|---|---|
| `OSError: [Errno 19] ENODEV` or similar around `i2c.writeto_mem` | MPU6050 not wired correctly, or wired to the wrong pins — recheck Section 2, especially SDA/SCL not swapped. |
| Hangs forever at `[wifi] connecting to ...` | Wrong WiFi password, or a 5GHz-only network (the ESP32's WiFi radio is 2.4GHz only) — confirm your network has a 2.4GHz band available and the ESP32 is using it. |
| `ImportError: no module named 'ussl'` | Already handled automatically — `firmware/main.py` falls back to `import ssl as ussl` on MicroPython builds that dropped the `u` prefix. If you still see this exact error, your build is missing both names; try a different/newer MicroPython `.bin`. |
| `[time] NTP sync attempt N/3 failed` / `[time] NTP sync failed after 3 attempts` | The firmware retries NTP 3 times (2s apart) before giving up — observed live that a single attempt right after WiFi association intermittently times out (`ETIMEDOUT`) even though a retry succeeds. **Failure here is now handled, not fatal:** the firmware falls back to treating the RTC as *local* time and subtracts `RTC_LOCAL_UTC_OFFSET_SECONDS` to get UTC, and prints exactly that. Read Step 9.1 before assuming a `stale_timestamp` rejection means NTP — if the offset constant is wrong for your timezone, you get rejections *because of* this fallback rather than despite it. `boot_id`/`seq` (the primary anti-replay mechanism) is unaffected either way. |
| `OSError: [Errno 104] ECONNRESET` or connection refused at `[mqtt] connecting...` | Wrong `MQTT_HOST`, broker not running, or the gateway machine's firewall is blocking the ESP32's subnet — confirm Section 5's checks. |
| `MQTTException: 5` at `client.connect()` | CONNACK "not authorized" — almost always `MQTT_USERNAME`/`MQTT_PASSWORD` not matching `certs/mosquitto_passwd` exactly. See Step 7's typo-checking tip. |
| `[main] MPU6050 read failed (sensor disconnected, unpowered, or wired incorrectly?): [Errno 116] ETIMEDOUT` | The sensor read (not WiFi/MQTT) failed — a genuinely unpowered or disconnected MPU6050 (VCC or SDA/SCL loose). Not fatal: the firmware re-initializes I2C and retries every cycle, recovering automatically the moment the wiring/power is restored (no reset needed) — verified live, including the automatic-recovery path. If this persists with the wiring connected, recheck Section 2's pinout. |
| Real readings publish fine, but `rms`/`peak`/`crest_factor`/`kurtosis` all read exactly `0.0` | A more subtle sensor fault than the error above — some disconnection states leave the I2C bus responsive but returning all-zero bytes instead of raising an error (observed live when only SDA/SCL, not VCC, was disconnected). Physically impossible for a connected accelerometer (gravity alone is ~1g at rest). `src/config.py`'s `rms` rule-check bound (`expected_ranges`) has a `0.1` floor specifically to catch this — if you're seeing it on the gateway console as `ALLOW`/normal rather than flagged, something upstream of that check needs attention. |

---

## 9.1 If every message is `REJECTED (stale_timestamp)` — the clock trap

This is the single most likely thing to block a first bring-up on an isolated
hotspot, and the symptom is misleading: the board looks perfectly healthy, WiFi
and MQTT connect, the HMAC is correct, and yet the gateway refuses every message.

**Diagnose it by the size of the offset, which tells you which of three problems
you have:**

| Board clock vs gateway | Cause |
|---|---|
| ~30 years behind | The 2000-epoch bug — MicroPython's `time.time()` counts from 2000-01-01, not 1970. The firmware adds `946684800` s; if you edited that, put it back. |
| **A constant offset exactly equal to a timezone** (e.g. +19,800 s = +5:30) | **The timezone trap below.** A whole-timezone offset is never drift. |
| Slowly growing by minutes | Genuine RTC drift with no NTP. This is what `REPLAY_WINDOW_SECONDS = 600` accommodates. |

### The timezone trap

When NTP is unreachable, the ESP32's RTC keeps whatever last wrote to it — and on
a Thonny-managed board, that is **Thonny**. Its ESP32 backend connects with
`local_rtc: True`, meaning it writes **local** time, not UTC. The firmware then
adds the epoch gap assuming the RTC is UTC, so every message lands exactly one
timezone offset **into the future** and fails the freshness window.

Measured on this deployment: **+19,784 s**, precisely IST's +5:30, with every
message rejected.

### The fix

`firmware/main.py` defines:

```python
RTC_LOCAL_UTC_OFFSET_SECONDS = 5 * 3600 + 30 * 60   # IST (UTC+5:30)
```

applied **only when NTP fails**. `sync_time()` returns whether it succeeded, so:

- **NTP succeeded** → the RTC is true UTC → offset is 0, this constant is ignored
  entirely. A board with a real internet route needs no configuration.
- **NTP failed** → the RTC holds local time → the offset converts it to UTC.

**Set this to your own timezone**, or to `0` if your IDE syncs UTC. Watch the
boot log to see which path you are on:

```
[time] synced via NTP -- RTC is true UTC, no offset needed
```
or
```
[time] NTP sync failed after 3 attempts -- treating the RTC as LOCAL time and
[time] subtracting RTC_LOCAL_UTC_OFFSET_SECONDS = 19800 to get UTC
```

After the fix the measured delta was **+2.3 s to +21.3 s**, with zero
`stale_timestamp` rejections across 46 consecutive rows.

### Why not just hardcode the date?

An earlier version of this firmware did exactly that —
`machine.RTC().datetime((2026, 9, 1, ...))` — and it is the wrong answer even
though it works on the day you write it. A pinned instant drifts a day further
out of date every day, and it fails with a *plausible-looking* wrong time rather
than an obviously wrong one, which is much harder to diagnose. An offset stays
correct as long as your timezone does. **Do not replace this with a fixed
timestamp.**

### The real fix, if you want one

Share your laptop's internet connection to the hotspot (enable ICS on Windows).
The board then reaches a real NTP server, `sync_time()` succeeds, the offset is
bypassed automatically with no firmware change, and you can revert
`config.REPLAY_WINDOW_SECONDS` from 600 back to 30.

## 10. The Critical First Integration Test

**Do this before trusting anything else.** MicroPython's `ujson` and
CPython's `json` can theoretically serialize floats or key ordering
slightly differently — if the canonicalization doesn't match byte-for-byte
between the firmware and the gateway, HMAC verification will fail on
*every single message*, even though nothing is "attacking" anything.

1. Watch the gateway's console for the first `esp32-vib-001` line after
   the board boots.
2. If it shows real `security=`/`process=` values and a decision
   (`ALLOW`/`ALERT`/`STEP_UP`/`BLOCK`) — **the canonicalization matches,
   you're done, skip to Step 11.**
3. If instead you see `esp32-vib-001 | REJECTED (hmac_mismatch) | ...` —
   the firmware's computed signature doesn't match what the gateway
   independently computes. This means either:
   - `DEVICE_SECRET` in `firmware/main.py` doesn't exactly match
     `DEVICE_SECRETS["esp32-vib-001"]` in `src/secrets_local.py` (most
     common cause — re-check for a copy-paste typo or trailing
     whitespace; see Step 7's length-check tip), or
   - a genuine float-formatting mismatch between MicroPython's number
     rendering and Python's (less likely, since `firmware/main.py`'s
     `format_py_float()` was specifically verified against thousands of
     synthetic values before this file was ever flashed — but not
     impossible on a MicroPython build/version this wasn't tested against).
4. To debug a suspected formatting mismatch: add a `print(canonical)` line
   right after `canonical = canonical_json(fields)` in
   `firmware/main.py::build_and_sign()`, reflash, capture one printed
   canonical string from Thonny's Shell, and manually compare it
   character-by-character against what `src/trust_engine.py`'s
   `rule_range_score` path or a quick Python one-liner
   (`json.dumps({...same fields...}, sort_keys=True, separators=(", ", ": "))`)
   produces for the identical field values. The first differing character
   tells you exactly which field's formatting to fix.

---

### 10.1 The second integration test — feature maths, not just signatures

Step 10 proves the *envelope* is right. It cannot prove the *contents* are, and
that is a separate failure mode worth its own test.

The five features are computed **on the device**, while every model is trained
against `src/feature_engineering.py`. Those are two independent implementations
of the same maths. The HMAC signs whatever number the device computed — correct
or not — so a numerically wrong feature sails through Step 10 untouched.

This has already happened once on this project. A hand-rolled `_sin()` in the
firmware carried up to **7.5e-2** error, which selected the wrong DFT bin for
`dominant_freq` in **57 of 300** windows (19%), by as much as 46.9 Hz. Every one
of those messages was perfectly signed and cheerfully accepted. Because the
models train on the reference implementation, the result was a **silent
train/serve skew visible only on real hardware** — no simulated row and no
offline evaluation script could have shown it.

**The test**, and it costs a minute:

1. Copy the firmware's `extract_features()` / `_dominant_frequency()` maths into
   a throwaway CPython script (they are plain arithmetic; only `_sin`/`_cos`
   need substituting).
2. Generate a few hundred randomised windows across several regimes — quiet
   baseline, single impulsive spike, low-frequency sinusoid.
3. Run both implementations over the same windows and diff all five features.
4. **Every feature must match exactly.** The current firmware does: 0/300
   mismatches on all five.

If `dominant_freq` disagrees, suspect trigonometry first: use `math.sin` /
`math.cos` from MicroPython's built-in `math` module (present in every standard
ESP32 build — the board has hardware floating point) rather than any hand-rolled
series approximation.

## 11. Running Real Hardware Alongside the Simulator

Once Step 10 passes, `esp32-vib-001` is being published from **two**
places at once if `device_simulator.py` is also running: the real board,
and the simulator's software stand-in. Both publish under the identical
`device_id`, which will race on `boot_id`/`seq`
(`trust_engine.check_boot_replay()`) — whichever one's message arrives
second will often get rejected as a replay of the other's.

To fix this, add `esp32-vib-001` to `src/config.py`:

```python
REAL_HARDWARE_DEVICE_IDS = {"esp32-vib-001"}
```

`device_simulator.py` will then automatically skip `esp32-vib-001`
entirely (no client created, no scenario injection for it — including the
`anomalous_shock`, `stealthy_forged_values`, and `reboot` scenarios, which
only make sense for a simulated device) while continuing to simulate
`sensor-002` and `actuator-001` normally. This is the supported way to run
a genuine hybrid testbed — "N simulated CPS nodes plus one physical
validation node" — rather than an either/or choice between the two.

To go back to pure simulation (e.g. the board is disconnected), set
`REAL_HARDWARE_DEVICE_IDS = set()` again.

---

## 12. Baseline Calibration & Folding Real Data Into the Trained Models

> **Before capturing:** make sure your firmware passes Step 10.1. Data captured
> with wrong feature maths gets merged into the training set and teaches the
> models the wrong distribution — and because it is labelled *normal* like every
> other real row, nothing downstream will flag it. The four sessions currently in
> `data/collected/` predate the `dominant_freq` fix and still carry an inflated
> high-frequency tail; see `HARDWARE_DATA_LOG.md` §3.
>
> **Also note what the capture script's `phase` field is and is not.** It records
> what the operator was *asked* to do, not what the board physically experienced,
> and on the existing sessions the two do not line up — `at_rest_1` contains a
> higher maximum `rms` (3.416 g) than `moderate_shake` (1.050 g). Do not build
> labelled training or evaluation data on it. If you want trustworthy labels,
> record them at the moment of injection rather than inferring them from a timed
> phase schedule afterwards (`HARDWARE_DATA_LOG.md` §2).

`src/config.py`'s `DEVICE_REGISTRY["esp32-vib-001"]["expected_ranges"]`
and the trained Isolation Forest / LSTM-AE / GNN / fusion meta-learner are
all originally calibrated against `device_simulator.py`'s **synthetic**
normal/shock distributions, not a real MPU6050. Expect the live
`process=` (Process Anomaly) score to read low/anomalous for a
genuinely-normal real board at first — this is a real train/serve
distribution mismatch, not a bug (verified: the rule-range check itself
passes fine; it's specifically the ML scorers reading real statistics as
unfamiliar). Two scripts exist to close this gap with real data instead of
manual range-editing:

1. **`scripts/collect_hardware_session.py`** — a read-only MQTT subscriber
   (safe to run alongside a live `gateway.py`, different client_id) that
   walks you through a scripted 5-phase physical routine (at rest / gentle
   tap / moderate shake / tilt-rotate / at rest again, ~45s each), captures
   every real `esp32-vib-001` reading during it, joins in `gateway.py`'s
   own live `fused_score`/`security_trust_score`/`decision` for each
   message from `audit_log.db`, and writes:
   - `data/collected/hardware_session_<timestamp>.json` (raw records, same
     shape `scripts/generate_training_data.py` produces)
   - `firmware/HARDWARE_DATA_LOG.md` (human-readable per-phase summary)

   Run it multiple times across different sessions/conditions — each
   session's file is additive, nothing gets overwritten.

2. **`scripts/merge_real_hardware_data.py`** — regenerates a fresh
   synthetic training session (same `generate_training_data.py` used for
   `scripts/train_*.py`) and appends every `data/collected/
   hardware_session_*.json` record collected so far as additional real
   `esp32-vib-001` "normal" examples, writing the combined set back to
   `data/collected/training_session.json`. Idempotent — safe to re-run any
   time you've collected more real sessions.

Then retrain in dependency order (each stage's scorer is loaded by the
next):

```bash
python scripts/train_isolation_forest.py
python scripts/train_lstm_ae.py
python scripts/train_gnn.py
python scripts/train_fusion_meta_learner.py
```

**Before trusting a retrain, check it didn't regress** — `scripts/
evaluate_ablation.py` scores the retrained pipeline against the held-out
`data/collected/test_session.json` (untouched by the merge step) and
reports accuracy/precision/recall/F1 per signal; compare against a
pre-retrain run (back up `models/*.joblib`/`models/*.pt` first if you want
a clean before/after, since retraining overwrites them in place). A real
measured run of this exact procedure (253 real records blended in) moved
the deployed `fused_score`'s accuracy/recall/F1 up (0.707→0.745 /
0.684→0.728 / 0.811→0.840) with a negligible precision cost, alongside one
honest trade-off: the LSTM-AE's undiluted F1 dropped (0.910→0.871) because
its reconstruction-error baseline necessarily widens to accommodate real
hardware's noisier signal, making it less sensitive to the tighter
synthetic-scale anomalies in one specific hard test category
(`stealthy_forged_values`). Net positive on the metric that's actually
deployed; not a free lunch on every sub-signal.

If you'd rather hand-tune `expected_ranges` instead of / in addition to
retraining: watch the `rms`/`peak`/`crest_factor`/`kurtosis`/
`dominant_freq` values in `firmware/HARDWARE_DATA_LOG.md` or query recent
rows from `audit_log.db`, and update `expected_ranges` in `src/config.py`
to reflect the real observed range with reasonable margin.

---

## 13. Known Limitations (Stated Explicitly, Not Hidden)

- **`cert_reqs=ussl.CERT_NONE`** (`firmware/main.py::connect_mqtt()`): the
  board does not verify the broker's TLS certificate. Traffic is still
  encrypted, but a man-in-the-middle with control of your local network
  could in principle present a fake certificate the board wouldn't reject.
  Accepted as a stated prototype simplification (`CLAUDE.md` Section 8) —
  getting genuine CA verification working reliably varies by MicroPython
  build and is real, non-trivial follow-up work, not a quick fix.
- **`DEVICE_SECRET`/`MQTT_PASSWORD` are plaintext constants in flash** —
  no secure element, no flash encryption. Same accepted simplification,
  same section.
- **Wall-clock dependency (NTP *or* a correct offset)**: the secondary
  timestamp-freshness check needs the board's clock roughly correct. With a
  working NTP path that is automatic. Without one — which is the case on an
  isolated hotspot — it depends on `RTC_LOCAL_UTC_OFFSET_SECONDS` being right
  for your timezone (Step 9.1). The *primary* anti-replay mechanism
  (`boot_id`/`seq`) does not depend on either. Note the accommodation this
  forced: `config.REPLAY_WINDOW_SECONDS` is widened from 30 s to **600 s**
  because a manually-set RTC drifts by minutes; revert it to 30 once the board
  has real NTP time.
- **`boot_id` persistence uses a plain file on the MicroPython
  filesystem** (`boot_id.txt`), not a hardware-backed counter — a full
  flash chip erase (not just a normal reboot or even a firmware
  re-flash that preserves the filesystem) would reset it. This is the same
  "flash-equivalent" scheme `docs/01_simulation_and_hardware_abstraction.md`
  Section 5.1 specifies.

---

## 14. Files in This Folder

- `main.py` — the actual firmware, uploaded to the board as-is (Step 8).
- `HARDWARE_SETUP.md` — this file.
- `HARDWARE_DATA_LOG.md` — generated by `scripts/collect_hardware_session.py`
  (Section 12); a human-readable summary of the most recent real-data
  collection session. Regenerated (overwritten) on every run.
- `boot_id.txt` — **not** part of this repo; created automatically on the
  board's own filesystem the first time `main.py` runs (Step 9). If you
  ever see a `boot_id.txt` show up in your local git status, it means you
  ran the firmware on this computer somehow rather than on the board —
  delete it, it doesn't belong in the repo.
