# Environment Specification

> **2026-09-05 audit update:** This is a recorded environment snapshot. Sampling and transport descriptions are corrected below; firmware TLS peer verification and a held-out Device 2 (VALIDATION/TEST) capture still require hardware work.
> Current evidence and limitations: RESULTS §0.13.17, §0.13.18.

Recorded so every timing and training number in `RESULTS.md` can be interpreted
and reproduced. Values marked `UNKNOWN` or `PENDING` are not guessed.

Captured: 2026-09-03. Re-verified live and extended with measured training
compute (§1a): 2026-09-05.

---

## 1. Host (gateway, training, evaluation)

| | |
|---|---|
| CPU | Intel(R) Core(TM) Ultra 7 255H — 16 cores / 16 logical processors (no hyperthreading) |
| RAM | 31.4 GB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU |
| VRAM | 8.55 GB |
| CUDA available | yes (`torch.cuda.is_available() == True`), CUDA 12.8 |
| OS | Windows 11, build 10.0.26200 |
| Python | 3.12.10 |

All latency figures in `results/latency/` were measured on this host with
`time.perf_counter_ns` (monotonic, nanosecond resolution), warm, with cold start
reported separately.

### 1a. Measured training compute (2026-09-05, this host, wall-clock)

Every script below ran `torch.cuda.is_available() == True` and used the GPU
above where the model is a `torch.nn.Module`; the two sklearn models (M1
`MLPClassifier`, M2 `HistGradientBoostingClassifier`) are CPU-only by
construction.

**Six-step deployed chain** (`scripts/train_*.py`, 20 feature-vector devices
after §0.13.18's network growth — `esp32-vib-001/002` + `esp32-sim-03..20`):

| Step | Wall-clock | Notes |
|---|---|---|
| `train_isolation_forest.py` | 6 s | CPU (sklearn), 20 per-device forests |
| `train_lstm_ae.py` | 17 s | GPU, 20 per-device models, 100 epochs each |
| `train_transformer.py` | 9 s | GPU, 2 per-device models (only `esp32-vib-001/002` have `training_session.json` rows — see §0.13.18), 150 epochs each |
| `train_gnn.py` | 64 s | GPU, single shared model, 150 epochs, 29,820 snapshots |
| `train_fusion_meta_learner.py` | 23 s | CPU (sklearn `LogisticRegression`), replays IF/LSTM-AE/GNN over VALIDATION |
| `train_adaptive_pdp.py` | 26 s | CPU, 20 episodes, replays the full two-score pipeline |
| **Total, six steps** | **~145 s (~2.4 min)** | |

**Cross-device network benchmark** (20-node graph, `scripts/evaluate_gnn_baselines.py` + `scripts/benchmark_crossdevice_models.py`):

| Script | Wall-clock | Notes |
|---|---|---|
| `evaluate_gnn_baselines.py` | 1,490 s (24.8 min), measured | GCN self-loop sweep (4 candidates) + 5 baselines, TRAIN 2,400 / VALIDATION+TEST 1,200 snapshots each at 20 nodes |
| `benchmark_crossdevice_models.py` | 1,264 s (21.1 min), measured | M1–M8 (8 architectures) + 5 structural probes (dilution/degree/peer-density/coordination/permutation, 400 trials/cell); M1 (`MLPClassifier`) and M2 (`HistGradientBoostingClassifier`) account for most of the wall-clock — CPU-bound sklearn fits over a 100-dim × 48,000-row TRAIN matrix, not the GPU torch models |
| **Total, both network-scale scripts** | **2,754 s (~46 min)** | |

Per-model training time and parameter count (`results/crossdevice_benchmark/metrics.json`, `train_time_ms_total`/`parameters`):

| Model | Train time | Epochs | Params | Inference (mean, single sample) |
|---|---|---|---|---|
| M1 concat_mlp | 9.4 s | 42 | 3,777 | 0.185 ms |
| M2 grad_boosting | 9.9 s | 200 | n/a (tree ensemble) | 7.707 ms |
| M3 deep_sets | 2.2 s | 300 | 2,121 | 1.223 ms |
| M4 gcn | 0.5 s | 150 | 1,217 | 0.784 ms |
| M5 gatv2 | 11.4 s | 300 | 945 | 2.698 ms |
| M6 set_transformer | 5.2 s | 300 | 2,609 | 2.137 ms |
| M7 np_st | 5.7 s | 300 | 3,778 | 1.733 ms |
| M8 set_transformer_mixed_n | 5.2 s | 300 | 2,609 | 2.166 ms |

The GCN's training cost is trivially small (0.5 s) despite being the weakest
performer at n=20 (§0.13.18.1) — its cost is not why it is not recommended.

## 2. Python packages

| Package | Version |
|---|---|
| torch | 2.11.0+cu128 |
| scikit-learn | 1.9.0 |
| numpy | 2.4.4 |
| shap | 0.52.0 |
| joblib | 1.5.3 |
| paho-mqtt | installed, version not exposed via `__version__` |

No `pyyaml` — deliberately. `docs/11` records the decision to keep configuration
in `src/config.py` rather than a YAML tree, so the node-profile and topology
files in `config/` are JSON.

No `torch-geometric` — the GCN layer is a hand-rolled matmul against a
normalised adjacency (`src/gnn_scorer.py`), because torch-geometric's compiled
extensions are version-locked and a common source of broken installs.

## 3. Device 01 — ESP32 + MPU6050

| | |
|---|---|
| Board | ESP32 (variant string UNKNOWN — not recorded at flash time) |
| CPU frequency | UNKNOWN — `machine.freq()` was not logged |
| Firmware | MicroPython, exact build UNKNOWN |
| Sensor | MPU6050, I²C address `0x68` (`AD0 → GND`) |
| Accelerometer range | default ±2 g (`AFS_SEL` not written) |
| Anti-alias filter | `MPU6050_DLPF_CFG = 1` → 184 Hz |
| Declared sample rate | 500 Hz nominal |
| Achieved sample rate | current paced 64 ms window at nominal 500 Hz; no precision clock characterization |
| Window size | 32 samples |
| Telemetry interval | 2 s |
| Wiring | `VCC→3.3V`, `GND→GND`, `SDA→GPIO21`, `SCL→GPIO22`, `AD0→GND` |

The earlier 26 ms unpaced loop against a declared 100 Hz is historical
(RESULTS 13.4c). Current firmware explicitly paces the 500 Hz sampling chain;
the reference and firmware share 32 samples and 15.625 Hz bin spacing. Exact
board clock and calibrated spectral accuracy remain unmeasured.

## 4. Device 02 — ESP32 + SW-420

| | |
|---|---|
| Board | ESP32 (variant UNKNOWN) |
| CPU frequency | UNKNOWN |
| Firmware | `firmware/main_sw420.py`, MicroPython build UNKNOWN |
| Sensor | SW-420 vibration switch, LM393 comparator, digital `D0` |
| Interface | single GPIO, `GPIO4`, `PULL_DOWN` |
| Sample representation | binary (0/1), not an amplitude |
| Sample rate | 1000 Hz |
| Window size | 256 samples (256 ms) |
| Telemetry interval | 1 s |
| Comparator threshold | onboard potentiometer — **setting is per-session and must be recorded**; see `firmware/HARDWARE_SETUP_SW420.md` §3 |
| Wiring | `VCC→3.3V`, `GND→GND`, `D0→GPIO4` |

**Captured sessions: ONE, TRAIN split only.** Session `20260905_162002`
(321 records, 8 marked intervals: `at_rest` ×4, `gentle_tap`, `moderate_shake`,
`tilt_rotate`, `sharp_impact`), allocated to TRAIN in
`data/splits/session_split.json`. At rest, all four features
(`trigger_rate`, `duty_cycle`, `burst_max_ms`, `inter_event_cv`) read exactly
`0.0` across all 140 at-rest rows — see `config/simulated_nodes.json`'s
`sw420_measured` for the full per-phase breakdown. **No VALIDATION or TEST
session exists yet** — every network record for this node in those splits
still carries `source_type: "PENDING_REAL_HARDWARE_DATA"` and is excluded
from metrics there. RESULTS §0.13.18.2 originally attributed a measured
M1/M2 isolated-anomaly recall collapse to this gap; §0.13.19 found the real
cause was a separate pending-node masking bug (now fixed) and the recall
collapse does not reproduce once fixed. The split gap remains real and
unresolved, but its previously-claimed concrete cost was not actually a
consequence of it — see §0.13.19 before citing §0.13.18.2.

**Physical limitation of this sensor.** It reports occurrence, not magnitude. A
disconnected `D0`, a mis-set potentiometer, and a genuinely still board are
indistinguishable from the feature vector alone — all four features read 0. The
MPU6050 has no such ambiguity (gravity alone is ~1 g, which is why its
`expected_ranges` carries an `rms` floor of 0.1). The check must therefore be
performed by a person at capture time.

## 5. Transport

| | |
|---|---|
| Broker | Mosquitto |
| Broker version | UNKNOWN — not recorded |
| MQTT | TLS on port 8883, auto-enabled once `certs/ca.crt` exists |
| Broker auth | username/password (`certs/mosquitto_passwd`) + topic ACLs (`certs/mosquitto_acl`) |
| CoAP | HTTPS POST over TLS on port 5684 (`coap_server.py` is a historical filename); not CoAP wire protocol |
| Application-layer auth | HMAC-SHA256 over a canonical JSON payload, per message |

## 6. Seeds

Centralised in `src/config.py` (`TRAINING_SEED`, overridable via `ZTCPS_SEED`)
and `src/splits.py` (`SIM_SESSION_SEEDS`). Each simulated node draws from its own
stream seeded by `sha256("scenario|split|device_id")` rather than an incrementing
counter — two nodes seeded *n* and *n+1* can produce visibly correlated streams,
which would undercut the claim that the eight simulated nodes are distinct.

| Stream | Seed |
|---|---|
| `TRAINING_SEED` (python, numpy, torch, sklearn) | 0 |
| `SIM_SESSION_TRAIN_001` | 42 |
| `SIM_SESSION_VAL_001` (fusion meta-learner) | 4242 |
| `SIM_SESSION_VAL_002` (thresholds + policy) | 4243 |
| `SIM_SESSION_TEST_001` | 999 |
| Simulated nodes 03–20 | 10003 … 10020 (`config/simulated_nodes.json`; 03–10 are the original 8, 11–20 added §0.13.18 to equalise sensor-type representation) |

Repeated training across seeds measures **optimization stability across random
initialization**. It is not evidence of hardware generalization and is not
described as such.
