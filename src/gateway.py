"""
The Zero-Trust Gateway -- Report Section 7.2 (Layer 2) / synopsis Section 7.2.

This single process implements the Policy Decision / Enforcement Point:
  Module 1 (Device Identity)      -> DEVICE_REGISTRY lookup
  Module 2 (Authentication)       -> verify_signature() + boot/seq replay +
                                      timestamp freshness + step-up
                                      challenge/response +
                                      IdentityTargetingRisk (attribution fix)
  Module 3, Section A             -> trust_engine.score_security_trust()
                                      (Security Trust Score: cyber-behaviour
                                      evidence ONLY -- rate/flood, step-up
                                      outcomes, silence)
  Module 3, Section B             -> trust_engine.rule_range_score()
                                      + isolation_forest_scorer (6a)
                                      + lstm_ae_scorer (6b)
                                      + gnn_scorer (6c)
                                      -> fusion_engine.FusionEngine.combine()
                                      (Process Anomaly Score: physical sensor
                                      evidence ONLY)
  Module 4 (Continuous Verification) -> trust_engine's per-device state
                                      store for both scores; both recomputed
                                      on every authenticated message
  Module 5 (Access Control)       -> policy_engine.decide() (2x2 table) or
                                      adaptive_pdp (RL) -- reads BOTH scores,
                                      combines them ONLY through this lookup,
                                      never blended into one number
  Module 6 (Secure Communication) -> MQTT/TLS and CoAP/TLS (coap_server.py)
  Module 7 (Monitoring)           -> audit_log.log_decision() (hash-chained)
                                      + NIST/IEC 62443 tenet mapping + console

TWO-SCORE REARCHITECTURE (see trust_engine.py's module docstring for the
full rationale): the Security Trust Score and Process Anomaly Score are
computed independently and meet ONLY inside policy_engine.decide() /
adaptive_pdp's Q-table lookup -- never blended into one number before that.
A rejected verification attempt (unknown device, bad HMAC, boot/seq replay,
stale timestamp) now NEVER touches the claimed device's own state at all --
see _reject() below and trust_engine.IdentityTargetingRisk.

Every ML scorer here (isolation_forest_scorer, lstm_ae_scorer, gnn_scorer,
fusion_engine) is INFERENCE ONLY -- all training happens offline in
scripts/train_*.py. Run those (in order: isolation_forest, lstm_ae, gnn,
fusion_meta_learner, adaptive_pdp) before starting the gateway, or every
scorer just returns its neutral "not trained yet" fallback.

Run this BEFORE device_simulator.py (or the real ESP32/firmware/main.py).
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
    CHALLENGE_TOPIC,
    DEVICE_REGISTRY,
    USE_RL_POLICY,
    FEATURE_NAMES,
    COAP_ENABLED,
    COAP_TLS_PORT,
)
from trust_engine import RuleBasedTrustEngine, rule_range_score, IdentityTargetingRisk
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from policy_engine import decide
from adaptive_pdp import AdaptivePDP
import feature_engineering as fe
import nist_mapping
import audit_log
import explainability

trust_engine = RuleBasedTrustEngine()
identity_targeting_risk = IdentityTargetingRisk()
if_scorer = IsolationForestScorer()
lstm_scorer = LSTMAEScorer()
gnn_scorer = GNNScorer()
fusion_engine = FusionEngine()
adaptive_pdp = AdaptivePDP()

DECISION_ICON = {
    "ALLOW": "\033[92mALLOW  \033[0m",
    "STEP_UP": "\033[93mSTEP_UP\033[0m",
    "ALERT": "\033[96mALERT  \033[0m",
    "BLOCK": "\033[91mBLOCK  \033[0m",
}


def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
    """Module 2: does this REGISTERED device's signature check out? (The
    unknown-device_id case is handled by the caller before this is ever
    called -- see process_telemetry().)"""
    info = DEVICE_REGISTRY[device_id]
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


def _reject(device_id: str, reason: str, transport: str) -> None:
    """Module 2 Section 5 attribution fix: EVERY rejected verification
    attempt lands here, and here ONLY updates IdentityTargetingRisk for the
    CLAIMED device_id -- it never touches that device's own
    SecurityTrustState/ProcessAnomalyState (trust_engine.py). The audit row
    carries the device's LAST KNOWN security trust (read-only peek, via
    get_security_trust()) purely so the legacy NOT-NULL trust_score column
    has something sensible in it -- that value is not modified by this call."""
    count = identity_targeting_risk.record(device_id, reason)
    security_trust_score = trust_engine.get_security_trust(device_id)
    tenets = nist_mapping.tenets_for_decision(False, MQTT_USE_TLS, fusion_engine.is_trained())
    audit_log.log_decision(
        device_id, auth_ok=False, decision="REJECTED", reason=reason,
        security_trust_score=security_trust_score, process_trust_score=None, process_status="",
        policy_source="", nist_tenets=tenets, transport=transport,
        reason_category="identity_targeting", identity_targeting_count_60s=count,
    )
    print(
        f"{device_id:14s} | REJECTED ({reason}) | identity_targeting_risk_60s={count} "
        f"| [{transport}] -- claimed device's OWN trust state untouched"
    )


def process_telemetry(envelope: dict, transport: str, transport_secured: bool) -> None:
    """Shared processing path for one telemetry envelope, regardless of
    which transport delivered it (MQTT in on_message below, or CoAP in
    coap_server.py's resource handler)."""
    try:
        payload = envelope["payload"]
        signature = envelope["signature"]
        device_id = payload["device_id"]
        ts = payload["ts"]
        boot_id = payload["boot_id"]
        seq = payload["seq"]
    except (KeyError, TypeError):
        print(f"[gateway/{transport}] malformed message, dropping")
        return
    step_up_echo = payload.get("step_up_nonce_echo")

    # Module 1: identity known at all? Checked before HMAC (and before
    # even touching IdentityTargetingRisk's throttle) -- an unregistered
    # claimed id is itself routed to IdentityTargetingRisk, never to a
    # registered device's state, since by definition there is none here.
    if device_id not in DEVICE_REGISTRY:
        _reject(device_id, "unknown_device_id", transport)
        return

    # Optional gateway-level protective response (Module 2 Section 5.1):
    # once a claimed id has crossed the failure threshold, drop further
    # attempts against it before even attempting verification.
    if identity_targeting_risk.is_throttled(device_id):
        return

    # Module 2 Check 3: HMAC, against the current key.
    if not verify_signature(device_id, payload, signature):
        _reject(device_id, "hmac_mismatch", transport)
        return

    # Module 2 Check 4: boot-aware anti-replay.
    is_replay, replay_reason = trust_engine.check_boot_replay(device_id, boot_id, seq)
    if is_replay:
        _reject(device_id, replay_reason, transport)
        return

    # Module 2 Check 5: secondary timestamp-freshness window.
    if not trust_engine.check_timestamp_freshness(ts):
        _reject(device_id, "stale_timestamp", transport)
        return

    # -- Fully authenticated from here on. ----------------------------------

    # IEC 62443 FR7 "Resource Availability": a rate anomaly from a
    # genuinely authenticated device is Security Trust evidence, NOT a
    # reason to reject the message or skip Process Anomaly scoring (a
    # flooding-but-real device is still reporting real sensor data).
    is_flood = trust_engine.check_flood(device_id)

    # Module 2 Section 7: resolve any outstanding step-up challenge for
    # this device BEFORE scoring, so a successful response's bounded trust
    # boost is visible to this same message's policy decision.
    step_up_result = trust_engine.check_step_up_response(device_id, step_up_echo)

    security_trust_score, security_reason = trust_engine.score_security_trust(
        device_id, is_flood, step_up_result
    )

    # Module 3, Section B: Process Anomaly Engine (unchanged fusion
    # pipeline -- rule + Isolation Forest + LSTM-AE + GNN + meta-learner,
    # zero retraining needed for the two-score rearchitecture).
    reading = _extract_reading(device_id, payload)
    rule_score, rule_reason = rule_range_score(device_id, reading) if reading is not None else (0.15, "missing reading")

    fv = None
    if device_id == "esp32-vib-001" and isinstance(reading, dict) and all(v is not None for v in reading.values()):
        fv = fe.feature_vector(reading)
        if_score = if_scorer.score(fv)
        lstm_score = lstm_scorer.score(device_id, fv)
    else:
        if_score = lstm_score = rule_score

    gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
    process_trust_score, process_confidence, fused_reason = fusion_engine.combine(
        rule_score, if_score, lstm_score, gnn_score
    )
    trust_engine.update_process_anomaly(device_id, process_trust_score)
    _, process_status = trust_engine.get_process_anomaly(device_id)

    # Module 3 Section C — Two-Level Explainability. Level 1 (which SIGNAL
    # dominated) is already computed inside fusion_engine.combine() above
    # (fusion_engine.last_shap); Level 2 (which raw feature/node WITHIN
    # that signal) is computed here, since only gateway.py holds every
    # scorer instance needed to drill in (see explainability.py's
    # docstring for why this doesn't live inside FusionEngine itself).
    dominant_signal = explainability.dominant_signal_name(fusion_engine.last_shap)
    level2_feature, level2_summary = (
        explainability.level2_explain(
            dominant_signal, device_id, fv, rule_reason, if_scorer, lstm_scorer, gnn_scorer,
        ) if dominant_signal else ("n/a", "fusion model not trained yet -- no dominant signal to explain")
    )

    # Module 5: two-score 2x2 table (static) or the offline-trained RL
    # bandit reading the same two-dimensional state -- either way, the two
    # scores are combined ONLY here, through a lookup, never blended.
    if USE_RL_POLICY:
        decision = adaptive_pdp.greedy_action(security_trust_score, process_trust_score)
        policy_source = "RL"
    else:
        decision = decide(security_trust_score, process_trust_score, process_status)
        policy_source = "STATIC"

    reason_category = ""
    if step_up_result in ("TIMEOUT", "MISMATCH"):
        # Module 5 Section 3: a failed step-up escalates to BLOCK regardless
        # of what the table/bandit said, since the device just failed the
        # extra proof that was specifically demanded of it.
        decision = "BLOCK"
        reason_category = "step_up_failed"
    elif decision == "STEP_UP" and not trust_engine.has_pending_step_up(device_id):
        # No challenge outstanding yet for this device -- issue one now.
        # (step_up_result is None both when nothing is pending AND when a
        # challenge is pending but hasn't been answered yet -- the
        # has_pending_step_up() check is what distinguishes "issue a new
        # one" from "still waiting on the one already sent," so this
        # doesn't move the target on every message while genuinely waiting.)
        nonce = trust_engine.initiate_step_up(device_id)
        _publish_challenge(device_id, nonce)
        reason_category = "step_up_initiated"
    elif step_up_result == "SUCCESS":
        reason_category = "step_up_succeeded"

    _publish_decision(device_id, decision)

    tenets = nist_mapping.tenets_for_decision(True, transport_secured, fusion_engine.is_trained())
    audit_log.log_decision(
        device_id, auth_ok=True, decision=decision,
        reason=f"security: {security_reason} | process: {fused_reason}",
        security_trust_score=security_trust_score, process_trust_score=process_trust_score,
        process_status=process_status,
        if_score=if_score, lstm_score=lstm_score, gnn_score=gnn_score, fused_score=process_trust_score,
        policy_source=policy_source, confidence=process_confidence, nist_tenets=tenets,
        transport=transport, rule_score=rule_score,
        shap=fusion_engine.last_shap, reason_category=reason_category,
        level2_dominant_feature=level2_feature, level2_summary=level2_summary,
    )

    flags = " FLOOD" if is_flood else ""
    print(
        f"{device_id:14s} | {_format_reading(reading)}{flags} "
        f"| security={security_trust_score:5.2f} | process={process_trust_score:5.2f}({process_status}) "
        f"| {DECISION_ICON[decision]}({policy_source}) "
        f"| [{transport}{'/secured' if transport_secured else ''}] | {security_reason} | {fused_reason}"
    )
    if level2_feature not in ("n/a", "unavailable"):
        print(f"{'':14s} | Level-2: {level2_summary}")


_mqtt_publish_client = None  # set in run(); coap_server.py gets its own reference passed in


def _sign_decision(device_id: str, payload: dict) -> str:
    """Module 2 mutual-authentication extension: sign the gateway's own
    outgoing decision the same way a device signs its telemetry."""
    secret = DEVICE_REGISTRY[device_id]["secret"]
    canonical = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def _publish_decision(device_id: str, decision: str) -> None:
    if _mqtt_publish_client is not None:
        payload = {"device_id": device_id, "decision": decision, "ts": int(time.time() * 1000)}
        signature = _sign_decision(device_id, payload)
        _mqtt_publish_client.publish(
            f"{DECISION_TOPIC}/{device_id}", json.dumps({"payload": payload, "signature": signature})
        )


def _publish_challenge(device_id: str, nonce: str) -> None:
    """Module 2 Section 7: the gateway-issued half of the real step-up
    challenge/response flow. Not signed/enveloped like telemetry/decisions
    -- the nonce itself carries no authority (only the DEVICE's signed echo
    of it, over the normal HMAC'd telemetry channel, does), so there's
    nothing here for a forger to gain by spoofing this message beyond
    making a device echo a nonce nobody asked for, which
    check_step_up_response() would simply not have a pending match for."""
    if _mqtt_publish_client is not None:
        _mqtt_publish_client.publish(f"{CHALLENGE_TOPIC}/{device_id}", json.dumps({"nonce": nonce}))


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
    """Runs MQTT and the HTTPS second-transport (coap_server.py) concurrently."""
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
        print(f"[gateway] connecting over plain MQTT ({MQTT_HOST}:{MQTT_PORT})")

    _mqtt_publish_client = client

    print("=" * 110)
    print(" ZERO-TRUST GATEWAY -- Security Trust + Process Anomaly, independently scored (Ctrl+C to stop)")
    print(f" Policy: {'RL-adaptive' if USE_RL_POLICY else 'static 2x2 table'} | "
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
