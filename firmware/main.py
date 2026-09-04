# firmware/main.py -- runs on the ESP32 under MicroPython (CLAUDE.md Section 3).
#
# TWO-SCORE REARCHITECTURE additions (mirrors src/device_simulator.py --
# see that file and src/trust_engine.py for the full rationale). This HAS
# now been run on real hardware: the board authenticates and publishes
# live, and the HMAC/canonicalisation path is confirmed by hundreds of
# consecutive gateway-accepted messages with zero hmac_mismatch, which is
# a stronger check than the hand-comparison it originally shipped with
# (canonical_json() here must reproduce Python's
# json.dumps(payload, sort_keys=True) byte-for-byte or every message would
# be rejected). The on-device feature math is separately verified against
# src/feature_engineering.py, the reference implementation -- all five
# features now agree exactly (see the trig note further down for the one
# real bug that check found).
#
#   - boot_id: read the persisted counter from a local file (this board's
#     flash-equivalent of docs/01_simulation_and_hardware_abstraction.md
#     Section 5.1 point 1's "flash storage"), increment by 1, write back
#     immediately -- ONE flash write per boot, not per message. seq starts
#     at 1 each boot and is NOT persisted (boot_id already makes that safe
#     -- see trust_engine.check_boot_replay()).
#   - ts is now WALL-CLOCK epoch milliseconds, not ms-since-boot as before
#     -- the gateway's secondary freshness check (check_timestamp_freshness)
#     compares against its own time.time(), so this board now syncs its
#     clock via NTP at startup (best-effort; if it fails, ts freshness will
#     fail until it's retried, but boot_id/seq is the PRIMARY anti-replay
#     mechanism and doesn't depend on wall-clock time at all).
#   - subscribes to cps/challenge/<device_id> and echoes a received nonce
#     as step_up_nonce_echo in the NEXT published message (Module 2
#     Section 7) -- included in the signed canonical payload like every
#     other field.
#
# Required libraries: as before, plus `ntptime` (bundled with standard
# MicroPython ESP32 builds).

import math
import network
import time
import ujson
import ubinascii
import uhashlib
import gc
import os
try:
    import ussl
except ImportError:
    import ssl as ussl  # newer MicroPython builds dropped the 'u' prefix
from machine import I2C, Pin
from umqtt.simple import MQTTClient

# ==================== CONFIGURE BEFORE FLASHING ====================
# Copy device_secrets.example.py to device_secrets.py and upload it alongside
# this file when flashing. device_secrets.py is deliberately gitignored.
from device_secrets import (
    WIFI_SSID, WIFI_PASSWORD, MQTT_HOST, DEVICE_ID, DEVICE_SECRET,
    MQTT_USERNAME, MQTT_PASSWORD,
)

MQTT_TLS_PORT = 8883
MQTT_USE_TLS = True
MQTT_USE_AUTH = True

# Offset to convert this board's RTC to UTC when NTP could NOT be reached.
#
# Why this exists: on an isolated laptop hotspot with no internet route (this
# deployment -- see config.REPLAY_WINDOW_SECONDS' comment), ntptime.settime()
# always fails, so the RTC holds whatever last set it. Thonny sets it on every
# connect, and Thonny's ESP32 backend runs with `local_rtc: True`, meaning it
# writes LOCAL time, not UTC. The gateway compares `ts` against its own
# time.time(), which is UTC-based, so an un-corrected local RTC makes every
# message look exactly one timezone offset into the future and it is rejected
# as stale_timestamp -- observed live at +19784s, i.e. exactly IST's +5:30.
#
# This replaced a hardcoded `machine.RTC().datetime((2026, 9, 1, ...))` line.
# That worked only on the day it was written: it pinned the clock to a fixed
# instant, so it silently drifted a day further out of date every day, and its
# failure mode was a plausible-looking wrong time rather than an obvious one.
# An offset does not rot -- it stays correct as long as the timezone does.
#
# Set to 0 if the board HAS a working NTP route, or if your IDE syncs UTC.
# Ignored entirely when NTP succeeds, since NTP sets a true UTC clock.
RTC_LOCAL_UTC_OFFSET_SECONDS = 5 * 3600 + 30 * 60   # IST (UTC+5:30)

MPU6050_I2C_ADDR = 0x68

TELEMETRY_TOPIC = b"cps/telemetry"
DECISION_TOPIC = ("cps/decisions/" + DEVICE_ID).encode()
CHALLENGE_TOPIC = ("cps/challenge/" + DEVICE_ID).encode()
BOOT_ID_FILE = "boot_id.txt"
# ACQUISITION CHAIN -- rate, anti-alias filter and window size are ONE decision.
#
# 500 Hz sampling, 184 Hz sensor bandwidth, 32-sample window:
#   Nyquist   250 Hz, a 66 Hz margin above the filter's corner
#   window    64 ms, bins every 15.625 Hz up to 250 Hz
#   read cost 0.81 ms/sample, so 2.0 ms spacing leaves 1.2 ms of slack
#
# This replaced a declared-but-never-achieved 100 Hz. The history is worth
# keeping, because each step only became visible once the previous was fixed:
#
#   1. sample_window() had no delay at all and ran at ~1231 Hz while claiming
#      100 Hz, so dominant_freq was scaled by a constant 12.3x wrong.
#   2. Pacing it to a true 100 Hz fixed the scale but moved Nyquist from 615 Hz
#      to 50 Hz -- BELOW the sensor's 260 Hz default bandwidth -- so 210 Hz of
#      content began folding into the measured band. Measured: dominant_freq
#      collapsed onto 28-50 Hz, pinned to the top of the band.
#   3. DLPF_CFG=3 (44 Hz) cut most of that, but 44 Hz against a 50 Hz Nyquist
#      leaves no margin for the filter's gradual rolloff. Measured: 38% of
#      samples still landed in the top three bins, 2x uniform -- content just
#      above 50 Hz folding back to just below it.
#   4. The 100 Hz target was never a requirement; it came from a comment
#      describing a sampling loop that did not exist. Raising the rate beats
#      narrowing the filter: 500 Hz gives a 66 Hz margin, 5x the usable
#      bandwidth of a 21 Hz filter at 100 Hz, AND a 64 ms window not 320 ms.
#
# Changing any of these three requires retraining -- every dominant_freq value
# the models learned is scaled by SAMPLE_RATE_HZ. src/config.py's
# FEATURE_SAMPLE_RATE_HZ must match this exactly (tests enforce it).
SAMPLE_RATE_HZ = 500
WINDOW_SIZE = 32
PUBLISH_INTERVAL_MS = 2000
# =====================================================================


# ---------- WiFi / MQTT / time plumbing ----------

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("[wifi] connecting to", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            time.sleep_ms(300)
    print("[wifi] connected, ip=", wlan.ifconfig()[0])


def sync_time():
    # Best-effort: the gateway's secondary timestamp-freshness check needs
    # this board's clock to be roughly wall-clock-correct. boot_id/seq
    # (Module 2 Check 4) is the PRIMARY anti-replay mechanism and does not
    # depend on this succeeding -- if NTP fails (no internet route to an
    # NTP server, blocked port, etc.), telemetry will still be accepted or
    # rejected correctly on the replay dimension, only the independent
    # freshness-window check would misbehave until this is retried.
    #
    # Retries a few times with a short pause -- observed live that a single
    # NTP attempt right after WiFi association intermittently times out
    # (ETIMEDOUT) even though a retry a couple seconds later succeeds, so
    # one-shot was leaving the board on an un-synced clock for its whole
    # session more often than it should.
    import ntptime
    for attempt in range(1, 4):
        try:
            ntptime.settime()
            print("[time] synced via NTP -- RTC is true UTC, no offset needed")
            return True
        except Exception as e:
            print("[time] NTP sync attempt %d/3 failed:" % attempt, e)
            if attempt < 3:
                time.sleep_ms(2000)
    print("[time] NTP sync failed after 3 attempts -- treating the RTC as LOCAL time and")
    print("[time] subtracting RTC_LOCAL_UTC_OFFSET_SECONDS =", RTC_LOCAL_UTC_OFFSET_SECONDS,
          "to get UTC (see that constant's comment)")
    return False


def load_and_increment_boot_id():
    # Read the persisted counter, increment by 1, write back immediately --
    # ONE flash write per boot (docs/01 Section 5.1 point 1), not per
    # message, which is what makes this cheap on flash wear compared to
    # persisting `seq` itself instead.
    try:
        with open(BOOT_ID_FILE) as f:
            boot_id = int(f.read().strip()) + 1
    except (OSError, ValueError):
        boot_id = 1
    with open(BOOT_ID_FILE, "w") as f:
        f.write(str(boot_id))
    return boot_id


def connect_mqtt():
    client_id = DEVICE_ID + "-" + ubinascii.hexlify(machine_unique_id()).decode()
    user = MQTT_USERNAME if MQTT_USE_AUTH else None
    pw = MQTT_PASSWORD if MQTT_USE_AUTH else None
    if MQTT_USE_TLS:
        client = MQTTClient(client_id, MQTT_HOST, port=MQTT_TLS_PORT, user=user, password=pw,
                             ssl=True, ssl_params={"cert_reqs": ussl.CERT_NONE})
        print("[mqtt] connecting over TLS to", MQTT_HOST, MQTT_TLS_PORT)
    else:
        client = MQTTClient(client_id, MQTT_HOST, port=1883, user=user, password=pw)
        print("[mqtt] connecting over PLAIN MQTT to", MQTT_HOST, "-- TLS disabled, debugging only")
    client.connect()
    print("[mqtt] connected", "with broker credentials" if MQTT_USE_AUTH else "anonymously")
    return client




def machine_unique_id():
    try:
        import machine
        return machine.unique_id()
    except Exception:
        return b"\x00\x00\x00\x00"


# ---------- Deployment footprint (RESULTS.md Section 13.1/13.4) ----------
# Real measurements, not synthetic-device-process proxies. Printed once at
# boot (RAM/flash are near-static after init) so they land in Thonny's
# Shell where they can be copied back and recorded in RESULTS.md -- this
# file has no way to phone the numbers home itself, since the whole point
# is to observe the REAL constrained device, not add a reporting
# dependency that costs its own RAM/flash.

def print_deployment_footprint():
    gc.collect()
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    print("[footprint] RAM: %d bytes free, %d bytes allocated (%d total)" %
          (free, alloc, free + alloc))
    try:
        stat = os.statvfs("/")
        block_size, frag_size, blocks, free_blocks = stat[0], stat[1], stat[2], stat[3]
        total = blocks * frag_size
        free_flash = free_blocks * frag_size
        print("[footprint] Flash filesystem: %d bytes free, %d bytes used (%d total)" %
              (free_flash, total - free_flash, total))
    except Exception as e:
        print("[footprint] flash stat unavailable:", e)


# ---------- MPU6050 (minimal register-level driver, no external lib) ----------

i2c = None


# MPU6050 CONFIG register 0x1A, bits [2:0] = DLPF_CFG -- the sensor's internal
# digital low-pass filter, i.e. its ANTI-ALIASING filter.
#
# DLPF_CFG=3 gives 44 Hz accelerometer bandwidth, just under the 50 Hz Nyquist
# limit of our 100 Hz sampling rate. The reset default is 0 = 260 Hz.
#
# This is not optional, and leaving it at the default is an active bug once the
# sampling loop is correctly paced. At 100 Hz sampling, everything the sensor
# passes between 50 Hz and 260 Hz -- 210 Hz of bandwidth -- folds back into the
# 0-50 Hz band we measure, and folded energy is indistinguishable from real
# low-frequency content once it has aliased. Observed directly: after the
# sampling-rate fix, dominant_freq collapsed onto the TOP of the band (28-50 Hz
# on every message) where the same board had previously reported 3-15 Hz.
#
# Note the ordering trap. Before the sampling fix the board ran at ~1231 Hz, so
# Nyquist was 615 Hz, comfortably above the 260 Hz bandwidth, and there was no
# aliasing to see. Correcting the sample rate is what CREATED the aliasing, by
# moving Nyquist below the sensor's passband. A rate fix and an anti-alias
# filter are one change, not two.
MPU6050_DLPF_CFG = 1      # 184 Hz accel bandwidth, 66 Hz below the 250 Hz Nyquist


def mpu6050_init():
    global i2c
    i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
    i2c.writeto_mem(MPU6050_I2C_ADDR, 0x6B, b"\x00")  # PWR_MGMT_1 = 0 -- wake it up
    i2c.writeto_mem(MPU6050_I2C_ADDR, 0x1A, bytes([MPU6050_DLPF_CFG]))  # CONFIG: anti-alias filter
    # SMPLRT_DIV=0: with the DLPF enabled the sensor refreshes its output
    # registers at 1 kHz, comfortably faster than our 500 Hz read rate, so every
    # read returns a fresh sample rather than repeating a stale one.
    i2c.writeto_mem(MPU6050_I2C_ADDR, 0x19, b"\x00")  # SMPLRT_DIV


def read_accel_magnitude_g():
    data = i2c.readfrom_mem(MPU6050_I2C_ADDR, 0x3B, 6)  # ACCEL_XOUT_H..ACCEL_ZOUT_L

    def s16(hi, lo):
        v = (hi << 8) | lo
        return v - 65536 if v > 32767 else v

    ax = s16(data[0], data[1]) / 16384.0
    ay = s16(data[2], data[3]) / 16384.0
    az = s16(data[4], data[5]) / 16384.0
    return (ax * ax + ay * ay + az * az) ** 0.5


# ---------- Feature extraction (Section 5.1, all computed on-device) ----------

def extract_features(window):
    n = len(window)
    mean = sum(window) / n
    rms = (sum(v * v for v in window) / n) ** 0.5
    peak = max(window) - min(window)
    crest_factor = (peak / rms) if rms > 1e-9 else 0.0

    std = (sum((v - mean) ** 2 for v in window) / n) ** 0.5
    if std > 1e-9:
        kurtosis = (sum(((v - mean) / std) ** 4 for v in window) / n) - 3.0
    else:
        kurtosis = 0.0

    dominant_freq = _dominant_frequency(window, mean, SAMPLE_RATE_HZ)

    return {
        "rms": round(rms, 4),
        "peak": round(peak, 4),
        "crest_factor": round(crest_factor, 4),
        "kurtosis": round(kurtosis, 4),
        "dominant_freq": round(dominant_freq, 4),
    }


def _dominant_frequency(window, mean, sample_rate_hz):
    n = len(window)
    centered = [v - mean for v in window]
    best_mag_sq = -1.0
    best_freq = 0.0
    for k in range(1, n // 2 + 1):
        re = 0.0
        im = 0.0
        for t in range(n):
            angle = -2.0 * 3.14159265358979 * k * t / n
            re += centered[t] * _cos(angle)
            im += centered[t] * _sin(angle)
        mag_sq = re * re + im * im
        if mag_sq > best_mag_sq:
            best_mag_sq = mag_sq
            best_freq = k * sample_rate_hz / n
    return best_freq


# Real trig from MicroPython's built-in `math` module (present in every
# standard ESP32 build -- this port has hardware float). This REPLACED a
# hand-rolled truncated-Taylor _sin()/_cos() pair, which was accurate only
# near zero: measured max error 7.5e-2 across [0, 2pi], which corrupted the
# DFT above badly enough to select the WRONG dominant_freq bin in 57 of 300
# test windows (19%), off by as much as 46.9 Hz. That mattered beyond the
# feature itself: src/feature_engineering.py is the reference implementation
# the models are TRAINED against, so a firmware-only frequency error is a
# silent train/serve skew present on real telemetry and absent from every
# simulated row. With math.sin/math.cos the firmware reproduces
# feature_engineering.dominant_frequency() exactly (0/300 mismatches).
def _sin(x):
    return math.sin(x)


def _cos(x):
    return math.cos(x)


def sample_window():
    """Collects WINDOW_SIZE samples at an ACTUAL rate of SAMPLE_RATE_HZ.

    This used to be a bare list comprehension with no delay, which read as fast
    as I2C allowed: measured at 26 ms for 32 samples, i.e. ~1231 Hz against a
    declared 100 Hz -- a 12.3x overstatement. That mattered because
    dominant_freq is computed as `k * SAMPLE_RATE_HZ / n`, so every reported
    frequency was scaled by a constant that was not true. Bin spacing was
    really ~38.5 Hz, not 3.125, and Nyquist ~615 Hz, not 50. See RESULTS.md
    Section 13.4c.

    Timing is scheduled against a moving DEADLINE rather than by sleeping a
    fixed amount after each read. A fixed sleep would add the read's own
    duration to every interval and let that error accumulate across the
    window, so 32 samples would span measurably longer than 320 ms and the
    frequency axis would drift again -- a subtler version of the same bug.
    Advancing `next_t` by exactly dt each iteration means a slow read steals
    from its own slack instead of pushing every later sample back.

    ticks_add/ticks_diff (not plain arithmetic) because MicroPython's tick
    counters wrap around, and only these handle the wrap correctly."""
    dt_us = int(1000000 / SAMPLE_RATE_HZ)
    window = []
    next_t = time.ticks_us()
    for _ in range(WINDOW_SIZE):
        window.append(read_accel_magnitude_g())
        next_t = time.ticks_add(next_t, dt_us)
        remaining = time.ticks_diff(next_t, time.ticks_us())
        if remaining > 0:
            time.sleep_us(remaining)
    return window


# ---------- HMAC-SHA256 (manual, portable across MicroPython builds) ----------

def hmac_sha256(key: bytes, message: bytes) -> bytes:
    block_size = 64
    if len(key) > block_size:
        key = uhashlib.sha256(key).digest()
    key = key + b"\x00" * (block_size - len(key))
    o_pad = bytes(b ^ 0x5C for b in key)
    i_pad = bytes(b ^ 0x36 for b in key)
    inner = uhashlib.sha256(i_pad + message).digest()
    return uhashlib.sha256(o_pad + inner).digest()


# ---------- Python-compatible float formatting ----------

def format_py_float(v, decimals=4):
    s = "%.*f" % (decimals, v)
    if "." in s:
        while s.endswith("0"):
            s = s[:-1]
        if s.endswith("."):
            s += "0"
    return s


def canonical_json(fields: dict) -> str:
    """Generic replacement for the old hand-interpolated fixed-field
    template -- needed now that the field set is variable
    (step_up_nonce_echo only appears some of the time). Each value in
    `fields` must ALREADY be a JSON-literal string (numbers unquoted,
    strings pre-quoted) -- same philosophy as format_py_float() above, just
    generalized, so this still never depends on a general-purpose
    MicroPython JSON encoder matching Python's exact number formatting.
    Separators (", " between pairs, ": " within a pair) match Python's
    json.dumps(payload, sort_keys=True) default (no separators= override)."""
    parts = ['"%s": %s' % (k, fields[k]) for k in sorted(fields.keys())]
    return "{" + ", ".join(parts) + "}"


# ---------- Build + sign + publish ----------
def build_and_sign(features, boot_id, seq, ts_ms, pending_nonce):
    fields = {
        "boot_id": str(boot_id),
        "crest_factor": format_py_float(features["crest_factor"]),
        "device_id": '"%s"' % DEVICE_ID,
        "dominant_freq": format_py_float(features["dominant_freq"]),
        "kurtosis": format_py_float(features["kurtosis"]),
        "peak": format_py_float(features["peak"]),
        "rms": format_py_float(features["rms"]),
        "seq": str(seq),
        "ts": str(ts_ms),
    }
    if pending_nonce is not None:
        fields["step_up_nonce_echo"] = '"%s"' % pending_nonce
    canonical = canonical_json(fields)
    signature = ubinascii.hexlify(hmac_sha256(DEVICE_SECRET.encode(), canonical.encode())).decode()
    envelope = '{"payload": %s, "signature": "%s"}' % (canonical, signature)
    return envelope



# ---------- Mutual authentication + step-up challenge handling ----------

def _consteq(a, b):
    if len(a) != len(b):
        return False
    diff = 0
    for i in range(len(a)):
        diff |= ord(a[i]) ^ ord(b[i])
    return diff == 0


def verify_decision_signature(payload, signature_hex):
    # Reuses canonical_json() (the same generic sorted-keys builder telemetry
    # uses) instead of a hand-rolled fixed-field format string, now that the
    # gateway's payload carries 5 fields (decision, device_id, ts,
    # gateway_boot_id, decision_seq), not 3 -- one canonicalisation
    # implementation for both directions is less risk than two.
    fields = {
        "decision": '"%s"' % payload["decision"],
        "device_id": '"%s"' % payload["device_id"],
        "ts": str(payload["ts"]),
        "gateway_boot_id": str(payload["gateway_boot_id"]),
        "decision_seq": str(payload["decision_seq"]),
    }
    canonical = canonical_json(fields)
    expected = ubinascii.hexlify(hmac_sha256(DEVICE_SECRET.encode(), canonical.encode())).decode()
    return _consteq(expected, signature_hex)


# Decision-channel anti-replay (RESULTS.md Section 14 item 3): mirrors
# gateway.py's own check_boot_replay() logic for telemetry, applied here to
# the gateway's OUTGOING decisions instead. RAM-only, not persisted to
# flash like the device's own boot_id.txt -- a device reboot means
# starting trust fresh anyway, and a captured-and-replayed old decision is
# a much lower-stakes forgery than replayed sensor data (it's an ephemeral
# access grant, not something feeding a trust score), so losing this state
# across a device reboot is an accepted, deliberate simplification, not an
# oversight.
_last_decision_boot_id = None
_last_decision_seq = 0


def check_decision_replay(payload):
    global _last_decision_boot_id, _last_decision_seq
    boot_id = payload["gateway_boot_id"]
    seq = payload["decision_seq"]
    if _last_decision_boot_id is None or boot_id > _last_decision_boot_id:
        _last_decision_boot_id = boot_id
        _last_decision_seq = seq
        return False  # not a replay -- first decision seen, or a fresh gateway restart supersedes everything before it
    if boot_id < _last_decision_boot_id:
        return True  # a lower boot_id is from a superseded gateway session -- always stale
    if seq <= _last_decision_seq:
        return True  # same gateway session, but this seq was already seen or is going backwards
    _last_decision_seq = seq
    return False


_pending_step_up_nonce = None  # module-level: set by on_message(), consumed by the next build_and_sign() call


def on_message(topic, msg):
    global _pending_step_up_nonce
    if topic == CHALLENGE_TOPIC:
        try:
            body = ujson.loads(msg)
            _pending_step_up_nonce = body["nonce"]
            print("[challenge] received step-up nonce, will echo on next publish")
        except (ValueError, KeyError):
            print("[challenge] malformed challenge message, dropping")
        return
    try:
        envelope = ujson.loads(msg)
        payload = envelope["payload"]
        signature = envelope["signature"]
    except (ValueError, KeyError):
        print("[decision] malformed message, dropping")
        return
    if not verify_decision_signature(payload, signature):
        print("[decision] !! REJECTED decision -- signature invalid (forged/tampered, or not really "
              "from the gateway) -- ignoring, NOT acting on it")
        return
    if check_decision_replay(payload):
        print("[decision] !! REJECTED decision -- valid signature, but boot_id/seq indicates a replay "
              "(gateway_boot_id=%s decision_seq=%s) -- ignoring, NOT acting on it" %
              (payload["gateway_boot_id"], payload["decision_seq"]))
        return
    print("[decision] << verified gateway decision:", payload["decision"])


def main():
    global _pending_step_up_nonce
    connect_wifi()
    # 0 when NTP gave us a true UTC clock; the timezone offset when it did not
    # and the RTC therefore holds local time. See RTC_LOCAL_UTC_OFFSET_SECONDS.
    _utc_offset = 0 if sync_time() else RTC_LOCAL_UTC_OFFSET_SECONDS
    mpu6050_init()
    client = connect_mqtt()
    client.set_callback(on_message)
    client.subscribe(DECISION_TOPIC)
    client.subscribe(CHALLENGE_TOPIC)
    print_deployment_footprint()  # RAM/flash after full init, RESULTS.md Section 13.4

    boot_id = load_and_increment_boot_id()
    seq = 0
    print("[main] boot_id =", boot_id, "-- publishing", DEVICE_ID, "telemetry every", PUBLISH_INTERVAL_MS, "ms")

    while True:
        # Sensor read is its OWN try/except, separate from the MQTT
        # publish/reconnect block below. Found live (RESULTS.md Section
        # 13.2): removing the MPU6050's VCC raises an OSError (I2C bus
        # timeout, ETIMEDOUT) from sample_window() -- previously this was
        # caught by the same broad `except OSError` the MQTT reconnect
        # logic used, which always assumed a NETWORK problem and tried to
        # reconnect MQTT (which was never broken), succeeding every time,
        # then immediately failing the SAME I2C read again next loop --
        # an infinite loop of pointless MQTT reconnects that never
        # diagnosed or attempted to recover from the actual problem.
        # Correctly identified and retried here instead: on an I2C
        # failure, re-run mpu6050_init() (so power being restored is
        # picked up automatically, same retry philosophy as sync_time()'s
        # NTP retries) and skip straight to the next cycle without
        # touching MQTT at all.
        try:
            t_sample_start = time.ticks_ms()
            window = sample_window()
            t_sample_done = time.ticks_ms()
            features = extract_features(window)
            t_features_done = time.ticks_ms()
        except OSError as e:
            print("[main] MPU6050 read failed (sensor disconnected, unpowered, or wired "
                  "incorrectly?):", e, "-- re-initializing I2C and retrying next cycle")
            try:
                mpu6050_init()
            except OSError:
                pass  # still not there -- next cycle will report the same failure, not silently hang
            time.sleep_ms(PUBLISH_INTERVAL_MS)
            continue

        try:
            # Two corrections, both needed before the gateway's freshness check
            # (check_timestamp_freshness) will accept this message:
            #   1. MicroPython's time.time() counts seconds since 2000-01-01, not
            #      the Unix epoch (1970-01-01) the gateway uses. NTP sets the RTC
            #      correctly but does not change that reference point, so the fixed
            #      946684800s gap is always added or every message looks ~30 years
            #      stale.
            #   2. If NTP could NOT be reached, the RTC holds LOCAL time (whatever
            #      the IDE last synced -- Thonny writes local time), so the
            #      timezone offset is subtracted to get UTC. When NTP succeeded the
            #      RTC is already true UTC and _utc_offset is 0.
            ts_ms = int((time.time() + 946684800 - _utc_offset) * 1000)
            seq += 1

            nonce_to_echo = _pending_step_up_nonce
            _pending_step_up_nonce = None  # consumed -- only echoed once
            t_sign_start = time.ticks_ms()
            envelope = build_and_sign(features, boot_id, seq, ts_ms, nonce_to_echo)
            t_sign_done = time.ticks_ms()
            client.publish(TELEMETRY_TOPIC, envelope)
            print("[publish]", envelope)
            # RESULTS.md Section 13.1 -- real on-device latency, not the
            # simulated-device-process proxy used everywhere else in this
            # project. time.ticks_diff() (not plain subtraction) is the
            # MicroPython-correct way to measure this: ticks_ms() wraps
            # around periodically, and ticks_diff() handles that wraparound
            # correctly where naive subtraction would not.
            print("[latency] sampling=%dms feature_extraction=%dms sign=%dms" % (
                time.ticks_diff(t_sample_done, t_sample_start),
                time.ticks_diff(t_features_done, t_sample_done),
                time.ticks_diff(t_sign_done, t_sign_start),
            ))
            # DRAIN the inbound queue, do not sample it. check_msg() processes at
            # most ONE pending message, and the gateway publishes a signed decision
            # for EVERY telemetry message -- so at one call per PUBLISH_INTERVAL_MS
            # the queue is saturated by decisions alone and never empties. A step-up
            # challenge then waits behind queued decisions, is handled well past
            # STEP_UP_CHALLENGE_TIMEOUT_SECONDS (10 s), and the nonce it echoes is
            # already stale. Observed live as 32-34 step-up TIMEOUT/MISMATCH failures
            # on a board that was in fact answering correctly -- each one dropping
            # Security Trust below threshold and producing a spurious BLOCK, with the
            # late response then landing as a SUCCESS boost (sec 0.561 -> 0.854).
            # Bounded rather than while-True: a malicious or wedged broker must not be
            # able to hold the publish loop open indefinitely.
            for _ in range(8):
                if client.check_msg() is None:
                    break
        except OSError as e:
            print("[main] MQTT/network error, reconnecting:", e)
            try:
                client = connect_mqtt()
                client.set_callback(on_message)
                client.subscribe(DECISION_TOPIC)
                client.subscribe(CHALLENGE_TOPIC)
            except OSError:
                connect_wifi()

        time.sleep_ms(PUBLISH_INTERVAL_MS)


if __name__ == "__main__":
    main()
