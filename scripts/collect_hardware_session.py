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
    feature_names_for, DEVICE_REGISTRY,
    LSTM_SEQ_LEN,
)

# How close (seconds) a record's own receipt time must be to an audit_log
# row's processing time to count as "the same message" -- gateway.py and
# this script both react to the same MQTT publish almost immediately, so a
# few seconds comfortably covers processing/clock jitter between the two
# independent subscribers without accidentally matching the NEXT message
# (publishes are ~2s apart).
FUSED_MATCH_TOLERANCE_S = 3.0

def _arg(flag, default=None):
    """--flag value, or `default`. Every capture-condition knob is a command-line
    argument rather than a source edit: an operator running six sessions in a row
    must not have to open this file between them, and a condition recorded by
    editing code is a condition nobody can reconstruct afterwards."""
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


# Which physical node(s) this capture listens to.
#   --device esp32-vib-002        one node
#   --devices esp32-vib-001,esp32-vib-002   BOTH, for the coordinated
#                                  simultaneous-disturbance conditions (C4)
DEVICE_IDS = [d.strip() for d in _arg("--devices", _arg("--device", "esp32-vib-001")).split(",")]
DEVICE_ID = DEVICE_IDS[0]          # kept: the audit-log join and summary tables are per-device
MULTI_DEVICE = len(DEVICE_IDS) > 1

# Capture conditions, recorded on EVERY record and in the session header.
# mounting_condition/orientation exist so the mounting-robustness analysis is
# possible at all -- a session that does not say how the sensor was mounted
# cannot contribute to it, and "I think that was the remounted one" is not data.
MOUNTING_CONDITION = _arg("--mount", "MOUNT_A")
ORIENTATION = _arg("--orientation", "ORIENTATION_A")
NETWORK_EXPERIMENT_ID = _arg("--experiment", None)
CAPTURE_NOTES = _arg("--notes", "")

# Fixed once, at import, so every record carries the SAME id the output file is
# named with. Derived at write time instead, a capture crossing a second
# boundary would name records and file differently and splits.session_id_of()
# would not be able to find the session it belongs to.
SESSION_ID = time.strftime("%Y%m%d_%H%M%S")

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
LABELLED = "--labelled" in sys.argv
FAULT_MODE = "--fault" in sys.argv

# ---------------------------------------------------------------------------
# OPERATOR-MARKED LABELLING  (--labelled)
#
# Why this mode exists. Both schedules above advance on a CLOCK: the label a
# record receives depends on when it arrived relative to a fixed timetable, not
# on what the board was physically doing. Analysis of the four sessions captured
# that way showed the two do not line up -- `at_rest_1` contained a higher
# maximum rms (3.416 g) than `moderate_shake` (1.050 g), the exact opposite of
# what the labels claim (firmware/HARDWARE_DATA_LOG.md Section 2). Those labels
# are therefore unusable as ground truth, which is why merge_real_hardware_data.py
# folds every real row in as one undifferentiated "normal" class.
#
# The fix is not a better timetable. It is to stop inferring the label after the
# fact: the operator MARKS the start and the end of each event as they perform
# it, and only records that fall strictly inside a marked interval carry that
# event's label. A label then describes an observation someone actually made,
# which is the whole difference between annotation and ground truth.
#
# MARK_MARGIN_S trims both ends of every marked interval. The keypress and the
# physical action are not simultaneous -- reaching for the keyboard disturbs a
# hand-held board, and letting go to press ENTER at the end does too -- so the
# boundary samples are the least trustworthy ones in the interval. Trimming is
# cheap; a contaminated label is not.
LABELLED_EVENTS = [
    ("at_rest",        120, "Put the board DOWN on the desk and take your hands off it. LONG block."),
    ("gentle_tap",      60, "Tap the MPU6050 breakout gently with one finger, about every 2 seconds."),
    ("at_rest",         60, "Board DOWN on the desk again, hands off."),
    ("moderate_shake",  60, "Pick the board up and shake it continuously, moderately."),
    ("at_rest",         60, "Board DOWN on the desk again, hands off."),
    ("tilt_rotate",     60, "Hold the board and slowly rotate it through different orientations."),
    ("sharp_impact",    60, "Tap the board SHARPLY a few times -- brief, hard impacts with pauses between."),
    ("at_rest",        120, "Board DOWN one last time, hands off. LONG block."),
]

# --fault: a SUSTAINED LOW-AMPLITUDE fault, which is a different detection problem
# from everything captured so far.
#
# Every one of the 136 detected disturbances in the existing sessions is violent
# hand manipulation: peak 0.4-3.1 g against a resting maximum of 0.035 g, a 10-90x
# margin. Detecting that is easy, and 136/136 says less than it appears to. A real
# mechanical fault -- a worn bearing, a loosening mount, an unbalanced load -- is
# LOW amplitude, CONTINUOUS, and close to the noise floor. The LSTM-AE exists
# specifically to catch that class (it is the only scorer that models a sequence)
# and it has never been tested on one.
#
# The fault source is a phone set to continuous vibrate, sharing the board's
# surface. Distance is the amplitude knob, which makes it repeatable without any
# rig: further away is a weaker fault. `fault_weak` is the one that matters -- it
# is meant to sit just above the resting floor, where the margin is small enough
# that detection is a real question rather than a formality.
FAULT_EVENTS = [
    ("at_rest",      90, "BASELINE. Board flat on the desk, hands off, nothing else touching the desk."),
    ("fault_weak",  120, "Phone on CONTINUOUS vibrate, on the SAME surface but ~30 cm away, "
                         "not touching the board. Hands off. This should be barely perceptible."),
    ("at_rest",      60, "Phone OFF and removed. Board still, hands off."),
    ("fault_strong",120, "Phone on CONTINUOUS vibrate, now TOUCHING the board or directly "
                         "under it. Hands off."),
    ("at_rest",      90, "RECOVERY. Phone off and removed. Board still, hands off."),
]

# --intensity: LOW / MEDIUM / HIGH operator-controlled disturbance.
#
# NOT calibrated. There is no shaker table, no accelerometer reference, and no
# repeatable excitation source here -- the amplitude knob is how hard a person
# moves the board. So these are recorded as "operator-controlled low/medium/high
# intensity", and the ACTUAL observed rms / peak / crest / dominant_freq of each
# block is what the analysis reports. Calling three levels of hand movement
# "calibrated" would be claiming an instrument that does not exist.
#
# The point of the sweep is the DETECTION FLOOR: existing sessions detect
# 136/136 disturbances, but every one of them is violent (peak 0.4-3.1 g against
# a 0.035 g resting maximum, a 10-90x margin), so 100% says very little. The
# question worth answering is where detection actually stops.
INTENSITY_EVENTS = [
    ("at_rest",          90, "BASELINE. Board flat, hands off, nothing touching the desk."),
    ("intensity_low",   120, "LOW: rest a fingertip on the board and press very lightly, "
                             "continuously. Barely perceptible movement."),
    ("at_rest",          60, "Hands off. Board still."),
    ("intensity_medium",120, "MEDIUM: hold the board and rock it gently and continuously."),
    ("at_rest",          60, "Hands off. Board still."),
    ("intensity_high",  120, "HIGH: hold the board and shake it firmly and continuously."),
    ("at_rest",          90, "RECOVERY. Board down, hands off."),
]

# --mount-check: mounting / orientation robustness.
#
# Run this schedule ONCE PER PHYSICAL CONFIGURATION, passing the configuration
# on the command line so it lands in the data:
#     --mount-check --mount MOUNT_A --orientation ORIENTATION_A
#     --mount-check --mount MOUNT_A --orientation ORIENTATION_B   (rotated 90 deg)
#     --mount-check --mount MOUNT_B --orientation ORIENTATION_A   (detached, remounted)
#
# Mostly at-rest, because the question is whether the learned NORMAL region is
# specific to one mounting -- not whether a shake is detectable. The single
# reference tap gives each session one known-disturbed block, so a session that
# scores everything normal can be distinguished from a dead sensor.
MOUNT_EVENTS = [
    ("at_rest",       150, "Board in the CURRENT mounting/orientation, flat, hands off. LONG block."),
    ("gentle_tap",     60, "One reference block: tap gently every ~2s. Sanity check that the "
                           "sensor is alive in this configuration."),
    ("at_rest",       150, "Hands off again, same mounting. LONG block."),
]

# --coordinated: the two-physical-node conditions C1-C4.
#
# Requires --devices esp32-vib-001,esp32-vib-002 and BOTH boards publishing.
# Each block names which node(s) are being disturbed, so the labelled interval
# carries the coordination state and not just "something moved".
COORDINATED_EVENTS = [
    ("C1_both_normal",     120, "C1. BOTH boards flat on the desk, hands off both. LONG block."),
    ("C2_node01_only",      90, "C2. Disturb the MPU6050 board (esp32-vib-001) ONLY -- shake it "
                                "continuously. Do NOT touch the SW-420 board."),
    ("C1_both_normal",      60, "Hands off both boards."),
    ("C3_node02_only",      90, "C3. Disturb the SW-420 board (esp32-vib-002) ONLY -- tap the "
                                "surface it sits on. Do NOT touch the MPU6050 board."),
    ("C1_both_normal",      60, "Hands off both boards."),
    ("C4_both_disturbed",   90, "C4. Disturb BOTH boards SIMULTANEOUSLY -- one hand on each, or "
                                "shake the shared surface both are on."),
    ("C1_both_normal",     120, "RECOVERY. Hands off both. LONG block."),
]

# firmware/main.py's PUBLISH_INTERVAL_MS. Not imported because it lives on the
# device, not in config.py -- if you change it there, change it here.
TELEMETRY_INTERVAL_S = 2.0

# Exactly one schedule wins; later flags do not silently merge with earlier ones.
if FAULT_MODE:
    LABELLED_EVENTS = FAULT_EVENTS
elif "--intensity" in sys.argv:
    LABELLED_EVENTS = INTENSITY_EVENTS
elif "--mount-check" in sys.argv:
    LABELLED_EVENTS = MOUNT_EVENTS
elif "--coordinated" in sys.argv:
    LABELLED_EVENTS = COORDINATED_EVENTS
    if not MULTI_DEVICE:
        raise SystemExit(
            "--coordinated needs both physical nodes. Re-run with:\n"
            "    --coordinated --labelled --devices esp32-vib-001,esp32-vib-002")

MARK_MARGIN_S = 2.0      # trimmed from each end of every marked interval
# Below this an event cannot contribute a single SCOREABLE sample, so it is
# rejected rather than kept as decoration. evaluate_real_hardware.py restarts the
# LSTM-AE's rolling window at every phase boundary and drops the first
# LSTM_SEQ_LEN-1 records of each block, so a block needs LSTM_SEQ_LEN messages
# left AFTER margin trimming just to yield one window. The old hardcoded 16.0
# left 6 -- one short of a single window, i.e. a minimum-length event was worth
# literally nothing downstream, silently. Derived from the three constants that
# actually govern it so they cannot drift apart again.
# 2*LSTM_SEQ_LEN, not LSTM_SEQ_LEN: evaluate_real_hardware.py now drops the first
# 2*LSTM_SEQ_LEN-1 records of every block, because filling the window is not the
# same as clearing the block's own settling disturbance out of it. An event that
# only fills the window contributes nothing under that rule.
MIN_EVENT_SECONDS = 2 * MARK_MARGIN_S + 2 * LSTM_SEQ_LEN * TELEMETRY_INTERVAL_S

marked_intervals = []     # (event_name, t_start, t_end) in wall-clock seconds

# The live "[n samples received] ..." status line (on_message, below) is only
# safe to print while genuinely inside a START/STOP marking window. Telemetry
# arrives continuously on the background MQTT thread, including during every
# input() prompt outside that window (the initial "gateway ready?" prompt,
# between-event pauses, the retry y/n prompt) -- an unguarded \r-line there
# overwrites the prompt itself mid-keystroke, and the operator sees no
# question to answer at all. Found live: a labelled run appeared to hang at
# the very first prompt because the prompt was being redrawn over.
_marking = False


def label_for_wall_time(t):
    """The event whose MARKED interval contains t, after margin trimming.
    Returns None for anything outside every interval -- unlabelled records are
    dropped rather than guessed at, which is the entire point of this mode."""
    for name, t0, t1 in marked_intervals:
        if (t0 + MARK_MARGIN_S) <= t <= (t1 - MARK_MARGIN_S):
            return name
    return None


def run_labelled_capture():
    """Walks the operator through LABELLED_EVENTS, recording a start and stop
    mark for each. Telemetry keeps arriving on the MQTT client's background
    thread while this blocks on input(), so nothing is missed."""
    global _marking
    print()
    print("=" * 78)
    print("OPERATOR-MARKED CAPTURE")
    print("=" * 78)
    print("For each event you will press ENTER twice: once at the moment you START,")
    print("and once when you STOP. Only samples strictly inside that window get the")
    print(f"label, minus a {MARK_MARGIN_S:g}s margin at each end for the keypress itself.")
    print()
    print("Take your time between events -- there is no clock running. Anything")
    print("outside a marked window is discarded, not guessed at.")
    print()
    input("Press ENTER when the gateway is running and the board is publishing... ")

    for i, (name, target, instruction) in enumerate(LABELLED_EVENTS, 1):
        while True:
            print()
            print("=" * 70)
            print(f"  EVENT {i}/{len(LABELLED_EVENTS)}:  {name}   (aim for ~{target}s)")
            print(f"  {instruction}")
            print("=" * 70)
            input("  >>> Press ENTER, THEN perform the action... ")
            t0 = time.time()
            print()
            print(f"  RECORDING {name} -- do it now.")
            print(f"  Keep going for about {target}s ({MIN_EVENT_SECONDS:g}s absolute minimum),")
            print(f"  then press ENTER to stop.")
            print()
            _marking = True
            input("  >>> Press ENTER when you have STOPPED... ")
            _marking = False
            t1 = time.time()
            duration = t1 - t0
            if duration >= MIN_EVENT_SECONDS:
                marked_intervals.append((name, t0, t1))
                usable = duration - 2 * MARK_MARGIN_S
                # Windows, not seconds, is what the evaluation actually consumes.
                windows = max(0, int(usable / TELEMETRY_INTERVAL_S) - (LSTM_SEQ_LEN - 1))
                print(f"  recorded: {duration:.1f}s marked, {usable:.1f}s usable after margins "
                      f"-> ~{windows} scoreable window(s)")
                break
            # Too short is almost always the operator pressing ENTER twice rather
            # than a genuinely brief action, so OFFER THE RETRY instead of silently
            # dropping it. The first labelled run lost all eight events this way and
            # only reported it at the end, by which point the session was unusable.
            print()
            print(f"  TOO SHORT: {duration:.1f}s, under the {MIN_EVENT_SECONDS:g}s minimum.")
            print(f"  Press ENTER once to START, do the action for {MIN_EVENT_SECONDS:g}s+,")
            print(f"  then press ENTER again to STOP. Two separate presses.")
            again = input("  Retry this event? [Y/n] ").strip().lower()
            if again in ("n", "no"):
                print(f"  skipped {name}")
                break

    print()
    print("=" * 70)
    if marked_intervals:
        print(f"{len(marked_intervals)}/{len(LABELLED_EVENTS)} intervals marked:")
        for nm, a, b in marked_intervals:
            usable = b - a - 2 * MARK_MARGIN_S
            windows = max(0, int(usable / TELEMETRY_INTERVAL_S) - (LSTM_SEQ_LEN - 1))
            print(f"    {nm:16s} {b - a:6.1f}s marked, {usable:6.1f}s usable, "
                  f"~{windows:3d} scoreable window(s)")
    else:
        print("NO intervals were marked -- nothing will be labelled or saved.")
    print("=" * 70)
    print("Waiting briefly for in-flight messages...")
    time.sleep(3)


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
        return  # capture hasn't started yet
    elapsed = time.time() - start_time
    if LABELLED:
        # No schedule: buffer everything with its arrival time and assign labels
        # afterwards from the operator's marks. A record that falls outside every
        # marked interval is DISCARDED in finalise_labelled(), never guessed at.
        phase, time_in_phase = "(pending mark)", SETTLE_SECONDS
    else:
        phase, time_in_phase = phase_and_time_in_phase(elapsed)
        if phase is None:
            return  # schedule already finished, ignore stragglers

    try:
        envelope = json.loads(msg.payload.decode())
        payload = envelope["payload"]
    except (json.JSONDecodeError, KeyError):
        return
    if payload.get("device_id") not in DEVICE_IDS:
        return

    src_device = payload.get("device_id")
    reading = {name: payload.get(name) for name in feature_names_for(src_device)}
    if any(v is None for v in reading.values()):
        return

    if time_in_phase < SETTLE_SECONDS:
        settled_count += 1
        print(f"[settling]  [{phase:16s}] excluded (t+{time_in_phase:.1f}s < {SETTLE_SECONDS:g}s settle window)")
        return

    records.append({
        "tick": len(records),
        "device_id": src_device,
        "source_type": "REAL",
        "sensor_type": DEVICE_REGISTRY.get(src_device, {}).get("sensor_type", "MPU6050"),
        "session_id": SESSION_ID,
        "mounting_condition": MOUNTING_CONDITION,
        "orientation": ORIENTATION,
        "network_experiment_id": NETWORK_EXPERIMENT_ID,
        "reading": reading,
        "auth_ok": True,
        "ts": payload.get("ts"),
        "label": 1,               # ground truth: legitimate real hardware reading
        "event_type": "normal",   # all phases here are real, non-adversarial conditions
        "phase": phase,
        "elapsed_s": round(elapsed, 1),
        "label_source": "operator_mark" if LABELLED else "timed_schedule",
        "arrival_wall_time": time.time(),   # used to assign operator-marked labels
        "received_wall_time": time.time(),  # for joining against audit_log.db's processing timestamp
    })
    if LABELLED:
        # A line per message buries the interactive prompts. That is not cosmetic:
        # in the first labelled run every prompt scrolled off screen, the operator
        # pressed ENTER twice in quick succession to get past the noise, and all
        # eight intervals came out 0.6-12s long against 25-50s of real activity.
        # Every record was discarded. A capture UI that talks over its own
        # instructions cannot be driven, so during a labelled run this collapses
        # to one rewritten status line -- and ONLY while _marking is True (inside
        # an actual recording window), never over an input() prompt outside one.
        # Telemetry arrives continuously, including during every prompt, so an
        # unguarded \r-line here overwrote the very first "gateway ready?" prompt
        # before the operator could see there was anything to answer.
        if _marking:
            summary = "  ".join(f"{name}={reading[name]:.3f}" for name in feature_names_for(src_device))
            print(f"\r    [{len(records)} samples received]  {summary}   ", end="", flush=True)
    else:
        summary = " ".join(f"{name}={reading[name]:.3f}" for name in feature_names_for(src_device))
        print(f"[collector] [{phase:16s}] {summary}  (n={len(records)})")


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
        # Require BOTH scores to be non-None before attaching: the nearest
        # match can be a SILENT (watchdog) or otherwise process-less audit row
        # for esp32-vib-001, whose fused_score/security_trust_score columns are
        # NULL. Attaching a None fused_score still sets "fused_score" in r,
        # which would then crash write_outputs()'s sum() over the per-phase
        # averages. Leaving them unattached falls through to the "n/a (no
        # gateway match)" path there instead.
        if (abs(best[0] - wall_time) <= FUSED_MATCH_TOLERANCE_S
                and best[3] is not None and best[2] is not None):
            r["decision"] = best[1]
            r["security_trust_score"] = best[2]
            r["fused_score"] = best[3]


def finalise_labelled():
    """Assigns each buffered record the event whose MARKED interval contains its
    arrival time, and DROPS everything else. Dropping is the point: a record
    captured while the operator was reaching for the keyboard, or between events,
    has no trustworthy label, and inventing one is exactly what made the earlier
    timed-schedule sessions unusable as ground truth."""
    global records
    kept, dropped = [], 0
    for r in records:
        label = label_for_wall_time(r.pop("arrival_wall_time", 0))
        if label is None:
            dropped += 1
            continue
        r["phase"] = label
        kept.append(r)
    for i, r in enumerate(kept):
        r["tick"] = i
    records = kept
    print(f"[collector] {len(kept)} records fell inside a marked interval; "
          f"{dropped} discarded as unlabelled (between events, or inside a "
          f"{MARK_MARGIN_S:g}s keypress margin)")


def summarize():
    by_phase = {}
    for r in records:
        by_phase.setdefault(r["phase"], []).append(r)
    return by_phase


def write_outputs(by_phase):
    os.makedirs(DATA_COLLECTED_DIR, exist_ok=True)
    stamp = SESSION_ID
    # evaluate_real_hardware.py selects its input by GLOBBING "*_labelled.json".
    # Without this suffix a --labelled run wrote a file that script silently never
    # read: the first operator-marked session had to be renamed by hand, and a
    # capture that is ignored looks identical to one that was never taken.
    suffix = "_labelled" if LABELLED else ""
    json_path = os.path.join(DATA_COLLECTED_DIR, f"hardware_session_{stamp}{suffix}.json")
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"[collector] wrote {len(records)} records -> {json_path}")

    # A capture writes its OWN log beside the JSON rather than overwriting
    # firmware/HARDWARE_DATA_LOG.md. That file is curated -- it carries the
    # provenance warnings, the phase-label analysis and the sample-rate finding,
    # none of which this script can regenerate, and an earlier version of this
    # function would have silently replaced all of it with a single session's
    # table.
    md_path = os.path.join(DATA_COLLECTED_DIR, f"hardware_session_{stamp}{suffix}.md")
    matched = sum(1 for r in records if "fused_score" in r)
    # Feature columns from what was actually captured, not a fixed MPU6050
    # schema -- a single-device SW-420 session has trigger_rate/duty_cycle/
    # burst_max_ms/inter_event_cv instead of rms/peak/crest_factor/kurtosis/
    # dominant_freq, and a --coordinated session mixes both devices' fields
    # (rng() below already scopes each column to the records that HAVE it).
    feature_cols = sorted({k for r in records for k in r["reading"]})
    lines = [
        f"# Hardware Data Log -- {', '.join(DEVICE_IDS)}",
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
        "| phase | n | " + " | ".join(feature_cols)
        + " | avg security_trust | avg fused (process) | decisions |",
        "|---|---|" + "---|" * len(feature_cols) + "---|---|---|",
    ]
    # In --labelled mode the phase names come from the operator's marks, not
    # from PHASES, so iterate what was actually captured.
    phase_names = sorted(by_phase) if LABELLED else [n for n, _, _ in PHASES]
    for name in phase_names:
        phase_records = by_phase.get(name, [])
        if not phase_records:
            lines.append(f"| {name} | 0 | " + " | ".join("--" for _ in feature_cols) + " | -- | -- | -- |")
            continue

        def rng(key):
            vals = [r["reading"][key] for r in phase_records if key in r["reading"]]
            if not vals:
                return "--"
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
            f"| {name} | {len(phase_records)} | " + " | ".join(rng(c) for c in feature_cols)
            + f" | {sec_str} | {fused_str} | {decision_str} |"
        )
    lines.append("")
    if LABELLED:
        lines.append("## Operator-marked intervals (labels recorded AT injection time)")
        lines.append("")
        lines.append(f"Each interval below was marked by the operator pressing ENTER at the "
                     f"start and again at the stop, with {MARK_MARGIN_S:g}s trimmed from each "
                     f"end for the keypress itself. Records outside every marked interval were "
                     f"discarded, not guessed at. `label_source` on every record is "
                     f"`operator_mark`.")
        lines.append("")
        for name, t0, t1 in marked_intervals:
            lines.append(f"- **{name}**: {t1 - t0:.1f}s marked, "
                         f"{max(0.0, t1 - t0 - 2 * MARK_MARGIN_S):.1f}s usable")
    else:
        lines.append("## Phase instructions (what the operator was doing)")
        lines.append("")
        lines.append("**Labels here come from a fixed timetable, not from the operator's "
                     "actions, and the two were shown not to agree.** See "
                     "`firmware/HARDWARE_DATA_LOG.md` Section 2.")
        lines.append("")
        for name, duration, instruction in PHASES:
            lines.append(f"- **{name}** ({duration}s): {instruction}")
    lines.append("")

    all_readings = [r["reading"] for r in records]
    if all_readings:
        lines.append("## Overall observed range (all phases combined)")
        lines.append("")
        for key in feature_cols:
            vals = [r[key] for r in all_readings if key in r]
            if vals:
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

    if LABELLED:
        start_time = time.time()
        run_labelled_capture()
        session_end = time.time()
        finalise_labelled()
    else:
        print("=" * 90)
        print(" HARDWARE DATA COLLECTION -- timed schedule")
        print(" NOTE: labels here come from the CLOCK, not from what you actually did.")
        print(" Analysis of the earlier sessions showed the two disagree (at_rest_1 held")
        print(" a HIGHER max rms than moderate_shake). Use --labelled for ground truth.")
        print("=" * 90)
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
