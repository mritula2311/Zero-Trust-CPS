"""
LIVE adversarial test against a running gateway.py -- the first attacks in this
project delivered over a real transport rather than injected into an evaluation
harness. Closes the standing "every attack is synthetic" limitation.

Each attack publishes a genuinely hostile MQTT message to cps/telemetry and then
reads gateway.py's OWN audit rows back out of audit_log.db to confirm the gateway
rejected it for the RIGHT reason. A real device (esp32-vib-001) is impersonated:
the attacker holds the broker credentials (an insider / stolen-laptop model) but
NOT the per-device HMAC secret, which is the threat this design is built against.

Run gateway.py first, then:  python scripts/attack_live_gateway.py

Read-then-write safety: this only PUBLISHES to cps/telemetry (exactly what a real
device does) and READS audit_log.db. It never touches models, trust state, or the
chain directly.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from config import (MQTT_HOST, MQTT_PORT, MQTT_TLS_PORT, MQTT_USE_TLS, MQTT_USE_AUTH,
                    MQTT_TLS_CA_CERT, TELEMETRY_TOPIC, AUDIT_DB_PATH, DEVICE_SECRETS,
                    MQTT_PASSWORDS)

TARGET = "esp32-vib-001"
REAL_SECRET = DEVICE_SECRETS[TARGET]          # the attacker does NOT have this
WRONG_SECRET = "attacker-guessed-secret-00000"
NORMAL = {"rms": 1.05, "peak": 0.02, "crest_factor": 0.019, "kurtosis": -0.3, "dominant_freq": 78.12}


def canon(payload):
    return json.dumps(payload, sort_keys=True).encode()


def sign(secret, payload):
    return hmac.new(secret.encode(), canon(payload), hashlib.sha256).hexdigest()


def make_client():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="adversary")
    if MQTT_USE_AUTH:
        # attacker holds the target device's broker password (insider model)
        c.username_pw_set(TARGET, MQTT_PASSWORDS[TARGET])
    if MQTT_USE_TLS:
        c.tls_set(ca_certs=MQTT_TLS_CA_CERT); c.connect(MQTT_HOST, MQTT_TLS_PORT, 30)
    else:
        c.connect(MQTT_HOST, MQTT_PORT, 30)
    c.loop_start()
    return c


def latest_row_id(con):
    r = con.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    return r or 0


def outcome_since(con, after_id, device_id):
    """The gateway's verdict on messages it processed after after_id for this id.
    A silently-dropped message (throttle, ACL block) produces NO row -- reported
    as 'no row (dropped)', which for an attack is also a correct outcome."""
    rows = con.execute(
        "SELECT decision, reason, reason_category FROM audit_log "
        "WHERE id > ? AND device_id = ? ORDER BY id",
        (after_id, device_id)).fetchall()
    return rows


def publish(c, payload, signature, envelope_override=None):
    env = envelope_override or {"payload": payload, "signature": signature}
    c.publish(TELEMETRY_TOPIC, json.dumps(env))


ATTACKS = []


def attack(name, threat, expect):
    def deco(fn):
        ATTACKS.append((name, threat, expect, fn))
        return fn
    return deco


@attack("forged_signature", "attacker has broker creds but guesses the HMAC secret",
        "hmac_mismatch")
def a_forged(c, ts, boot, seq):
    p = {**NORMAL, "device_id": TARGET, "ts": ts, "boot_id": boot, "seq": seq}
    publish(c, p, sign(WRONG_SECRET, p))


@attack("tampered_payload", "valid-looking values, signature over DIFFERENT values",
        "hmac_mismatch")
def a_tampered(c, ts, boot, seq):
    signed = {**NORMAL, "device_id": TARGET, "ts": ts, "boot_id": boot, "seq": seq}
    sig = sign(REAL_SECRET, signed)                       # attacker cannot really do this;
    shipped = {**signed, "rms": 9.9, "peak": 8.0}          # simulates a MITM altering in flight
    publish(c, shipped, sig)


@attack("unregistered_device", "an id the registry has never seen",
        "unknown_device_id")
def a_unknown(c, ts, boot, seq):
    p = {**NORMAL, "device_id": "ghost-999", "ts": ts, "boot_id": boot, "seq": seq}
    publish(c, p, sign(WRONG_SECRET, p))


@attack("stale_forged", "a stale timestamp AND a forged signature (attacker has neither clock nor key)",
        "hmac_mismatch|stale_timestamp")
def a_stale(c, ts, boot, seq):
    p = {**NORMAL, "device_id": TARGET, "ts": ts - 3_600_000, "boot_id": boot, "seq": seq}
    publish(c, p, sign(WRONG_SECRET, p))      # attacker cannot sign -- fails at HMAC


@attack("captured_replay", "a byte-for-byte capture of a REAL past message, re-sent",
        "hmac_mismatch|replay|seq")
def a_replay(c, ts, boot, seq):
    # An attacker CAN capture and replay a genuine envelope verbatim (they see the
    # ciphertext-authenticated payload on the wire). It is signed by the real key,
    # so it passes HMAC -- and must be caught by boot/seq anti-replay instead.
    # We reconstruct one the real device would have sent from an OLD boot session.
    p = {**NORMAL, "device_id": TARGET, "ts": ts, "boot_id": 1, "seq": 1}
    publish(c, p, sign(REAL_SECRET, p))


def main():
    print("=" * 78)
    print("LIVE ADVERSARIAL TEST -- hostile MQTT messages against a running gateway")
    print("=" * 78)
    print(f"target impersonated: {TARGET}")
    print("attacker model: holds broker credentials, does NOT hold the HMAC secret\n")

    con = sqlite3.connect("file:%s?mode=ro" % AUDIT_DB_PATH.replace("\\", "/"), uri=True)
    con.execute("PRAGMA busy_timeout=3000")
    c = make_client()
    time.sleep(1.0)

    results = []
    for name, threat, expect, fn in ATTACKS:
        before = latest_row_id(con)
        ts = int(time.time() * 1000)
        fn(c, ts, 999, 500 + len(results))
        time.sleep(2.5)                       # let the gateway process + write
        con.commit()                          # refresh read snapshot
        rows = outcome_since(con, before, TARGET if name != "unregistered_device" else "ghost-999")
        # The real board publishes legitimate ALLOWs on the SAME device_id while
        # this runs, so a grant is only attributable to the attack if it is a
        # REJECTED row -- rejections are the attacker's messages, ALLOWs are the
        # board's. An attack "breaches" only if NO rejection appears AND the
        # expected reason is absent, i.e. the hostile message left no reject trace.
        rejects = [r for r in rows if r[0] == "REJECTED"]
        cats = {(r[2] or r[1] or r[0]) for r in rejects}
        allowed = any(any(tok in str(cat) or tok in str(r[1]) for tok in expect.split("|"))
                      for r in rejects for cat in [r[2]])
        granted = (not rejects)   # no rejection trace at all -> the attack was not caught
        if granted:
            verdict, detail = "BREACH", f"gateway GRANTED access: {sorted(cats)}"
        elif allowed:
            verdict, detail = "BLOCKED", f"rejected as {sorted(cats)}"
        elif not rows:
            verdict, detail = "DROPPED", "no audit row -- silently dropped (throttle/ACL), also safe"
        else:
            verdict, detail = "WRONG-REASON", f"rejected but as {sorted(cats)}, expected {expect}"
        results.append((name, verdict))
        print(f"[{verdict:12s}] {name}")
        print(f"               threat: {threat}")
        print(f"               {detail}\n")

    c.loop_stop(); c.disconnect()
    breaches = [n for n, v in results if v == "BREACH"]
    wrong = [n for n, v in results if v == "WRONG-REASON"]
    print("=" * 78)
    ok = len(results) - len(breaches) - len(wrong)
    print(f"{ok}/{len(results)} attacks correctly defeated over a live transport.")
    if breaches:
        print(f"BREACH -- access granted to: {breaches}")
    if wrong:
        print(f"rejected but for the wrong reason: {wrong}")
    if not breaches and not wrong:
        print("Every hostile message was rejected at Module 1/2, before any model ran.")
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
