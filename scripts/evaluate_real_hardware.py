"""
Evaluates the Process Anomaly pipeline against REAL, LABELLED hardware data.

Why this script exists, and why it is different from every other evaluate_*.py
here: all of those score SYNTHETIC data whose labels are known by construction,
because the generator decided them. This one scores telemetry from a physical
ESP32 + MPU6050, against labels an operator recorded AT THE MOMENT of each
action rather than inferring them afterwards from a timetable.

That distinction is the whole point. The four earlier hardware sessions were
labelled by a fixed schedule, and analysis showed the labels did not match the
physics -- `at_rest_1` contained a higher maximum rms (3.416 g) than
`moderate_shake` (1.050 g). Labels like that cannot support any claim about
detection quality, which is why merge_real_hardware_data.py folds those rows in
as one undifferentiated "normal" class rather than trusting the phases.

WHAT THE LABELS MEAN. The operator was asked to hold the board in a named
physical state; the label records that instruction, timestamped. So this
measures "does the pipeline distinguish a resting board from a disturbed one",
not "does it detect an attack" -- nobody attacked anything. A shaken board is
a genuine PROCESS anomaly (the thing Module 3 exists to flag), not a security
event, and the two-score architecture is built precisely so those stay separate.

READ THE OVERLAP NUMBERS, NOT JUST THE ACCURACY. Intermittent actions have
genuinely quiet moments between them: a tap every ~2 seconds means some 64 ms
windows legitimately catch silence. Those samples are labelled with the action
but physically indistinguishable from rest, and scoring them as misses would
be measuring the labelling granularity rather than the model.
"""

import collections
import json
import glob
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, PROCESS_THRESHOLD, is_feature_vector, LSTM_SEQ_LEN
import feature_engineering as fe
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from trust_engine import rule_range_score

DEVICE = "esp32-vib-001"

# Phases that represent a healthy, undisturbed board. Everything else is a real
# physical disturbance the Process Anomaly engine should score lower.
NORMAL_PHASES = {"at_rest"}

# Actions performed intermittently, so a fraction of their windows genuinely
# contain no activity. Reported separately rather than counted as failures.
INTERMITTENT_PHASES = {"gentle_tap", "tilt_rotate", "sharp_impact"}


def load_sessions():
    rows = []
    for path in sorted(glob.glob(os.path.join(DATA_COLLECTED_DIR, "*_labelled.json"))):
        with open(path) as f:
            session = json.load(f)
        rows.extend(session)
        print(f"  {os.path.basename(path)}: {len(session)} labelled records")
    return rows


def score_all(rows):
    """Scores each record through the real pipeline.

    The LSTM-AE's rolling window is RESET at every phase boundary, and the first
    LSTM_SEQ_LEN-1 records of each block are dropped, because otherwise this
    measures the wrong thing. Feeding all 114 records through one continuous
    window means every window straddling a boundary contains two different
    physical states -- half rest, half shaking -- and reconstructs badly by
    construction. Measured: with a continuous window the LSTM scored 0.000 even
    on at_rest, while the same at_rest samples fed as their own sequence
    reconstruct at error 0.725, z=0.0, i.e. a 0.9 score. The continuous number
    was measuring transitions, not the model.

    That transition behaviour is real and matters live -- it is the ALERT
    recovery tail after a disturbance -- but it belongs to a different question
    than "given the board is in state X, does the pipeline score X correctly",
    which is what a labelled per-phase evaluation exists to answer.

    The GNN needs a graph, and a single real device publishing alone IS the
    deployed topology, so the two simulated devices are marked active with
    neutral evidence -- matching what the live gateway sees with all three up."""
    if_s, gnn_s, fusion = IsolationForestScorer(), GNNScorer(), FusionEngine()
    out = []
    lstm_s = LSTMAEScorer()
    prev_phase = None
    warmup = 0
    for r in rows:
        if r.get("phase") != prev_phase:
            lstm_s = LSTMAEScorer()   # fresh rolling window per physical state
            prev_phase = r.get("phase")
            warmup = 0
        warmup += 1
        reading = r["reading"]
        rule, _ = rule_range_score(DEVICE, reading)
        if is_feature_vector(DEVICE):
            fv = fe.feature_vector(reading)
            iso = if_s.score(DEVICE, fv)
            lstm = lstm_s.score(DEVICE, fv)
        else:
            iso = lstm = rule
        gnn_s.score("sensor-002", 0.9, 0.9, 0.9)
        gnn_s.score("actuator-001", 0.9, 0.9, 0.9)
        gnn = gnn_s.score(DEVICE, rule, iso, lstm)
        fused, _, _ = fusion.combine(rule, iso, lstm, gnn)
        if warmup >= LSTM_SEQ_LEN:      # only score once the window is genuinely full
            out.append({**r, "rule": rule, "iso": iso, "lstm": lstm, "gnn": gnn, "fused": fused})
    return out


def main():
    print("=" * 78)
    print("REAL HARDWARE EVALUATION -- operator-labelled ESP32 + MPU6050 telemetry")
    print("=" * 78)
    rows = load_sessions()
    if not rows:
        raise SystemExit(
            "No *_labelled.json sessions found. Capture one with:\n"
            "    python collect_hardware_session.py --labelled")

    scored = score_all(rows)
    by = collections.defaultdict(list)
    for r in scored:
        by[r["phase"]].append(r)

    print(f"\nScored {len(scored)} real readings through the live pipeline "
          f"(threshold {PROCESS_THRESHOLD}).\n")
    print(f"{'phase':16s} {'n':>4s} {'rule':>7s} {'iso':>7s} {'lstm':>7s} {'gnn':>7s} "
          f"{'fused':>8s} {'flagged':>9s}")
    print("-" * 78)
    order = sorted(by, key=lambda p: (p not in NORMAL_PHASES, p))
    for phase in order:
        v = by[phase]
        med = lambda k: st.median([x[k] for x in v])
        flagged = sum(1 for x in v if x["fused"] < PROCESS_THRESHOLD) / len(v)
        print(f"{phase:16s} {len(v):>4d} {med('rule'):>7.3f} {med('iso'):>7.3f} "
              f"{med('lstm'):>7.3f} {med('gnn'):>7.3f} {med('fused'):>8.3f} {flagged:>8.0%}")

    normal = [r for r in scored if r["phase"] in NORMAL_PHASES]
    events = [r for r in scored if r["phase"] not in NORMAL_PHASES]

    print()
    if normal:
        fp = sum(1 for r in normal if r["fused"] < PROCESS_THRESHOLD) / len(normal)
        print(f"FALSE POSITIVE RATE on a genuinely resting board: {fp:.1%} "
              f"({sum(1 for r in normal if r['fused'] < PROCESS_THRESHOLD)}/{len(normal)})")
        print(f"  fused median {st.median([r['fused'] for r in normal]):.3f}, "
              f"min {min(r['fused'] for r in normal):.3f}")
    if events:
        det = sum(1 for r in events if r["fused"] < PROCESS_THRESHOLD) / len(events)
        print(f"DETECTION RATE on real physical disturbance:      {det:.1%} "
              f"({sum(1 for r in events if r['fused'] < PROCESS_THRESHOLD)}/{len(events)})")

    # The honest caveat: some labelled-action windows contain no action.
    if normal and events:
        rest_max_peak = max(r["reading"]["peak"] for r in normal)
        quiet = [r for r in events if r["reading"]["peak"] <= rest_max_peak]
        if quiet:
            loud = [r for r in events if r["reading"]["peak"] > rest_max_peak]
            det_loud = sum(1 for r in loud if r["fused"] < PROCESS_THRESHOLD) / len(loud)
            print()
            print(f"  {len(quiet)} of {len(events)} action-labelled windows are physically "
                  f"indistinguishable from rest")
            print(f"  (peak <= {rest_max_peak:.3f} g, the resting maximum) -- intermittent "
                  f"actions have gaps between them.")
            print(f"  Detection on the {len(loud)} windows that DO contain movement: {det_loud:.1%}")
            print(f"  Reported both ways rather than silently excluding the quiet ones, which")
            print(f"  would measure labelling granularity rather than the model.")

    print()
    print("Note this measures PHYSICAL anomaly discrimination on real hardware, not")
    print("attack detection -- no attack was performed. Security Trust is untouched")
    print("throughout, which is the two-score separation behaving correctly.")


if __name__ == "__main__":
    main()
