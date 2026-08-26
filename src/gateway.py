"""
The Zero-Trust Gateway -- Report Section 7.2 (Layer 2) / synopsis Section 7.2.

This single process implements the Policy Decision / Enforcement Point:
  Module 1 (Device Identity)      -> DEVICE_REGISTRY lookup
  Module 2 (Authentication)       -> verify_signature()
  Module 3 (Trust Evaluation)     -> trust_engine.rule_range_score()
                                      + isolation_forest_scorer (6a)
                                      + lstm_ae_scorer (6b)
                                      + gnn_scorer (6c)
                                      -> fusion_engine.FusionEngine.combine() (7: stacking + SHAP)
                                      -> trust_engine.score_message() (EWMA)
  Module 4 (Continuous Verification) -> trust re-scored on EVERY message +
                                      time-decay + replay/freshness check
  Module 5 (Access Control)       -> policy_engine.decide() (5) or adaptive_pdp (8)
  Module 6 (Secure Communication) -> MQTT/TLS and CoAP/TLS (coap_server.py)
  Module 7 (Monitoring)           -> audit_log.log_decision() + NIST tenet mapping + console

CLAUDE.md Section 8 hard constraint: every ML scorer here (isolation_forest_scorer,
lstm_ae_scorer, gnn_scorer, fusion_engine) is INFERENCE ONLY -- all training
happens offline in scripts/train_*.py. Run those (in order: isolation_forest,
lstm_ae, gnn, fusion_meta_learner, adaptive_pdp) before starting the gateway,
or every scorer just returns its neutral "not trained yet" fallback.

Run this BEFORE device_simulator.py (or the real ESP32/firmware/main.py).

`_ground_truth_label()` was `_pseudo_label()` in the online-learning
version of this file -- it's now ONLY used for the console/audit-log
display of what the rule+auth check alone would conclude; it does not
feed any training, since all training now happens offline against REAL
ground-truth labels from scripts/generate_training_data.py's synthetic
session (see fusion_engine.py's docstring for why that's a meaningfully
stronger claim than the old online version's heuristic).
"""

import hashlib
import hmac
import json
import time

import paho.mqtt.client as mqtt

from config import (
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TLS_PORT,
    MQTT_USE_TLS,
    MQTT_TLS_CA_CERT,
    MQTT_USE_AUTH,
    MQTT_GATEWAY_USERNAME,
    MQTT_GATEWAY_PASSWORD,
    TELEMETRY_TOPIC,
    DECISION_TOPIC,
    DEVICE_REGISTRY,
    USE_RL_POLICY,
    AUTH_FAIL_SENTINEL_SCORE,
    FEATURE_NAMES,
    COAP_ENABLED,
    COAP_TLS_PORT,
)
from trust_engine import RuleBasedTrustEngine, rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from policy_engine import decide
from adaptive_pdp import AdaptivePDP
import feature_engineering as fe
import nist_mapping
import audit_log

trust_engine = RuleBasedTrustEngine()
if_scorer = IsolationForestScorer()
lstm_scorer = LSTMAEScorer()
gnn_scorer = GNNScorer()
fusion_engine = FusionEngine()
adaptive_pdp = AdaptivePDP()

DECISION_ICON = {"ALLOW": "\033[92mALLOW\033[0m", "STEP_UP": "\033[93mSTEP_UP\033[0m", "DENY": "\033[91mDENY \033[0m"}


def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
    """Module 1 + 2: does this device exist, and does its signature check out?"""
    info = DEVICE_REGISTRY.get(device_id)
    if info is None:
        return False  # unknown device -> automatic fail, never implicitly trusted
    canonical = json.dumps(payload, sort_keys=True).encode()
    expected = hmac.new(info["secret"].encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _extract_reading(device_id: str, payload: dict):
    """Module 1's `kind` field decides the shape: a plain float for scalar
    devices, or a dict of Section-5.1 features for feature_vector devices."""
    kind = DEVICE_REGISTRY.get(device_id, {}).get("kind", "scalar")
    if kind == "feature_vector":
        return {name: payload.get(name) for name in FEATURE_NAMES}
    return payload.get("value")


def _format_reading(reading) -> str:
    if isinstance(reading, dict):
        return "rms=" + f"{reading.get('rms', 0):.2f}" if reading.get("rms") is not None else "n/a"
    try:
        return f"{reading:>8.2f}"
    except (TypeError, ValueError):
        return str(reading)


def _ground_truth_label(auth_ok: bool, is_replay: bool, is_flood: bool, rule_score: float) -> int:
    """Display-only summary of what auth+range alone would conclude -- NOT
    used for training (see module docstring)."""
    return 1 if (auth_ok and not is_replay and not is_flood and rule_score >= 0.5) else 0


def process_telemetry(envelope: dict, transport: str, transport_secured: bool) -> None:
    """Shared processing path for one telemetry envelope, regardless of
    which transport delivered it (MQTT in on_message below, or CoAP in
    coap_server.py's resource handler) -- Module 6's whole point is that
    the rest of the pipeline doesn't care which secured channel a message
    arrived over."""
    try:
        payload = envelope["payload"]
        signature = envelope["signature"]
        device_id = payload["device_id"]
        ts = payload["ts"]
    except (KeyError, TypeError):
        print(f"[gateway/{transport}] malformed message, dropping")
        return

    reading = _extract_reading(device_id, payload)

    # Module 1 + 2
    auth_ok = verify_signature(device_id, payload, signature)
    # Module 4 extension: replay/freshness check -- a captured, replayed
    # message has a VALID signature by construction, so this has to run
    # independently of auth_ok, not as a special case of it.
    is_replay = trust_engine.check_replay(device_id, ts) if isinstance(ts, int) else False
    # IEC 62443 FR7 "Resource Availability" extension: same reasoning as
    # replay -- a flooding device's messages are each validly signed, so
    # this has to run independently of auth_ok too.
    is_flood = trust_engine.check_flood(device_id)

    rule_score, _ = rule_range_score(device_id, reading) if reading is not None else (0.15, "missing reading")
    label = _ground_truth_label(auth_ok, is_replay, is_flood, rule_score)

    # Module 3 (6a/6b): the per-value scorers only run on authenticated,
    # non-replayed, non-flood data from esp32-vib-001 specifically (they're
    # trained on ITS feature vector). sensor-002/actuator-001 have no model
    # of their own -- mirror rule_score into those slots (documented in
    # gnn_scorer.py and every scripts/train_*.py), matching exactly how
    # the offline training scripts built their datasets.
    if auth_ok and not is_replay and not is_flood:
        if device_id == "esp32-vib-001" and isinstance(reading, dict) and all(v is not None for v in reading.values()):
            fv = fe.feature_vector(reading)
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score
    else:
        if_score = lstm_score = AUTH_FAIL_SENTINEL_SCORE

    gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
    fused_observation, confidence, fused_reason = fusion_engine.combine(rule_score, if_score, lstm_score, gnn_score)

    if auth_ok and not is_replay and not is_flood:
        trust_score, confidence, reason = trust_engine.score_message(
            device_id, reading, auth_ok, fused_observation, fused_reason, confidence
        )
    else:
        # trust_engine's own auth-failure/replay/flood penalty stays
        # authoritative here -- fused_observation was still computed above
        # so the console line shows what the ML pipeline currently thinks,
        # but it doesn't override the auth/replay/flood penalty.
        trust_score, confidence, reason = trust_engine.score_message(
            device_id, reading, auth_ok, is_replay=is_replay, is_flood=is_flood
        )

    # Module 5 (Phase 5 static thresholds, or Phase 8 offline-trained RL bandit)
    if USE_RL_POLICY:
        decision = adaptive_pdp.greedy_action(trust_score, confidence)  # no exploration -- see adaptive_pdp.py's docstring
        policy_source = "RL"
    else:
        decision = decide(trust_score)
        policy_source = "STATIC"

    # Module 6 -- publish the decision back out (e.g., an actuator would check this
    # before acting on a command)
    _publish_decision(device_id, decision)

    # Module 7 -- NIST SP 800-207 tenet mapping (synopsis Section 10.1)
    tenets = nist_mapping.tenets_for_decision(auth_ok, transport_secured, fusion_engine.is_trained())
    audit_log.log_decision(
        device_id, auth_ok, trust_score, decision, reason,
        if_score, lstm_score, gnn_score, fused_observation, policy_source,
        confidence, tenets, transport, rule_score,
        shap=fusion_engine.last_shap,  # full per-signal SHAP breakdown, not just the top feature in `reason`
    )

    flags = (" REPLAY" if is_replay else "") + (" FLOOD" if is_flood else "")
    print(
        f"{device_id:14s} | {_format_reading(reading)} | auth={'OK ' if auth_ok else 'FAIL'}{flags} "
        f"| trust={trust_score:5.2f} | conf={confidence:4.2f} | {DECISION_ICON[decision]}({policy_source}) "
        f"| [{transport}{'/secured' if transport_secured else ''}] | {reason}"
    )


_mqtt_publish_client = None  # set in run(); coap_server.py gets its own reference passed in


def _sign_decision(device_id: str, payload: dict) -> str:
    """Module 2 mutual-authentication extension: sign the gateway's own
    outgoing decision the same way a device signs its telemetry -- same
    HMAC-SHA256 construction, same canonicalisation, same per-device secret
    (already provisioned to both sides in Module 1's DEVICE_REGISTRY, so
    reusing it here needs no new key-distribution step). This is what
    upgrades authentication from one-directional to genuinely MUTUAL: the
    device can now independently verify a `cps/decisions` message really
    came from the gateway (and wasn't forged or tampered with on the wire)
    before acting on it -- see implementation-docs/02_module_authentication.md's
    "Honesty note on 'mutual'" for what this does and does not close (it's
    still not an interactive nonce challenge/response round trip)."""
    secret = DEVICE_REGISTRY[device_id]["secret"]
    canonical = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def _publish_decision(device_id: str, decision: str) -> None:
    """Publishes to a PER-DEVICE topic (cps/decisions/<device_id>), not a
    flat shared topic -- see config.DECISION_TOPIC's comment for why this
    is what makes certs/mosquitto_acl's per-device read restriction
    (IEC 62443 FR5) possible at all. Signed (see _sign_decision above) so
    the receiving device can verify it, mirroring the exact envelope shape
    (`{"payload": ..., "signature": ...}`) devices already use to sign
    THEIR messages to the gateway."""
    if _mqtt_publish_client is not None:
        payload = {"device_id": device_id, "decision": decision, "ts": int(time.time() * 1000)}
        signature = _sign_decision(device_id, payload)
        _mqtt_publish_client.publish(
            f"{DECISION_TOPIC}/{device_id}", json.dumps({"payload": payload, "signature": signature})
        )


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[gateway] connected to broker (rc={reason_code}), subscribing to '{TELEMETRY_TOPIC}'")
    client.subscribe(TELEMETRY_TOPIC)


def on_message(client, userdata, msg):
    try:
        envelope = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        print("[gateway/mqtt] malformed message, dropping")
        return
    process_telemetry(envelope, transport="mqtt", transport_secured=MQTT_USE_TLS)


def run():
    """Runs MQTT and the HTTPS second-transport (coap_server.py -- see its
    docstring for why HTTPS substitutes for CoAP/DTLS here) concurrently:
    HTTPS starts in its own background thread, MQTT's network loop owns
    the main thread. Module 6 requires both transports live at once, not
    either/or."""
    global _mqtt_publish_client
    audit_log.init_db()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="zt-gateway")
    client.on_connect = on_connect
    client.on_message = on_message

    if MQTT_USE_AUTH:
        client.username_pw_set(MQTT_GATEWAY_USERNAME, MQTT_GATEWAY_PASSWORD)

    if MQTT_USE_TLS:
        client.tls_set(ca_certs=MQTT_TLS_CA_CERT)
        client.connect(MQTT_HOST, MQTT_TLS_PORT, keepalive=30)
        print(f"[gateway] connecting over MQTT/TLS ({MQTT_HOST}:{MQTT_TLS_PORT})")
    else:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        print(f"[gateway] connecting over plain MQTT ({MQTT_HOST}:{MQTT_PORT}) -- run docs/03_add_tls.md's setup to switch to TLS")

    _mqtt_publish_client = client

    print("=" * 110)
    print(" ZERO-TRUST GATEWAY -- live trust evaluation + access decisions (Ctrl+C to stop)")
    print(f" Policy: {'RL-adaptive (Phase 8)' if USE_RL_POLICY else 'static thresholds (Phase 5)'} | "
          f"Fusion trained: {fusion_engine.is_trained()} | IF trained: {if_scorer.is_trained()} | "
          f"LSTM-AE trained: {lstm_scorer.is_trained()} | GNN trained: {gnn_scorer.is_trained()}")
    print(f" Second transport (HTTPS, substituting for CoAP/DTLS): "
          f"{'enabled, port ' + str(COAP_TLS_PORT) if COAP_ENABLED else 'disabled (no certs/coap_server.* found)'}")
    print(f" MQTT broker auth (IEC 62443 FR5, per-device credentials + topic ACLs): "
          f"{'enabled' if MQTT_USE_AUTH else 'disabled (anonymous broker access -- no certs/mosquitto_passwd found)'}")
    print("=" * 110)

    if COAP_ENABLED:
        import coap_server
        coap_server.start_https_server()  # non-blocking -- own background thread

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[gateway] stopped.")


if __name__ == "__main__":
    run()
