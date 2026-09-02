"""
Merges real esp32-vib-001 captures (data/collected/hardware_session_*.json,
from scripts/collect_hardware_session.py) into the synthetic training
session (data/collected/training_session.json, from
generate_training_data.py), so scripts/train_isolation_forest.py,
train_lstm_ae.py, train_gnn.py, and train_fusion_meta_learner.py pick up
real hardware statistics without any of them needing to change -- see
generate_training_data.py's module docstring for why this is the intended
mechanism for folding real data in.

All real records are genuinely legitimate readings under varying physical
conditions (at rest / tapped / shaken / tilted), not attacks -- they're
folded in as additional NORMAL esp32-vib-001 examples (label=1,
event_type="normal"), exactly like the synthetic normal examples they sit
alongside.

Re-running this script is idempotent: it always starts from a fresh
synthetic generate() call (same seed=42) rather than reading back a
previously-merged training_session.json, so re-running never double-adds
the same real data.

`tick` numbers for the real records start well past the synthetic session's
max tick + train_gnn.py's EDGE_WINDOW_TICKS(=1), so sensor-002/actuator-001
correctly read as inactive graph neighbors for every real record (matching
what a standalone real board with no other live devices actually looks
like) rather than spuriously inheriting the synthetic session's last
neighbor state.
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR
from generate_training_data import generate as generate_synthetic

OUTPUT_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
TICK_GAP = 20  # comfortably past EDGE_WINDOW_TICKS=1


# Only sessions captured through the CURRENT acquisition chain may be merged.
#
# The four 20260901 sessions were recorded with unpaced sampling (~1231 Hz while
# labelling the axis 100 Hz -- a 12.3x error) and with no anti-alias filter, so
# their dominant_freq values sit on a completely different frequency axis than
# anything the board produces now (median 6.25 Hz against 15.62 Hz, max 50 Hz
# against 250 Hz). Pooling them would teach every model that one physical
# condition has two different spectral signatures. They are kept on disk as a
# historical record and excluded here. See RESULTS.md 13.4c.
#
# Only files matching this suffix are merged; re-capture with
# `collect_hardware_session.py --labelled` produces one.
MERGEABLE_SUFFIX = "_labelled.json"

# Of the labelled phases, only genuinely-at-rest samples are NORMAL training
# data. gentle_tap/tilt_rotate/moderate_shake/sharp_impact are real physical
# disturbances -- exactly the thing the Process Anomaly engine exists to flag --
# so folding them in as "normal" would be teaching the models that a shaken
# board is healthy. They are held out instead, and
# scripts/evaluate_real_hardware.py scores them as a labelled test set.
NORMAL_PHASES = {"at_rest"}


def load_real_records():
    real = []
    paths = sorted(glob.glob(os.path.join(DATA_COLLECTED_DIR, "*" + MERGEABLE_SUFFIX)))
    if not paths:
        print("  (no *_labelled.json sessions found -- training on synthetic data only)")
    for path in paths:
        with open(path) as f:
            session = json.load(f)
        rest = [r for r in session if r.get("phase") in NORMAL_PHASES]
        held = len(session) - len(rest)
        print(f"  {os.path.basename(path)}: {len(session)} records, "
              f"{len(rest)} at-rest merged as normal, {held} held out as labelled events")
        real.extend(rest)
    return real


def main():
    synthetic = generate_synthetic()
    max_tick = max(r["tick"] for r in synthetic)
    print(f"generated {len(synthetic)} fresh synthetic records (max tick={max_tick})")

    print("loading real hardware sessions:")
    real = load_real_records()
    if not real:
        raise SystemExit("no data/collected/hardware_session_*.json files found -- "
                          "run scripts/collect_hardware_session.py first")

    next_tick = max_tick + TICK_GAP
    merged_real = []
    for r in real:
        merged_real.append({
            "tick": next_tick,
            "device_id": "esp32-vib-001",
            "reading": r["reading"],
            "auth_ok": True,
            "ts": r.get("ts") or 0,
            "label": 1,
            "event_type": "normal",
            "simulated_flood": False,
        })
        next_tick += 1

    combined = synthetic + merged_real
    with open(OUTPUT_PATH, "w") as f:
        json.dump(combined, f, indent=1)

    print(f"wrote {len(combined)} total records to {OUTPUT_PATH} "
          f"({len(synthetic)} synthetic + {len(merged_real)} real esp32-vib-001)")


if __name__ == "__main__":
    main()
