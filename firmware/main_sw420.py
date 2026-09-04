# firmware/main_sw420.py -- MicroPython, ESP32_REAL_02 (esp32-vib-002)
#
# SECOND REAL NODE. ESP32 + SW-420 digital vibration switch.
#
# WHY THIS IS A SEPARATE FILE AND NOT A FLAG IN main.py.
# Each ESP32 is flashed with its own `main.py`, so the two boards need two
# files regardless. main.py is currently flashed, working, and holds live
# credentials in its working copy; adding a sensor-selection branch to it would
# mean re-flashing and re-validating a node that is producing the project's only
# real telemetry. The plumbing below (WiFi, MQTT/TLS, HMAC, canonical_json,
# boot_id/seq, decision verification, step-up echo) is therefore a deliberate
# copy of main.py's, byte-identical in the parts that must agree with the
# gateway. If you change canonicalisation, HMAC, or the replay scheme in one
# file, change it in the other -- tests/test_invariants.py checks BOTH firmware
# files against src/ rather than only the first.
#
# WHAT IS GENUINELY DIFFERENT: the sensor and the features.
#   - The SW-420 is a spring-contact vibration SWITCH behind an LM393
#     comparator. D0 is a logic level, not a measurement. There is no
#     amplitude, no axis, no units.
#   - It therefore publishes the FOUR event-statistics features defined in
#     src/feature_engineering_sw420.py, and does NOT publish rms / peak /
#     crest_factor / kurtosis / dominant_freq. Those are physically undefined
#     for a binary switch and are absent rather than synthesised.
#
# WIRING (see HARDWARE_SETUP_SW420.md):
#   SW-420 VCC -> 3.3V     GND -> GND     D0 -> GPIO4
#   The onboard potentiometer sets the comparator threshold. Turn it until the
#   module LED is OFF at rest and flickers when you tap the desk. Record where
#   you left it -- it is part of the acquisition chain, and a session captured
#   at a different threshold is not comparable to one captured at this one.

import machine
import network
import time
import ubinascii
import uhashlib
import ujson
from umqtt.simple import MQTTClient

# ---------- Credentials (kept in ignored device_secrets.py) ----------
# Copy device_secrets.example.py to device_secrets.py and upload it alongside
# this file when flashing. device_secrets.py is deliberately gitignored.
from device_secrets import (
    WIFI_SSID, WIFI_PASSWORD, MQTT_HOST, DEVICE_ID, DEVICE_SECRET,
    MQTT_USERNAME, MQTT_PASSWORD,
)

MQTT_TLS_PORT = 8883
MQTT_USE_TLS = True
MQTT_USE_AUTH = True

TELEMETRY_TOPIC = b"cps/telemetry"
DECISION_TOPIC = b"cps/decisions/" + DEVICE_ID.encode()
CHALLENGE_TOPIC = b"cps/challenge/" + DEVICE_ID.encode()
BOOT_ID_FILE = "boot_id.txt"

PUBLISH_INTERVAL_MS = 1000
RTC_LOCAL_UTC_OFFSET_SECONDS = 5 * 3600 + 1800   # IST, used only if NTP is unreachable

# ---------- Acquisition chain -- MUST match src/config.py exactly ----------
# SW420_SAMPLE_RATE_HZ / SW420_WINDOW_SIZE there. Rate and window move
# together; changing either requires retraining this device's models, for the
# same reason the MPU6050 node's chain is "one decision".
SAMPLE_RATE_HZ = 1000
WINDOW_SIZE = 256
SW420_PIN = 4

_pin = None


# ---------- WiFi / MQTT / time plumbing (mirrors main.py) ----------

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("[wifi] connecting to", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(40):
            if wlan.isconnected():
                break
            time.sleep_ms(500)
    if not wlan.isconnected():
        raise OSError("wifi connect failed")
    print("[wifi] connected:", wlan.ifconfig())


def sync_time():
    """True if NTP set a real UTC clock. Same retry philosophy as main.py: an
    isolated hotspot often has no route to an NTP server, and the caller
    compensates with RTC_LOCAL_UTC_OFFSET_SECONDS rather than failing."""
    try:
        import ntptime
        for _ in range(3):
            try:
                ntptime.settime()
                print("[time] NTP sync OK")
                return True
            except Exception:
                time.sleep_ms(500)
    except ImportError:
        pass
    print("[time] NTP unreachable -- assuming RTC holds LOCAL time")
    return False


def load_and_increment_boot_id():
    """Flash-persisted boot counter -- the anti-replay scheme's outer index."""
    try:
        with open(BOOT_ID_FILE) as f:
            boot_id = int(f.read().strip()) + 1
    except (OSError, ValueError):
        boot_id = 1
    with open(BOOT_ID_FILE, "w") as f:
        f.write(str(boot_id))
    return boot_id


def connect_mqtt():
    ssl_params = {"server_hostname": MQTT_HOST} if MQTT_USE_TLS else None
    client = MQTTClient(
        client_id=DEVICE_ID,
        server=MQTT_HOST,
        port=MQTT_TLS_PORT if MQTT_USE_TLS else 1883,
        user=MQTT_USERNAME if MQTT_USE_AUTH else None,
        password=MQTT_PASSWORD if MQTT_USE_AUTH else None,
        ssl=MQTT_USE_TLS,
        ssl_params=ssl_params or {},
        keepalive=60,
    )
    client.connect()
    print("[mqtt] connected to", MQTT_HOST, "TLS" if MQTT_USE_TLS else "plaintext")
    return client


# ---------- SW-420 driver ----------

def sw420_init():
    """D0 as a plain input. PULL_DOWN so an UNPLUGGED signal wire reads a
    steady 0 rather than floating and generating phantom edges -- a floating
    input on an ESP32 picks up enough noise to fabricate a convincing vibration
    trace, which would be indistinguishable from real activity in the data.

    Note the failure mode this leaves: a disconnected sensor reads all-zero,
    which is ALSO what a genuinely still board reads. Unlike the MPU6050 -- where
    all-zero is physically impossible because gravity alone is ~1 g, which is why
    that device has an rms floor of 0.1 -- a binary switch has no such
    signature, so 'unplugged' and 'perfectly still' are not separable from the
    feature vector alone. Recorded here rather than papered over: an SW-420
    session must be verified at capture time (tap the board, see the count move)
    and that check is built into collect_hardware_session.py's SW-420 path."""
    global _pin
    _pin = machine.Pin(SW420_PIN, machine.Pin.IN, machine.Pin.PULL_DOWN)
    print("[sw420] D0 on GPIO", SW420_PIN, "as input, pull-down")


def sample_window():
    """WINDOW_SIZE binary samples at an ACTUAL rate of SAMPLE_RATE_HZ.

    Deadline-scheduled, exactly as main.py's sample_window() is, and for the
    same reason: a fixed sleep after each read adds the read's own duration to
    every interval and the error accumulates across the window, so the window
    would span longer than WINDOW_SIZE/SAMPLE_RATE_HZ and every rate-derived
    feature (trigger_rate, burst_max_ms) would be scaled by a constant that is
    not true. That exact defect cost this project three retrains on the other
    node (RESULTS.md 13.4c); it is not repeated here.

    ticks_add/ticks_diff rather than plain arithmetic because MicroPython's
    tick counters wrap."""
    dt_us = int(1000000 / SAMPLE_RATE_HZ)
    window = []
    next_t = time.ticks_us()
    for _ in range(WINDOW_SIZE):
        window.append(_pin.value())
        next_t = time.ticks_add(next_t, dt_us)
        remaining = time.ticks_diff(next_t, time.ticks_us())
        if remaining > 0:
            time.sleep_us(remaining)
    return window


# ---------- Feature extraction (mirrors src/feature_engineering_sw420.py) ----------

def extract_features(window):
    """The four SW-420 features, computed on-device. Must agree with
    src/feature_engineering_sw420.py -- that module is the reference
    implementation and the models train against it, so a divergence here is
    train/serve skew that no offline evaluation can detect. Checked by
    tests/test_invariants.py::TestSW420FirmwareReferenceEquivalence over
    randomised windows, not by reading the two files side by side."""
    n = len(window)
    duration_s = n / float(SAMPLE_RATE_HZ)

    edges = []
    for i in range(1, n):
        if window[i] == 1 and window[i - 1] == 0:
            edges.append(i)

    active = 0
    best_run = 0
    run = 0
    for v in window:
        if v:
            active += 1
            run += 1
            if run > best_run:
                best_run = run
        else:
            run = 0

    trigger_rate = len(edges) / duration_s if duration_s > 0 else 0.0
    duty_cycle = active / float(n) if n else 0.0
    burst_max_ms = 1000.0 * best_run / SAMPLE_RATE_HZ

    # Population std/mean of inter-edge gaps. Needs >= 3 edges for >= 2 gaps;
    # below that there is no gap distribution and the honest answer is 0.0,
    # matching the reference implementation exactly (a NaN here would be signed
    # and published).
    inter_event_cv = 0.0
    if len(edges) >= 3:
        gaps = [(edges[i] - edges[i - 1]) / float(SAMPLE_RATE_HZ) for i in range(1, len(edges))]
        m = sum(gaps) / len(gaps)
        if m > 1e-9:
            var = sum((g - m) * (g - m) for g in gaps) / len(gaps)
            inter_event_cv = (var ** 0.5) / m

    return {
        "trigger_rate": round(trigger_rate, 4),
        "duty_cycle": round(duty_cycle, 4),
        "burst_max_ms": round(burst_max_ms, 4),
        "inter_event_cv": round(inter_event_cv, 4),
    }


# ---------- HMAC-SHA256 (identical to main.py -- must agree with the gateway) ----------

def hmac_sha256(key: bytes, message: bytes) -> bytes:
    block_size = 64
    if len(key) > block_size:
        key = uhashlib.sha256(key).digest()
    key = key + b"\x00" * (block_size - len(key))
    o_pad = bytes(b ^ 0x5C for b in key)
    i_pad = bytes(b ^ 0x36 for b in key)
    inner = uhashlib.sha256(i_pad + message).digest()
    return uhashlib.sha256(o_pad + inner).digest()


def format_py_float(v, decimals=4):
    s = "%.*f" % (decimals, v)
    if "." in s:
        while s.endswith("0"):
            s = s[:-1]
        if s.endswith("."):
            s += "0"
    return s


def canonical_json(fields: dict) -> str:
    """Sorted-key JSON with Python's default separators. Each value must
    ALREADY be a JSON literal string. Identical to main.py's."""
    parts = ['"%s": %s' % (k, fields[k]) for k in sorted(fields.keys())]
    return "{" + ", ".join(parts) + "}"


# ---------- Build + sign + publish ----------

def build_and_sign(features, boot_id, seq, ts_ms, pending_nonce):
    """M0 = canonical(device_id, features, boot_id, seq, ts [, nonce echo])
       sigma = HMAC-SHA256(device_key, M0)
       M = {"payload": M0, "signature": sigma}
    The signature is never an input to itself."""
    fields = {
        "boot_id": str(boot_id),
        "burst_max_ms": format_py_float(features["burst_max_ms"]),
        "device_id": '"%s"' % DEVICE_ID,
        "duty_cycle": format_py_float(features["duty_cycle"]),
        "inter_event_cv": format_py_float(features["inter_event_cv"]),
        "seq": str(seq),
        "trigger_rate": format_py_float(features["trigger_rate"]),
        "ts": str(ts_ms),
    }
    if pending_nonce is not None:
        fields["step_up_nonce_echo"] = '"%s"' % pending_nonce
    canonical = canonical_json(fields)
    signature = ubinascii.hexlify(hmac_sha256(DEVICE_SECRET.encode(), canonical.encode())).decode()
    return '{"payload": %s, "signature": "%s"}' % (canonical, signature)


# ---------- Mutual authentication + decision anti-replay (mirrors main.py) ----------

def _consteq(a, b):
    if len(a) != len(b):
        return False
    diff = 0
    for i in range(len(a)):
        diff |= ord(a[i]) ^ ord(b[i])
    return diff == 0


def verify_decision_signature(payload, signature_hex):
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


_last_decision_boot_id = None
_last_decision_seq = 0


def check_decision_replay(payload):
    global _last_decision_boot_id, _last_decision_seq
    boot_id = payload["gateway_boot_id"]
    seq = payload["decision_seq"]
    if _last_decision_boot_id is None or boot_id > _last_decision_boot_id:
        _last_decision_boot_id = boot_id
        _last_decision_seq = seq
        return False
    if boot_id < _last_decision_boot_id:
        return True
    if seq <= _last_decision_seq:
        return True
    _last_decision_seq = seq
    return False


_pending_step_up_nonce = None


def on_message(topic, msg):
    global _pending_step_up_nonce
    if topic == CHALLENGE_TOPIC:
        try:
            _pending_step_up_nonce = ujson.loads(msg)["nonce"]
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
        print("[decision] !! REJECTED -- signature invalid, NOT acting on it")
        return
    if check_decision_replay(payload):
        print("[decision] !! REJECTED -- replayed decision, NOT acting on it")
        return
    print("[decision] << verified gateway decision:", payload["decision"])


# ---------- Main loop ----------

def main():
    global _pending_step_up_nonce
    connect_wifi()
    _utc_offset = 0 if sync_time() else RTC_LOCAL_UTC_OFFSET_SECONDS
    sw420_init()
    client = connect_mqtt()
    client.set_callback(on_message)
    client.subscribe(DECISION_TOPIC)
    client.subscribe(CHALLENGE_TOPIC)

    boot_id = load_and_increment_boot_id()
    seq = 0
    print("[main] boot_id =", boot_id, "-- publishing", DEVICE_ID,
          "every", PUBLISH_INTERVAL_MS, "ms")
    print("[main] SANITY CHECK: tap the board now. trigger_rate must move off 0.")
    print("[main] If it never moves, the D0 wire or the potentiometer threshold is wrong --")
    print("[main] a disconnected SW-420 reads all-zero, exactly like a still board.")

    while True:
        window = sample_window()
        features = extract_features(window)

        try:
            # MicroPython epoch is 2000-01-01, the gateway uses Unix; and if NTP
            # failed the RTC holds local time. Both corrections, same as main.py.
            ts_ms = int((time.time() + 946684800 - _utc_offset) * 1000)
            seq += 1
            nonce_to_echo = _pending_step_up_nonce
            _pending_step_up_nonce = None
            envelope = build_and_sign(features, boot_id, seq, ts_ms, nonce_to_echo)
            client.publish(TELEMETRY_TOPIC, envelope)
            client.check_msg()
            print("[tx] seq=%d rate=%.1f/s duty=%.3f burst=%.1fms cv=%.3f" % (
                seq, features["trigger_rate"], features["duty_cycle"],
                features["burst_max_ms"], features["inter_event_cv"]))
        except OSError as e:
            print("[main] MQTT error:", e, "-- reconnecting")
            try:
                client = connect_mqtt()
                client.set_callback(on_message)
                client.subscribe(DECISION_TOPIC)
                client.subscribe(CHALLENGE_TOPIC)
            except OSError:
                pass

        time.sleep_ms(PUBLISH_INTERVAL_MS)


if __name__ == "__main__":
    main()
