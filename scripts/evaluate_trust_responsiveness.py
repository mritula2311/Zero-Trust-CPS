"""
docs/10_testing_and_attack_simulation.md Section 8 evaluation metric: how
quickly each score reacts to injected anomalous behaviour.

This is the one evaluate_*.py script that runs the REAL stateful pipeline
-- trust_engine.RuleBasedTrustEngine's Security Trust EWMA, and the
Process Anomaly state store -- across an entire session IN ORDER, per
device, rather than scoring each message independently
(evaluate_ablation.py's approach).

TWO-SCORE REARCHITECTURE: measures Security Trust Score responsiveness and
Process Anomaly Score responsiveness SEPARATELY -- they're never blended,
so "how fast did trust react" is now two different questions with two
different answers depending on which kind of attack was injected. Also:
`forged_signature` and `replay` events are REJECTED at Module 2 in the
live architecture and never reach either score at all (see gateway.py's
_reject() / trust_engine.IdentityTargetingRisk) -- they're reported
separately as "rejected, not scored" rather than forced into a trust-drop
measurement that no longer applies to them. (This harness has no
boot_id/seq in its synthetic records -- not needed for offline model
training -- so a `replay` event_type stands in directly for "Module 2's
boot/seq check would reject this," rather than literally replaying
through check_boot_replay().)

Time handling: trust_engine.py's decay reads time.time() (wall-clock),
correct for the live gateway but wrong for a batch replay -- every record
would appear to arrive "instantly." This script monkey-patches
trust_engine's `time` module to follow each record's own `ts` field (ms)
instead -- safe here because generate_training_data.py's `ts` values come
from its own trusted generator, not an attacker.

Held-out data only (data/collected/test_session.json), same as every
other evaluate_*.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import DATA_COLLECTED_DIR, SECURITY_THRESHOLD, PROCESS_THRESHOLD, is_feature_vector
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
    advances to follow each record's own `ts` field, so decay timing math
    behaves sensibly. MUST stay monotonically non-decreasing regardless of
    what `ts` says -- see SESSION_LOG.md for the bug this fixed the first
    time (a replayed record's earlier ts fed straight into the mocked
    clock made `elapsed` go negative, inflating trust instead of
    penalising it)."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def advance(self, candidate: float) -> None:
        self.now = candidate if candidate > self.now else self.now + 0.001


def replay_with_state(records):
    """Returns a per-record trace, processed IN ORDER through the real
    stateful two-score pipeline -- same call sequence as gateway.py's
    process_telemetry() for the authenticated path, without its MQTT/
    audit_log side effects."""
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
                trace.append({**r, "security_trust_score": None, "process_trust_score": None,
                              "process_status": None, "rejected": True})
                continue

            is_flood = r.get("simulated_flood", False)
            security_trust_score, _ = engine.score_security_trust(device_id, is_flood, step_up_result=None)

            rule_score, _ = rule_range_score(device_id, reading)
            if is_feature_vector(device_id):
                fv = fe.feature_vector(reading)
                if_score = if_scorer.score(device_id, fv)
                lstm_score = lstm_scorer.score(device_id, fv)
            else:
                if_score = lstm_score = rule_score
            gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
            process_trust_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)
            engine.update_process_anomaly(device_id, process_trust_score)
            _, process_status = engine.get_process_anomaly(device_id)

            trace.append({**r, "security_trust_score": security_trust_score,
                          "process_trust_score": process_trust_score,
                          "process_status": process_status, "rejected": False})
        return trace
    finally:
        trust_engine_module.time = real_time_module


def _messages_to_break(rows, i, key, threshold, below=True):
    for j in range(i, len(rows)):
        val = rows[j][key]
        if val is None:
            continue
        crossed = (val < threshold) if below else (val >= threshold)
        if crossed:
            return j - i
    return None


def measure_responsiveness(trace):
    """For each injected event (event_type != 'normal'), measures how many
    of that SAME DEVICE's subsequent SCORED messages it takes for the
    running Security Trust Score to drop below SECURITY_THRESHOLD, and
    separately for the Process Anomaly Score to drop below
    PROCESS_THRESHOLD -- None if it never does. Rejected events (replay,
    forged_signature) get both as None with `rejected=True`, since they
    never reach either score in the live architecture."""
    by_device = {}
    for row in trace:
        by_device.setdefault(row["device_id"], []).append(row)

    results = []
    for device_id, rows in by_device.items():
        for i, row in enumerate(rows):
            if row["event_type"] == "normal":
                continue

            if row["rejected"]:
                results.append({
                    "event_type": row["event_type"], "device_id": device_id, "tick": row["tick"],
                    "rejected": True, "messages_to_security_break": None, "messages_to_process_break": None,
                })
                continue

            results.append({
                "event_type": row["event_type"], "device_id": device_id, "tick": row["tick"],
                "rejected": False,
                "messages_to_security_break": _messages_to_break(rows, i, "security_trust_score", SECURITY_THRESHOLD),
                "messages_to_process_break": _messages_to_break(rows, i, "process_trust_score", PROCESS_THRESHOLD),
            })
    return results


def summarize(results):
    event_types = sorted({r["event_type"] for r in results})
    print(f"{'Event type':<22} {'n':>4} {'rejected':>9} {'mean msgs->SECURITY break':>26} {'mean msgs->PROCESS break':>25}")
    print("-" * 92)
    for et in event_types:
        subset = [r for r in results if r["event_type"] == et]
        rejected_n = sum(1 for r in subset if r["rejected"])
        sec_msgs = [r["messages_to_security_break"] for r in subset if r["messages_to_security_break"] is not None]
        proc_msgs = [r["messages_to_process_break"] for r in subset if r["messages_to_process_break"] is not None]
        mean_sec = f"{np.mean(sec_msgs):.2f}" if sec_msgs else "n/a"
        mean_proc = f"{np.mean(proc_msgs):.2f}" if proc_msgs else "n/a"
        print(f"{et:<22} {len(subset):>4} {rejected_n:>9} {mean_sec:>26} {mean_proc:>25}")

    print(
        "\n'rejected' = event_type is rejected at Module 2 in the live architecture (replay) "
        "and never reaches EITHER score -- reported honestly as not-applicable rather than forced "
        "into a trust-drop measurement. 'mean msgs->SECURITY/PROCESS break' = average number of "
        "that device's own subsequent scored messages (0 = the event message itself) before the "
        "respective score first crosses its threshold. Expect 'high_rate' to move ONLY the Security "
        "column and 'anomalous_shock'/'coordinated' to move ONLY the Process column -- if either "
        "moves the OTHER score too, that's a sign the two-score separation has a leak somewhere and "
        "needs investigating before trusting this result. 'stealthy_forged_values' is NOT expected to "
        "move the SECURITY column at all (it's a fully valid, correctly-authenticated message), and is "
        "NOT expected to reliably move the PROCESS column either (docs/04 Section B.8) -- some partial, "
        "inconsistent detection is a plausible, honest result (the reported values are close to the edge "
        "of normal by construction, not deliberately deep in-range), not a guaranteed zero."
    )


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)

    print(f"Replaying {len(records)} held-out messages through the real stateful two-score pipeline...")
    trace = replay_with_state(records)
    results = measure_responsiveness(trace)
    print(f"Measured responsiveness for {len(results)} injected events.\n")
    summarize(results)


if __name__ == "__main__":
    main()
