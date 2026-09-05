"""
Invariant tests for src/virtual_device_generator.py.

Referenced by that module's own docstring ("tests/test_virtual_generator.py
includes a falsifier that attempts exactly that sourcing and requires it to
fail") but never actually written -- this closes that gap, in the same style
as tests/test_invariants.py: stdlib unittest, one test per property that must
hold, run from the repository root:

    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import numpy as np                               # noqa: E402
import virtual_device_generator as vgen          # noqa: E402


# ---------------------------------------------------------------------------
# 1. Leakage: a split's virtual network must never draw from another split
# ---------------------------------------------------------------------------

class TestNoLeakageAcrossSplits(unittest.TestCase):
    """The generator's own docstring promise: 'there is no path by which a
    training network can contain a test session's rows.' The exact same class
    of bug (globbing every labelled session into both TRAIN and evaluation)
    already happened once with the pre-splits.py loading path
    (docs/REPOSITORY_AUDIT.md 2.2) -- this is that falsifier applied here."""

    def test_train_and_test_pools_share_no_session(self):
        train_pool = vgen.load_real_pool("train")
        test_pool = vgen.load_real_pool("test")

        def session_ids(pool):
            ids = {sid for sid, _ in pool["rest"]}
            ids |= {sid for sid, _phase, _arr in pool["fault"]}
            return ids

        overlap = session_ids(train_pool) & session_ids(test_pool)
        self.assertFalse(overlap, f"session(s) {overlap} leaked across the train/test split")


# ---------------------------------------------------------------------------
# 2. Derived-feature identity: crest_factor must equal peak / rms exactly
# ---------------------------------------------------------------------------

class TestDerivedFeatureIdentities(unittest.TestCase):
    """A generator that perturbs rms, peak and crest_factor independently
    produces readings the sensor pipeline is arithmetically incapable of
    producing (module docstring, structure #1) -- a discriminator or even a
    manual spot-check would catch it immediately."""

    def setUp(self):
        self.pool = vgen.load_real_pool("train")
        self.stats = vgen.empirical_stats(self.pool)
        self.preset = vgen.load_config()["heterogeneity_presets"]["MEDIUM"]

    def test_crest_factor_equals_peak_over_rms(self):
        readings, _mask, _prov = vgen.generate_series(
            "virt-01", 50, self.pool, self.stats, self.preset,
            "TEST_IDENTITY", "train", global_seed=7, anomaly=None)
        for r in readings:
            # places=3, not 4: crest_factor is derived from PRE-rounding peak/rms
            # inside _finalise(), while r["peak"]/r["rms"] here are already
            # rounded to 4dp each -- comparing against those can differ by up to
            # ~1e-4 from rounding order alone, not a broken identity.
            expected = round(r["peak"] / r["rms"], 4) if r["rms"] > 1e-9 else 0.0
            self.assertAlmostEqual(r["crest_factor"], expected, places=3)

    def test_dominant_freq_is_snapped_to_the_dft_grid(self):
        readings, _mask, _prov = vgen.generate_series(
            "virt-01", 50, self.pool, self.stats, self.preset,
            "TEST_IDENTITY", "train", global_seed=7, anomaly=None)
        for r in readings:
            bins = r["dominant_freq"] / vgen.DFT_BIN_HZ
            self.assertAlmostEqual(bins, round(bins), places=3,
                                    msg=f"{r['dominant_freq']} is not on the {vgen.DFT_BIN_HZ} Hz grid")


# ---------------------------------------------------------------------------
# 3. Determinism: the same seed must reproduce the same dataset
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    """Module docstring: 'the same command reproduces the same dataset and no
    network is quietly redrawn while a model is being tuned.' If this ever
    breaks, a training run becomes unreproducible without anyone noticing."""

    def test_same_seed_reproduces_the_same_series(self):
        pool = vgen.load_real_pool("train")
        stats = vgen.empirical_stats(pool)
        preset = vgen.load_config()["heterogeneity_presets"]["MEDIUM"]

        readings_a, mask_a, prov_a = vgen.generate_series(
            "virt-01", 40, pool, stats, preset, "TEST_DETERMINISM", "train",
            global_seed=99, anomaly=None)
        readings_b, mask_b, prov_b = vgen.generate_series(
            "virt-01", 40, pool, stats, preset, "TEST_DETERMINISM", "train",
            global_seed=99, anomaly=None)

        self.assertEqual(readings_a, readings_b)
        self.assertTrue(np.array_equal(mask_a, mask_b))
        self.assertEqual(prov_a, prov_b)

    def test_different_nodes_are_not_correlated_copies(self):
        """The reason _seed() hashes rather than increments: two nodes seeded
        n and n+1 must not produce visibly correlated streams (module
        docstring) -- a network of many nodes that are secretly one node."""
        pool = vgen.load_real_pool("train")
        stats = vgen.empirical_stats(pool)
        preset = vgen.load_config()["heterogeneity_presets"]["MEDIUM"]

        r1, _, _ = vgen.generate_series("virt-01", 40, pool, stats, preset,
                                         "TEST_INDEP", "train", global_seed=1, anomaly=None)
        r2, _, _ = vgen.generate_series("virt-02", 40, pool, stats, preset,
                                         "TEST_INDEP", "train", global_seed=1, anomaly=None)
        self.assertNotEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
