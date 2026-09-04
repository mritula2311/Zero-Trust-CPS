"""
Module 3 feature engineering for `esp32-vib-002` -- ESP32 + SW-420 digital
vibration switch. Reference implementation, exactly as `feature_engineering.py`
is for the MPU6050 node: `firmware/main_sw420.py` computes the MicroPython
equivalent of these formulas on-device and is checked against this file by a
differential test.

WHY THIS IS A SEPARATE MODULE AND NOT FIVE MORE COLUMNS.

The SW-420 is a comparator-gated vibration SWITCH, not an accelerometer. Its D0
line is binary: a spring-and-pin contact closes when the module is disturbed
past a potentiometer-set threshold, and an LM393 squares that into a logic
level. There is no amplitude, no axis, and no calibrated units.

Therefore:

    rms, peak, crest_factor, kurtosis, dominant_freq DO NOT EXIST for this
    device, and computing them from the 0/1 stream would produce five numbers
    that look like the MPU6050's and mean nothing physical. Root-mean-square of
    a bit sequence is a re-expression of its duty cycle; "dominant frequency"
    of a square wave whose edges are set by a mechanical contact bounce is a
    property of the comparator, not of the machine.

What a binary event stream genuinely supports is EVENT-STATISTICS: how often
the switch fires, what fraction of the window it is held closed, how long the
longest closure lasts, and how regular the gaps between firings are. Those four
are computed below and are the whole feature set for this device.

This is why the two-node experiment is HETEROGENEOUS-SENSOR validation and not
same-model replication -- the second node cannot reproduce the first node's
measurements even in principle. See docs/EXPERIMENTAL_PROTOCOL.md.

The models are per-device (config.isolation_forest_path(device_id) etc.), so a
4-feature device and a 5-feature device coexist without either model changing
shape. The GNN and the fusion meta-learner consume already-normalised [0,1]
sub-scores, not raw features, so both stay device-agnostic and shared.
"""

import numpy as np

FEATURE_NAMES_SW420 = ["trigger_rate", "duty_cycle", "burst_max_ms", "inter_event_cv"]


def _edges(window) -> np.ndarray:
    """Indices of RISING edges (0 -> 1). Rising rather than any transition so a
    single long closure counts as one event, not two."""
    arr = np.asarray(window, dtype=np.int8)
    if len(arr) < 2:
        return np.empty(0, dtype=np.int64)
    return np.flatnonzero((arr[1:] == 1) & (arr[:-1] == 0)) + 1


def trigger_rate(window, sample_rate_hz: float) -> float:
    """Rising edges per second. The primary activity indicator -- a resting
    board on a still desk produces 0."""
    duration_s = len(window) / sample_rate_hz
    if duration_s <= 0:
        return 0.0
    return float(len(_edges(window)) / duration_s)


def duty_cycle(window) -> float:
    """Fraction of the window with the switch closed, in [0, 1]. Distinguishes
    'many brief taps' from 'sustained shaking' at the same trigger_rate."""
    arr = np.asarray(window, dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(arr.mean())


def burst_max_ms(window, sample_rate_hz: float) -> float:
    """Longest contiguous closure, in milliseconds. The SW-420's analogue of a
    peak: a sharp impact holds the contact closed longer than a light tap."""
    arr = np.asarray(window, dtype=np.int8)
    if arr.size == 0 or not arr.any():
        return 0.0
    best = run = 0
    for v in arr:
        run = run + 1 if v else 0
        if run > best:
            best = run
    return float(1000.0 * best / sample_rate_hz)


def inter_event_cv(window, sample_rate_hz: float) -> float:
    """Coefficient of variation (std/mean) of the gaps between rising edges --
    regularity. A rotating imbalance fires at near-constant intervals (low CV);
    a hand tapping irregularly gives a high CV. Returns 0.0 when fewer than
    three edges leave no gap distribution to describe, which is a real
    'undefined here' and is why the models see a floor rather than a NaN."""
    e = _edges(window)
    if len(e) < 3:
        return 0.0
    gaps = np.diff(e).astype(np.float64) / sample_rate_hz
    m = gaps.mean()
    if m <= 1e-9:
        return 0.0
    return float(gaps.std() / m)


def extract_features(window, sample_rate_hz: float) -> dict:
    """window: raw 0/1 D0 samples from one on-device sampling window.
    Returns a dict keyed by FEATURE_NAMES_SW420."""
    return {
        "trigger_rate": round(trigger_rate(window, sample_rate_hz), 4),
        "duty_cycle": round(duty_cycle(window), 4),
        "burst_max_ms": round(burst_max_ms(window, sample_rate_hz), 4),
        "inter_event_cv": round(inter_event_cv(window, sample_rate_hz), 4),
    }


def feature_vector(features: dict) -> list[float]:
    """Fixed-order list matching FEATURE_NAMES_SW420."""
    return [features[name] for name in FEATURE_NAMES_SW420]


if __name__ == "__main__":
    # Self-check: three physically distinguishable stimuli must produce
    # distinguishable feature vectors, and a still board must read all zeros.
    rate = 1000.0
    still = [0] * 256
    regular = [1 if (i % 40) < 4 else 0 for i in range(256)]          # steady 25 Hz firing
    impact = [0] * 100 + [1] * 30 + [0] * 126                          # one long closure
    for name, w in (("still", still), ("regular", regular), ("impact", impact)):
        print(f"{name:8s} {extract_features(w, rate)}")
    assert extract_features(still, rate) == {
        "trigger_rate": 0.0, "duty_cycle": 0.0, "burst_max_ms": 0.0, "inter_event_cv": 0.0}
    f_reg, f_imp = extract_features(regular, rate), extract_features(impact, rate)
    assert f_reg["trigger_rate"] > f_imp["trigger_rate"], "steady firing must out-rate one impact"
    assert f_imp["burst_max_ms"] > f_reg["burst_max_ms"], "one long closure must hold longer"
    assert f_reg["inter_event_cv"] < 0.1, "evenly spaced edges must read as regular"
    print("self-check OK")
