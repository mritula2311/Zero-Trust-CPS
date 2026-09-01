# firmware/main.py -- runs on the ESP32 under MicroPython (CLAUDE.md Section 3).
#
# TWO-SCORE REARCHITECTURE additions (mirrors src/device_simulator.py --
# see that file and src/trust_engine.py for the full rationale). NONE of
# this has been run on real hardware yet (no board has been flashed at the
# time of writing -- see SESSION_LOG.md); it is verified only the way the
# rest of this file's HMAC/canonicalisation logic was originally verified,
# by hand-checking the string-building logic against the Python-side
# equivalent, not by a live board round trip. Budget real debugging time
# for this on first flash, same as every other integration point this file
# already flags.
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

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_HOST = "192.168.x.x"          # your gateway machine's LAN IP -- see firmware/HARDWARE_SETUP.md
MQTT_TLS_PORT = 8883               # matches config.MQTT_TLS_PORT; switches on automatically once certs/ exists
MQTT_USE_TLS = True                # set False only for initial bring-up/debugging over plaintext 1883
DEVICE_ID = "esp32-vib-001"
# Must exactly match src/secrets_local.py's DEVICE_SECRETS["esp32-vib-001"]
# (payload HMAC) -- that file is gitignored and holds the real value; copy
# it in here before flashing, never commit the real value to this file.
DEVICE_SECRET = "CHANGE-ME-match-secrets_local.py-DEVICE_SECRETS"
# MQTT broker login (separate from DEVICE_SECRET above -- transport layer,
# not application layer, IEC 62443 FR5). Must exactly match
# src/secrets_local.py's MQTT_PASSWORDS["esp32-vib-001"] and
# certs/mosquitto_passwd. Only used if the broker has auth enabled.
MQTT_USE_AUTH = True
MQTT_USERNAME = "esp32-vib-001"
MQTT_PASSWORD = "CHANGE-ME-match-secrets_local.py-MQTT_PASSWORDS"

MPU6050_I2C_ADDR = 0x68            # default address when AD0 is tied to GND

TELEMETRY_TOPIC = b"cps/telemetry"
DECISION_TOPIC = ("cps/decisions/" + DEVICE_ID).encode()
CHALLENGE_TOPIC = ("cps/challenge/" + DEVICE_ID).encode()   # Module 2 Section 7 step-up
BOOT_ID_FILE = "boot_id.txt"                                 # flash-equivalent persisted counter
SAMPLE_RATE_HZ = 100                # matches config.FEATURE_SAMPLE_RATE_HZ
WINDOW_SIZE = 32                    # matches config.FEATURE_WINDOW_SIZE
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
            print("[time] synced via NTP")
            return
        except Exception as e:
            print("[time] NTP sync attempt %d/3 failed:" % attempt, e)
            if attempt < 3:
                time.sleep_ms(2000)
    print("[time] NTP sync failed after 3 attempts (non-fatal, see comment above)")


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


def mpu6050_init():
    global i2c
    i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
    i2c.writeto_mem(MPU6050_I2C_ADDR, 0x6B, b"\x00")  # PWR_MGMT_1 = 0 -- wake it up


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


def _sin(x):
    x = x % (2 * 3.14159265358979)
    if x > 3.14159265358979:
        x -= 2 * 3.14159265358979
    x2 = x * x
    return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42)))


def _cos(x):
    return _sin(x + 1.5707963267948966)


def sample_window():
    return [read_accel_magnitude_g() for _ in range(WINDOW_SIZE)]


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
    sync_time()
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
            # MicroPython's time.time() counts seconds since 2000-01-01, not the
            # Unix epoch (1970-01-01) the gateway's time.time() uses -- NTP sync
            # sets the RTC correctly but doesn't change that reference point, so
            # the fixed 946684800s gap must be added here or every message looks
            # ~30 years stale to check_timestamp_freshness().
            ts_ms = int((time.time() + 946684800) * 1000)
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
            client.check_msg()  # non-blocking: process any pending decision/challenge message
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

