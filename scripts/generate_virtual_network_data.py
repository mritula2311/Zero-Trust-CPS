"""
Builds a 5-node REAL_DERIVED_VIRTUAL network for M9, mirroring
generate_network_data.py's scenario/tick/block structure so the virtual
network is comparable in size and event structure to the existing 10-node
hybrid network -- config/virtual_generator.json's own _ticks_note already
states this intent (ticks_per_split matches generate_network_data.py's TICKS,
block_ticks matches its BLOCK_TICKS).

    V_NETWORK_NORMAL   control -- every virtual node normal
    V_SCENARIO_A       virt-01 isolated anomalous; 02-05 normal
    V_SCENARIO_B       virt-01 isolated AND virt-02,03 coordinated; 04-05 normal
    V_SCENARIO_C       virt-02, virt-04 coordinated, NOT adjacent in id order;
                       01, 03, 05 normal -- mirrors SCENARIO_C's own point
                       (a coordinated pattern spread across the population,
                       not handed to a relational model pre-grouped)

PRESET IS LOW, ONLY. scripts/validate_virtual_device_generator.py measured
that LOW passes every check (marginals, correlation, lag-1 autocorrelation,
a balanced real-vs-generated discriminator) while MEDIUM/HIGH show a real,
measured rms/peak residual divergence against the tiny real resting sample.
MEDIUM/HIGH are therefore out-of-distribution STRESS TESTS for a model
trained on this data, not additional training regimes -- do not add them
here without re-validating first.

A FRESH fault_displacement() PER EVENT WINDOW, not one shared delta per
(scenario, split). An earlier version drew one delta per split and reused its
leading segment at every event block (a consequence of
virtual_device_generator.generate_series()'s windowed-anomaly application
always slicing from delta's start, not the window's own tick offset) -- a
1-seed sanity check (scripts/benchmark_crossdevice_models.py's
m9_sanity_check) measured the result directly: a coordinated scenario's
anomalous scores clustered at std=0.0054 across 300 rows, an easily-learned
repeated signature rather than a realistic anomaly distribution. Each window
now draws its own real disturbance run independently, giving a split-safe
library of many trajectories (fault_displacement() already restricts its
draw to the calling split's own `pool["fault"]`, so this cannot leak across
splits) instead of one template stamped everywhere.

Writes data/collected/virtual_network/virtual_{scenario}_{split}.json, in
generate_network_data.py's own record schema, so
build_virtual_snapshots() in scripts/benchmark_crossdevice_models.py can
score them through the identical rule/Isolation-Forest/LSTM-AE pipeline
build_snapshots() uses for the real network.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

import virtual_device_generator as vgen

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "collected", "virtual_network")

N_VIRTUAL_NODES = 5
VIRTUAL_NODES = vgen.node_ids(N_VIRTUAL_NODES)

VIRTUAL_SCENARIOS = {
    "V_NETWORK_NORMAL": set(),
    "V_SCENARIO_A": {"virt-01"},
    "V_SCENARIO_B": {"virt-01", "virt-02", "virt-03"},
    "V_SCENARIO_C": {"virt-02", "virt-04"},
}

TICKS = {"train": 600, "validation": 300, "test": 300}   # matches generate_network_data.py
BLOCK_TICKS = 30                                          # matches generate_network_data.py
PRESET_NAME = "LOW"


def _seed_for(scenario: str, split: str, node_id: str) -> int:
    h = hashlib.sha256(f"{scenario}|{split}|{node_id}".encode()).hexdigest()
    return int(h[:8], 16)


def _in_event(tick: int, anomalous_nodes: set) -> bool:
    return (tick // BLOCK_TICKS) % 2 == 1 and bool(anomalous_nodes)


def build(scenario: str, split: str, preset_name: str = PRESET_NAME) -> list[dict]:
    anomalous_nodes = VIRTUAL_SCENARIOS[scenario]
    n_ticks = TICKS[split]
    preset = vgen.load_config()["heterogeneity_presets"][preset_name]
    pool = vgen.load_real_pool(split)
    stats = vgen.empirical_stats(pool)

    windows = [(t, min(t + BLOCK_TICKS, n_ticks))
               for t in range(0, n_ticks, BLOCK_TICKS) if (t // BLOCK_TICKS) % 2 == 1]

    series, masks = {}, {}
    for node_id in VIRTUAL_NODES:
        # Pure normal series first -- device identity (scale/bias/drift), base
        # trajectory and noise only, no anomaly. Ungated by node_id: a
        # non-anomalous node's series is exactly this.
        readings, _mask, _prov = vgen.generate_series(
            node_id, n_ticks, pool, stats, preset, scenario, split,
            global_seed=_seed_for(scenario, split, node_id), anomaly=None)
        mask = np.zeros(n_ticks, dtype=bool)

        if node_id in anomalous_nodes:
            # A FRESH fault_displacement() draw PER WINDOW, not one shared
            # delta per (scenario, split) -- a split-safe library of many real
            # fault trajectories (each fault_displacement() call independently
            # samples a random real disturbance run from `pool["fault"]`,
            # which load_real_pool(split) already restricts to this split's
            # own sessions, so this cannot leak across splits) rather than one
            # template stamped at every event. This was measured to matter:
            # sharing one delta across all of a split's event blocks produced
            # near-zero anomalous-score variance within a coordinated
            # scenario (std=0.0054 across 300 rows) -- an easily-learned
            # repeated signature, not a realistic anomaly distribution
            # (scripts/benchmark_crossdevice_models.py's m9_sanity_check
            # demonstrated this directly before this fix).
            node_rng = np.random.default_rng(_seed_for(scenario, split, node_id))
            lo, hi = preset["anomaly_severity_range"]
            lag = int(node_rng.integers(0, preset["coordinated_lag_ticks_max"] + 1))
            x = np.array([[r[k] for k in vgen.FREE_FEATURES] for r in readings])
            for t0, t1 in windows:
                a0, a1 = min(t0 + lag, n_ticks), min(t1 + lag, n_ticks)
                if a0 >= a1:
                    continue
                w_rng = np.random.default_rng(_seed_for(scenario, split, f"{node_id}_{t0}"))
                alpha = float(w_rng.uniform(lo, hi))
                _sid, _phase, delta = vgen.fault_displacement(pool, stats, a1 - a0, w_rng)
                x[a0:a1] += alpha * delta
                mask[a0:a1] = True
            readings = [vgen._finalise(row) for row in x]

        series[node_id], masks[node_id] = readings, mask

    records = []
    for tick in range(n_ticks):
        in_event = _in_event(tick, anomalous_nodes)
        event_id = f"{scenario}_{split}_evt{tick // (2 * BLOCK_TICKS):03d}" if in_event else None
        for node_id in VIRTUAL_NODES:
            is_anom = bool(masks[node_id][tick])
            records.append({
                "tick": tick,
                "device_id": node_id,
                "session_id": f"VNET_{scenario}_{split.upper()}_001",
                "scenario": scenario,
                "split": split,
                "event_id": event_id,
                "condition": "PHYSICAL_ANOMALY" if is_anom else "NORMAL",
                "label": 0 if is_anom else 1,
                "event_type": "coordinated" if is_anom else "normal",
                "source_type": vgen.SOURCE_TYPE,
                "heterogeneity_preset": preset_name,
                "reading": series[node_id][tick],
            })
    return records


def output_path(scenario: str, split: str, preset_name: str = PRESET_NAME) -> str:
    """LOW keeps the bare filename (build_virtual_snapshots()'s default,
    unchanged for backward compatibility -- LOW is the only TRAINING regime).
    MEDIUM/HIGH are OOD stress-test data only, suffixed so they never collide
    with or get mistaken for the validated LOW files."""
    suffix = "" if preset_name == "LOW" else f"_{preset_name}"
    return os.path.join(OUTPUT_DIR, f"virtual_{scenario}_{split}{suffix}.json")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    preset_name = PRESET_NAME
    if "--preset" in sys.argv:
        preset_name = sys.argv[sys.argv.index("--preset") + 1]
    # MEDIUM/HIGH are OOD stress tests evaluated against the LOW-trained model,
    # never trained on -- only TEST data is needed for them.
    splits_to_build = ("train", "validation", "test") if preset_name == "LOW" else ("test",)

    print("=" * 78)
    print(f"{N_VIRTUAL_NODES}-NODE VIRTUAL NETWORK -- REAL_DERIVED_VIRTUAL, preset={preset_name}")
    print("=" * 78)
    for split in splits_to_build:
        for scenario in VIRTUAL_SCENARIOS:
            records = build(scenario, split, preset_name)
            path = output_path(scenario, split, preset_name)
            with open(path, "w") as f:
                json.dump(records, f, indent=1)
            anom = sum(1 for r in records if r["label"] == 0)
            print(f"{scenario:18s} {split:11s} {len(records):6d} rows  anomalous={anom}")
    print(f"\nwritten to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
