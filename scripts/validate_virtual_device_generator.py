"""
Validates src/virtual_device_generator.py before it is used to train M9.

Referenced by that module's own docstring ("falsified by
scripts/validate_virtual_device_generator.py") but never actually written --
this closes that gap. Five falsifiable checks, run per heterogeneity preset
(LOW/MEDIUM/HIGH from config/virtual_generator.json):

  1. Marginals     -- per-feature KS test, real residuals vs. generated
                       residuals (both detrended per-run/per-block, see below).
  2. Covariance    -- generated residual covariance vs. the real residual
                       covariance empirical_stats() measured (should match by
                       construction; this proves it does, not assumes it).
  3. Temporal      -- generated lag-1 autocorrelation vs. the real one.
  4. Discriminator -- a plain LogisticRegression trying to tell real residuals
                       from generated residuals apart. Near-chance accuracy is
                       the pass condition; anything higher means the noise
                       process leaves a detectable synthetic footprint.
  5. Heterogeneity -- confirms LOW < MEDIUM < HIGH cross-node rms spread, so
                       the presets actually order the way their names claim.

WHY RESIDUALS, NOT RAW VALUES, FOR CHECKS 1-4. A virtual node's persistent
scale/bias/drift IS deliberate heterogeneity (the whole point of this
generator), not noise -- comparing raw pooled multi-node output against the
one real device's raw distribution would fail by design, the same way
comparing two real devices with different mounting offsets would. What the
generator's docstring actually promises to reproduce is the CROSS-FEATURE
COVARIANCE and LAG-1 AUTOCORRELATION OF THE RESIDUAL (empirical_stats()'s own
target), so these checks detrend exactly the way empirical_stats() detrends
real data -- per independent run, own median removed -- before comparing.
Blocks are BLOCK_TICKS long (config/virtual_generator.json's block_ticks, the
length the generator is actually invoked at), not one long continuous run:
drift_period_ticks=400 would otherwise dominate a much-longer synthetic
window in a way no real captured run (average ~15 rows) was ever exposed to.

Also reports how often _finalise()'s rms clip engages per preset. This is a
measurement, not a pass/fail check: config/virtual_generator.json's HIGH
preset only spreads scale by +-5%, nowhere near the physical (0.1, 3.0) band,
so clipping is not expected to bind under ordinary heterogeneity. If this
number is ever non-trivial, that is the trigger to revisit the bound -- not a
guess made without it.

Run: python scripts/validate_virtual_device_generator.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
from scipy.stats import ks_2samp
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

import virtual_device_generator as vgen
from config import DEVICE_REGISTRY

SPLIT = "train"
N_BLOCK_REPEATS = 6  # cycle through the real run-length distribution this many
                     # times per preset, rather than picking one fixed length --
                     # real runs are short (avg ~15 ticks) and vary run to run;
                     # a fixed length the real side never had is itself a
                     # detectable signature having nothing to do with the noise
                     # model's realism.
N_NODES = 5          # distinct virtual devices, for the heterogeneity check
PRESETS = ("LOW", "MEDIUM", "HIGH")


def _rms_bounds():
    return DEVICE_REGISTRY[vgen.BASE_REAL_NODE]["expected_ranges"]["rms"]


def _real_residual_blocks(pool):
    """Same filter and per-run detrend empirical_stats() uses internally."""
    return [a for _, a in pool["rest"] if len(a) >= 3]


def _generated_residual_blocks(pool, stats, preset, seed0, real_lengths):
    """Independent virtual runs whose LENGTHS match the real run-length
    distribution (cycled N_BLOCK_REPEATS times), one fresh virtual node per
    block -- mirrors how empirical_stats() treats real data (many independent
    short runs of varying length), so neither a persistent per-node bias/scale
    nor an arbitrary fixed block length becomes a confound in what should be a
    noise-only comparison."""
    blocks, clipped = [], []
    lo, hi = _rms_bounds()
    b = 0
    for _ in range(N_BLOCK_REPEATS):
        for length in real_lengths:
            readings, _mask, _prov = vgen.generate_series(
                f"virt-block-{b:03d}", length, pool, stats, preset,
                "VALIDATE", SPLIT, seed0 + b, None)
            arr = np.array([[r[k] for k in vgen.FREE_FEATURES] for r in readings])
            blocks.append(arr)
            clipped.extend(r["rms"] <= lo + 1e-6 or r["rms"] >= hi - 1e-6 for r in readings)
            b += 1
    return blocks, np.asarray(clipped)


def _residual_array_and_lag1(blocks):
    resid = np.vstack([a - np.median(a, axis=0) for a in blocks])
    lag1 = np.zeros(resid.shape[1])
    for j in range(resid.shape[1]):
        num = den = 0.0
        for a in blocks:
            v = a[:, j] - np.median(a[:, j])
            num += float(np.dot(v[:-1], v[1:]))
            den += float(np.dot(v, v))
        lag1[j] = 0.0 if den <= 1e-12 else num / den
    return resid, lag1


def _node_rms_medians(pool, stats, preset, seed0):
    medians = []
    for node_id in vgen.node_ids(N_NODES):
        readings, _mask, _prov = vgen.generate_series(
            node_id, 120, pool, stats, preset, "VALIDATE", SPLIT,
            seed0, None)
        medians.append(float(np.median([r["rms"] for r in readings])))
    return np.asarray(medians)


def marginals(real_resid, gen_resid):
    ok = True
    for j, name in enumerate(vgen.FREE_FEATURES):
        stat, p = ks_2samp(real_resid[:, j], gen_resid[:, j])
        flag = "OK" if p > 0.01 else "DIVERGES"
        ok = ok and p > 0.01
        print(f"        {name:14s} KS={stat:.3f} p={p:.4f}  {flag}")
    return ok


def _to_corr(cov):
    """Covariance -> correlation: unit-free, entries in [-1, 1] regardless of
    a feature's own scale (dominant_freq's variance is ~1000x rms's, so
    comparing raw covariance entries with one threshold mostly measures
    dominant_freq and calls it "covariance structure")."""
    sd = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    return cov / np.outer(sd, sd)


def covariance(real_stats, gen_resid):
    real_corr = _to_corr(real_stats["residual_cov"])
    gen_corr = _to_corr(np.cov(gen_resid, rowvar=False, ddof=1))
    diff = np.abs(gen_corr - real_corr)
    off_diag = diff[~np.eye(len(diff), dtype=bool)]
    print(f"  [2] cross-feature correlation: max abs diff = {off_diag.max():.3f}, "
          f"mean = {off_diag.mean():.3f}")
    return off_diag.max() < 0.5


def temporal(real_stats, gen_lag1):
    diff = np.abs(gen_lag1 - real_stats["lag1"]).max()
    print(f"  [3] lag-1 autocorrelation: real={np.round(real_stats['lag1'], 3)} "
          f"generated={np.round(gen_lag1, 3)} max diff={diff:.3f}")
    return diff < 0.25


def discriminator(real_resid, gen_resid, rng):
    """Balanced 1:1 real-vs-generated, so chance is exactly 0.5 -- there are
    6x more generated rows than the 103 real rows total, and unbalanced
    classes make "always predict the majority class" look like a finding
    (618/(618+103) = 0.857, which is exactly what an earlier, unbalanced
    version of this check reported for all three presets identically)."""
    n = min(len(real_resid), len(gen_resid))
    real_sub = real_resid[rng.choice(len(real_resid), n, replace=False)]
    gen_sub = gen_resid[rng.choice(len(gen_resid), n, replace=False)]
    X = np.vstack([real_sub, gen_sub])
    y = np.concatenate([np.zeros(n), np.ones(n)])
    acc = float(cross_val_score(LogisticRegression(max_iter=1000), X, y, cv=5).mean())
    flag = "OK (near-chance)" if acc < 0.65 else "FAILS (detectable footprint)"
    print(f"  [4] real-vs-generated residual discriminator (balanced, n={n} each): "
          f"accuracy={acc:.3f}  {flag}")
    return acc < 0.65


def main():
    pool = vgen.load_real_pool(SPLIT)
    stats = vgen.empirical_stats(pool)
    real_blocks = _real_residual_blocks(pool)
    real_lengths = [len(a) for a in real_blocks]
    real_resid, _real_lag1 = _residual_array_and_lag1(real_blocks)
    config = vgen.load_config()

    print(f"Real resting rows: {sum(len(a) for a in real_blocks)} "
          f"({len(real_blocks)} runs, lengths {real_lengths}), split={SPLIT!r}\n")

    rng = np.random.default_rng(42)
    all_ok = True
    preset_medians = {}
    for i, preset_name in enumerate(PRESETS):
        preset = config["heterogeneity_presets"][preset_name]
        gen_blocks, clipped = _generated_residual_blocks(
            pool, stats, preset, seed0=1000 + i * 100, real_lengths=real_lengths)
        gen_resid, gen_lag1 = _residual_array_and_lag1(gen_blocks)
        preset_medians[preset_name] = _node_rms_medians(pool, stats, preset, seed0=2000 + i)

        n_rows = sum(len(a) for a in gen_blocks)
        print(f"--- {preset_name} preset ({n_rows} generated rows over {len(gen_blocks)} blocks) ---")
        print("  [1] marginals (detrended residuals):")
        all_ok = marginals(real_resid, gen_resid) and all_ok
        all_ok = covariance(stats, gen_resid) and all_ok
        all_ok = temporal(stats, gen_lag1) and all_ok
        all_ok = discriminator(real_resid, gen_resid, rng) and all_ok
        print(f"  [clip] rms clip engaged on {clipped.mean():.1%} of generated rows")
        print()

    print("--- [5] heterogeneity ordering (cross-node rms spread) ---")
    spreads = {p: float(np.std(preset_medians[p], ddof=1)) for p in PRESETS}
    for p in PRESETS:
        print(f"        {p:6s} spread={spreads[p]:.5f}")
    ordered = spreads["LOW"] < spreads["MEDIUM"] < spreads["HIGH"]
    print(f"        LOW < MEDIUM < HIGH: {'OK' if ordered else 'FAILS'}")
    all_ok = ordered and all_ok

    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
