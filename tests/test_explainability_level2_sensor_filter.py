"""Regression for mixed-sensor input to the MPU-only repair-set experiment."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import evaluate_explainability_level2 as level2


class TestMinimalRepairSetSensorBoundary(unittest.TestCase):
    def test_mpu_windows_exclude_sw420_rows(self):
        mpu = {
            "rms": 1.0, "peak": 0.1, "crest_factor": 0.1,
            "kurtosis": 2.0, "dominant_freq": 15.625,
        }
        switch = {
            "trigger_rate": 10.0, "duty_cycle": 0.1,
            "burst_max_ms": 4.0, "inter_event_cv": 0.2,
        }
        rows = []
        for tick in range(level2.LSTM_SEQ_LEN):
            rows.append(("mpu.json", {
                "tick": tick, "device_id": "esp32-vib-001",
                "phase": "sharp_impact", "reading": mpu,
            }))
            rows.append(("switch.json", {
                "tick": tick, "device_id": "esp32-vib-002",
                "phase": "sharp_impact", "reading": switch,
            }))

        windows = level2._mpu_disturbance_windows(rows)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].shape, (level2.LSTM_SEQ_LEN, 5))


if __name__ == "__main__":
    unittest.main()
