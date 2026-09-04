"""Split-preserving empirical virtual-node generator.

Builds controlled CPS networks at n = 2, 3, 5, 10, 15 from the real telemetry
this project has actually captured, so that relational-model experiments are not
capped at the ten-node hybrid network. It is INFRASTRUCTURE for the next
experiment and is not itself a result: the presence of generated n=15 data is not
a finding, and nothing here licenses a claim about physical validation.

WHAT A VIRTUAL NODE IS. A contiguous block of REAL captured feature vectors from
the split being built, carrying the real cross-feature and temporal structure,
with a persistent per-device scale, bias, extra measurement noise and slow drift
applied on top:

    x_i(t) = A_i . x_base(t) + b_i + eps_i(t) + d_i(t)

Every row is marked source_type = REAL_DERIVED_VIRTUAL. A virtual node is not a
physical device and must never be counted as one, however real its source rows.

WHY NOT A LEARNED GENERATOR. A GAN/VAE/diffusion model would make synthetic-data
realism a second research problem, and its failures would be invisible: the
question "is this sample plausible" becomes unanswerable without another model.
Every transformation here is arithmetic that can be read, logged per row, and
falsified by scripts/validate_virtual_device_generator.py.

THREE STRUCTURES THAT ARE PRESERVED DELIBERATELY, each of which a naive
per-feature Gaussian perturbation destroys:

  1. crest_factor = peak / rms, EXACTLY, in all 429 real rows. It is derived
     after every transformation, never perturbed. Perturbing rms, peak and
     crest_factor independently produces readings the sensor pipeline is
     arithmetically incapable of producing.
  2. dominant_freq lives on the DFT grid, FEATURE_SAMPLE_RATE_HZ /
     FEATURE_WINDOW_SIZE = 15.625 Hz. All 22 distinct real values are multiples
     of it. Generated values are snapped back; a continuous dominant_freq is a
     synthetic artefact a discriminator finds immediately.
  3. Cross-feature covariance AND per-feature lag-1 autocorrelation, both
     measured from the split's own real rows. The extra per-device noise is a
     vector AR(1) whose stationary covariance reproduces the measured residual
     covariance and whose per-feature autocorrelation reproduces the measured
     lag-1 -- see _ar1_noise(). Independent Gaussian noise per feature per row
     would flatten both, and the LSTM-AE exists to model exactly the temporal
     structure it would flatten.

LEAKAGE. Generation happens AFTER the session-level split is fixed, and a
network built for a split draws base trajectories, residual statistics and fault
displacements only from that split's own sessions (src/splits.py). There is no
path by which a training network can contain a test session's rows: the pool is
loaded per split and never merged. tests/test_virtual_generator.py includes a
falsifier that attempts exactly that sourcing and requires it to fail.

DETERMINISM. Every random quantity derives from sha256 over
(scenario, split, virtual_node_id, base_session, global_seed), so the same
command reproduces the same dataset and no network is quietly redrawn while a
model is being tuned.
"""

import hashlib
import json
import os

import numpy as np

import splits
from config import (
    DATA_COLLECTED_DIR, FEATURE_NAMES, FEATURE_SAMPLE_RATE_HZ,
    FEATURE_WINDOW_SIZE, DEVICE_REGISTRY,
)

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_SRC_DIR, "..", "config", "virtual_generator.json")
OUTPUT_DIR = os.path.join(DATA_COLLECTED_DIR, "virtual")

SOURCE_TYPE = "REAL_DERIVED_VIRTUAL"

# The four coordinates the generator perturbs. crest_factor is absent because it
# is derived (peak / rms) rather than free -- see the module docstring.
FREE_FEATURES = ("rms", "peak", "kurtosis", "dominant_freq")

# Phases that count as resting. Everything else in a labelled session is an
# operator-marked physical disturbance. "(pending mark)" is neither and is
# dropped, as everywhere else in this repository: a sample outside a marked
# interval is discarded, not guessed at.
REST_PHASES = ("at_rest", "C1_both_normal")

DFT_BIN_HZ = FEATURE_SAMPLE_RATE_HZ / FEATURE_WINDOW_SIZE

# The physical node whose captures every virtual device is derived from. Named
# rather than inferred so that a second captured device cannot silently become
# a source without this constant changing.
BASE_REAL_NODE = "esp32-vib-001"


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def _seed(scenario: str, split: str, node_id: str, base_session: str,
          global_seed: int) -> int:
    """Deterministic and independent per (scenario, split, node, source, seed).

    Hashed rather than incremented for generate_network_data.py's reason: two
    nodes seeded n and n+1 produce visibly correlated streams, which is the one
    failure this whole file exists to avoid -- a network of fifteen nodes that
    are secretly one node."""
    key = f"{scenario}|{split}|{node_id}|{base_session}|{global_seed}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


# ---------------------------------------------------------------------------
# the real pool: base trajectories and fault displacements, per split
# ---------------------------------------------------------------------------

def load_real_pool(split: str) -> dict:
    """Real MPU6050 rows for `split`, grouped into CONTIGUOUS per-session runs.

    Contiguity is the point. A shuffled pool of rows would let the generator
    build base trajectories with no temporal structure at all, and the temporal
    structure is one of the three things this generator promises to preserve.
    Rows keep their file order, which is acquisition order.

    Returns {"rest": [(session_id, array), ...], "fault": [(session_id, phase,
    array), ...]}, arrays shaped (n_rows, len(FREE_FEATURES))."""
    rest, fault = [], []
    for path in splits.labelled_session_paths(split):
        with open(path) as f:
            session = json.load(f)
        sid = splits.session_id_of(path)
        run_rows, run_phase = [], None
        for r in session:
            if r.get("device_id") != BASE_REAL_NODE or not r.get("reading"):
                continue
            phase = r.get("phase") or ""
            if phase == "(pending mark)":
                continue
            if phase != run_phase:
                _flush_run(rest, fault, sid, run_phase, run_rows)
                run_rows, run_phase = [], phase
            run_rows.append([r["reading"][k] for k in FREE_FEATURES])
        _flush_run(rest, fault, sid, run_phase, run_rows)
    if not rest:
        raise ValueError(
            f"split {split!r} has no real resting rows for {BASE_REAL_NODE}; a "
            f"virtual network cannot be built from nothing, and filling it in "
            f"with plausible numbers is what this repository does not do")
    return {"rest": rest, "fault": fault}


def _flush_run(rest, fault, sid, phase, rows):
    if not rows or phase is None:
        return
    arr = np.asarray(rows, dtype=np.float64)
    if phase in REST_PHASES:
        rest.append((sid, arr))
    else:
        fault.append((sid, phase, arr))


def empirical_stats(pool: dict) -> dict:
    """The EMPIRICALLY SUPPORTED half of the generator's parameters.

    Everything here is measured from the split's own real resting rows:
    per-feature centre and spread, the cross-feature covariance of the
    within-run residuals, and each feature's lag-1 autocorrelation. Nothing here
    is a choice, and nothing here describes device-to-device variation -- that
    is the other half, and it lives in config/virtual_generator.json because it
    is not measurable with one physical device."""
    runs = [a for _, a in pool["rest"] if len(a) >= 3]
    stacked = np.vstack([a for _, a in pool["rest"]])
    centre = np.median(stacked, axis=0)
    spread = stacked.std(axis=0, ddof=1)

    # Residuals within a run, so a session-to-session offset is not counted as
    # measurement noise. Runs are short (tens of rows); subtracting each run's
    # own median is the same de-trending evaluate_real_hardware.py applies.
    resid = np.vstack([a - np.median(a, axis=0) for a in runs])
    cov = np.cov(resid, rowvar=False, ddof=1)

    # Lag-1 autocorrelation per feature, pooled over runs. Computed on residuals
    # for the same reason: the between-run offset would otherwise inflate it
    # towards 1 and the generated data would carry a temporal structure the real
    # board does not have.
    rho = np.zeros(len(FREE_FEATURES))
    for j in range(len(FREE_FEATURES)):
        num = den = 0.0
        for a in runs:
            v = a[:, j] - np.median(a[:, j])
            num += float(np.dot(v[:-1], v[1:]))
            den += float(np.dot(v, v))
        rho[j] = 0.0 if den <= 1e-12 else float(np.clip(num / den, -0.95, 0.95))

    return {"centre": centre, "spread": spread, "residual_cov": cov,
            "lag1": rho, "n_rest_rows": int(len(stacked)),
            "n_rest_runs": len(pool["rest"]), "n_fault_runs": len(pool["fault"])}


# ---------------------------------------------------------------------------
# per-device persistent identity
# ---------------------------------------------------------------------------

def device_params(node_id: str, scenario: str, split: str, base_session: str,
                  stats: dict, preset: dict, global_seed: int) -> dict:
    """A virtual device's PERSISTENT identity: scale, bias, noise, drift.

    Drawn once per (node, scenario, split, source session) and held for that
    node's whole series. Redrawing them per message would produce rows that are
    perturbations of a real device rather than a heterogeneous population of
    devices, and a relational model would see fifteen copies of one node with
    extra noise -- which is precisely the confound the mixed-cardinality
    experiment is meant to remove."""
    rng = np.random.default_rng(
        _seed(scenario, split, node_id, base_session, global_seed))
    k = len(FREE_FEATURES)
    s = preset["scale_spread"]
    return {
        "scale": rng.uniform(1.0 - s, 1.0 + s, k),
        "bias": rng.normal(0.0, preset["bias_sd_multiple"], k) * stats["spread"],
        "noise_fraction": float(preset["extra_noise_fraction"]),
        "drift_amplitude": rng.normal(0.0, preset["drift_sd_multiple"], k)
                           * stats["spread"],
        "drift_phase": rng.uniform(0.0, 2 * np.pi, k),
        "drift_period_ticks": float(preset["drift_period_ticks"]),
    }


def _ar1_noise(n_ticks: int, stats: dict, fraction: float, rng) -> np.ndarray:
    """Unit-specific measurement variation, correlated across features AND time.

    A vector AR(1) with diagonal coefficients rho (the measured per-feature
    lag-1) driven by multivariate innovations. The innovation covariance is set
    so the process's STATIONARY covariance equals the measured residual
    covariance scaled by `fraction`:

        Sigma_stat[i,j] = C[i,j] / (1 - rho_i rho_j)   =>   C = Sigma * (1 - rho rho^T)

    so the generated noise reproduces both the measured cross-feature covariance
    and the measured lag-1 autocorrelation instead of only one of them. It is
    ADDED to the real noise the base trajectory already carries, which is why
    `fraction` is a fraction: it represents the extra variation attributable to
    a different physical unit, not a replacement for the sensor noise."""
    rho = stats["lag1"]
    target = stats["residual_cov"] * (fraction ** 2)
    innov = target * (1.0 - np.outer(rho, rho))
    # Numerical symmetry, then a PSD floor: the empirical covariance of a few
    # hundred rows can carry a marginally negative eigenvalue, and a Cholesky on
    # it fails outright rather than degrading.
    innov = (innov + innov.T) / 2.0
    w, V = np.linalg.eigh(innov)
    L = V @ np.diag(np.sqrt(np.clip(w, 0.0, None)))

    out = np.zeros((n_ticks, len(rho)))
    # Start from the stationary distribution rather than from zero, or the first
    # few ticks of every device are quieter than the rest -- a seam an LSTM
    # window would sit across.
    tw, tV = np.linalg.eigh((target + target.T) / 2.0)
    out[0] = tV @ np.diag(np.sqrt(np.clip(tw, 0.0, None))) @ rng.standard_normal(len(rho))
    for t in range(1, n_ticks):
        out[t] = rho * out[t - 1] + L @ rng.standard_normal(len(rho))
    return out


# ---------------------------------------------------------------------------
# base trajectories and fault displacements
# ---------------------------------------------------------------------------

def _base_trajectory(pool: dict, n_ticks: int, rng) -> tuple:
    """A contiguous block of real resting rows, wrapped if the run is short.

    Wrapping rather than stitching several runs together: a stitch joins two
    captures taken at different times into a window that never existed, which is
    the defect merge_real_hardware_data.py's per-(session, phase) reset exists to
    prevent. Wrapping repeats a real run, which is honest and traceable -- the
    provenance records the source run and the offset."""
    sid, arr = pool["rest"][rng.integers(len(pool["rest"]))]
    start = int(rng.integers(len(arr)))
    idx = (start + np.arange(n_ticks)) % len(arr)
    return sid, start, arr[idx], idx


def fault_displacement(pool: dict, stats: dict, n_ticks: int, rng) -> tuple:
    """A REAL fault trajectory expressed as displacement from resting.

        delta_fault(t) = x_fault(t) - x_normal_reference

    Taken from a contiguous run of operator-marked fault rows in this split, so
    the joint physical behaviour of the measured disturbance survives: a real
    sharp_impact is brief impulses separated by quiet, and 29% of its samples are
    quiet (RESULTS.md, 'window-averaged error is not severity'). Synthesising an
    anomalous vector feature-by-feature would lose that and produce a fault shape
    no physical event has."""
    if not pool["fault"]:
        raise ValueError(
            "this split has no operator-marked fault rows, so an anomaly cannot "
            "be derived from a real displacement; refusing to invent one")
    sid, phase, arr = pool["fault"][rng.integers(len(pool["fault"]))]
    start = int(rng.integers(len(arr)))
    idx = (start + np.arange(n_ticks)) % len(arr)
    return sid, phase, arr[idx] - stats["centre"]


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def _finalise(x: np.ndarray) -> dict:
    """Free coordinates -> a physically consistent reading dict.

    Order matters: snap the frequency to the DFT grid, floor rms at the physical
    bound the rule check uses, THEN derive crest_factor from the peak and rms
    that actually survived. Deriving it first and clipping afterwards would emit
    a crest_factor that does not equal peak / rms."""
    rms, peak, kurt, freq = (float(v) for v in x)
    lo, hi = DEVICE_REGISTRY[BASE_REAL_NODE]["expected_ranges"]["rms"]
    rms = float(np.clip(rms, lo, hi))
    peak = max(0.0, peak)
    freq = float(np.clip(round(freq / DFT_BIN_HZ) * DFT_BIN_HZ,
                         0.0, FEATURE_SAMPLE_RATE_HZ / 2.0))
    return {
        "rms": round(rms, 4),
        "peak": round(peak, 4),
        "crest_factor": round(peak / rms if rms > 1e-9 else 0.0, 4),
        "kurtosis": round(kurt, 4),
        "dominant_freq": round(freq, 4),
    }


def node_ids(n: int) -> list:
    return [f"virt-{i:02d}" for i in range(1, n + 1)]


def generate_series(node_id: str, n_ticks: int, pool: dict, stats: dict,
                    preset: dict, scenario: str, split: str, global_seed: int,
                    anomaly: dict | None) -> tuple:
    """One virtual device's whole tick series, plus its provenance.

    `anomaly`, when present, carries the shared displacement for a coordinated
    event or this node's own for an isolated one, with a per-node severity and
    lag. Generated in one contiguous pass per node so the AR(1) noise and the
    drift are continuous across the series."""
    probe = np.random.default_rng(_seed(scenario, split, node_id, "base", global_seed))
    src_session, src_start, base, src_idx = _base_trajectory(pool, n_ticks, probe)

    p = device_params(node_id, scenario, split, src_session, stats, preset, global_seed)
    rng = np.random.default_rng(
        _seed(scenario, split, node_id, src_session, global_seed) ^ 0x5EED)

    t = np.arange(n_ticks)[:, None]
    drift = p["drift_amplitude"] * np.sin(
        2 * np.pi * t / p["drift_period_ticks"] + p["drift_phase"])
    noise = _ar1_noise(n_ticks, stats, p["noise_fraction"], rng)

    x = base * p["scale"] + p["bias"] + noise + drift

    anom_mask = np.zeros(n_ticks, dtype=bool)
    if anomaly is not None:
        delta, alpha, lag = anomaly["delta"], anomaly["alpha"], anomaly["lag"]
        for t0, t1 in anomaly["windows"]:
            a0, a1 = min(t0 + lag, n_ticks), min(t1 + lag, n_ticks)
            if a0 >= a1:
                continue
            x[a0:a1] += alpha * delta[a0 - t0 - lag + (t0 + lag - a0):a1 - a0 + (a0 - t0 - lag)] \
                if False else alpha * delta[(a0 - lag - t0):(a1 - lag - t0)]
            anom_mask[a0:a1] = True

    prov = {
        "source_session": src_session,
        "source_start_row": src_start,
        "source_rows": [int(i) for i in src_idx],
        "scale": [round(float(v), 6) for v in p["scale"]],
        "bias": [round(float(v), 6) for v in p["bias"]],
        "drift_amplitude": [round(float(v), 6) for v in p["drift_amplitude"]],
        "extra_noise_fraction": p["noise_fraction"],
        "generator_seed": _seed(scenario, split, node_id, src_session, global_seed),
    }
    return [_finalise(row) for row in x], anom_mask, prov
