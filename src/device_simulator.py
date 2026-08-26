"""
Modules 1, 2 & 6 (device side): CPS Device Identity, Authentication, and
Secure Communication.

Hybrid testbed (CLAUDE.md Section 2 / synopsis Section 5.4): this process
simulates the ORIGINAL starter-kit scalar devices (`sensor-002`,
`actuator-001`) AND a software stand-in for the real ESP32
(`esp32-vib-001`, real firmware in `firmware/main.py`) -- same wire
protocol either way, so the gateway/trust-engine/scorer pipeline can be
developed and tested without hardware plugged in, then the real board
swapped in for `esp32-vib-001` with zero gateway-side changes.

`esp32-vib-001` publishes the 5-feature vibration-analysis vector (Section
5.1) computed via feature_engineering.extract_features() over a synthetic
raw accel-magnitude window -- the exact same function the offline training
scripts and (conceptually) the firmware use, so simulated and real
telemetry are shaped identically.

NOTE on `ts`: integer milliseconds, not a raw Python float -- keeps the
HMAC canonical string (json.dumps(payload, sort_keys=True)) byte-identical
regardless of which language computed it (matters for firmware/main.py's
MicroPython signer). Also now the input to replay protection (Module 4 /
synopsis Stage 6) -- see config.REBOOT_TS_THRESHOLD_MS.

Deliberate misbehaviour injected, one flavour per adversarial-testing
scenario the synopsis's Stage 6 names explicitly:
  - esp32-vib-001: an in-range-but-anomalous shock window (behavioural
    drift / developing fault) -- catchable only by the ML scorers, not
    the plain range check.
  - actuator-001: a forged signature (impersonation).
  - sensor-002: an out-of-range value (spoofed/faulty reading).
  - esp32-vib-001 (separately): a verbatim REPLAY of an earlier valid,
    correctly-signed message -- tests Module 4's new freshness check.
  - ALL THREE simultaneously: a COORDINATED multi-device event -- each
    device's reading is individually only MILDLY off (still inside its
    hard expected_range/expected_ranges, so the rule-based check never
    fires, and each one alone is ambiguous enough that a single-device
    scorer can't confidently call it either way) but all three drift the
    same direction in the same tick. This is the scenario Stage 6 names
    as "coordinated multi-device attack" and the one gnn_scorer.py's
    relational, cross-device signal specifically exists to catch -- see
    that file's docstring and scripts/train_gnn.py's snapshot-labelling
    fix for why per-device scorers structurally can't see this pattern
    even in principle (each one only ever looks at its own device).
"""

import hashlib
import hmac
import json
import random
import time

import paho.mqtt.client as mqtt

from config import (
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TLS_PORT,
    MQTT_USE_TLS,
    MQTT_TLS_CA_CERT,
    MQTT_USE_AUTH,
    TELEMETRY_TOPIC,
    DECISION_TOPIC,
    DEVICE_REGISTRY,
    FEATURE_SAMPLE_RATE_HZ,
    FEATURE_WINDOW_SIZE,
)
import feature_engineering as fe


def sign(secret: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def verify_decision_signature(secret: str, envelope: dict) -> bool:
    """Module 2 mutual-authentication extension (device side): recompute
    what the gateway's signature on this decision SHOULD be, using the same
    secret this device already holds to sign its own telemetry, and compare
    in constant time -- mirrors gateway.py's verify_signature() exactly,
    just with the roles reversed. This is the device-side half of what
    makes authentication mutual rather than one-directional; see
    implementation-docs/02_module_authentication.md."""
    payload = envelope.get("payload")
    signature = envelope.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return False
    canonical = json.dumps(payload, sort_keys=True).encode()
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _make_on_decision(device_id: str, secret: str):
    def _on_decision(client, userdata, msg):
        try:
            envelope = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            print(f"[simulator/{device_id}] malformed decision message, dropping")
            return
        if verify_decision_signature(secret, envelope):
            decision = envelope["payload"]["decision"]
            print(f"[simulator/{device_id}] << verified gateway decision: {decision}")
        else:
            print(f"[simulator/{device_id}] !! REJECTED decision message -- signature invalid "
                  f"(forged/tampered, or not really from the gateway) -- ignoring, NOT acting on it")
    return _on_decision


def _synthetic_accel_window(anomalous: bool, coordinated: bool = False) -> list[float]:
    """Fabricated raw accel-magnitude samples standing in for what the real
    MPU6050 would produce -- quiet baseline (~1g + small noise) normally,
    an impulsive SINGLE-sample shock (large spike + higher-frequency
    content) when `anomalous`, mirroring a real developing mechanical
    fault. `coordinated` is a deliberately different SHAPE, not just a
    smaller version of the same spike: a mild elevation spread across
    several samples rather than one isolated outlier. That distinction
    matters -- kurtosis (the 4th standardised moment) is dominated by
    whether a single sample is an outlier at all, almost regardless of its
    exact magnitude, so a scaled-down single-sample spike still saturates
    kurtosis close to the full-shock case and isn't actually ambiguous.
    Spreading the elevation over multiple samples keeps kurtosis and
    crest_factor genuinely mid-range -- individually ambiguous, only
    meaningful combined with the other two devices also drifting in the
    same tick (see module docstring)."""
    n = FEATURE_WINDOW_SIZE
    baseline = [max(0.0, random.gauss(1.0, 0.03)) for _ in range(n)]
    if anomalous:
        baseline[random.randrange(n)] = random.uniform(3.0, 4.5)
    elif coordinated:
        num_elevated = random.randint(3, 5)
        for idx in random.sample(range(n), num_elevated):
            baseline[idx] = max(0.0, random.gauss(1.5, 0.1))
    return baseline


def make_reading(device_id: str, anomalous: bool = False, coordinated: bool = False):
    """Returns the value(s) to publish for one message: a plain float for
    scalar devices, or a features dict for esp32-vib-001. `coordinated`
    (mutually exclusive with `anomalous` in practice) nudges the reading
    toward the edge of its expected range instead of past it -- see module
    docstring's "ALL THREE simultaneously" scenario."""
    if device_id == "esp32-vib-001":
        window = _synthetic_accel_window(anomalous, coordinated)
        if anomalous:
            raw = random.randint(2000, 4095)
        elif coordinated:
            raw = random.randint(900, 1500)
        else:
            raw = random.randint(50, 400)
        features = fe.extract_features(window, FEATURE_SAMPLE_RATE_HZ)
        features["vibration_raw"] = raw
        return features
    lo, hi = DEVICE_REGISTRY[device_id]["expected_range"]
    if anomalous:
        return round(hi + random.uniform(hi * 2, hi * 6) + 1.0, 2)
    if coordinated:
        span = hi - lo
        return round(hi - random.uniform(0.0, span * 0.06), 2)  # tight band at the top edge, still in-range
    return round(random.uniform(lo, hi), 2)


def _build_payload(device_id: str, reading) -> dict:
    payload = {"device_id": device_id, "ts": int(time.time() * 1000)}
    if isinstance(reading, dict):
        payload.update(reading)
    else:
        payload["value"] = reading
    return payload


def _connect(client: mqtt.Client, device_id: str, info: dict) -> None:
    """Each device gets its OWN broker connection/credential (see
    module docstring's "one connection per device" note) -- if
    MQTT_USE_AUTH is on, this is `info["mqtt_username"]`/`mqtt_password`,
    NOT a shared simulator-wide login. That's what makes
    certs/mosquitto_acl's per-device topic restriction (IEC 62443 FR5)
    real rather than theater: if all 3 simulated devices shared one
    over-privileged connection, the broker couldn't actually tell them
    apart or enforce least-privilege between them."""
    if MQTT_USE_AUTH:
        client.username_pw_set(info["mqtt_username"], info["mqtt_password"])
    client.on_message = _make_on_decision(device_id, info["secret"])
    decision_topic = f"{DECISION_TOPIC}/{device_id}"
    client.on_connect = lambda c, userdata, flags, reason_code, properties=None: c.subscribe(decision_topic)
    if MQTT_USE_TLS:
        client.tls_set(ca_certs=MQTT_TLS_CA_CERT)
        client.connect(MQTT_HOST, MQTT_TLS_PORT, keepalive=30)
    else:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)


def run():
    transport_desc = f"MQTT/TLS ({MQTT_HOST}:{MQTT_TLS_PORT})" if MQTT_USE_TLS else f"plain MQTT ({MQTT_HOST}:{MQTT_PORT})"
    auth_desc = "with per-device broker credentials" if MQTT_USE_AUTH else "anonymously -- no certs/mosquitto_passwd found"
    print(f"[simulator] connecting each of {list(DEVICE_REGISTRY.keys())} over {transport_desc}, {auth_desc}")

    clients: dict[str, mqtt.Client] = {}
    for device_id, info in DEVICE_REGISTRY.items():
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=device_id)
        _connect(client, device_id, info)
        client.loop_start()
        clients[device_id] = client

    tick = 0
    captured_message = None  # JSON string of a real, validly-signed message -- for the replay scenario
    try:
        while True:
            coordinated_tick = tick % 25 == 3
            if coordinated_tick:
                print("[simulator]  >> injecting COORDINATED multi-device drift across all 3 devices")
            for device_id, info in DEVICE_REGISTRY.items():
                anomalous = device_id == "esp32-vib-001" and tick % 12 == 7
                if anomalous:
                    print(f"[simulator]  >> injecting anomalous shock window for {device_id}")
                reading = make_reading(device_id, anomalous, coordinated=coordinated_tick and not anomalous)
                payload = _build_payload(device_id, reading)

                if device_id == "actuator-001" and tick % 15 == 9:
                    signature = "0" * 64  # deliberately wrong -- impersonation scenario (APPLICATION layer, HMAC)
                    print(f"[simulator]  >> injecting bad SIGNATURE for {device_id}")
                else:
                    signature = sign(info["secret"], payload)

                message_str = json.dumps({"payload": payload, "signature": signature})
                clients[device_id].publish(TELEMETRY_TOPIC, message_str)

                if device_id == "esp32-vib-001" and not anomalous:
                    captured_message = message_str  # keep the most recent legit esp32-vib-001 message on hand

            # --- REPLAY scenario (synopsis Stage 6): every ~20 ticks, re-send
            # a previously captured, validly-signed message verbatim. A
            # working Module 4 freshness check rejects it even though the
            # signature is genuine -- this is the scenario docs/06 used to
            # list as an unaddressed limitation, now actually exercised.
            if captured_message is not None and tick % 20 == 14:
                print("[simulator]  >> REPLAYING a previously captured esp32-vib-001 message")
                clients["esp32-vib-001"].publish(TELEMETRY_TOPIC, captured_message)

            tick += 1
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[simulator] stopped.")
    finally:
        for client in clients.values():
            client.loop_stop()
            client.disconnect()


if __name__ == "__main__":
    run()
