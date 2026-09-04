"""
Builds the 10-node hybrid CPS network sessions used by every network-scale
experiment (GNN baselines, coordinated detection, hybrid latency).

    2 REAL physical nodes  +  8 SIMULATED nodes  =  10-node hybrid network

THE RULE THAT SHAPES THIS WHOLE FILE: the two real nodes' telemetry is never
generated. Their rows are drawn from actual captured sessions, split-respecting
(`data/splits/session_split.json`), and marked `source_type: "REAL"`. Simulating
a node the project calls physical would make the entire hybrid claim false.

Where a real node has no capture for the split being built, its rows are emitted
with `source_type: "PENDING_REAL_HARDWARE_DATA"` and carry no features. They are
excluded from metrics and counted separately, rather than being filled in with
plausible numbers. See the console summary each run prints.

SCENARIOS (brief section 10). Each is a coordination pattern over the ten nodes:

    NETWORK_NORMAL   control -- every node normal
    SCENARIO_A       nodes 01-02 (both REAL, group A) anomalous; 03-10 normal
    SCENARIO_B       nodes 01-02 anomalous AND 03-06 correlated anomalous;
                     07-10 normal  -- an event spreading within and beyond group A
    SCENARIO_C       nodes 03,05,07,09 coordinated anomalous, real nodes NORMAL
                     -- a coordinated pattern that no single-node view of a real
                     device can see, and which spans three process groups

SCENARIO_C is the case the whole graph question turns on, and it is deliberately
adversarial to the GNN's topology: its four anomalous nodes are spread across
groups A/B/C, so they are NOT mutually adjacent. If relational information helps
here it is not because the anomaly was handed to the model pre-grouped.

Seeds are frozen per (scenario, split, node) so a regeneration is byte-identical
and the final test network is never quietly redrawn while tuning.
"""

import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import (
    DATA_COLLECTED_DIR, NETWORK_NODES, REAL_NODES, SIMULATED_NODES,
    SIMULATED_NODE_PROFILES, DEVICE_REGISTRY, GRAPH_TOPOLOGY,
    FEATURE_SAMPLE_RATE_HZ, FEATURE_WINDOW_SIZE,
    SW420_SAMPLE_RATE_HZ, SW420_WINDOW_SIZE,
)
import feature_engineering as fe
import feature_engineering_sw420 as fes
import device_simulator as sim
import splits

OUTPUT_DIR = os.path.join(DATA_COLLECTED_DIR, "network")

SCENARIOS = {
    "NETWORK_NORMAL": set(),
    "SCENARIO_A": {"esp32-vib-001", "esp32-vib-002"},
    "SCENARIO_B": {"esp32-vib-001", "esp32-vib-002",
                   "esp32-sim-03", "esp32-sim-04", "esp32-sim-05", "esp32-sim-06"},
    "SCENARIO_C": {"esp32-sim-03", "esp32-sim-05", "esp32-sim-07", "esp32-sim-09"},
}

# Ticks per scenario per split. Test is the same size as validation so the
# comparison is like-for-like; train is larger because models fit on it.
TICKS = {"train": 600, "validation": 300, "test": 300}

# A scenario alternates quiet and event blocks rather than being anomalous
# throughout: an "event" that never ends is not an event, and event-level
# metrics need boundaries to count against.
BLOCK_TICKS = 30


def _seed_for(scenario: str, split: str, device_id: str) -> int:
    """Deterministic and independent per (scenario, split, node). Deriving from
    a hash rather than incrementing a counter avoids the failure where two nodes
    seeded n and n+1 produce visibly correlated streams -- the brief's 'do not
    accidentally generate identical node sequences'."""
    import hashlib
    h = hashlib.sha256(f"{scenario}|{split}|{device_id}".encode()).hexdigest()
    return int(h[:8], 16)


def _sim_feature_vector_reading(profile: dict, rng: random.Random, anomalous: bool, drift_phase: float):
    """One MPU6050-like reading for a simulated node.

    Reuses device_simulator._synthetic_accel_window() -- the SAME generator the
    real training data is calibrated against -- then applies this node's
    documented offsets. Building a second, independent window generator here
    would mean the simulated nodes and the calibrated simulator could drift
    apart silently."""
    b, n = profile["baseline_parameters"], profile["noise_parameters"]
    a = profile["anomaly_parameters"]

    # NOTE: the caller is responsible for having seeded the module-level `random`
    # ONCE for this node's whole series, and for having reset device_simulator's
    # persistent resting walk (`_rest_dc`, `_rest_drift_hz`) at the series start.
    #
    # This function used to reseed per call. That was a real defect, caught by
    # scripts/evaluate_simulator_validation.py rather than by reading the code:
    # `_synthetic_accel_window` deliberately CARRIES resting state between
    # windows -- the comment in device_simulator.py explains that independent
    # draws give ~zero temporal structure while a real board carries its
    # slowly-varying state forward. Reseeding every call restarted that walk on
    # every window, so the simulated nodes came out with lag-1 rms
    # autocorrelation ~0.05 against the real board's 0.587, destroying exactly
    # the sequential structure the LSTM-AE exists to model. It also made two
    # nodes' resting medians collide to 4 decimal places.
    window = sim._synthetic_accel_window(anomalous=anomalous)
    arr = np.asarray(window, dtype=np.float64)

    # Baseline offset + this node's noise scaling, applied to the raw window so
    # every derived feature moves consistently (offsetting rms alone would leave
    # crest_factor describing a window that no longer exists).
    centre = arr.mean()
    arr = centre + (arr - centre) * n["rms_sd_scale"]
    arr = arr + b["rms_offset"] + n.get("drift_amplitude", 0.0) * np.sin(drift_phase)

    if anomalous:
        # Attenuate or amplify the injected disturbance about the node's own
        # baseline, per profile. magnitude_scale < 1 makes the node HARDER.
        arr = centre + (arr - centre) * a["magnitude_scale"]

    feats = fe.extract_features(arr.tolist(), FEATURE_SAMPLE_RATE_HZ)
    feats["peak"] = round(feats["peak"] * b["peak_scale"], 4)
    feats["crest_factor"] = round(
        feats["peak"] / feats["rms"] if feats["rms"] > 1e-9 else 0.0, 4)
    feats["kurtosis"] = round(feats["kurtosis"] + b["kurtosis_offset"], 4)
    feats["dominant_freq"] = round(feats["dominant_freq"] * b["dominant_freq_scale"], 4)
    return feats


def _sim_switch_reading(profile: dict, rng: random.Random, anomalous: bool):
    """One SW-420-like reading for a simulated switch node.

    Generates a BINARY WINDOW and runs it through the real reference
    implementation, rather than sampling the four features directly. Sampling
    features independently would produce combinations a physical switch cannot
    produce -- e.g. a high trigger_rate with a burst longer than the gaps
    between triggers -- and the models would learn a normal region that includes
    physically impossible points."""
    b, n = profile["baseline_parameters"], profile["noise_parameters"]
    a = profile["anomaly_parameters"]

    rate = max(0.0, rng.gauss(b["rest_trigger_rate"], n["trigger_rate_sd"]))
    burst_ms = max(0.5, rng.gauss(b["rest_burst_ms"], n["burst_sd_ms"]))
    if anomalous:
        # A disturbed switch fires far more often and holds longer.
        rate = rate * (14.0 * a["magnitude_scale"]) + 12.0 * a["magnitude_scale"]
        burst_ms *= (2.5 * a["duration_scale"])

    window = [0] * SW420_WINDOW_SIZE
    duration_s = SW420_WINDOW_SIZE / SW420_SAMPLE_RATE_HZ
    n_events = np.random.default_rng(rng.randrange(2 ** 31)).poisson(rate * duration_s)
    burst_samples = max(1, int(burst_ms * SW420_SAMPLE_RATE_HZ / 1000.0))
    for _ in range(int(n_events)):
        start = rng.randrange(SW420_WINDOW_SIZE)
        # Jitter each closure's length; a real contact does not bounce identically.
        length = max(1, int(rng.gauss(burst_samples, max(1.0, burst_samples * 0.3))))
        for j in range(start, min(SW420_WINDOW_SIZE, start + length)):
            window[j] = 1
    return fes.extract_features(window, SW420_SAMPLE_RATE_HZ)


def _load_real_pool(split: str):
    """Real rows for the two physical nodes, keyed by (device_id, anomalous).

    Drawn only from sessions allocated to `split`. A real node with no capture
    in this split yields an empty pool and its rows are emitted as
    PENDING_REAL_HARDWARE_DATA."""
    pool = {(d, False): [] for d in REAL_NODES}
    pool.update({(d, True): [] for d in REAL_NODES})
    for path in splits.labelled_session_paths(split):
        with open(path) as f:
            session = json.load(f)
        sid = splits.session_id_of(path)
        for r in session:
            did = r.get("device_id")
            if did not in REAL_NODES:
                continue
            phase = r.get("phase") or ""
            if phase == "(pending mark)":
                continue
            anomalous = phase not in ("at_rest", "C1_both_normal")
            r["_session_id"] = sid
            pool[(did, anomalous)].append(r)
    return pool


def _in_event(tick, anomalous_nodes):
    """Alternating quiet / event blocks, so events have boundaries to count."""
    return (tick // BLOCK_TICKS) % 2 == 1 and bool(anomalous_nodes)


def _simulated_series(device_id, profile, scenario, split, anomalous_nodes, n_ticks):
    """One simulated node's ENTIRE tick series, generated contiguously.

    Contiguous and per-node, not interleaved tick-by-tick across nodes, because
    device_simulator carries persistent resting state in module-level globals
    (`_rest_dc`, `_rest_drift_hz`). Interleaving ten nodes through those globals
    would braid ten different devices' random walks into one, and reseeding per
    call to avoid that destroys the temporal structure the walk exists to
    provide. Generating each node's series in one pass, from one seed, gives
    each node an independent walk that actually persists."""
    random.seed(_seed_for(scenario, split, device_id))
    # Reset the shared walk to its calibrated centre so this node starts from
    # the documented resting point rather than inheriting the previous node's
    # final state.
    sim._rest_dc = sim.REST_DC_CENTRE
    sim._rest_drift_hz = sim.REST_DRIFT_HZ_CENTRE
    rng = random.Random(_seed_for(scenario, split, device_id) ^ 0x5EED)

    series = []
    for tick in range(n_ticks):
        is_anom = _in_event(tick, anomalous_nodes) and device_id in anomalous_nodes
        if profile["kind"] == "feature_vector":
            drift_phase = 2 * np.pi * tick / profile["noise_parameters"].get(
                "drift_period_ticks", 400)
            series.append(_sim_feature_vector_reading(profile, rng, is_anom, drift_phase))
        else:
            series.append(_sim_switch_reading(profile, rng, is_anom))
    return series


def build(scenario: str, split: str):
    anomalous_nodes = SCENARIOS[scenario]
    real_pool = _load_real_pool(split)
    rngs = {d: random.Random(_seed_for(scenario, split, d)) for d in NETWORK_NODES}
    n_ticks = TICKS[split]
    records, pending = [], {d: 0 for d in REAL_NODES}

    # Every simulated node's full series first, then assemble by tick.
    sim_series = {d: _simulated_series(d, SIMULATED_NODE_PROFILES[d], scenario, split,
                                       anomalous_nodes, n_ticks)
                  for d in NETWORK_NODES if d in SIMULATED_NODE_PROFILES}

    for tick in range(n_ticks):
        in_event = _in_event(tick, anomalous_nodes)
        event_id = f"{scenario}_{split}_evt{tick // (2 * BLOCK_TICKS):03d}" if in_event else None

        for device_id in NETWORK_NODES:
            is_anom = in_event and device_id in anomalous_nodes
            rng = rngs[device_id]
            base = {
                "tick": tick,
                "device_id": device_id,
                "session_id": f"NET_{scenario}_{split.upper()}_001",
                "network_experiment_id": GRAPH_TOPOLOGY["network_experiment_id"],
                "scenario": scenario,
                "split": split,
                "event_id": event_id,
                "condition": "PHYSICAL_ANOMALY" if is_anom else "NORMAL",
                "label": 0 if is_anom else 1,
                "auth_ok": True,
                "event_type": "coordinated" if is_anom else "normal",
                "simulated_flood": False,
            }

            if device_id in REAL_NODES:
                candidates = real_pool[(device_id, is_anom)]
                if not candidates:
                    pending[device_id] += 1
                    records.append({**base,
                                    "source_type": "PENDING_REAL_HARDWARE_DATA",
                                    "sensor_type": DEVICE_REGISTRY[device_id].get("sensor_type"),
                                    "reading": None})
                    continue
                src = candidates[rng.randrange(len(candidates))]
                records.append({**base,
                                "source_type": "REAL",
                                "sensor_type": DEVICE_REGISTRY[device_id].get("sensor_type", "MPU6050"),
                                "real_session_id": src.get("_session_id"),
                                "real_phase": src.get("phase"),
                                "label_source": src.get("label_source"),
                                "reading": src["reading"]})
            else:
                profile = SIMULATED_NODE_PROFILES[device_id]
                reading = sim_series[device_id][tick]
                records.append({**base,
                                "source_type": "SIMULATED",
                                "sensor_type": DEVICE_REGISTRY[device_id]["sensor_type"],
                                "simulation_profile": profile["variation"],
                                "seed": profile["seed"],
                                "reading": reading})
    return records, pending


def main():
    splits.assert_disjoint()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 78)
    print("10-NODE HYBRID NETWORK -- 2 REAL + 8 SIMULATED")
    print(f"  real      : {REAL_NODES}")
    print(f"  simulated : {len(SIMULATED_NODES)} nodes, profiles in config/simulated_nodes.json")
    print("=" * 78)

    for split in ("train", "validation", "test"):
        for scenario in SCENARIOS:
            records, pending = build(scenario, split)
            path = os.path.join(OUTPUT_DIR, f"network_{scenario}_{split}.json")
            with open(path, "w") as f:
                json.dump(records, f, indent=1)
            by_src = {}
            for r in records:
                by_src[r["source_type"]] = by_src.get(r["source_type"], 0) + 1
            anom = sum(1 for r in records if r["label"] == 0)
            print(f"{scenario:16s} {split:11s} {len(records):6d} rows  "
                  f"REAL={by_src.get('REAL', 0):5d} SIM={by_src.get('SIMULATED', 0):5d} "
                  f"PENDING={by_src.get('PENDING_REAL_HARDWARE_DATA', 0):5d}  anomalous={anom}")
            for d, n in pending.items():
                if n:
                    print(f"    ! {d}: {n} rows PENDING_REAL_HARDWARE_DATA -- no capture in the "
                          f"{split} split. Excluded from metrics, NOT filled in.")
    print(f"\nwritten to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
