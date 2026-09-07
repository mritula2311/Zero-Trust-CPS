"""Regression tests for the comparator-repair follow-up (2026-09-07):

1. scripts/train_adaptive_pdp.py must select its relational/fusion artifacts
   via an explicit src/relational_pin.py RelationalPin, never the ambient
   config.GNN_MODEL_PATH / config.FUSION_MODEL_PATH default (Part 3's fix --
   see that script's module docstring for the corruption this prevents).
2. relational_pin.verify_policy_lineage() must fail loudly on a missing or
   mismatched metadata sidecar (Part 3's mismatch check).
3. GNNScorer/SetTransformerScorer's active-neighbour window must be
   controllable by an injected deterministic clock, and repeated offline
   replays with the same seed/data/artifacts/clock must produce identical
   policy metrics (Part 4's determinism requirement).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import relational_pin as rp
from gnn_scorer import GNNScorer
from set_transformer_scorer import SetTransformerScorer


class TestClockInjection(unittest.TestCase):
    def test_gnnscorer_default_clock_is_walltime(self):
        scorer = GNNScorer()
        import time
        before = time.time()
        scorer.score("esp32-vib-001", 0.9, 0.9, 0.9)
        after = time.time()
        self.assertTrue(before - 1 <= scorer.last_seen[scorer._index["esp32-vib-001"]] <= after + 1)

    def test_gnnscorer_injected_clock_is_used_verbatim(self):
        box = {"t": 12345.0}
        scorer = GNNScorer(clock=lambda: box["t"])
        scorer.score("esp32-vib-001", 0.9, 0.9, 0.9)
        self.assertEqual(scorer.last_seen[scorer._index["esp32-vib-001"]], 12345.0)
        box["t"] = 99999.0
        scorer.score("sensor-002", 0.9, 0.9, 0.9)
        self.assertEqual(scorer.last_seen[scorer._index["sensor-002"]], 99999.0)

    def test_set_transformer_scorer_injected_clock_is_used_verbatim(self):
        box = {"t": 555.0}
        scorer = SetTransformerScorer(clock=lambda: box["t"])
        scorer.score("esp32-vib-001", 0.9, 0.9, 0.9)
        self.assertEqual(scorer.last_seen[scorer._index["esp32-vib-001"]], 555.0)

    def test_deterministic_clock_gives_identical_scores_across_repeated_runs(self):
        """Same fixed clock value + same inputs -> byte-identical output,
        across freshly constructed scorer instances -- the property offline
        replay training/evaluation depends on."""
        box = {"t": 1000.0}
        readings = [("esp32-vib-001", 0.9, 0.85, 0.7), ("sensor-002", 0.6, 0.6, 0.6)]
        results = []
        for _ in range(3):
            scorer = GNNScorer(clock=lambda: box["t"])
            results.append([scorer.score(*r) for r in readings])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])


class TestPolicyLineageMismatchCheck(unittest.TestCase):
    def test_verify_policy_lineage_raises_on_missing_qtable(self):
        with self.assertRaises(rp.ArtifactMismatchError):
            rp.verify_policy_lineage(rp.GCN, os.path.join(tempfile.gettempdir(), "does_not_exist_qtable.json"))

    def test_verify_policy_lineage_raises_on_missing_metadata_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            qtable_path = os.path.join(d, "qtable.json")
            with open(qtable_path, "w") as f:
                json.dump({}, f)
            with self.assertRaises(rp.ArtifactMismatchError):
                rp.verify_policy_lineage(rp.GCN, qtable_path)

    def test_verify_policy_lineage_raises_on_wrong_pin_name(self):
        with tempfile.TemporaryDirectory() as d:
            qtable_path = os.path.join(d, "qtable.json")
            meta_path = rp.policy_meta_path(qtable_path)
            with open(qtable_path, "w") as f:
                json.dump({}, f)
            with open(meta_path, "w") as f:
                json.dump({
                    "pin_name": "m6_deployed",  # deliberately wrong
                    "relational_checkpoint_sha256": rp.GCN.relational_checkpoint_sha256,
                    "fusion_model_sha256": rp.GCN.fusion_model_sha256,
                }, f)
            with self.assertRaises(rp.ArtifactMismatchError):
                rp.verify_policy_lineage(rp.GCN, qtable_path)

    def test_verify_policy_lineage_raises_on_stale_checkpoint_hash(self):
        with tempfile.TemporaryDirectory() as d:
            qtable_path = os.path.join(d, "qtable.json")
            meta_path = rp.policy_meta_path(qtable_path)
            with open(qtable_path, "w") as f:
                json.dump({}, f)
            with open(meta_path, "w") as f:
                json.dump({
                    "pin_name": "gcn",
                    "relational_checkpoint_sha256": "0" * 64,  # stale/wrong
                    "fusion_model_sha256": rp.GCN.fusion_model_sha256,
                }, f)
            with self.assertRaises(rp.ArtifactMismatchError):
                rp.verify_policy_lineage(rp.GCN, qtable_path)

    def test_verify_policy_lineage_passes_and_returns_metadata_on_agreement(self):
        with tempfile.TemporaryDirectory() as d:
            qtable_path = os.path.join(d, "qtable.json")
            meta_path = rp.policy_meta_path(qtable_path)
            with open(qtable_path, "w") as f:
                json.dump({}, f)
            expected = {
                "pin_name": "gcn",
                "relational_checkpoint_sha256": rp.GCN.relational_checkpoint_sha256,
                "fusion_model_sha256": rp.GCN.fusion_model_sha256,
            }
            with open(meta_path, "w") as f:
                json.dump(expected, f)
            meta = rp.verify_policy_lineage(rp.GCN, qtable_path)
            self.assertEqual(meta["pin_name"], "gcn")


class TestTrainAdaptivePdpUsesExplicitPin(unittest.TestCase):
    """Regression guard for the exact corruption this fix prevents: training
    must never fall back to bare GNNScorer()/FusionEngine() ambient
    construction (see train_adaptive_pdp.py module docstring)."""

    def test_build_training_triples_default_pin_is_gcn_not_ambient(self):
        import train_adaptive_pdp as tap
        # Default parameter value must be the explicit GCN pin object, not
        # left unset in a way that would fall through to bare GNNScorer().
        import inspect
        sig = inspect.signature(tap.build_training_triples)
        self.assertIs(sig.parameters["pin"].default, rp.GCN)

    def test_build_training_triples_accepts_m6_corrected_pin(self):
        import train_adaptive_pdp as tap
        with open(tap.SESSION_PATH) as f:
            records = json.load(f)
        small = [r for r in records if r["tick"] < 30]
        triples = tap.build_training_triples(small, pin=rp.M6_CORRECTED)
        self.assertIsInstance(triples, list)


class TestReproducibleOfflineReplay(unittest.TestCase):
    """Part 4's core claim: same seed + data + artifacts + clock -> identical
    triples, run to run. Uses a small record slice to keep the test fast."""

    def test_repeated_replays_produce_identical_triples(self):
        import train_adaptive_pdp as tap
        with open(tap.SESSION_PATH) as f:
            records = json.load(f)
        small = [r for r in records if r["tick"] < 40]
        first = tap.build_training_triples(small, pin=rp.GCN)
        second = tap.build_training_triples(small, pin=rp.GCN)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
