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
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
    is_feature_vector,
    COAP_ENABLED,
    COAP_TLS_PORT,
    SECURITY_THRESHOLD,
    PROCESS_THRESHOLD,
    NIST_TENETS,
    ADAPTIVE_PDP_MODEL_PATH,
    DASHBOARD_PORT,
    GATEWAY_BOOT_ID_PATH,
    SILENCE_CHECK_INTERVAL_SECONDS,
)
from trust_engine import (
    RuleBasedTrustEngine, rule_range_score, IdentityTargetingRisk,
    is_revoked, verify_signature_with_rotation,
)
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from policy_engine import decide
from adaptive_pdp import AdaptivePDP, ACTIONS
import feature_engineering as fe
import nist_mapping
import governance_validation
import iec62443_mapping
import audit_log
import explainability

trust_engine = RuleBasedTrustEngine()
identity_targeting_risk = IdentityTargetingRisk()
if_scorer = IsolationForestScorer()
lstm_scorer = LSTMAEScorer()
gnn_scorer = GNNScorer()
fusion_engine = FusionEngine()
adaptive_pdp = AdaptivePDP()

# Serializes the whole telemetry pipeline. run() starts several threads that
# reach the same UNLOCKED mutable state -- the MQTT loop and the HTTPS second
# transport (coap_server.py) both call process_telemetry(), and the silence
# watchdog reads/mutates trust_engine's per-device state -- so the
# "single-threaded pipeline" assumption documented in fusion_engine.py and
# trust_engine.py does not actually hold. Without this lock two in-flight
# messages can interleave and corrupt shared state: FusionEngine.last_shap
# (read by process_telemetry right after combine() to log it), LSTMAEScorer's
# per-device rolling window, GNNScorer's last_features/last_seen arrays, and
# check_boot_replay()'s last_seen_seq. Held pipeline -> chain (audit_log's
# own lock) and never the reverse, so the two locks cannot deadlock.
_pipeline_lock = threading.Lock()

DECISION_ICON = {
    "ALLOW": "\033[92mALLOW  \033[0m",
    "STEP_UP": "\033[93mSTEP_UP\033[0m",
    "ALERT": "\033[96mALERT  \033[0m",
    "BLOCK": "\033[91mBLOCK  \033[0m",
}


def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
    """Module 2: does this REGISTERED device's signature check out? (The
    unknown-device_id case is handled by the caller before this is ever
    called -- see process_telemetry().) Tries the CURRENT key first; only
    if that fails does it fall back to secret_previous, and only within
    KEY_ROTATION_GRACE_SECONDS of the last rotate_key() call
    (trust_engine.verify_signature_with_rotation()) -- a device that
    hasn't yet picked up a just-rotated key still authenticates during the
    grace window, but the fallback never widens acceptance beyond what a
    real prior key would have covered."""
    info = DEVICE_REGISTRY[device_id]
    canonical = json.dumps(payload, sort_keys=True).encode()

    def matches(secret: str) -> bool:
        expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    if matches(info["secret"]):
        return True
    return verify_signature_with_rotation(device_id, matches)


def _extract_reading(device_id: str, payload: dict):
    """Module 1's `kind` field decides the shape: a plain float for scalar
    devices, or a dict of Section-5.1 features for feature_vector devices."""
    if is_feature_vector(device_id):
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
    coap_server.py's resource handler). Serialized under _pipeline_lock so
    the MQTT and HTTPS transport threads can't interleave and corrupt the
    shared scorer/trust state -- see that lock's definition."""
    with _pipeline_lock:
        _process_telemetry(envelope, transport, transport_secured)


def _process_telemetry(envelope: dict, transport: str, transport_secured: bool) -> None:
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

    # Module 1 (docs/02_module1_device_identity.md Section 3): a revoked
    # device is rejected unconditionally, BEFORE HMAC -- a hard override
    # regardless of signature validity, same as the doc's spec. Checked
    # right after identity (a revoked id is still a KNOWN id, so it's
    # correctly distinct from unknown_device_id above) and before the
    # throttle below, since there's no reason to spend throttle bookkeeping
    # on an identity that's already permanently rejected.
    if is_revoked(device_id):
        _reject(device_id, "device_revoked", transport)
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
    if is_feature_vector(device_id) and isinstance(reading, dict) and all(v is not None for v in reading.values()):
        fv = fe.feature_vector(reading)
        if_score = if_scorer.score(device_id, fv)
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

# Decision-channel anti-replay (RESULTS.md Section 14 item 3): the SAME
# boot_id/seq scheme telemetry replay already uses, applied to the
# gateway's outgoing decisions instead of a device's outgoing telemetry.
# gateway_boot_id increments once per gateway process start (persisted the
# same way firmware/main.py persists its own boot_id.txt); decision_seq is
# a simple in-memory per-device counter within this run -- no need to
# persist it, since a strictly-higher gateway_boot_id after a restart
# already makes any lower seq from a prior run correctly stale to a
# device checking it, the same way a device's own reboot does for its
# telemetry seq.
_gateway_boot_id = 1
_decision_seq_by_device: dict = {}


def _load_and_increment_gateway_boot_id() -> int:
    try:
        with open(GATEWAY_BOOT_ID_PATH) as f:
            boot_id = int(f.read().strip()) + 1
    except (OSError, ValueError):
        boot_id = 1
    os.makedirs(os.path.dirname(GATEWAY_BOOT_ID_PATH), exist_ok=True)
    with open(GATEWAY_BOOT_ID_PATH, "w") as f:
        f.write(str(boot_id))
    return boot_id


def _sign_decision(device_id: str, payload: dict) -> str:
    """Module 2 mutual-authentication extension: sign the gateway's own
    outgoing decision the same way a device signs its telemetry."""
    secret = DEVICE_REGISTRY[device_id]["secret"]
    canonical = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def _publish_decision(device_id: str, decision: str) -> None:
    if _mqtt_publish_client is not None:
        seq = _decision_seq_by_device.get(device_id, 0) + 1
        _decision_seq_by_device[device_id] = seq
        payload = {
            "device_id": device_id, "decision": decision, "ts": int(time.time() * 1000),
            "gateway_boot_id": _gateway_boot_id, "decision_seq": seq,
        }
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


# =============================================================================
# Module 9 extension: dashboard HTTP server.
#
# Formerly a separate script (webapp_server.py) -- merged directly into
# gateway.py on explicit user instruction, so there is exactly one process
# to run and exactly one dashboard file (design/zero-trust-cps-command-
# center.html), not a second competing script. Same non-blocking
# background-thread pattern coap_server.py's second transport already
# uses (see start_dashboard_server() / run() below).
#
# The page is FULLY LIVE. It renders itself from the /api/* endpoints below,
# polling every 2s, so there is no injection step and no static shell: device
# cards, decision stream, NIST coverage and its validation, IEC FR status, the
# RL policy table and audit-chain integrity are all read from this gateway.
#
# It did not start that way, and the history matters if you are reading old
# comments elsewhere: the served file used to be a 2.2MB flattened export of a
# Claude Design canvas whose device names were hardcoded, stale text
# (`vibration-001`, `mpu6050-001`) predating the current registry entirely, with
# one genuinely-live overlay bar spliced in above it. That export has been
# deleted and replaced outright by the hand-written live page; the canvas SOURCE
# it was exported from survives in design/canvas.json and design/Main.dc.html.
#
# Two things worth knowing before changing this server:
#   - It is a ThreadingHTTPServer, and that is load-bearing rather than
#     incidental -- see start_dashboard_server() for the measured saturation
#     failure a single-threaded one caused.
#   - The read caches below are what keep /api/chain affordable; its cost grows
#     with every logged decision, since it re-verifies the whole hash chain.
# =============================================================================

DASHBOARD_DESIGN_HTML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "design", "zero-trust-cps-command-center.html"
)
DASHBOARD_FIGURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "figures")
DASHBOARD_ROWS_TO_FETCH = 300



# --- Dashboard read caches -------------------------------------------------
# The dashboard polls every 2s, but these three answers do not meaningfully
# change that fast and each one SCANS the audit log: verify_chain_integrity()
# re-hashes every row (O(n), and n only ever grows -- 0.66s at 14k rows), while
# the NIST/IEC reports re-tally the most recent DASHBOARD_ROWS_TO_FETCH rows.
# Recomputing all of that per poll is what saturated the server. A short TTL
# keeps the numbers live to the eye (a decision shows up within a couple of
# seconds) while collapsing repeated identical work, and the lock means ten
# concurrent pollers trigger ONE recompute rather than ten.
_cache_lock = threading.Lock()
_cache: dict = {}


def _cached(key: str, ttl_seconds: float, compute):
    """Returns compute()'s value, recomputing only if the cached copy is
    older than ttl_seconds. Deliberately NOT used for /api/decisions, which
    must show the newest row the instant it is written."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and (now - hit[0]) < ttl_seconds:
            return hit[1]
    value = compute()          # computed OUTSIDE the lock: a slow chain
    with _cache_lock:          # verification must not block other endpoints
        _cache[key] = (time.time(), value)
    return value


CHAIN_CACHE_TTL_SECONDS = 10.0       # integrity re-verification is the expensive one
GOVERNANCE_CACHE_TTL_SECONDS = 5.0   # NIST/IEC tallies over the recent window


def _dashboard_json(handler: BaseHTTPRequestHandler, payload) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _build_qtable_view() -> dict:
    """The policy table AS THE GATEWAY WOULD APPLY IT, not the raw JSON file.

    That distinction was a real defect. Six of the ten security buckets were
    never visited during offline training, and reading the artifact directly
    rendered them as a wall of `0.00` -- implying the policy has no opinion
    there, or worse that every action scores equally. Neither is what happens
    live: AdaptivePDP._get_q() SEEDS an unvisited state from the static 2x2
    table (policy_engine.decide()), so the gateway falls back to the static
    policy rather than picking arbitrarily. The panel now asks the same
    AdaptivePDP object the gateway uses what it would actually do, and labels
    each row's provenance -- `trained` where offline episodes visited the state,
    `static-fallback` where they did not.

    State is (security_bucket, process_bucket); to stay a readable single table
    this fixes process_bucket=9 (process score in [0.9, 1.0), the common case)
    and varies the security bucket across its 10 buckets, the same bucketing
    adaptive_pdp.state_key() uses live."""
    trained_states = {}
    if os.path.exists(ADAPTIVE_PDP_MODEL_PATH):
        with open(ADAPTIVE_PDP_MODEL_PATH) as f:
            trained_states = json.load(f)

    rows = []
    PROCESS_BUCKET_SLICE = 9
    process_score = PROCESS_BUCKET_SLICE / 10 + 0.05   # mid-bucket representative
    for security_bucket in range(10):
        security_score = security_bucket / 10 + 0.05
        key = f"{security_bucket},{PROCESS_BUCKET_SLICE}"
        known = key in trained_states
        # Ask the live objects, so this table can never drift from behaviour.
        effective = adaptive_pdp.greedy_action(security_score, process_score)
        rows.append({
            "label": f"{security_bucket / 10:.1f}-{(security_bucket + 1) / 10:.1f}",
            "known": known,
            "source": "trained" if known else "static-fallback",
            "effective_action": effective,
            "static_action": decide(security_score, process_score, "FRESH"),
            "q": trained_states.get(key) or {a: None for a in ACTIONS},
        })
    return {
        "rows": rows,
        "actions": ACTIONS,
        "trained": os.path.exists(ADAPTIVE_PDP_MODEL_PATH),
        "process_bucket": PROCESS_BUCKET_SLICE,
        "note": (
            "Rows marked static-fallback were never visited during offline training. "
            "They are NOT undefined and NOT all-zero in practice: AdaptivePDP seeds an "
            "unvisited state from the static 2x2 table, so the gateway's decision there "
            "is the static policy's. The effective action column is what this gateway "
            "would actually return for that state, taken from the same object it uses live."
        ),
    }


def _build_governance_view() -> dict:
    """NIST SP 800-207 completeness over the recent audit window, plus the
    EVIDENCE behind each number. The raw coverage fraction alone is not a
    validation -- a reader has to be able to see WHICH logged rows count as
    evidence for a tenet and how many there were, otherwise "100%" is an
    assertion. `evidence_counts` and `sample_size` make the percentage
    checkable against the audit log itself."""
    rows = audit_log.recent(DASHBOARD_ROWS_TO_FETCH)
    report = nist_mapping.completeness_report(rows)
    counts = {t: 0 for t in NIST_TENETS}
    for row in rows:
        for part in (row.get("nist_tenets") or "").split(","):
            part = part.strip()
            if part.isdigit() and int(part) in counts:
                counts[int(part)] += 1
    validation = governance_validation.validate(rows)
    return {
        "tenets": NIST_TENETS,
        "coverage": report,
        "evidence_counts": counts,
        "validation": validation,
        "validation_summary": governance_validation.summary(validation),
        "sample_size": len(rows),
        "window_note": (
            f"Coverage = fraction of the {len(rows)} most recent logged decisions "
            f"carrying that tenet's tag. Every decision is tagged at the moment it "
            f"is made (gateway.py calls nist_mapping.tenets_for_decision() before "
            f"every log_decision()), so this is measured evidence, not a checklist."
        ),
        "validation_note": (
            "Coverage measures TAGGING. nist_mapping.tenets_for_decision() writes tenets "
            "1/3/4/5/6 on every decision unconditionally, so 100% coverage there is true by "
            "construction rather than a finding. The VALIDATION column is the one that can "
            "fail: each check reads only the audit log and names the observation that would "
            "falsify it. scripts/evaluate_governance.py proves 6/6 of them reject their own "
            "falsifier when it is injected."
        ),
    }


def _build_iec_view() -> dict:
    rows = audit_log.recent(DASHBOARD_ROWS_TO_FETCH)
    coverage = iec62443_mapping.fr_coverage_report(rows)
    frs = [
        {
            "id": fr, "name": info["name"], "status": info["status"],
            "coverage": coverage.get(fr) if info["status"] != "not_implemented" else None,
            "detail": info.get("where") or info.get("note"),
            "gap_note": info.get("note") if info["status"] == "partial" else None,
        }
        for fr, info in iec62443_mapping.FOUNDATIONAL_REQUIREMENTS.items()
    ]
    return {
        "zones": iec62443_mapping.ZONES,
        "conduits": iec62443_mapping.CONDUITS,
        "frs": frs,
        "sl_assessment": iec62443_mapping.SECURITY_LEVEL_ASSESSMENT,
        "sample_size": len(rows),
        "status_note": (
            "'partial' is a deliberate, honest rating, not an unfinished one: the "
            "transport-layer control genuinely exists, but the physical control "
            "(network segmentation for FR5, redundancy for FR7) does not. Each "
            "partial FR carries the exact boundary in its gap_note."
        ),
    }


def _build_chain_view() -> dict:
    """Two INDEPENDENT integrity checks, reported separately on purpose.
    chain_ok catches an attacker who edits a row and does not recompute the
    following hashes; checkpoint_ok catches the strictly stronger attacker who
    does recompute them, because the checkpoint file is stored elsewhere and
    HMAC'd with a key no device holds. Both must pass for the log to be
    trustworthy -- collapsing them into one boolean would hide which of the
    two attacker models was actually defeated."""
    chain_ok, broken_row = audit_log.verify_chain_integrity()
    checkpoint_ok, checkpoint_note = audit_log.verify_against_checkpoints()
    total = len(audit_log.recent(10 ** 9))
    return {
        "chain_ok": chain_ok, "broken_row": broken_row,
        "checkpoint_ok": checkpoint_ok, "checkpoint_note": checkpoint_note,
        "rows_verified": total,
        "verified_at": time.strftime("%H:%M:%S"),
    }


def _build_devices_view() -> list:
    return [
        {"device_id": d, "kind": info["kind"]}
        for d, info in DEVICE_REGISTRY.items()
    ]


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep console quiet, same rationale as coap_server.py

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_design_dashboard()
        elif self.path == "/figures" or self.path == "/figures/":
            self._serve_figures_gallery()
        elif self.path.startswith("/figures/"):
            self._serve_figure_file(self.path[len("/figures/"):])
        elif self.path.startswith("/api/decisions"):
            rows = audit_log.recent(DASHBOARD_ROWS_TO_FETCH)
            _dashboard_json(self, {"rows": rows})
        elif self.path == "/api/devices":
            _dashboard_json(self, {"devices": _build_devices_view()})
        elif self.path == "/api/governance":
            _dashboard_json(self, _cached("governance", GOVERNANCE_CACHE_TTL_SECONDS, _build_governance_view))
        elif self.path == "/api/iec62443":
            _dashboard_json(self, _cached("iec62443", GOVERNANCE_CACHE_TTL_SECONDS, _build_iec_view))
        elif self.path == "/api/qtable":
            _dashboard_json(self, _build_qtable_view())
        elif self.path == "/api/chain":
            _dashboard_json(self, _cached("chain", CHAIN_CACHE_TTL_SECONDS, _build_chain_view))
        elif self.path == "/api/status":
            _dashboard_json(self, {
                "use_rl_policy": USE_RL_POLICY,
                "security_threshold": SECURITY_THRESHOLD,
                "process_threshold": PROCESS_THRESHOLD,
            })
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_design_dashboard(self) -> None:
        """Serves design/zero-trust-cps-command-center.html byte-for-byte.

        No injection of any kind: the dashboard is a single self-contained
        page that polls the /api/* endpoints itself. It previously WAS a
        2.2MB flattened design-canvas export with a live overlay bar spliced
        in before its closing </body>; that export and the overlay constant
        that patched it are both gone."""
        if not os.path.exists(DASHBOARD_DESIGN_HTML_PATH):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"design/zero-trust-cps-command-center.html not found")
            return
        # design/zero-trust-cps-command-center.html is now a single, fully-live
        # dashboard that polls the /api/* endpoints itself and fills the whole
        # page -- served byte-for-byte, no overlay injection. The old 2.2MB
        # flattened canvas export it replaced has been deleted; the canvas
        # SOURCE it was exported from is still in design/canvas.json and
        # design/Main.dc.html if it ever needs regenerating.
        with open(DASHBOARD_DESIGN_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_figures_gallery(self) -> None:
        """Serves a small, self-contained HTML gallery of every PNG in
        docs/figures/ (scripts/generate_evaluation_graphs.py's output),
        linked from the dashboard header."""
        if not os.path.isdir(DASHBOARD_FIGURES_DIR):
            names = []
        else:
            names = sorted(f for f in os.listdir(DASHBOARD_FIGURES_DIR) if f.lower().endswith(".png"))
        cards = "".join(
            f'<figure style="margin:0;background:#0d1420;border:1px solid #2a3548;border-radius:8px;'
            f'padding:10px;"><img src="/figures/{n}" style="width:100%;border-radius:4px;" loading="lazy">'
            f'<figcaption style="color:#94a3b8;font-size:11px;margin-top:6px;font-family:ui-monospace,monospace;">'
            f'{n}</figcaption></figure>'
            for n in names
        )
        if not cards:
            cards = (
                '<p style="color:#94a3b8;">No figures found -- run '
                '<code>python scripts/generate_evaluation_graphs.py</code> first.</p>'
            )
        html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Model Evaluation Figures</title>
<style>
body{{background:#0a0f18;color:#dbe4f0;font-family:ui-sans-serif,system-ui,sans-serif;margin:0;padding:24px;}}
h1{{font-size:18px;color:#7dd3fc;}}
p.sub{{color:#94a3b8;font-size:13px;max-width:800px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;margin-top:20px;}}
a{{color:#7dd3fc;}}
</style></head><body>
<h1>Zero-Trust CPS -- Model Evaluation Figures</h1>
<p class="sub">Every figure here is produced by <code>scripts/generate_evaluation_graphs.py</code>,
which calls the SAME functions the corresponding <code>scripts/evaluate_*.py</code> script uses --
a figure and its script's printed numbers can never silently drift apart. See
<code>RESULTS.md</code> and <code>docs/12_model_validation_and_justification.md</code> for the
full write-up behind each comparison. <a href="/">&larr; back to live dashboard</a></p>
<div class="grid">{cards}</div>
</body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_figure_file(self, filename: str) -> None:
        """Serves one PNG from docs/figures/ by exact filename -- no
        directory traversal (basename-only, rejects any path separator)."""
        safe_name = os.path.basename(filename)
        if safe_name != filename or not safe_name.lower().endswith(".png"):
            self.send_response(400)
            self.end_headers()
            return
        path = os.path.join(DASHBOARD_FIGURES_DIR, safe_name)
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_dashboard_server() -> ThreadingHTTPServer:
    """Starts the dashboard HTTP server in a background thread -- same
    non-blocking pattern as coap_server.py's start_https_server(), called
    from run() below alongside MQTT and the HTTPS second transport.

    THREADING (was a plain single-threaded HTTPServer): the dashboard polls
    seven /api/* endpoints every 2s, and one full refresh cost ~1.99s of
    SERIAL server time once the audit log reached ~14k rows (/api/chain
    alone, which re-verifies the whole hash chain, was 0.66s and grows with
    every logged decision). At ~100% saturation refreshes overlapped, queued,
    and endpoints began returning EMPTY responses -- which is what "the
    dashboard shows static values" actually was: the page kept its last good
    render because the next fetch never completed. audit_log opens a fresh
    sqlite3 connection per call and guards writes with its own _chain_lock,
    so concurrent readers are safe here; the caches below then remove most of
    the repeated work outright."""
    server = ThreadingHTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[dashboard] serving http://localhost:{DASHBOARD_PORT} -- "
          f"design/zero-trust-cps-command-center.html -- fully live, polls /api/*")
    return server


_silence_alerted: set = set()  # device_ids currently flagged silent, so we alert once per episode, not every sweep


def _silence_watchdog_loop() -> None:
    """Periodically (not message-triggered) checks every registered
    device's staleness -- the only thing that actually exercises
    trust_engine.is_stale()/get_process_anomaly()'s lazy staleness checks
    independent of a new message arriving, which is what makes staleness
    observable at all in a live gateway (see SILENCE_CHECK_INTERVAL_SECONDS's
    comment in config.py for why the message-triggered path alone can
    never do this). Logs a real audit_log row on BOTH the silence-start and
    silence-end transition, so 'this device went quiet for N seconds' is
    queryable history, not just a console line that scrolls away -- exactly
    the visibility a device that's been powered off, disconnected, or
    deliberately silenced by an attacker would otherwise have none of."""
    while True:
        time.sleep(SILENCE_CHECK_INTERVAL_SECONDS)
        for device_id in DEVICE_REGISTRY:
            # Hold the pipeline lock across the ENTIRE per-device block, not
            # just the staleness read: get_process_anomaly() mutates
            # process_state[device].status (FRESH->STALE), and get_security_trust()
            # reads security_state[device] concurrently with score_security_trust()'s
            # writes on the MQTT/HTTPS path. Holding it through the log_decision()
            # call too means a device's SILENT row can never be observed or written
            # against a half-updated snapshot of its own scores -- maximal
            # strictness, matching process_telemetry()'s own whole-pipeline lock.
            with _pipeline_lock:
                security_stale = trust_engine.is_stale(device_id)
                _, process_status = trust_engine.get_process_anomaly(device_id)
                currently_silent = security_stale or process_status == "STALE"

                if currently_silent and device_id not in _silence_alerted:
                    _silence_alerted.add(device_id)
                    security_trust_score = trust_engine.get_security_trust(device_id)
                    print(f"{device_id:14s} | SILENT | no message in over "
                          f"{SILENCE_CHECK_INTERVAL_SECONDS}s-checked staleness window -- "
                          f"last known scores frozen, not decayed toward normal or spiked toward anomalous")
                    audit_log.log_decision(
                        device_id, auth_ok=True, decision="SILENT",
                        reason="no message received within the staleness window -- device offline, "
                               "disconnected, or possibly silenced/compromised; indistinguishable from here",
                        security_trust_score=security_trust_score, process_trust_score=None, process_status="STALE",
                        policy_source="", nist_tenets=nist_mapping.tenets_for_decision(True, MQTT_USE_TLS, fusion_engine.is_trained()),
                        transport="", reason_category="device_silent",
                    )
                elif not currently_silent and device_id in _silence_alerted:
                    _silence_alerted.discard(device_id)
                    print(f"{device_id:14s} | back online after a silence episode")


def start_silence_watchdog() -> threading.Thread:
    thread = threading.Thread(target=_silence_watchdog_loop, daemon=True)
    thread.start()
    print(f"[watchdog] checking every registered device for silence every {SILENCE_CHECK_INTERVAL_SECONDS}s")
    return thread


def run():
    """Runs MQTT and the HTTPS second-transport (coap_server.py) concurrently."""
    global _mqtt_publish_client, _gateway_boot_id
    audit_log.init_db()
    _gateway_boot_id = _load_and_increment_gateway_boot_id()
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
    print(f" Dashboard: http://localhost:{DASHBOARD_PORT} (design/zero-trust-cps-command-center.html, fully live)")
    print("=" * 110)

    if COAP_ENABLED:
        import coap_server
        coap_server.start_https_server()  # non-blocking -- own background thread

    start_dashboard_server()  # non-blocking -- own background thread
    start_silence_watchdog()  # non-blocking -- own background thread

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[gateway] stopped.")


if __name__ == "__main__":
    run()
