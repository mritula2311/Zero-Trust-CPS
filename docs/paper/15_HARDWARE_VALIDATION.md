# Hardware validation

[VERIFIED: preserved captures and fresh offline replay] This audit did not collect new hardware data. The physical evidence is one MPU6050-equipped ESP32 and one SW-420-equipped ESP32, documented in [04](04_HARDWARE_DATA_AND_PROVENANCE.md). Exact flashed firmware versions, board variant and calibrated timing remain unknown.

The current MPU held-out evaluation runs [evaluate_real_hardware.py](../../scripts/evaluate_real_hardware.py) on TEST session 20260902_221217 using current IF/LSTM/GCN/fusion artifacts. It selects no threshold on TEST. Its warm-up rule excludes the first two temporal windows after relevant resets, leaving 42 scored readings from 116 raw rows. At-rest false alarms are 5/12; physical disturbances detected are 30/30. Printed Wilson intervals and phase medians are in [13 Q](13_RESULTS_MASTER_TABLES.md) and the [fresh log](../../results/final_verification/hardware_evaluation.log).

This is the strongest directly reproduced physical component-chain evidence, but the 41.7% resting false-alarm rate prevents a low-false-alarm hardware claim. The actions are hand-induced motion/fault phases. No cyberattack was performed in this held-out physical replay; it does not measure authenticated attack prevention or final policy enforcement. It also does not establish performance of M6 fusion.

## SW-420 boundary

The first SW capture is 20260905_162002: 321 labelled records, including 140 all-zero at-rest feature vectors, allocated to TRAIN. There is no physical held-out SW validation/test session. Network test metrics exclude its pending rows. Simulated SW-like nodes do not close this physical gap. Local four-channel checkpoints and passing schema tests prove software compatibility, not generalization.

SW-420 measures comparator-trigger activity rather than acceleration magnitude. A disconnected input, inappropriate potentiometer setting and still sensor can share an all-zero reading. Require a recorded functional tap check and comparator setting in subsequent capture metadata. Do not use the heterogeneous second sensor to infer MPU manufacturing generalization.

## Evidence grades and next capture

Operator-marked sessions outrank reconstructed transcript labels. Four unpaced early MPU sessions remain historical and excluded. Future acquisition should record firmware commit/hash, MicroPython build, board variant, sample timing, sensor wiring, source tick/boot/run boundaries, operator labels, sensor attachment and timestamps. Capture distinct SW TRAIN/VALIDATION/TEST sessions and independent MPU sessions; preserve allocation before tuning. The current raw captures, labels and model checkpoints are retained unchanged.
