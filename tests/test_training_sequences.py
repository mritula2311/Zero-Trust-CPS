"""Regression tests for contiguous normal time-series training records.

Run from the repository root:
    python -m unittest discover -s tests -p test_training_sequences.py -v

Fixtures are in memory; no captured data or model artifacts are accessed.
"""

import copy
import os
import sys
import unittest
from unittest.mock import patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import datasets


DEVICE = "esp32-vib-003"


def record(tick, **overrides):
    row = {
        "device_id": DEVICE,
        "tick": tick,
        "label": 1,
        "auth_ok": True,
        "reading": {
            "rms": 1.0,
            "peak": 2.0,
            "crest_factor": 2.0,
            "kurtosis": 3.0,
            "dominant_freq": 10.0,
        },
    }
    row.update(overrides)
    return row


class TestNormalTrainingSequences(unittest.TestCase):
    def test_source_tick_retains_gaps_hidden_by_merge_renumbering(self):
        rows = [record(0, source_tick=10), record(1, source_tick=11),
                record(2, source_tick=25), record(3, source_tick=26)]
        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [rows[:2], rows[2:]])

    def test_both_trainers_pass_only_within_run_windows_to_model(self):
        import torch
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import train_lstm_ae
        import train_transformer

        class CaptureAE(torch.nn.Module):
            def __init__(self, **kwargs):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.tensor(1.0))

            def forward(self, x):
                self.windows = x.detach().cpu().numpy()
                return x * self.weight

        rows = [record(t, device_id="esp32-vib-001", session_id=s)
                for s in ("one", "two") for t in range(10)]
        for module, factory, epochs in (
                (train_lstm_ae, "LSTMAutoencoder", "LSTM_EPOCHS"),
                (train_transformer, "TransformerAutoencoder", "TRANSFORMER_EPOCHS")):
            with self.subTest(trainer=module.__name__):
                model = CaptureAE()
                with patch.object(module, factory, return_value=model), \
                        patch.object(module, epochs, 0), \
                        patch.object(module.torch, "save"), \
                        patch.object(module.os, "makedirs"), \
                        patch("builtins.open", mock_open()), patch("builtins.print"):
                    self.assertTrue(module.train_one(rows, "esp32-vib-001"))
                self.assertEqual(model.windows.shape, (6, 8, 5))

    def test_scenario_blocks_with_restarting_ticks_never_braid(self):
        # The corpus loader concatenates independent files. Their scenario
        # order says nothing about time, and their tick counters all restart.
        expected = [
            [record(t, session_id=f"NET_{name}", scenario=name) for t in range(5)]
            for name in ("propagation", "all_normal", "localized")
        ]
        rows = [row for run in expected for row in run]

        actual = datasets.normal_sequences(rows, DEVICE)

        self.assertEqual(actual, expected)

    def test_each_metadata_change_is_a_boundary_even_with_consecutive_ticks(self):
        for field in ("session_id", "scenario", "phase"):
            with self.subTest(field=field):
                before = [record(t, **{field: "first"}) for t in (0, 1)]
                after = [record(t, **{field: "second"}) for t in (2, 3)]

                self.assertEqual(
                    datasets.normal_sequences(before + after, DEVICE),
                    [before, after],
                )

    def test_returning_to_previous_metadata_does_not_rejoin_an_old_run(self):
        rows = [record(0, phase="rest"), record(1, phase="event"), record(2, phase="rest")]

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [[row] for row in rows])

    def test_anomalous_or_invalid_target_record_interrupts_normal_readings(self):
        invalid_rows = [
            record(1, label=0),
            record(1, auth_ok=False),
            record(1, reading=None),
            record(None),
            record("invalid"),
        ]
        for missing in ("label", "auth_ok", "reading", "tick"):
            incomplete = record(1)
            del incomplete[missing]
            invalid_rows.append(incomplete)

        for invalid in invalid_rows:
            with self.subTest(invalid=invalid):
                before = record(0)
                # Deliberately consecutive to the last VALID row: filtering
                # before segmentation would hide the intervening invalid row.
                after = record(1)
                self.assertEqual(
                    datasets.normal_sequences([before, invalid, after], DEVICE),
                    [[before], [after]],
                )

    def test_tick_gap_splits_legacy_records_without_metadata(self):
        before = [record(t) for t in (10, 11, 12)]
        after = [record(t) for t in (14, 15, 16)]

        self.assertEqual(datasets.normal_sequences(before + after, DEVICE), [before, after])

    def test_duplicate_tick_starts_a_new_run(self):
        before = [record(0), record(1)]
        after = [record(1), record(2)]

        self.assertEqual(datasets.normal_sequences(before + after, DEVICE), [before, after])

    def test_reversed_ticks_are_not_sorted_into_false_continuity(self):
        before = [record(3), record(4)]
        after = [record(1), record(2)]

        self.assertEqual(datasets.normal_sequences(before + after, DEVICE), [before, after])

    def test_other_device_interleaving_does_not_break_a_valid_run(self):
        expected = [record(t) for t in range(4)]
        rows = []
        for row in expected:
            rows.extend([
                row,
                record(row["tick"], device_id="another-device", label=0, reading=None),
            ])

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [expected])

    def test_legacy_contiguous_run_and_singleton_remain_available(self):
        rows = [record(t) for t in range(30)]

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [rows])
        self.assertEqual(datasets.normal_sequences(rows[:1], DEVICE), [rows[:1]])

    def test_absent_metadata_and_explicit_none_share_legacy_run(self):
        rows = [record(0), record(1, session_id=None, scenario=None, phase=None), record(2)]

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [rows])

    def test_empty_or_no_eligible_device_returns_no_runs(self):
        for rows in ([], [record(0, device_id="another-device")], [record(0, label=0)]):
            with self.subTest(rows=rows):
                self.assertEqual(datasets.normal_sequences(rows, DEVICE), [])

    def test_segmentation_does_not_change_input_records_or_order(self):
        rows = [record(4, scenario="z"), record(1, scenario="a"), record(2, scenario="a")]
        original = copy.deepcopy(rows)

        datasets.normal_sequences(rows, DEVICE)

        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
