"""The original three-device experiment must not change as registry grows."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_training_data import generate


class TestLegacyGeneration(unittest.TestCase):
    def test_registry_expansion_does_not_inject_research_or_pending_nodes(self):
        rows = generate(ticks=2, seed=42)
        self.assertEqual({r["device_id"] for r in rows},
                         {"esp32-vib-001", "sensor-002", "actuator-001"})
        self.assertEqual(len(rows), 6)

    def test_repeated_seed_resets_persistent_simulator_walk(self):
        first = generate(ticks=10, seed=42)
        generate(ticks=7, seed=999)
        self.assertEqual(generate(ticks=10, seed=42), first)


if __name__ == "__main__":
    unittest.main()
