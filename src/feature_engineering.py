"""
Module 3 feature engineering (CLAUDE.md Section 5.1 / synopsis Section 4.3).

Computes the five standard vibration-analysis features every Module 3
scorer (rule-based, Isolation Forest, LSTM-AE, GNN) consumes for the real
device (`esp32-vib-001`). This module is used two places:

  - `firmware/main.py` computes the MicroPython-equivalent of these same
    formulas ON-DEVICE (see that file's docstring for why all 5 features
    are computed there rather than shipping a raw sample window over the
    signed MQTT channel) -- this module is the reference implementation
    the firmware's math is checked against.
  - `scripts/train_*.py` and `gateway.py` both import this module directly
    when working with simulated esp32-vib-001 telemetry (device_simulator.py
    generates raw sample windows and calls `extract_features()` here,
    exactly mirroring what the real firmware does on real hardware).

Kept dependency-light (numpy only) and pure-functional -- no state, easy
to unit-test each feature formula in isolation.
"""

import numpy as np

FEATURE_NAMES = ["rms", "peak", "crest_factor", "kurtosis", "dominant_freq"]


def rms(window: list[float]) -> float:
    """Root-mean-square of the windowed accel-magnitude samples -- overall
    vibration energy, the primary severity indicator."""
    arr = np.asarray(window, dtype=np.float64)
    return float(np.sqrt(np.mean(arr ** 2)))


def peak(window: list[float]) -> float:
    """Peak-to-peak amplitude -- shock events, impacts."""
    arr = np.asarray(window, dtype=np.float64)
    return float(np.max(arr) - np.min(arr))


def crest_factor(peak_value: float, rms_value: float) -> float:
    """Impulsiveness -- high crest factor with normal RMS suggests
    early-stage bearing damage, a classic predictive-maintenance signature."""
    return float(peak_value / rms_value) if rms_value > 1e-9 else 0.0


def kurtosis(window: list[float]) -> float:
    """Excess kurtosis (4th standardised moment) -- sensitive to sharp,
    infrequent spikes that RMS alone smooths over."""
    arr = np.asarray(window, dtype=np.float64)
    std = arr.std()
    if std < 1e-9:
        return 0.0
    return float(np.mean(((arr - arr.mean()) / std) ** 4) - 3.0)


def dominant_frequency(window: list[float], sample_rate_hz: float) -> float:
    """FFT of the windowed accel magnitude, peak-magnitude frequency bin --
    frequency-domain fault signatures (unbalance ~1x running speed,
    misalignment ~2x, bearing defects at characteristic frequencies).
    DC component (index 0) is excluded so a nonzero mean doesn't dominate."""
    arr = np.asarray(window, dtype=np.float64)
    arr = arr - arr.mean()
    spectrum = np.abs(np.fft.rfft(arr))
    freqs = np.fft.rfftfreq(len(arr), d=1.0 / sample_rate_hz)
    if len(freqs) <= 1:
        return 0.0
    spectrum[0] = 0.0
    return float(freqs[int(np.argmax(spectrum))])


def extract_features(window: list[float], sample_rate_hz: float) -> dict:
    """window: raw accel-magnitude samples from one on-device sampling
    window (32 samples at 100Hz on the real firmware). Returns a dict
    keyed by FEATURE_NAMES."""
    r = rms(window)
    p = peak(window)
    return {
        "rms": round(r, 4),
        "peak": round(p, 4),
        "crest_factor": round(crest_factor(p, r), 4),
        "kurtosis": round(kurtosis(window), 4),
        "dominant_freq": round(dominant_frequency(window, sample_rate_hz), 4),
    }


def feature_vector(features: dict) -> list[float]:
    """Fixed-order list, matching FEATURE_NAMES -- the shape every scorer
    (Isolation Forest, LSTM-AE input, rule-range checks) expects."""
    return [features[name] for name in FEATURE_NAMES]
