"""
Captures a real esp32-vib-001 telemetry session across a scripted sequence
of physical conditions, for two purposes:

  1. Calibrating DEVICE_REGISTRY["esp32-vib-001"]["expected_ranges"] in
     src/config.py against real MPU6050 statistics instead of
     device_simulator.py's synthetic placeholders (HARDWARE_SETUP.md
     Step 12).
  2. Producing a real-data JSON file in the SAME shape
     scripts/generate_training_data.py's output uses, so it can be fed
     into scripts/train_*.py later without any of those scripts needing
     to change (see generate_training_data.py's module docstring).

This is a READ-ONLY subscriber -- it does not publish anything and runs
alongside gateway.py without disturbing it (different MQTT client_id, same
'zt-gateway' username/ACL so it's allowed to read cps/telemetry).

Run this, then physically manipulate the board through the printed phase
schedule while it's running. It exits on its own once the schedule
completes, writing:
  - data/collected/hardware_session_<timestamp>.json  (raw records)
  - firmware/HARDWARE_DATA_LOG.md                      (human-readable log)

The first SETTLE_SECONDS of every phase (including the first) are
received but excluded from the output, printed as [settling] rather than
[collector] -- found live that handling the board right at a phase
transition (picking it up, cable movement) disturbs the NEXT phase's
readings more than the deliberate action does, which previously showed up
as e.g. moderate_shake looking calmer than the at_rest phases around it.
Phase labels are still approximate, not precise ground truth, even with
this window -- see RESULTS.md Section 13.2's methodology caveat.
"""

import datetime
import json
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import (
    MQTT_HOST, MQTT_PORT, MQTT_TLS_PORT, MQTT_USE_TLS, MQTT_USE_AUTH,
    MQTT_TLS_CA_CERT, MQTT_GATEWAY_USERNAME, MQTT_GATEWAY_PASSWORD,
    TELEMETRY_TOPIC, FEATURE_NAMES, DATA_COLLECTED_DIR, AUDIT_DB_PATH,
)

# How close (seconds) a record's own receipt time must be to an audit_log
# row's processing time to count as "the same message" -- gateway.py and
# this script both react to the same MQTT publish almost immediately, so a
# few seconds comfortably covers processing/clock jitter between the two
# independent subscribers without accidentally matching the NEXT message
# (publishes are ~2s apart).
FUSED_MATCH_TOLERANCE_S = 3.0

DEVICE_ID = "esp32-vib-001"

# (phase name, duration_seconds, instruction shown to the operator)
PHASES_SHORT = [
    ("at_rest_1",     45, "Leave the board completely still on the desk."),
    ("gentle_tap",    45, "Gently tap the MPU6050 breakout with a finger every 2-3 seconds."),
    ("moderate_shake", 45, "Hold the board and shake it moderately, continuously."),
    ("tilt_rotate",   45, "Slowly tilt/rotate the board through different orientations."),
    ("at_rest_2",     45, "Leave the board completely still again."),
]

# One long free-form window instead of rigid short phases -- prior sessions
# showed the strict phase boundaries didn't reliably match what was
# physically happening (handling noise landing in "at rest" windows, etc),
# so for bulk volume this just asks for continuous natural variation
# instead of pretending to label it precisely.
PHASES_LONG = [
    ("free_form_mixed", 280, "Continuously vary the board's physical state for the "
     "whole session: alternate between resting, tapping, shaking, and tilting. "
     "No need to follow a strict schedule -- just keep varying it."),
]

PHASES = PHASES_LONG if "--long" in sys.argv else PHASES_SHORT

# Excluded from recording at the START of every phase (including the very
# first) -- found live that picking the board up / setting it down / cable
# movement right at a phase transition produced more physical disturbance
# than the deliberate action for the NEXT phase, contaminating that
# phase's label (e.g. moderate_shake showing LESS variation than the
# at_rest phases around it). Settling records are still received and
# counted in the console log (as [settling], distinct from [collector]),
# just not written to the output JSON.
SETTLE_SECONDS = 5.0

records = []
settled_count = 0
start_time = None


def phase_and_time_in_phase(elapsed):
    """Returns (phase_name, seconds_since_this_phase_started) or (None, 0)
    once the whole schedule has finished."""
    t = 0
    for name, duration, _ in PHASES:
        if elapsed < t + duration:
            return name, elapsed - t
        t += duration
    return None, 0


def current_phase(elapsed):
    return phase_and_time_in_phase(elapsed)[0]


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[collector] connected (rc={reason_code}), subscribing to '{TELEMETRY_TOPIC}'")
    client.subscribe(TELEMETRY_TOPIC)


def on_message(client, userdata, msg):
    global start_time, settled_count
    if start_time is None:
        return  # schedule hasn't started yet
    elapsed = time.time() - start_time
    phase, time_in_phase = phase_and_time_in_phase(elapsed)
    if phase is None:
        return  # schedule already finished, ignore stragglers

    try:
        envelope = json.loads(msg.payload.decode())
        payload = envelope["payload"]
    except (json.JSONDecodeError, KeyError):
        return
    if payload.get("device_id") != DEVICE_ID:
        return

    reading = {name: payload.get(name) for name in FEATURE_NAMES}
    if any(v is None for v in reading.values()):
        return

    if time_in_phase < SETTLE_SECONDS:
        settled_count += 1
        print(f"[settling]  [{phase:16s}] excluded (t+{time_in_phase:.1f}s < {SETTLE_SECONDS:g}s settle window)")
        return

    records.append({
        "tick": len(records),
        "device_id": DEVICE_ID,
        "reading": reading,
        "auth_ok": True,
        "ts": payload.get("ts"),
        "label": 1,               # ground truth: legitimate real hardware reading
        "event_type": "normal",   # all phases here are real, non-adversarial conditions
        "phase": phase,
        "elapsed_s": round(elapsed, 1),
        "received_wall_time": time.time(),  # for joining against audit_log.db's processing timestamp
    })
    print(f"[collector] [{phase:16s}] rms={reading['rms']:.3f} peak={reading['peak']:.3f} "
          f"crest={reading['crest_factor']:.3f} kurt={reading['kurtosis']:.3f} "
          f"freq={reading['dominant_freq']:.2f}  (n={len(records)})")


def fetch_fused_scores(session_start, session_end):
    """Reads gateway.py's own scoring of these SAME messages back out of
    audit_log.db, independently of this script's raw MQTT capture -- lets
    the log show not just what the sensor reported but how the live
    fusion pipeline (rule + IF + LSTM-AE + GNN + meta-learner) actually
    scored it under each physical condition."""
    if not os.path.exists(AUDIT_DB_PATH):
        return []
    con = sqlite3.connect(AUDIT_DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT timestamp, decision, security_trust_score, fused_score
        FROM audit_log
        WHERE device_id = ?
        ORDER BY id
        """,
        (DEVICE_ID,),
    )
    rows = []
    for ts_str, decision, security_trust_score, fused_score in cur.fetchall():
        try:
            epoch = datetime.datetime.fromisoformat(ts_str).timestamp()
        except ValueError:
            continue
        if session_start - FUSED_MATCH_TOLERANCE_S <= epoch <= session_end + FUSED_MATCH_TOLERANCE_S:
            rows.append((epoch, decision, security_trust_score, fused_score))
    con.close()
    return rows


def attach_fused_scores(audit_rows):
    if not audit_rows:
        return
    for r in records:
        wall_time = r.pop("received_wall_time", None)
        if wall_time is None:
            continue
        best = min(audit_rows, key=lambda row: abs(row[0] - wall_time))
        if abs(best[0] - wall_time) <= FUSED_MATCH_TOLERANCE_S:
            r["decision"] = best[1]
            r["security_trust_score"] = best[2]
            r["fused_score"] = best[3]


def summarize():
    by_phase = {}
    for r in records:
        by_phase.setdefault(r["phase"], []).append(r)
    return by_phase


def write_outputs(by_phase):
    os.makedirs(DATA_COLLECTED_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DATA_COLLECTED_DIR, f"hardware_session_{stamp}.json")
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"[collector] wrote {len(records)} records -> {json_path}")

    md_path = os.path.join(os.path.dirname(__file__), "..", "firmware", "HARDWARE_DATA_LOG.md")
    matched = sum(1 for r in records if "fused_score" in r)
    lines = [
        "# Hardware Data Log -- esp32-vib-001 (real MPU6050)",
        "",
        f"Session captured {time.strftime('%Y-%m-%d %H:%M:%S')} via "
        f"`scripts/collect_hardware_session.py`. Raw records: "
        f"`data/collected/{os.path.basename(json_path)}`.",
        "",
        "One physical MPU6050 over I2C, no separate vibration sensor "
        "(see firmware/HARDWARE_SETUP.md).",
        "",
        f"`fused_score`/`security_trust_score`/`decision` columns below are "
        f"gateway.py's OWN live scoring of these same messages, joined back in "
        f"from `audit_log.db` by timestamp ({matched}/{len(records)} records matched "
        f"within {FUSED_MATCH_TOLERANCE_S:g}s) -- not recomputed by this script.",
        "",
        f"{settled_count} additional record(s) were excluded entirely (received during "
        f"the first {SETTLE_SECONDS:g}s of their phase, when handling disturbance from "
        f"the PREVIOUS phase's transition is still settling) -- not counted above and not "
        f"in the raw JSON. Even with this window, phase labels remain approximate, not "
        f"precise ground truth (RESULTS.md Section 13.2).",
        "",
        "## Per-phase observed feature ranges + live gateway scoring",
        "",
        "| phase | n | rms (g) | peak (g) | crest_factor | kurtosis | dominant_freq (Hz) "
        "| avg security_trust | avg fused (process) | decisions |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, _, instruction in PHASES:
        phase_records = by_phase.get(name, [])
        if not phase_records:
            lines.append(f"| {name} | 0 | -- | -- | -- | -- | -- | -- | -- | -- |")
            continue

        def rng(key):
            vals = [r["reading"][key] for r in phase_records]
            return f"{min(vals):.4f} - {max(vals):.4f}"

        scored = [r for r in phase_records if "fused_score" in r]
        if scored:
            avg_sec = sum(r["security_trust_score"] for r in scored) / len(scored)
            avg_fused = sum(r["fused_score"] for r in scored) / len(scored)
            decisions = {}
            for r in scored:
                decisions[r["decision"]] = decisions.get(r["decision"], 0) + 1
            decision_str = ", ".join(f"{k}={v}" for k, v in sorted(decisions.items()))
            sec_str = f"{avg_sec:.3f}"
            fused_str = f"{avg_fused:.6f}"
        else:
            sec_str = fused_str = decision_str = "n/a (no gateway match)"

        lines.append(
            f"| {name} | {len(phase_records)} | {rng('rms')} | {rng('peak')} | "
            f"{rng('crest_factor')} | {rng('kurtosis')} | {rng('dominant_freq')} | "
            f"{sec_str} | {fused_str} | {decision_str} |"
        )
    lines.append("")
    lines.append("## Phase instructions (what the operator was doing)")
    lines.append("")
    for name, duration, instruction in PHASES:
        lines.append(f"- **{name}** ({duration}s): {instruction}")
    lines.append("")

    all_readings = [r["reading"] for r in records]
    if all_readings:
        lines.append("## Overall observed range (all phases combined)")
        lines.append("")
        for key in FEATURE_NAMES:
            vals = [r[key] for r in all_readings]
            lines.append(f"- `{key}`: {min(vals):.4f} to {max(vals):.4f}")
        lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    print(f"[collector] wrote human-readable log -> {md_path}")


def main():
    global start_time
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hw-data-collector")
    client.on_connect = on_connect
    client.on_message = on_message

    if MQTT_USE_AUTH:
        client.username_pw_set(MQTT_GATEWAY_USERNAME, MQTT_GATEWAY_PASSWORD)
    if MQTT_USE_TLS:
        client.tls_set(ca_certs=MQTT_TLS_CA_CERT)
        client.connect(MQTT_HOST, MQTT_TLS_PORT, keepalive=30)
    else:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)

    client.loop_start()

    total_duration = sum(d for _, d, _ in PHASES)
    print("=" * 90)
    print(f" HARDWARE DATA COLLECTION -- {len(PHASES)} phases, {total_duration}s total")
    print(" Follow the on-screen phase instructions as they appear.")
    print("=" * 90)

    start_time = time.time()
    last_phase = None
    while True:
        elapsed = time.time() - start_time
        phase = current_phase(elapsed)
        if phase is None:
            break
        if phase != last_phase:
            duration, instruction = next((d, i) for n, d, i in PHASES if n == phase)
            print(f"\n>>> PHASE: {phase} ({duration}s) -- {instruction}\n")
            last_phase = phase
        time.sleep(0.5)

    session_end = time.time()
    print(f"\n[collector] schedule complete ({settled_count} record(s) excluded by the "
          f"{SETTLE_SECONDS:g}s settle window), disconnecting...")
    client.loop_stop()
    client.disconnect()

    print("[collector] joining gateway.py's live fused scores from audit_log.db...")
    audit_rows = fetch_fused_scores(start_time, session_end)
    attach_fused_scores(audit_rows)
    matched = sum(1 for r in records if "fused_score" in r)
    print(f"[collector] matched {matched}/{len(records)} records to a gateway decision")

    by_phase = summarize()
    write_outputs(by_phase)


if __name__ == "__main__":
    main()
