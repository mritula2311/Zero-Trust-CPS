# Environment Specification

> **2026-09-05 audit update:** This is a recorded environment snapshot. Sampling and transport descriptions are corrected below; firmware TLS peer verification and Device 2 captures still require hardware work.
> Current evidence and limitations: RESULTS §0.13.17.

Recorded so every timing and training number in `RESULTS.md` can be interpreted
and reproduced. Values marked `UNKNOWN` or `PENDING` are not guessed.

Captured: 2026-09-03.

---

## 1. Host (gateway, training, evaluation)

| | |
|---|---|
| CPU | Intel Core Ultra 7 255H |
| RAM | 31.4 GB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU |
| CUDA available | yes (`torch.cuda.is_available() == True`) |
| OS | Windows 11, build 10.0.26200 |
| Python | 3.12.10 |

All latency figures in `results/latency/` were measured on this host with
`time.perf_counter_ns` (monotonic, nanosecond resolution), warm, with cold start
reported separately.

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

**Captured sessions: PENDING.** No `esp32-vib-002` telemetry exists yet. Every
network record for this node currently carries
`source_type: "PENDING_REAL_HARDWARE_DATA"` and is excluded from all metrics.

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
| Simulated nodes 03–10 | 10003 … 10010 (`config/simulated_nodes.json`) |

Repeated training across seeds measures **optimization stability across random
initialization**. It is not evidence of hardware generalization and is not
described as such.
