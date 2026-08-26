"""
Synopsis Section 10.1 evaluation metric: "Trust-score responsiveness: how
quickly the fused trust score reacts to injected anomalous behaviour
(spoofing, replay, behavioural drift, coordinated multi-device attacks)."

This is the one evaluate_*.py script that runs the REAL stateful pipeline
-- trust_engine.RuleBasedTrustEngine's EWMA -- across an entire session IN
ORDER, per device, rather than scoring each message independently
(evaluate_ablation.py's approach). That statefulness is the whole point
here: "responsiveness" is a property of the trust score's trajectory over
consecutive messages, not any single message's classification.

Time handling: trust_engine.py's decay and check_flood() both read
time.time() (wall-clock), which is correct for the live gateway but wrong
for a batch replay -- every record would appear to arrive "instantly"
after the previous one, which would either flood-flag everything or
apply zero time-decay, neither of which reflects the session's actual
~2s-per-device cadence. This script monkey-patches trust_engine's `time`
module to follow each record's own `ts` field (ms) instead -- safe here
because generate_training_data.py's `ts` values come from its own trusted
generator, not an attacker (unlike check_replay(), which correctly never
trusts payload ts for anything security-relevant -- this patch only
affects decay/flood timing math, not the replay check's own logic).

Held-out data only (data/collected/test_session.json), same as every
other evaluate_*.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import DATA_COLLECTED_DIR, THRESHOLD_ALLOW, THRESHOLD_STEP_UP
import feature_engineering as fe
import trust_engine as trust_engine_module
from trust_engine import RuleBasedTrustEngine, rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")


class _FakeClock:
    """Replaces trust_engine.time.time() for the duration of the replay --
    advances to follow each record's own `ts` field (the session's real
    ~2s-per-device cadence), so decay/flood timing math behaves sensibly
    instead of seeing however fast this script actually executes.

    MUST stay monotonically non-decreasing regardless of what `ts` says,
    the same way real wall-clock time never runs backward even when a
    REPLAYED message's payload ts does (that backward jump in payload ts
    is exactly what check_replay() detects). advance() enforces this --
    without it, a replay record's earlier ts would make `elapsed` in
    score_message()'s decay calculation go negative, which inflates
    trust_score instead of penalising it: a bug in this harness, not in
    trust_engine.py, but one worth documenting since it's an easy trap for
    anyone else replaying `ts`-bearing session data outside the live
    gateway's real-time path."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def advance(self, candidate: float) -> None:
        self.now = candidate if candidate > self.now else self.now + 0.001


def replay_with_state(records):
    """Returns a per-record trace of (record, trust_score, confidence, reason),
    processed IN ORDER through the real stateful pipeline -- same call
    sequence as gateway.py's process_telemetry(), without its MQTT/audit_log
    side effects (same reimplementation pattern evaluate_ablation.py and
    evaluate_explainability.py already use)."""
    fake_clock = _FakeClock()
    real_time_module = trust_engine_module.time
    trust_engine_module.time = fake_clock

    try:
        engine = RuleBasedTrustEngine()
        if_scorer = IsolationForestScorer()
        lstm_scorer = LSTMAEScorer()
        gnn_scorer = GNNScorer()
        fusion = FusionEngine()

        trace = []
        for r in sorted(records, key=lambda r: r["tick"]):
            fake_clock.advance(r["ts"] / 1000.0)

            device_id = r["device_id"]
            auth_ok = r["auth_ok"]
            reading = r["reading"]

            is_replay = engine.check_replay(device_id, r["ts"])
            is_flood = engine.check_flood(device_id)

            rule_score, _ = rule_range_score(device_id, reading)

            if auth_ok and not is_replay and not is_flood:
                if device_id == "esp32-vib-001":
                    fv = fe.feature_vector(reading)
                    if_score = if_scorer.score(fv)
                    lstm_score = lstm_scorer.score(device_id, fv)
                else:
                    if_score = lstm_score = rule_score
            else:
                if_score = lstm_score = 0.1

            gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
            fused_observation, confidence, fused_reason = fusion.combine(rule_score, if_score, lstm_score, gnn_score)

            if auth_ok and not is_replay and not is_flood:
                trust_score, confidence, reason = engine.score_message(
                    device_id, reading, auth_ok, fused_observation, fused_reason, confidence
                )
            else:
                trust_score, confidence, reason = engine.score_message(
                    device_id, reading, auth_ok, is_replay=is_replay, is_flood=is_flood
                )

            trace.append({**r, "trust_score": trust_score, "confidence": confidence, "reason": reason})
        return trace
    finally:
        trust_engine_module.time = real_time_module


def measure_responsiveness(trace):
    """For each injected event (event_type != 'normal'), measures how many
    of that SAME DEVICE's subsequent messages (0 = the event message
    itself) it takes for the running trust score to drop below
    THRESHOLD_ALLOW and below THRESHOLD_STEP_UP -- None if it never does
    within the visible remainder of that device's trace (a real
    "the system never reacted" result, reported honestly, not hidden)."""
    by_device = {}
    for row in trace:
        by_device.setdefault(row["device_id"], []).append(row)

    results = []
    for device_id, rows in by_device.items():
        for i, row in enumerate(rows):
            if row["event_type"] == "normal":
                continue
            baseline = rows[i - 1]["trust_score"] if i > 0 else None
            at_event = row["trust_score"]

            msgs_to_allow_break = None
            msgs_to_stepup_break = None
            for j in range(i, len(rows)):
                if msgs_to_allow_break is None and rows[j]["trust_score"] < THRESHOLD_ALLOW:
                    msgs_to_allow_break = j - i
                if msgs_to_stepup_break is None and rows[j]["trust_score"] < THRESHOLD_STEP_UP:
                    msgs_to_stepup_break = j - i
                if msgs_to_allow_break is not None and msgs_to_stepup_break is not None:
                    break

            results.append({
                "event_type": row["event_type"],
                "device_id": device_id,
                "tick": row["tick"],
                "baseline_trust": baseline,
                "trust_at_event": at_event,
                "immediate_drop": (baseline - at_event) if baseline is not None else None,
                "messages_to_below_allow": msgs_to_allow_break,
                "messages_to_below_stepup": msgs_to_stepup_break,
            })
    return results


def summarize(results):
    event_types = sorted({r["event_type"] for r in results})
    print(f"{'Event type':<20} {'n':>4} {'mean drop':>10} {'mean msgs->ALLOW break':>24} {'mean msgs->STEP_UP break':>26} {'never crossed':>14}")
    print("-" * 100)
    for et in event_types:
        subset = [r for r in results if r["event_type"] == et]
        drops = [r["immediate_drop"] for r in subset if r["immediate_drop"] is not None]
        allow_msgs = [r["messages_to_below_allow"] for r in subset if r["messages_to_below_allow"] is not None]
        stepup_msgs = [r["messages_to_below_stepup"] for r in subset if r["messages_to_below_stepup"] is not None]
        never = sum(1 for r in subset if r["messages_to_below_allow"] is None)
        mean_drop = f"{np.mean(drops):.3f}" if drops else "n/a"
        mean_allow = f"{np.mean(allow_msgs):.2f}" if allow_msgs else "n/a"
        mean_stepup = f"{np.mean(stepup_msgs):.2f}" if stepup_msgs else "n/a"
        print(f"{et:<20} {len(subset):>4} {mean_drop:>10} {mean_allow:>24} {mean_stepup:>26} {never:>14}")

    print(
        "\n'mean msgs->ALLOW break' = average number of that device's own subsequent "
        "messages (0 = the event message itself) before the running EWMA trust score "
        "first drops below THRESHOLD_ALLOW -- i.e. how fast the system stops confidently "
        "trusting the device once the attack starts. 'never crossed' counts events where "
        "trust never dropped below THRESHOLD_ALLOW at all within the rest of that device's "
        "session -- for 'coordinated' events (individually mild by design, see "
        "device_simulator.py) this is expected to be nonzero and worth discussing honestly "
        "in the paper rather than hidden."
    )


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)

    print(f"Replaying {len(records)} held-out messages through the real stateful trust_engine...")
    trace = replay_with_state(records)
    results = measure_responsiveness(trace)
    print(f"Measured responsiveness for {len(results)} injected events.\n")
    summarize(results)


if __name__ == "__main__":
    main()
