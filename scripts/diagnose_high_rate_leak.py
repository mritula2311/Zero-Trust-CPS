"""
One-off diagnostic for RESULTS.md Section 14 item 5: "Unexplained
Process-score movement on high_rate" -- a pure rate/security event is
architecturally supposed to never move the Process Anomaly Score, but
scripts/evaluate_trust_responsiveness.py measured a mean of 3.03 messages
to PROCESS-threshold-break for high_rate events, which was reported as an
open, un-isolated finding.

Same stateful replay as evaluate_trust_responsiveness.py (import its
exact replay_with_state(), not a reimplementation, so this can't
accidentally diverge from what produced the original number), but with
each of the four Process Anomaly sub-signals (rule/IF/LSTM/GNN) captured
per record instead of just the fused output, so a high_rate record where
the fused score moved can be attributed to a specific sub-signal.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, PROCESS_THRESHOLD, is_feature_vector
from trust_engine import RuleBasedTrustEngine, rule_range_score
import trust_engine as trust_engine_module
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
import feature_engineering as fe

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def advance(self, candidate):
        self.now = candidate if candidate > self.now else self.now + 0.001


def replay_with_subscores(records):
    """Same call sequence/state machine as evaluate_trust_responsiveness.py's
    replay_with_state(), but keeps rule/if/lstm/gnn alongside the fused
    score per record."""
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
            event_type = r["event_type"]
            reading = r["reading"]

            rejected = (not auth_ok) or (event_type == "replay")
            if rejected:
                trace.append({**r, "process_trust_score": None, "rejected": True})
                continue

            is_flood = r.get("simulated_flood", False)
            engine.score_security_trust(device_id, is_flood, step_up_result=None)

            rule_score, rule_reason = rule_range_score(device_id, reading)
            if is_feature_vector(device_id):
                fv = fe.feature_vector(reading)
                if_score = if_scorer.score(device_id, fv)
                lstm_score = lstm_scorer.score(device_id, fv)
            else:
                if_score = lstm_score = rule_score
            gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
            process_trust_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)
            engine.update_process_anomaly(device_id, process_trust_score)

            trace.append({
                **r, "rejected": False,
                "rule_score": rule_score, "rule_reason": rule_reason,
                "if_score": if_score, "lstm_score": lstm_score, "gnn_score": gnn_score,
                "process_trust_score": process_trust_score,
            })
        return trace
    finally:
        trust_engine_module.time = real_time_module


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)

    trace = replay_with_subscores(records)
    by_tick = {}
    for row in trace:
        by_tick.setdefault(row["tick"], []).append(row)

    print("Scanning high_rate rows for process_trust_score dips below PROCESS_THRESHOLD "
          f"({PROCESS_THRESHOLD})...\n")

    flagged = 0
    for row in trace:
        if row["rejected"] or row["event_type"] != "high_rate":
            continue
        if row["process_trust_score"] is None or row["process_trust_score"] >= PROCESS_THRESHOLD:
            continue
        flagged += 1
        tick = row["tick"]
        device_id = row["device_id"]
        print(f"--- tick={tick} device={device_id} process_trust_score={row['process_trust_score']:.4f} "
              f"(rule={row['rule_score']:.3f} if={row['if_score']:.3f} "
              f"lstm={row['lstm_score']:.3f} gnn={row['gnn_score']:.3f}) ---")
        print(f"    rule_reason: {row['rule_reason']}")
        # Show what every device looked like on this SAME tick -- the
        # leading hypothesis is a cross-device coincidence, not a
        # single-device bug.
        for sibling in sorted(by_tick[tick], key=lambda x: x["device_id"]):
            if sibling is row:
                continue
            print(f"    same-tick sibling: device={sibling['device_id']} "
                  f"event_type={sibling['event_type']} auth_ok={sibling['auth_ok']} "
                  f"rejected={sibling['rejected']}")
        print()

    print(f"Total high_rate rows with process_trust_score < {PROCESS_THRESHOLD}: {flagged}")


if __name__ == "__main__":
    main()
