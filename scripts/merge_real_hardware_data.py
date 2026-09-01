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


def load_real_records():
    real = []
    for path in sorted(glob.glob(os.path.join(DATA_COLLECTED_DIR, "hardware_session_*.json"))):
        with open(path) as f:
            session = json.load(f)
        print(f"  {os.path.basename(path)}: {len(session)} records")
        real.extend(session)
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
