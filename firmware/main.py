# firmware/main.py -- runs on the ESP32 under MicroPython (CLAUDE.md Section 3).
#
# Replaces the earlier Arduino/C++ firmware (hardware/esp32_zt_device.ino) --
# CLAUDE.md Section 3 calls for MicroPython specifically: it shares almost
# identical logic (HMAC construction, JSON message shape) with the Python
# gateway/simulator, and iterates far faster than a C/Arduino compile-flash
# cycle. Publishes as ONE logical device, "esp32-vib-001" (feature_vector
# kind in src/config.py's DEVICE_REGISTRY) -- unlike the old two-identity
# Arduino firmware, this board is one physical device with one identity,
# per CLAUDE.md Section 2's hardware inventory.
#
# ALL FIVE Section-5.1 features (rms, peak, crest_factor, kurtosis,
# dominant_freq) are computed HERE, on-device, rather than shipping a raw
# 32-sample window over the signed MQTT channel. That's a deliberate
# departure from a literal reading of CLAUDE.md's firmware skeleton (which
# only computes rms/peak on-device and implies the gateway does the rest
# from a raw window): signing a 32-element float array would mean
# reproducing Python's exact json.dumps array-of-floats formatting across
# every element, multiplying the float-canonicalisation risk that was
# already the single trickiest part of the predecessor firmware. Computing
# all 5 scalars here keeps the signed payload flat (one canonicalisation
# concern per field, already verified against 6000+ random values in this
# project's build log -- see docs/06_hardware_setup.md) and doesn't need
# scikit-learn/numpy equivalents on the microcontroller: RMS/peak/crest
# factor are a few lines of arithmetic, kurtosis is one more pass over the
# window, and the DFT for dominant_freq is a direct O(N^2) sum (N=32,
# trivially fast on an ESP32, no FFT library needed).
#
# Required libraries: none beyond what ships with MicroPython's ESP32
# port (network, time, ujson, ubinascii, uhashlib, machine, umqtt.simple
# is bundled with most ESP32 MicroPython builds; if yours doesn't have it,
# `mip.install("umqtt.simple")` from the REPL).
#
# BEFORE trusting this end to end: verify the HMAC signature this board
# computes actually matches what gateway.py's verify_signature() expects,
# by publishing one test message and checking the gateway logs `auth=OK`.
# The float-formatting routine below (format_py_float) was verified in
# this project's Python-side build (docs/06_hardware_setup.md) against
# thousands of random values with zero mismatches at 4-decimal precision --
# MicroPython's own number formatting should match CPython's for this
# range, but budget real debugging time for this integration point rather
# than assuming it works on the first try; it's genuinely the part most
# likely to need a second look on real hardware.

import network
import time
import ujson
import ubinascii
import uhashlib
import ussl
from machine import I2C, Pin, ADC
from umqtt.simple import MQTTClient

# ==================== CONFIGURE BEFORE FLASHING ====================
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_HOST = "192.168.x.x"          # your gateway machine's LAN IP -- see docs/06_hardware_setup.md
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
# certs/mosquitto_passwd. Only used if the broker has auth enabled
# (certs/mosquitto_passwd exists) -- see docs/07_transport_zero_trust.md.
MQTT_USE_AUTH = True
MQTT_USERNAME = "esp32-vib-001"
MQTT_PASSWORD = "CHANGE-ME-match-secrets_local.py-MQTT_PASSWORDS"

VIBRATION_ADC_PIN = 34             # any ADC1 pin (32-39) -- avoid ADC2, it conflicts with WiFi
MPU6050_I2C_ADDR = 0x68            # default address when AD0 is tied to GND

TELEMETRY_TOPIC = b"cps/telemetry"
DECISION_TOPIC = ("cps/decisions/" + DEVICE_ID).encode()   # Module 2 mutual-auth extension, see below
SAMPLE_RATE_HZ = 100                # matches config.FEATURE_SAMPLE_RATE_HZ
WINDOW_SIZE = 32                    # matches config.FEATURE_WINDOW_SIZE
PUBLISH_INTERVAL_MS = 2000
# =====================================================================


# ---------- WiFi / MQTT plumbing ----------

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("[wifi] connecting to", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            time.sleep_ms(300)
    print("[wifi] connected, ip=", wlan.ifconfig()[0])


def connect_mqtt():
    client_id = DEVICE_ID + "-" + ubinascii.hexlify(machine_unique_id()).decode()
    user = MQTT_USERNAME if MQTT_USE_AUTH else None
    pw = MQTT_PASSWORD if MQTT_USE_AUTH else None
    if MQTT_USE_TLS:
        client = MQTTClient(client_id, MQTT_HOST, port=MQTT_TLS_PORT, user=user, password=pw,
                             ssl=True, ssl_params={"cert_reqs": ussl.CERT_NONE})
        # NOTE: cert_reqs=CERT_NONE skips CA verification -- acceptable for
        # this prototype's self-signed CA (see certs/ca.crt) on a private
        # testbed network; MicroPython's CA-verification support varies by
        # build/port, and getting cadata=<embedded CA bytes> working is a
        # real task, not a one-liner -- documented here as a stated
        # simplification (CLAUDE.md Section 8's "secret provisioning" note
        # applies the same spirit here: acceptable for a prototype, name it
        # explicitly rather than silently skipping it).
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


# ---------- Vibration sensor (analog) ----------

vib_adc = None


def vibration_init():
    global vib_adc
    vib_adc = ADC(Pin(VIBRATION_ADC_PIN))
    vib_adc.atten(ADC.ATTN_11DB)


def read_vibration_raw():
    return vib_adc.read()  # 0-4095 on the ESP32's 12-bit ADC


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
    # Direct O(N^2) DFT magnitude spectrum -- N=32 is trivially fast on an
    # ESP32, no FFT library needed. Matches feature_engineering.py's
    # dominant_frequency() (excludes the DC bin, same as there).
    n = len(window)
    centered = [v - mean for v in window]
    best_mag_sq = -1.0
    best_freq = 0.0
    # bins 1 .. n//2 (bin 0 is DC, excluded -- mirrors np.fft.rfft + spectrum[0]=0)
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
    # Minimal Taylor-series sine/cosine -- avoids depending on `math` being
    # a full C-accelerated build on every MicroPython port. Good enough
    # precision for a spectral-peak search (not for anything requiring
    # tight numerical accuracy).
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
#
# The gateway recomputes the HMAC over json.dumps(payload, sort_keys=True)
# on the PARSED payload -- so this only needs to reproduce Python's
# shortest-round-trip decimal rendering for values already rounded to 4
# decimals (round(x, 4) above), which was verified against 6000+ random
# values (including negatives, for kurtosis) with zero mismatches. See
# docs/06_hardware_setup.md.
def format_py_float(v, decimals=4):
    s = "%.*f" % (decimals, v)
    if "." in s:
        while s.endswith("0"):
            s = s[:-1]
        if s.endswith("."):
            s += "0"
    return s


# ---------- Build + sign + publish ----------
#
# Canonical key order MUST match json.dumps(payload, sort_keys=True)'s
# alphabetical ordering exactly: crest_factor, device_id, dominant_freq,
# kurtosis, peak, rms, ts, vibration_raw.
def build_and_sign(features, vibration_raw, ts_ms):
    canonical = (
        '{"crest_factor": %s, "device_id": "%s", "dominant_freq": %s, '
        '"kurtosis": %s, "peak": %s, "rms": %s, "ts": %d, "vibration_raw": %d}'
    ) % (
        format_py_float(features["crest_factor"]),
        DEVICE_ID,
        format_py_float(features["dominant_freq"]),
        format_py_float(features["kurtosis"]),
        format_py_float(features["peak"]),
        format_py_float(features["rms"]),
        ts_ms,
        vibration_raw,
    )
    signature = ubinascii.hexlify(hmac_sha256(DEVICE_SECRET.encode(), canonical.encode())).decode()
    envelope = '{"payload": %s, "signature": "%s"}' % (canonical, signature)
    return envelope


# ---------- Mutual authentication: verify the gateway's signed decisions ----------
#
# Module 2 mutual-authentication extension (device side). The decision
# payload is just {"decision": str, "device_id": str, "ts": int} -- no
# floats -- so, unlike build_and_sign() above, reconstructing the exact
# canonical string Python's json.dumps(payload, sort_keys=True) produced
# needs no float-formatting care at all; plain %s/%d string interpolation
# already matches it exactly for these three field types.
def _consteq(a, b):
    if len(a) != len(b):
        return False
    diff = 0
    for i in range(len(a)):
        diff |= ord(a[i]) ^ ord(b[i])
    return diff == 0


def verify_decision_signature(payload, signature_hex):
    canonical = (
        '{"decision": "%s", "device_id": "%s", "ts": %d}'
    ) % (payload["decision"], payload["device_id"], payload["ts"])
    expected = ubinascii.hexlify(hmac_sha256(DEVICE_SECRET.encode(), canonical.encode())).decode()
    return _consteq(expected, signature_hex)


def on_decision(topic, msg):
    try:
        envelope = ujson.loads(msg)
        payload = envelope["payload"]
        signature = envelope["signature"]
    except (ValueError, KeyError):
        print("[decision] malformed message, dropping")
        return
    if verify_decision_signature(payload, signature):
        print("[decision] << verified gateway decision:", payload["decision"])
    else:
        print("[decision] !! REJECTED decision -- signature invalid (forged/tampered, or not really "
              "from the gateway) -- ignoring, NOT acting on it")


def main():
    connect_wifi()
    mpu6050_init()
    vibration_init()
    client = connect_mqtt()
    client.set_callback(on_decision)
    client.subscribe(DECISION_TOPIC)

    boot_ms = time.ticks_ms()
    print("[main] publishing esp32-vib-001 telemetry every", PUBLISH_INTERVAL_MS, "ms")

    while True:
        try:
            window = sample_window()
            features = extract_features(window)
            vibration_raw = read_vibration_raw()
            ts_ms = time.ticks_diff(time.ticks_ms(), boot_ms)  # ms since boot -- see trust_engine.py's replay-check note

            envelope = build_and_sign(features, vibration_raw, ts_ms)
            client.publish(TELEMETRY_TOPIC, envelope)
            print("[publish]", envelope)
            client.check_msg()  # non-blocking: process any pending decision message
        except OSError as e:
            print("[main] connection error, reconnecting:", e)
            try:
                client = connect_mqtt()
                client.set_callback(on_decision)
                client.subscribe(DECISION_TOPIC)
            except OSError:
                connect_wifi()

        time.sleep_ms(PUBLISH_INTERVAL_MS)


if __name__ == "__main__":
    main()
