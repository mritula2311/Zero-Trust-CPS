# 06 — Real Hardware Setup: Complete Beginner's Guide

**Assumes zero prior experience** wiring a board or flashing firmware.
By the end of this doc, your ESP32 + MPU6050 + vibration sensor will be
publishing real, signed telemetry that the gateway (`gateway.py`)
authenticates and scores — with no changes needed on the gateway side; it
doesn't know or care whether a message came from `device_simulator.py` or
your real board.

Firmware is **MicroPython**, not Arduino/C++ (CLAUDE.md Section 3's
choice). We'll use **Thonny** — a single free app that handles USB driver
detection, flashing MicroPython onto the chip, and copying your code onto
it, all through simple menus. No command line required for any of this
(a VSCode-based alternative is mentioned at the very end, once you're
comfortable, but Thonny is the path this guide walks you through).

---

## Part A — What you need

**Hardware:**
- An ESP32 dev board (any "ESP32-WROOM-32"-style board is fine)
- An MPU6050 breakout board (3-axis accelerometer + gyroscope)
- A vibration sensor module (analog output — piezo disc or analog SW-420 variant)
- A **data-capable** USB cable for your board (many phone charging cables
  are power-only and won't work for programming — if Thonny can't see your
  board at all in Part D, try a different cable first)
- 6-8 male-to-female jumper wires
- A breadboard (optional, but makes wiring much less fiddly)

**Software** (all free): Thonny, installed in Part B.

## Part B — Install Thonny

1. Go to [thonny.org](https://thonny.org) and download the installer for
   Windows.
2. Run the installer, accepting the defaults.
3. Open Thonny once it's installed. You'll see a code editor at the top
   and a "Shell" panel at the bottom — that Shell is a live connection to
   whatever board is plugged in, once we set that up.

## Part C — Wire the board (do this with the ESP32 unplugged from USB)

### MPU6050 (I2C — 4 wires)

| MPU6050 pin | ESP32 pin | Notes |
|---|---|---|
| VCC | 3V3 | **Not** 5V — the MPU6050 and ESP32 GPIOs are 3.3V |
| GND | GND | |
| SCL | GPIO 22 | I2C clock |
| SDA | GPIO 21 | I2C data |
| AD0 | GND | Selects I2C address `0x68` (the address the firmware expects) |

### Vibration sensor (analog — 3 wires)

| Vibration sensor pin | ESP32 pin | Notes |
|---|---|---|
| VCC | 3V3 | |
| GND | GND | |
| OUT (analog) | GPIO 34 | Any pin from GPIO 32-39 works ("ADC1" pins) — **do not** use GPIO 0, 2, 4, 12-15, 25-27 for this (those are "ADC2" pins, and WiFi silently breaks ADC2 readings on the ESP32) |

**A tip for double-checking your wiring before powering on**: every GND
pin on every module should end up connected to the SAME ground — on a
breadboard, run one wire from an ESP32 GND pin to the breadboard's ground
rail, then connect every module's GND to that rail, rather than wiring
each module's GND to a separate ESP32 GND pin. Fewer chances for a loose
connection.

## Part D — Flash MicroPython onto the ESP32 (one-time)

1. Plug the ESP32 into your PC via USB.
2. In Thonny, go to **Run → Configure interpreter...** (or click the
   interpreter name in the bottom-right corner of the window).
3. In the dropdown at the top, choose **"MicroPython (ESP32)"**.
4. You'll see a **"Install or update MicroPython"** link/button in that
   same dialog — click it.
5. In the installer dialog: pick your board's **port** (if you're not
   sure which one, unplug the board, note what ports are listed, plug it
   back in, and see which new one appeared), and pick the **variant**
   "Espressif · ESP32 · Generic ESP32 module". Click **Install**.
6. Wait for it to finish (a minute or two) — it erases the chip and
   writes the MicroPython firmware onto it.
7. Close that dialog. Back in the main Thonny window, click the **Stop/
   Restart** button (a red circle icon) or press Ctrl+F2. You should see
   something like `MicroPython v1.2x on ... ESP32` appear in the Shell at
   the bottom — that means MicroPython is running on the board and Thonny
   is talking to it live.

**If Thonny doesn't see the board at all** (no new port appeared in step
5): you likely need a USB-to-serial driver. Most ESP32 boards use either
a "CP2102" or "CH340" chip for USB communication — check what's printed
on your board's USB-to-serial chip, search "[chip name] driver windows",
install it, unplug/replug the board, and retry.

## Part E — Configure and upload the firmware

1. In Thonny, go to **File → Open...**, and open
   `d:\zt-cps\zt-cps-starter\firmware\main.py`.
2. Near the top of the file, find the **`CONFIGURE BEFORE FLASHING`**
   block and edit these four lines:

   ```python
   WIFI_SSID = "YOUR_WIFI_SSID"
   WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
   MQTT_HOST = "192.168.x.x"
   ```

   - `WIFI_SSID` / `WIFI_PASSWORD`: your **2.4GHz** WiFi network (the
     ESP32 does not support 5GHz WiFi — if your router broadcasts a
     combined/5GHz-only network name, you need a 2.4GHz one to connect to).
   - `MQTT_HOST`: your PC's LAN IP address, **not** `localhost` —
     `localhost` only means anything on the machine it's typed on. Find
     yours by opening PowerShell on your PC and running:
     ```powershell
     ipconfig
     ```
     Look for the "Wireless LAN adapter Wi-Fi" section's **IPv4 Address**
     (on this machine right now, that's `10.20.47.206` — yours will be
     different and can change after a reboot, so re-check if things stop
     connecting later).

   Leave `DEVICE_ID`, `DEVICE_SECRET`, `VIBRATION_ADC_PIN`, and
   `MPU6050_I2C_ADDR` as they are — they already match
   `src/config.py`'s `DEVICE_REGISTRY` entry and the wiring in Part C.

3. Save the file (Ctrl+S) — Thonny will ask "This is not a MicroPython
   device, where to save to?" the FIRST time; that's just because you
   opened it from your PC's disk. We'll copy it to the device next.
4. With the ESP32 still connected and MicroPython running (from Part D),
   go to **File → Save as...**, choose **"MicroPython device"**, and save
   it as `main.py` (the board runs whatever file is named exactly
   `main.py` automatically on every boot).

## Part F — Run it and watch it work

1. Press the **Stop/Restart** button in Thonny (or unplug/replug the
   ESP32's USB cable) to reboot the board and start `main.py` fresh.
2. Watch the Shell panel at the bottom of Thonny. You should see, in order:
   ```
   [wifi] connecting to YOUR_WIFI_SSID
   [wifi] connected, ip= 192.168.x.x
   [mqtt] connecting over TLS to 10.20.47.206 8883
   [mqtt] connected
   [main] publishing esp32-vib-001 telemetry every 2000 ms
   [publish] {"crest_factor": ..., "device_id": "esp32-vib-001", ...}
   ```
   A new `[publish]` line should appear roughly every 2 seconds.
3. On your PC, open a terminal in `zt-cps-starter/src/` and start the
   gateway:
   ```bash
   python gateway.py
   ```
4. Watch the gateway's own output. You should see an `esp32-vib-001` line
   with **`auth=OK`** appear every ~2 seconds, alongside its trust score
   and decision — that's your real board, signed and verified end-to-end.

**One thing to try**: gently tap the MPU6050 or the vibration sensor while
this is running. After ~40 messages (the ML scorers need that much
history before they train), you should start seeing the trust score dip
in response to real physical vibration — that's Phase 6 working on real
data, not simulated data.

**Do not** also run `device_simulator.py` for `esp32-vib-001` at the same
time — two publishers claiming the same device identity will confuse the
trust engine's running average. `device_simulator.py` still simulates
`sensor-002`/`actuator-001` fine alongside your real board, if you want
all three devices active together.

## Troubleshooting

- **`auth=FAIL` on every message**: almost always a value-formatting
  mismatch, not the HMAC math itself — the gateway recomputes the HMAC
  over the *parsed* payload, so the firmware's floats must format exactly
  the way Python's `json.dumps` would. This was checked against 6,000+
  random values with zero mismatches before this doc was written (see
  `firmware/main.py`'s `format_py_float()`), so it should already match —
  if it doesn't, double check `DEVICE_SECRET` matches `config.py` exactly
  first, since a mismatched secret produces the exact same symptom and is
  a much more common mistake than a formatting bug.
- **MQTT/TLS handshake fails / times out**: confirm your PC's Windows
  Firewall allows inbound port 8883 (see `docs/03_add_tls.md`) and that
  Mosquitto is actually bound to your PC's real network interface, not
  just `127.0.0.1` (`Get-NetTCPConnection -LocalPort 8883 -State Listen`
  in PowerShell should show `0.0.0.0`, not only `127.0.0.1`). If you want
  to isolate whether TLS itself is the problem, set `MQTT_USE_TLS = False`
  temporarily to confirm the rest of the pipeline works over plaintext
  1883 first, then debug TLS separately.
- **WiFi won't connect**: double-check it's a 2.4GHz network (see Part E).
- **MPU6050 reads all zeros, or the gateway shows wildly wrong `rms`
  values**: check the AD0→GND wire (wrong I2C address is the most common
  cause) and that SDA/SCL aren't swapped.
- **Thonny says "Could not open port"**: another program (like the
  Arduino IDE, or another Thonny window) may already be connected to that
  port — close other programs that might be using it, or unplug/replug
  the board.
- **`ImportError: no module named 'umqtt'`**: open **Tools → Manage
  packages...** in Thonny (with the board connected) and install
  `micropython-umqtt.simple`, or from the Shell:
  ```python
  import mip
  mip.install("umqtt.simple")
  ```
  (needs WiFi already connected, since it downloads over the network).

## Once you're comfortable: the VSCode alternative

If you'd rather write/edit code in VSCode day-to-day, install the
**"Pymakr"** extension (Marketplace) — it gives VSCode a device file
browser and upload/run buttons similar to Thonny's, working with the same
MicroPython-flashed board from Part D (you only need to flash MicroPython
once, regardless of which editor you use afterward). This is optional —
Thonny alone is a complete workflow for this project.

## Known limitations worth stating in the paper

- **Replay protection has one blind spot**: a message captured from
  within the device's first few seconds of uptime could still be replayed
  successfully later (see `config.REBOOT_TS_THRESHOLD_MS`'s comment for
  the full reasoning). Closing this fully needs a monotonic hardware
  counter or synced wall-clock + nonce — out of scope for this prototype.
- **TLS certificate verification is disabled on the device side**
  (`cert_reqs=CERT_NONE` in `firmware/main.py`) — the firmware trusts
  whatever certificate the broker presents rather than verifying it
  against the CA. Acceptable for a prototype on an isolated test network;
  a production deployment would embed the CA certificate and verify it
  (CLAUDE.md Section 8's "secret provisioning" note applies the same
  spirit here).
