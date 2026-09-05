"""
Merges real hardware captures (data/collected/hardware_session_*.json,
from scripts/collect_hardware_session.py) into the synthetic training
session (data/collected/training_session.json, from
generate_training_data.py), so scripts/train_isolation_forest.py,
train_lstm_ae.py, train_gnn.py, and train_fusion_meta_learner.py pick up
real hardware statistics without any of them needing to change -- see
generate_training_data.py's module docstring for why this is the intended
mechanism for folding real data in.

Each real row keeps its OWN device_id/sensor_type/reading from the capture
(esp32-vib-001/MPU6050's 5-feature vector, esp32-vib-002/SW-420's 4-feature
vector) rather than being coerced onto one schema -- train_isolation_forest.py
and train_lstm_ae.py already train one model per device via
config.FEATURE_VECTOR_DEVICE_IDS, so a heterogeneous second device merges
in cleanly with no downstream change.

All real records are genuinely legitimate readings under varying physical
conditions (at rest / tapped / shaken / tilted), not attacks -- they're
folded in as additional NORMAL examples (label=1, event_type="normal"),
exactly like the synthetic normal examples they sit alongside.

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

from config import DATA_COLLECTED_DIR, DEVICE_REGISTRY
from generate_training_data import generate as generate_synthetic
import splits

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
    """At-rest rows from the TRAIN sessions ONLY.

    This used to glob every `*_labelled.json` on disk. That put the at-rest rows
    of the validation and test sessions into the training set while
    evaluate_real_hardware.py scored the disturbance rows of those same
    sessions -- one physical acquisition session contributing to both sides
    (docs/REPOSITORY_AUDIT.md 2.2). Routing through splits.labelled_session_paths
    makes the allocation a deliberate manifest entry rather than a glob.

    Provenance is carried through: each returned row keeps its session id and
    label_source so the merged record can name where it came from."""
    splits.assert_disjoint()
    real = []
    paths = splits.labelled_session_paths("train")
    if not paths:
        print("  (no TRAIN-split *_labelled.json sessions found -- training on synthetic data only)")
    for path in paths:
        with open(path) as f:
            session = json.load(f)
        sid = splits.session_id_of(path)
        rest = [r for r in session if r.get("phase") in NORMAL_PHASES]
        for r in rest:
            r["_session_id"] = sid
        held = len(session) - len(rest)
        print(f"  {os.path.basename(path)} [session {sid}, split=train]: {len(session)} records, "
              f"{len(rest)} at-rest merged as normal, {held} held out as labelled events")
        real.extend(rest)
    for other in ("validation", "test"):
        for path in splits.labelled_session_paths(other):
            print(f"  {os.path.basename(path)} [split={other}]: WITHHELD from training entirely")
    return real


def main():
    # --synthetic-only writes the SAME file with the real rows withheld, so the
    # whole chain can be retrained without them and the contribution of the 121
    # real at-rest samples measured directly (RESULTS.md 0.10.9). It is an
    # experiment switch, not a deployment mode: re-run without it to restore.
    synthetic_only = "--synthetic-only" in sys.argv
    synthetic = generate_synthetic()
    max_tick = max(r["tick"] for r in synthetic)
    print(f"generated {len(synthetic)} fresh synthetic records (max tick={max_tick})")

    if synthetic_only:
        print("--synthetic-only: WITHHOLDING all real hardware rows (ablation run)")
        real = []
    else:
        print("loading real hardware sessions:")
        real = load_real_records()
    if not real and not synthetic_only:
        raise SystemExit("no data/collected/hardware_session_*.json files found -- "
                          "run scripts/collect_hardware_session.py first")

    # Provenance fields (source_type / session_id / sensor_type / label_source /
    # split) are attached HERE and never stripped downstream. Before this, a
    # merged real row was indistinguishable from a synthetic one except by an
    # accident of tick arithmetic (docs/REPOSITORY_AUDIT.md 2.9), so no result
    # could report real and simulated evidence separately even in principle.
    next_tick = max_tick + TICK_GAP
    merged_real = []
    for r in real:
        merged_real.append({
            "tick": next_tick,
            "source_tick": r["tick"],
            "device_id": r["device_id"],
            "reading": r["reading"],
            "auth_ok": True,
            "ts": r.get("ts") or 0,
            "label": 1,
            "event_type": "normal",
            "simulated_flood": False,
            "source_type": "REAL",
            # Older esp32-vib-001 captures predate the "sensor_type" field on
            # each record; DEVICE_REGISTRY is the fallback for those.
            "sensor_type": r.get("sensor_type")
            or DEVICE_REGISTRY.get(r["device_id"], {}).get("sensor_type", "MPU6050"),
            "session_id": r.get("_session_id"),
            "phase": r.get("phase"),
            "label_source": r.get("label_source"),
            "split": "train",
        })
        next_tick += 1

    for r in synthetic:
        r.setdefault("source_type", "SIMULATED")
        r.setdefault("session_id", "SIM_SESSION_TRAIN_001")
        r.setdefault("split", "train")

    combined = synthetic + merged_real
    with open(OUTPUT_PATH, "w") as f:
        json.dump(combined, f, indent=1)

    by_device = {}
    for r in merged_real:
        by_device[r["device_id"]] = by_device.get(r["device_id"], 0) + 1
    real_breakdown = ", ".join(f"{n} {d}" for d, n in sorted(by_device.items()))
    print(f"wrote {len(combined)} total records to {OUTPUT_PATH} "
          f"({len(synthetic)} synthetic + {len(merged_real)} real: {real_breakdown or 'none'})")


if __name__ == "__main__":
    main()
