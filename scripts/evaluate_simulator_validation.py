"""
Simulator validation (reviewer concern, brief section 35).

Before nodes 03-10 may be treated as useful network context, their telemetry
must be shown PLAUSIBLE relative to the real reference. Plausible, not
identical: eight nodes that reproduced esp32-vib-001's distribution exactly
would be eight clones, which is the thing the brief explicitly forbids. The
target is documented variation around a measured centre.

So this script reports two things and refuses to collapse them into one verdict:

  1. PLAUSIBILITY -- does each simulated node's resting distribution sit within
     a defensible envelope around the real measured one? A node whose resting
     rms is nowhere near a real board is not a stand-in for a device, it is
     noise wearing a device_id.

  2. DISTINCTNESS -- are the eight nodes actually different from each other and
     from the real node? Identical nodes would inflate any network-scale result
     while adding no information.

Reference statistics come from the TRAIN split only. Using validation or test
real sessions here would parameterise-and-then-evaluate against the same data.

Writes results/simulator_validation/.
"""

import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import SIMULATED_NODES, SIMULATED_NODE_PROFILES, REAL_NODES, DEVICE_REGISTRY
import datasets
import splits

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "simulator_validation")

# Envelope for "plausible": the simulated node's resting median must sit within
# this many multiples of the real cross-session SPREAD of the real median.
# Sized from spread, not from a single session's median -- the same reasoning as
# ADR-18, which was learned the hard way when centring on the newest median put
# the next live resting board at -4.0 sigma.
PLAUSIBILITY_K = 6.0


def real_reference():
    """Resting statistics of the real MPU6050 node, TRAIN split only."""
    rows = []
    for path in splits.labelled_session_paths("train"):
        with open(path) as f:
            rows += [r for r in json.load(f) if r.get("phase") == "at_rest"]
    out = {}
    for feat in ("rms", "peak", "crest_factor", "kurtosis", "dominant_freq"):
        v = [r["reading"][feat] for r in rows]
        out[feat] = {"n": len(v), "mean": st.mean(v), "sd": st.pstdev(v),
                     "median": st.median(v), "min": min(v), "max": max(v),
                     "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90))}
    v = [r["reading"]["rms"] for r in rows]
    m = st.mean(v)
    num = sum((v[i] - m) * (v[i - 1] - m) for i in range(1, len(v)))
    den = sum((x - m) ** 2 for x in v)
    out["rms"]["lag1_autocorr"] = num / den if den else 0.0
    return out


def simulated_stats(device_id):
    """Resting statistics of one simulated node, from NETWORK_NORMAL train."""
    rows = [r for r in datasets.network_records("NETWORK_NORMAL", "train")
            if r["device_id"] == device_id and r.get("reading")]
    if not rows:
        return None
    names = list(rows[0]["reading"])
    out = {"n": len(rows)}
    for feat in names:
        v = [r["reading"][feat] for r in rows]
        out[feat] = {"mean": st.mean(v), "sd": st.pstdev(v), "median": st.median(v),
                     "min": min(v), "max": max(v)}
    v = [r["reading"][names[0]] for r in rows]
    m = st.mean(v)
    num = sum((v[i] - m) * (v[i - 1] - m) for i in range(1, len(v)))
    den = sum((x - m) ** 2 for x in v)
    out["lag1_autocorr_first_feature"] = num / den if den else 0.0
    return out


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ref = real_reference()
    print("=" * 78)
    print("SIMULATOR VALIDATION -- are nodes 03-10 plausible, and are they distinct?")
    print("=" * 78)
    print(f"Reference: {REAL_NODES[0]} resting, TRAIN split only, n={ref['rms']['n']}")
    print(f"  rms  mean {ref['rms']['mean']:.4f}  sd {ref['rms']['sd']:.4f}  "
          f"range [{ref['rms']['min']:.4f}, {ref['rms']['max']:.4f}]  "
          f"lag-1 autocorr {ref['rms']['lag1_autocorr']:.4f}")
    print(f"  peak mean {ref['peak']['mean']:.4f}  sd {ref['peak']['sd']:.4f}\n")

    # The plausibility envelope is built from the real cross-session spread.
    spread = ref["rms"]["max"] - ref["rms"]["min"]
    lo = ref["rms"]["median"] - PLAUSIBILITY_K * spread
    hi = ref["rms"]["median"] + PLAUSIBILITY_K * spread
    print(f"Plausibility envelope for resting rms: [{lo:.4f}, {hi:.4f}] "
          f"({PLAUSIBILITY_K}x the real cross-session spread of {spread:.4f} g)\n")

    report, accel_medians = {}, {}
    print(f"{'node':15s} {'kind':17s} {'n':>5s} {'feat1 med':>10s} {'feat1 sd':>9s} "
          f"{'autocorr':>9s}  verdict")
    print("-" * 78)
    for device_id in SIMULATED_NODES:
        s = simulated_stats(device_id)
        kind = SIMULATED_NODE_PROFILES[device_id]["kind"]
        if s is None:
            print(f"{device_id:15s} {kind:17s}  no data")
            continue
        first = [k for k in s if k not in ("n", "lag1_autocorr_first_feature")][0]
        med, sd = s[first]["median"], s[first]["sd"]
        if kind == "feature_vector":
            ok = lo <= s["rms"]["median"] <= hi
            accel_medians[device_id] = s["rms"]["median"]
            verdict = "PLAUSIBLE" if ok else "OUT OF ENVELOPE"
        else:
            # No real SW-420 telemetry exists yet, so there is no measured
            # reference to compare against. Saying "plausible" would be
            # asserting agreement with data that does not exist.
            verdict = "UNVALIDATED (no real SW-420 capture yet)"
        report[device_id] = {"kind": kind, "stats": s, "verdict": verdict}
        print(f"{device_id:15s} {kind:17s} {s['n']:>5d} {med:>10.4f} {sd:>9.4f} "
              f"{s['lag1_autocorr_first_feature']:>9.4f}  {verdict}")

    # --- distinctness -----------------------------------------------------
    print()
    print("DISTINCTNESS -- the eight nodes must not be clones of each other.")
    meds = sorted(accel_medians.items(), key=lambda kv: kv[1])
    closest = min(((a, b, abs(x - y)) for (a, x) in meds for (b, y) in meds if a < b),
                  key=lambda t: t[2])
    print(f"  accelerometer-type resting rms medians span "
          f"[{meds[0][1]:.4f}, {meds[-1][1]:.4f}] across {len(meds)} nodes")
    print(f"  closest pair: {closest[0]} vs {closest[1]}, difference {closest[2]:.4f} g "
          f"(real within-session sd is {ref['rms']['sd']:.4f} g)")
    distinct = closest[2] > 0.25 * ref["rms"]["sd"]
    print(f"  verdict: {'DISTINCT' if distinct else 'TOO SIMILAR -- profiles need widening'}")

    print()
    print("LIMITATIONS, stated rather than implied:")
    print("  - The two SW-420-type simulated nodes are UNVALIDATED. No real")
    print("    SW-420 telemetry exists, so their profiles are derived from the")
    print("    sensor's documented behaviour, not from measurement. Re-derive")
    print("    and regenerate once esp32-vib-002 sessions exist.")
    print("  - Plausibility here means 'resting distribution sits in a defensible")
    print("    envelope around one real device'. It is not evidence that a")
    print("    simulated node behaves like a real one under FAULT, which no")
    print("    amount of resting data can establish.")
    print("  - The reference is ONE physical device. A six-fold spread envelope")
    print("    around a single board is a weak constraint, and is reported as such.")

    out = {"reference": {"device": REAL_NODES[0], "split": "train", "stats": ref},
           "plausibility_envelope_rms": {"low": lo, "high": hi, "k": PLAUSIBILITY_K,
                                         "basis": "real cross-session spread"},
           "nodes": report,
           "distinctness": {"closest_pair": [closest[0], closest[1]],
                            "difference_g": closest[2],
                            "real_within_session_sd_g": ref["rms"]["sd"],
                            "verdict": "DISTINCT" if distinct else "TOO_SIMILAR"},
           "limitations": [
               "SW-420-type simulated nodes are UNVALIDATED -- no real SW-420 capture exists",
               "plausibility covers resting behaviour only, not fault behaviour",
               "the reference is a single physical device"]}
    with open(os.path.join(RESULTS_DIR, "metrics.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nwritten to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
