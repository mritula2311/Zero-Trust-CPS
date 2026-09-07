"""Explicit GCN-vs-M6 comparator artifact pinning must load correctly and
fail loudly on any mismatch -- see src/relational_pin.py's module docstring
for the bug this exists to prevent from silently recurring."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import relational_pin as rp
from gnn_scorer import GNNScorer
from set_transformer_scorer import SetTransformerScorer
from fusion_engine import FusionEngine


class TestKnownPinsLoadAndVerify(unittest.TestCase):
    def test_all_known_pins_verify(self):
        for pin in rp.KNOWN_PINS.values():
            pin.verify()  # must not raise

    def test_gcn_pin_loads_true_gcn_family(self):
        scorer = rp.GCN.load_relational_scorer()
        self.assertIsInstance(scorer, GNNScorer)
        self.assertTrue(scorer.is_trained())

    def test_m6_pins_load_set_transformer_family(self):
        for pin in (rp.M6_DEPLOYED, rp.M6_CORRECTED):
            scorer = pin.load_relational_scorer()
            self.assertIsInstance(scorer, SetTransformerScorer)
            self.assertTrue(scorer.is_trained())

    def test_each_pin_loads_a_working_fusion_engine(self):
        for pin in rp.KNOWN_PINS.values():
            fusion = pin.load_fusion_engine()
            self.assertIsInstance(fusion, FusionEngine)
            self.assertTrue(fusion.is_trained())

    def test_gcn_and_m6_fusion_coefficients_are_provably_different(self):
        """Regression guard for the exact bug this module fixes: before the
        fix, every 'GCN arm' silently read the M6-fitted fusion model, so
        this comparison would previously have found no difference at all."""
        gcn_coef = rp.GCN.load_fusion_engine().model.coef_[0]
        m6_coef = rp.M6_DEPLOYED.load_fusion_engine().model.coef_[0]
        self.assertFalse((gcn_coef == m6_coef).all())

    def test_m6_deployed_and_m6_corrected_are_distinct_checkpoints(self):
        self.assertNotEqual(
            rp.M6_DEPLOYED.relational_checkpoint_sha256,
            rp.M6_CORRECTED.relational_checkpoint_sha256,
        )
        deployed_coef = rp.M6_DEPLOYED.load_fusion_engine().model.coef_[0]
        corrected_coef = rp.M6_CORRECTED.load_fusion_engine().model.coef_[0]
        self.assertFalse((deployed_coef == corrected_coef).all())


class TestArtifactMismatchDetection(unittest.TestCase):
    def test_verify_raises_on_wrong_checkpoint_hash(self):
        tampered = rp.RelationalPin(
            name="tampered",
            family=rp.GCN.family,
            relational_checkpoint=rp.GCN.relational_checkpoint,
            relational_checkpoint_sha256="0" * 64,  # deliberately wrong
            fusion_model_path=rp.GCN.fusion_model_path,
            fusion_model_sha256=rp.GCN.fusion_model_sha256,
            fusion_background_path=rp.GCN.fusion_background_path,
            fusion_background_sha256=rp.GCN.fusion_background_sha256,
        )
        with self.assertRaises(rp.ArtifactMismatchError):
            tampered.verify()

    def test_verify_raises_on_wrong_fusion_hash(self):
        tampered = rp.RelationalPin(
            name="tampered",
            family=rp.M6_DEPLOYED.family,
            relational_checkpoint=rp.M6_DEPLOYED.relational_checkpoint,
            relational_checkpoint_sha256=rp.M6_DEPLOYED.relational_checkpoint_sha256,
            fusion_model_path=rp.M6_DEPLOYED.fusion_model_path,
            fusion_model_sha256="f" * 64,  # deliberately wrong
            fusion_background_path=rp.M6_DEPLOYED.fusion_background_path,
            fusion_background_sha256=rp.M6_DEPLOYED.fusion_background_sha256,
        )
        with self.assertRaises(rp.ArtifactMismatchError):
            tampered.verify()

    def test_verify_raises_on_missing_file(self):
        tampered = rp.RelationalPin(
            name="tampered",
            family=rp.GCN.family,
            relational_checkpoint=os.path.join(tempfile.gettempdir(), "does_not_exist.pt"),
            relational_checkpoint_sha256="a" * 64,
            fusion_model_path=rp.GCN.fusion_model_path,
            fusion_model_sha256=rp.GCN.fusion_model_sha256,
            fusion_background_path=rp.GCN.fusion_background_path,
            fusion_background_sha256=rp.GCN.fusion_background_sha256,
        )
        with self.assertRaises(rp.ArtifactMismatchError):
            tampered.verify()

    def test_load_relational_scorer_verifies_before_loading(self):
        tampered = rp.RelationalPin(
            name="tampered",
            family=rp.GCN.family,
            relational_checkpoint=rp.GCN.relational_checkpoint,
            relational_checkpoint_sha256="deadbeef" * 8,
            fusion_model_path=rp.GCN.fusion_model_path,
            fusion_model_sha256=rp.GCN.fusion_model_sha256,
            fusion_background_path=rp.GCN.fusion_background_path,
            fusion_background_sha256=rp.GCN.fusion_background_sha256,
        )
        with self.assertRaises(rp.ArtifactMismatchError):
            tampered.load_relational_scorer()


class TestExplicitConstructorOverridesBypassAmbientConfig(unittest.TestCase):
    """The fix's mechanism: an explicit path argument must actually change
    what gets loaded, not just be accepted and ignored."""

    def test_gnnscorer_explicit_checkpoint_overrides_default(self):
        from config import GNN_MODEL_PATH
        default_scorer = GNNScorer()
        explicit_scorer = GNNScorer(checkpoint_path=GNN_MODEL_PATH)
        self.assertEqual(default_scorer._checkpoint_path, explicit_scorer._checkpoint_path)

    def test_fusionengine_explicit_paths_load_gcn_backup_not_ambient_default(self):
        from config import FUSION_MODEL_PATH
        ambient = FusionEngine()
        pinned = rp.GCN.load_fusion_engine()
        # The ambient default is the M6-fitted model post-deployment; the
        # explicitly GCN-pinned engine must not match it.
        self.assertFalse((ambient.model.coef_[0] == pinned.model.coef_[0]).all())


if __name__ == "__main__":
    unittest.main()
