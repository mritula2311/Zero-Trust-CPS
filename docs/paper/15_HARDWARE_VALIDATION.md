# Hardware validation

[VERIFIED: preserved captures and GCN-era offline replay] This audit did not collect new hardware data. The physical evidence is one MPU6050-equipped ESP32 and one SW-420-equipped ESP32, documented in [04](04_HARDWARE_DATA_AND_PROVENANCE.md). Exact flashed firmware versions, board variant and calibrated timing remain unknown.

The preserved MPU held-out evaluation ran [evaluate_real_hardware.py](../../scripts/evaluate_real_hardware.py) on TEST session 20260902_221217 using the then-current IF/LSTM/GCN/fusion artifacts. `evaluate_real_hardware.py` now requires an explicit `--relational-model {gcn,m6_deployed,m6_corrected}` pin (`src/relational_pin.py`) rather than reading ambient config, so a rerun no longer silently mixes lineages. It selects no threshold on TEST. Its warm-up rule excludes the first two temporal windows after relevant resets, leaving 42 scored readings from 116 raw rows. At-rest false alarms are 5/12; physical disturbances detected are 30/30. Printed Wilson intervals and phase medians are in [13 Q](13_RESULTS_MASTER_TABLES.md) and the [fresh log](../../results/final_verification/hardware_evaluation.log).

This is the strongest directly reproduced physical component-chain evidence, but the 41.7% resting false-alarm rate prevents a low-false-alarm hardware claim. The actions are hand-induced motion/fault phases. No cyberattack was performed in this held-out physical replay; it does not measure authenticated attack prevention or final policy enforcement. M6 fusion's performance on this evidence IS now established (2026-09-07, `--relational-model m6_corrected`): identical to GCN — 30/30 detection, 5/12 resting FP, no regression — see [13](13_RESULTS_MASTER_TABLES.md) O4/O5 and `results/m6_corrected_policy/hardware_regression.json`.

## SW-420 boundary

The first SW capture is 20260905_162002: 321 labelled records, including 140 all-zero at-rest feature vectors, allocated to TRAIN. There is no physical held-out SW validation/test session. Network test metrics exclude its pending rows. Simulated SW-like nodes do not close this physical gap. Local four-channel checkpoints and passing schema tests prove software compatibility, not generalization.

SW-420 measures comparator-trigger activity rather than acceleration magnitude. A disconnected input, inappropriate potentiometer setting and still sensor can share an all-zero reading. Require a recorded functional tap check and comparator setting in subsequent capture metadata. Do not use the heterogeneous second sensor to infer MPU manufacturing generalization.

## Evidence grades and next capture

Operator-marked sessions outrank reconstructed transcript labels. Four unpaced early MPU sessions remain historical and excluded. Future acquisition should record firmware commit/hash, MicroPython build, board variant, sample timing, sensor wiring, source tick/boot/run boundaries, operator labels, sensor attachment and timestamps. Capture distinct SW TRAIN/VALIDATION/TEST sessions and independent MPU sessions; preserve allocation before tuning. The current raw captures, labels and model checkpoints are retained unchanged.
