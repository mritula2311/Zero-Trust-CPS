"""
Modules 1, 2 & 6 (device side): CPS Device Identity, Authentication, and
Secure Communication.

Hybrid testbed: this process simulates the original starter-kit scalar
devices (`sensor-002`, `actuator-001`) AND a software stand-in for the real
ESP32 (`esp32-vib-001`, real firmware in `firmware/main.py`) -- same wire
protocol either way.

TWO-SCORE REARCHITECTURE additions (see trust_engine.py / gateway.py):
  - Every device now carries `boot_id` (increments once per simulated
    reboot) and `seq` (resets to 1 per boot, strictly increasing within a
    boot) -- see the "reboot" scenario below and
    docs/03_module2_authentication.md Section 4.
  - Every device subscribes to its own `cps/challenge/{device_id}` topic
    and echoes a received nonce (`step_up_nonce_echo`) in its NEXT
    telemetry message -- the real step-up challenge/response mechanism,
    not just a policy label. Included in the signed payload like every
    other field.
  - `stealthy_forged_values`: esp32-vib-001 periodically publishes a fully
    valid, correctly-signed, correctly-sequenced message whose reported
    sensor values are deliberately fabricated to look normal regardless of
    what actually "happened" -- ground truth (for training/eval labels)
    is suspicious, but nothing in the telemetry itself distinguishes it
    from a real normal reading. This is expected to be caught near 0% of
    the time by design (docs/04_module3_trust_evaluation.md Section B.8)
    -- included to measure and honestly report that limit, not to solve it.

Deliberate misbehaviour injected, one flavour per adversarial-testing
scenario:
  - esp32-vib-001: an in-range-but-anomalous shock window (behavioural
    drift / developing fault) -- catchable only by the ML scorers.
  - actuator-001: a forged signature (impersonation).
  - sensor-002: an out-of-range value (spoofed/faulty reading).
  - esp32-vib-001 (separately): a verbatim REPLAY of an earlier valid,
    correctly-signed message.
  - esp32-vib-001 (separately): a "reboot" -- boot_id increments, seq
    resets to 1; a working gateway must ACCEPT the first post-reboot
    message, not reject it as a replay.
  - esp32-vib-001 (separately): "stealthy_forged_values" -- see above.
  - ALL THREE simultaneously: a COORDINATED multi-device event.
"""

import hashlib
import hmac
import json
import math
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
    CHALLENGE_TOPIC,
    DEVICE_REGISTRY,
    FEATURE_SAMPLE_RATE_HZ,
    FEATURE_WINDOW_SIZE,
    REAL_HARDWARE_DEVICE_IDS,
    is_feature_vector,
)
import feature_engineering as fe

# The original runtime demo/training task. Network research profiles are built
# separately by generate_network_data.py, with sensor-specific generators.
LEGACY_DEVICE_IDS = ("esp32-vib-001", "sensor-002", "actuator-001")


def sign(secret: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def verify_decision_signature(secret: str, envelope: dict) -> bool:
    """Module 2 mutual-authentication extension (device side)."""
    payload = envelope.get("payload")
    signature = envelope.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return False
    canonical = json.dumps(payload, sort_keys=True).encode()
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# device_id -> nonce (hex str) waiting to be echoed on the NEXT outgoing message
_pending_step_up_echo: dict[str, str] = {}


def _make_on_message(device_id: str, secret: str):
    decision_topic = f"{DECISION_TOPIC}/{device_id}"
    challenge_topic = f"{CHALLENGE_TOPIC}/{device_id}"

    def _on_message(client, userdata, msg):
        if msg.topic == challenge_topic:
            try:
                body = json.loads(msg.payload.decode())
                nonce = body["nonce"]
            except (json.JSONDecodeError, KeyError, TypeError):
                print(f"[simulator/{device_id}] malformed challenge, ignoring")
                return
            _pending_step_up_echo[device_id] = nonce
            print(f"[simulator/{device_id}] << received step-up challenge, will echo on next message")
            return
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

    return _on_message, decision_topic, challenge_topic


# At-rest noise std of the synthetic baseline. CALIBRATED TO REAL HARDWARE
# (firmware/HARDWARE_DATA_LOG.md): the real MPU6050 at rest produces
# peak-to-peak ~0.01-0.03g and crest_factor ~0.01-0.03, i.e. a per-sample std
# of ~0.005g -- MUCH quieter than the original synthetic 0.03 (which gave
# peak/crest ~0.15 and made every real at-rest reading look anomalous to the
# ML scorers, the train/serve gap seen on first bring-up). 0.006 makes the
# synthetic stand-in match what the real board actually reports, so one
# coherent "normal" distribution covers both simulated and real telemetry.
REST_NOISE_STD = 0.004        # white noise floor, calibrated to the real board
REST_DRIFT_AMPLITUDE = 0.002  # slow mechanical/thermal wander riding above it
# TRIED, MEASURED AND REVERTED -- do not re-apply without re-measuring the FUSED
# result. The real board's resting spectrum is lower than the synthetic one
# (median 62.5 vs 78.1 Hz, 27% vs 19% below 40 Hz), and the Isolation Forest's
# resting dips cluster in the under-covered 0-30 Hz bucket (iso median 0.666,
# 7/17 below threshold, against 0.974 for the well-covered 30-80 Hz bucket). So
# 10/90/40 was fitted to match the real distribution (match error 1.91 -> 0.74)
# and the full chain retrained. It made the SYSTEM worse: real-hardware
# false positives went 0/49 -> 3/49 while resting iso barely moved (28 -> 25
# samples below 0.6). Better marginal calibration of the noisiest axis is not
# the same as a better decision, and only the fused number tells you which.
REST_DRIFT_HZ_MIN = 15.0      # drawn per window so the spectrum has real spread
REST_DRIFT_HZ_MAX = 90.0
REST_DC_MIN = 0.975         # resting magnitude range -- see REST_DC_CENTRE below
REST_DC_MAX = 1.10
# RESTING DC IS NOT STABLE ACROSS SESSIONS, and this constant must not be
# tuned as if it were. Measured resting rms medians on the SAME board:
#     session 1  1.041 g      session 2/3  1.056 g      live re-check  1.011 g
# a 0.045 g spread, i.e. 4.5x the within-session std (0.009 g). Accelerometer
# bias and resting orientation both move it; |a| at rest is ~1 g by physics but
# not the SAME ~1 g twice.
#
# Recorded because it cost a wrong fix: centring tightly on the then-latest
# measurement (1.053) made the offline numbers on the three captured sessions
# look excellent -- real-hardware false positives went 2/49 to 0/49 -- and then
# the very next live reading of a genuinely resting board sat at -4.0 sigma,
# because the board had settled at 1.011 that day. Chasing the centre optimises
# for the last session captured; what the models need is a normal region wide
# enough to contain every session the board will actually have.
#
# So: centre on the MIDPOINT of the observed range and widen the spread to span
# it (stationary std = REST_DC_WALK / sqrt(1 - REST_PERSISTENCE^2) ~= 0.020,
# double the previous 0.010). Detection has enormous headroom to pay for this --
# a disturbed board reconstructs at 7,000-62,000 sigma of baseline error, so
# doubling the resting tolerance costs nothing measurable there, and the
# ablation/real-hardware evaluations below confirm it empirically.
REST_DC_CENTRE = 1.036      # midpoint of the observed cross-session range
REST_DRIFT_HZ_CENTRE = 52.0
REST_DC_WALK = 0.019        # per-window innovation (-> stationary std ~0.020)
REST_DRIFT_WALK = 22.0
REST_PERSISTENCE = 0.30     # how much of the previous window's state carries over;
                            # tuned so the synthetic lag-1 autocorrelation matches
                            # the real board's rather than exceeding it

# Persistent resting state, mean-reverting between windows rather than redrawn.
_rest_dc = REST_DC_CENTRE
_rest_drift_hz = REST_DRIFT_HZ_CENTRE


def _clamp(v, lo, hi):
    return min(hi, max(lo, v))


def _synthetic_accel_window(anomalous: bool, coordinated: bool = False) -> list[float]:
    """Fabricated raw accel-magnitude samples standing in for what the real
    MPU6050 would produce -- quiet baseline (~1g + REST_NOISE_STD noise,
    matched to the real board) normally, an impulsive SINGLE-sample shock
    when `anomalous`, a milder multi-sample elevation when `coordinated`."""
    n = FEATURE_WINDOW_SIZE
    # A resting accelerometer is NOT white noise, and modelling it as white was a
    # real train/serve mismatch. White noise puts the dominant DFT bin roughly
    # uniformly across the band (median 140.6 Hz at 500 Hz sampling), whereas the
    # real board at rest is low-frequency weighted (median 78.1 Hz) -- it carries
    # slow mechanical and thermal drift above its noise floor. Measured
    # consequence: the Isolation Forest scored synthetic normals 0.900 and the
    # REAL resting board 0.000, even with the real samples inside its own
    # training set, because 44 real rows against 3967 synthetic ones read as an
    # isolated cluster.
    #
    # Baseline is therefore a low-frequency drift term over a smaller white
    # floor. The three constants are calibrated against the real at-rest capture
    # (see firmware/HARDWARE_DATA_LOG.md): they reproduce its dominant_freq
    # median of 78.1 Hz and peak median of 0.017 g. drift_hz is drawn per window
    # rather than fixed, so the synthetic spectrum has the same SPREAD as the
    # real one instead of piling onto a single bin.
    # Resting DC level is drawn per window, not pinned to exactly 1.0 g. The real
    # board reads 1.041 g at rest -- gravity plus its own calibration offset --
    # and a synthetic class sitting exactly on 1.000 leaves a systematic 4% gap
    # an Isolation Forest can separate on. Drawing from a small range covers the
    # real operating point WITHOUT hardcoding one unit's calibration, which would
    # just be overfitting the simulator to this particular board.
    # Resting state PERSISTS between windows instead of being redrawn each time.
    # Independent draws give the synthetic sequence ~zero temporal structure
    # (measured lag-1 autocorrelation: rms 0.09, peak -0.02), while a real board
    # carries its slowly-varying state forward (rms 0.26, peak 0.16). That gap
    # only reaches ONE signal -- the LSTM-AE is the only scorer that models a
    # sequence rather than a point -- and it showed up exactly there: every
    # residual false positive on real resting data was LSTM-driven, with the
    # rule and Isolation Forest passing the same samples. A small random walk
    # gives the sequence the continuity the autoencoder is trained to expect.
    # MEAN-REVERTING, not a free random walk. A pure walk has no anchor: it
    # wanders off its own centre (measured: rms median drifted from 1.03 to 1.00
    # and clamped) and is far too persistent (lag-1 0.89 against the real 0.26).
    # Reverting toward a centre gives a stable long-run mean AND a tunable
    # autocorrelation, which is exactly the pair of properties needed here.
    global _rest_dc, _rest_drift_hz
    _rest_dc = _clamp(REST_DC_CENTRE + REST_PERSISTENCE * (_rest_dc - REST_DC_CENTRE)
                      + random.gauss(0.0, REST_DC_WALK), REST_DC_MIN, REST_DC_MAX)
    _rest_drift_hz = _clamp(
        REST_DRIFT_HZ_CENTRE + REST_PERSISTENCE * (_rest_drift_hz - REST_DRIFT_HZ_CENTRE)
        + random.gauss(0.0, REST_DRIFT_WALK), REST_DRIFT_HZ_MIN, REST_DRIFT_HZ_MAX)
    dc = _rest_dc
    drift_hz = _rest_drift_hz
    phase = random.uniform(0.0, 2.0 * math.pi)
    baseline = [
        max(0.0, dc
            + REST_DRIFT_AMPLITUDE * math.sin(2.0 * math.pi * drift_hz * t / FEATURE_SAMPLE_RATE_HZ + phase)
            + random.gauss(0.0, REST_NOISE_STD))
        for t in range(n)
    ]
    if anomalous:
        baseline[random.randrange(n)] = random.uniform(3.0, 4.5)
    elif coordinated:
        num_elevated = random.randint(3, 5)
        for idx in random.sample(range(n), num_elevated):
            baseline[idx] = max(0.0, random.gauss(1.5, 0.1))
    return baseline


def make_reading(device_id: str, anomalous: bool = False, coordinated: bool = False, stealthy: bool = False):
    """Returns the value(s) to publish for one message. `stealthy` forces
    the window to look exactly like a normal baseline regardless of
    `anomalous`/`coordinated` -- the whole point of the
    stealthy_forged_values scenario is that the REPORTED values are
    deliberately innocuous even though the situation (ground truth, for
    training/eval only) is not."""
    if is_feature_vector(device_id):
        if stealthy:
            window = _synthetic_accel_window(anomalous=False, coordinated=False)
        else:
            window = _synthetic_accel_window(anomalous, coordinated)
        return fe.extract_features(window, FEATURE_SAMPLE_RATE_HZ)
    lo, hi = DEVICE_REGISTRY[device_id]["expected_range"]
    if anomalous:
        return round(hi + random.uniform(hi * 2, hi * 6) + 1.0, 2)
    if coordinated:
        span = hi - lo
        return round(hi - random.uniform(0.0, span * 0.06), 2)  # tight band at the top edge, still in-range
    return round(random.uniform(lo, hi), 2)


def _build_payload(device_id: str, reading, boot_id: int, seq: int) -> dict:
    payload = {"device_id": device_id, "ts": int(time.time() * 1000), "boot_id": boot_id, "seq": seq}
    nonce = _pending_step_up_echo.pop(device_id, None)
    if nonce is not None:
        payload["step_up_nonce_echo"] = nonce
    if isinstance(reading, dict):
        payload.update(reading)
    else:
        payload["value"] = reading
    return payload


def _connect(client: mqtt.Client, device_id: str, info: dict) -> tuple[str, str]:
    """Each device gets its OWN broker connection/credential. Subscribes to
    both its decision topic and its challenge topic."""
    if MQTT_USE_AUTH:
        client.username_pw_set(info["mqtt_username"], info["mqtt_password"])
    on_message, decision_topic, challenge_topic = _make_on_message(device_id, info["secret"])
    client.on_message = on_message
    client.on_connect = lambda c, userdata, flags, reason_code, properties=None: (
        c.subscribe(decision_topic), c.subscribe(challenge_topic)
    )
    if MQTT_USE_TLS:
        client.tls_set(ca_certs=MQTT_TLS_CA_CERT)
        client.connect(MQTT_HOST, MQTT_TLS_PORT, keepalive=30)
    else:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    return decision_topic, challenge_topic


def run():
    # Real hardware onboarding: a device_id in REAL_HARDWARE_DEVICE_IDS
    # (src/config.py, see firmware/HARDWARE_SETUP.md) is excluded from
    # simulation entirely -- a real ESP32 publishing under that same
    # identity, plus this simulator ALSO publishing under it, would race
    # on boot_id/seq (trust_engine.check_boot_replay() can only track one
    # session per device_id) and produce spurious replay rejections on
    # whichever publisher's messages arrive second.
    SIMULATED_DEVICES = {d: DEVICE_REGISTRY[d] for d in LEGACY_DEVICE_IDS
                         if d not in REAL_HARDWARE_DEVICE_IDS}
    if REAL_HARDWARE_DEVICE_IDS:
        print(f"[simulator] {sorted(REAL_HARDWARE_DEVICE_IDS)} excluded -- real hardware handles them")

    transport_desc = f"MQTT/TLS ({MQTT_HOST}:{MQTT_TLS_PORT})" if MQTT_USE_TLS else f"plain MQTT ({MQTT_HOST}:{MQTT_PORT})"
    auth_desc = "with per-device broker credentials" if MQTT_USE_AUTH else "anonymously -- no certs/mosquitto_passwd found"
    print(f"[simulator] connecting each of {list(SIMULATED_DEVICES.keys())} over {transport_desc}, {auth_desc}")

    clients: dict[str, mqtt.Client] = {}
    boot_ids: dict[str, int] = {d: 1 for d in SIMULATED_DEVICES}
    seqs: dict[str, int] = {d: 0 for d in SIMULATED_DEVICES}  # incremented to 1 before first publish

    for device_id, info in SIMULATED_DEVICES.items():
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=device_id)
        _connect(client, device_id, info)
        client.loop_start()
        clients[device_id] = client

    tick = 0
    captured_message = None  # JSON string of a real, validly-signed pre-reboot message -- for the replay scenario
    try:
        while True:
            coordinated_tick = tick % 25 == 3
            if coordinated_tick:
                print("[simulator]  >> injecting COORDINATED multi-device drift across all 3 devices")

            reboot_tick = tick % 40 == 20
            stealthy_tick = tick % 30 == 22

            for device_id, info in SIMULATED_DEVICES.items():
                if device_id == "esp32-vib-001" and reboot_tick:
                    boot_ids[device_id] += 1
                    seqs[device_id] = 0
                    print(f"[simulator]  >> {device_id} REBOOTING (boot_id -> {boot_ids[device_id]}, seq resets to 1)")

                seqs[device_id] += 1
                boot_id, seq = boot_ids[device_id], seqs[device_id]

                anomalous = device_id == "esp32-vib-001" and tick % 12 == 7
                stealthy = device_id == "esp32-vib-001" and stealthy_tick and not anomalous
                if stealthy:
                    print(f"[simulator]  >> injecting STEALTHY forged values for {device_id} "
                          f"(valid signature, innocuous-looking values -- expected to evade detection)")
                if anomalous:
                    print(f"[simulator]  >> injecting anomalous shock window for {device_id}")

                reading = make_reading(
                    device_id, anomalous, coordinated=coordinated_tick and not anomalous and not stealthy,
                    stealthy=stealthy,
                )
                payload = _build_payload(device_id, reading, boot_id, seq)

                if device_id == "actuator-001" and tick % 15 == 9:
                    signature = "0" * 64  # deliberately wrong -- impersonation scenario
                    print(f"[simulator]  >> injecting bad SIGNATURE for {device_id}")
                else:
                    signature = sign(info["secret"], payload)

                message_str = json.dumps({"payload": payload, "signature": signature})
                clients[device_id].publish(TELEMETRY_TOPIC, message_str)

                if device_id == "esp32-vib-001" and not anomalous and not stealthy:
                    captured_message = message_str  # keep the most recent legit esp32-vib-001 message on hand

            # REPLAY scenario: every ~20 ticks, re-send a previously
            # captured, validly-signed message verbatim. If a reboot has
            # happened since it was captured, the boot_id check now rejects
            # it as replay_of_superseded_boot_session instead of (or in
            # addition to) the plain seq check -- a strictly stronger test
            # than the old ts-only heuristic.
            if captured_message is not None and "esp32-vib-001" in clients and tick % 20 == 14:
                print("[simulator]  >> REPLAYING a previously captured esp32-vib-001 message")
                clients["esp32-vib-001"].publish(TELEMETRY_TOPIC, captured_message)

            # HIGH-RATE / flood scenario (attack-matrix row 5): every ~18
            # ticks, sensor-002 publishes a rapid burst instead of waiting
            # for its normal ~2s cadence -- genuinely trips
            # trust_engine.check_flood()'s real wall-clock timing (not a
            # synthetic flag, unlike generate_training_data.py's offline
            # `simulated_flood`), so Module 3 Section A's Security Trust
            # Score actually degrades from real message-arrival timing,
            # live, exercising the STEP_UP challenge/response path this
            # scenario exists to test.
            if "sensor-002" in clients and tick % 18 == 11:
                print("[simulator]  >> injecting HIGH-RATE burst for sensor-002 (flood, authenticated)")
                info = SIMULATED_DEVICES["sensor-002"]
                for _ in range(4):
                    seqs["sensor-002"] += 1
                    burst_payload = _build_payload(
                        "sensor-002", make_reading("sensor-002"), boot_ids["sensor-002"], seqs["sensor-002"]
                    )
                    burst_sig = sign(info["secret"], burst_payload)
                    clients["sensor-002"].publish(
                        TELEMETRY_TOPIC, json.dumps({"payload": burst_payload, "signature": burst_sig})
                    )
                    time.sleep(0.1)

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
