# Independent hardware, temporal-split, feature, and virtual-generator review

**Scope.** Read-only inspection of raw capture JSON, the split manifest/loaders, generated network files, local-model trainers, firmware/gateway signing code, feature implementations, virtual generator, validation script, and available result artifacts. I ran only lightweight readers/counts; no model training or data generation. Branch observed: `<historical-review-branch>`.

## Verdict

**Request changes to evidence wording and one training-data design before strong hardware-generalization claims.** Physical-session allocation is disjoint and the MPU6050 has distinct train/validation/test captures. The SW-420 has only one train capture; all validation/test SW-420 network rows are PENDING. Moreover, its local models train on 1,800 normal network rows resampled from the same 140 at-rest capture rows in addition to those 140 originals. That is valid augmentation if disclosed, but it is not 1,940 independent hardware observations. The empirical virtual generator is technically coherent but has no checked-in validation-result artifact, and its validation statistics are internal goodness-of-fit checks on the same training capture, not external device validation.

## Raw physical capture inventory and split

Source of allocation: `data/splits/session_split.json`; enforcement/loading: `src/splits.py:56-142`. Counts below come from the JSON arrays themselves.

| Session file | Device | Rows | Phase counts | Allocation / evidence grade |
|---|---|---:|---|---|
| `hardware_session_20260902_102448_labelled.json` | esp32-vib-001 | 114 | at_rest 44; gentle_tap 16; moderate_shake 14; sharp_impact 16; tilt_rotate 24 | TRAIN; transcript reconstruction |
| `hardware_session_20260902_171313_labelled.json` | esp32-vib-001 | 152 | at_rest 59; gentle_tap 28; moderate_shake 33; tilt_rotate 32 | TRAIN; operator mark |
| `hardware_session_20260902_173108_labelled.json` | esp32-vib-001 | 47 | at_rest 18; sharp_impact 29 | VALIDATION; operator mark |
| `hardware_session_20260902_221217_labelled.json` | esp32-vib-001 | 116 | pending mark 1; at_rest 55; fault_weak 37; fault_strong 23 | TEST; operator mark |
| `hardware_session_20260905_162002_labelled.json` | esp32-vib-002 | 321 | at_rest 140; gentle_tap 43; moderate_shake 52; sharp_impact 35; tilt_rotate 51 | TRAIN only; operator mark |

Four older unlabelled MPU6050 sessions are explicitly excluded: `20260901_112219` (56 rows), `113103` (95), `115152` (102), and `125402` (127), because they used the old acquisition timing/frequency axis. They must not be counted as training or evaluation evidence.

**Required claim boundary:** esp32-vib-001 has 103 raw at-rest TRAIN rows, 18 validation at-rest rows, and 55 test at-rest rows (plus distinct marked disturbances). esp32-vib-002 has 140 raw at-rest TRAIN rows and zero physical validation/test rows. No held-out physical SW-420 performance can be reported.

## Exact 20-node identity, modality, and provenance

The checked `network_NETWORK_NORMAL_train.json` contains these exact contracts; all four train scenario files contain 600 rows/node. Validation and test contain 300 rows/node/scenario.

| IDs | Count | Modality / feature order | Train provenance | Validation/test provenance |
|---|---:|---|---|---|
| `esp32-vib-001` | 1 | MPU6050: rms, peak, crest_factor, kurtosis, dominant_freq | REAL | REAL |
| `esp32-vib-002` | 1 | SW-420: trigger_rate, duty_cycle, burst_max_ms, inter_event_cv | REAL | PENDING_REAL_HARDWARE_DATA |
| `esp32-sim-03,04,05,06,08,09,11,14,18` | 9 | MPU6050-like, same five-feature order | SIMULATED | SIMULATED |
| `esp32-sim-07,10,12,13,15,16,17,19,20` | 9 | SW-420-like, same four-feature order | SIMULATED | SIMULATED |

Every scenario/split file has exactly 20 IDs. Each train file has 12,000 rows: 1,200 REAL and 10,800 SIMULATED. Each validation/test file has 6,000 rows: 300 REAL (MPU6050), 300 PENDING (SW-420), and 5,400 SIMULATED. Across four scenarios that is 48,000 train rows and 24,000 rows in each held-out split, but the physical observations are sampled with replacement from the small session pools (`scripts/generate_network_data.py:167-189,227-287`), so row totals are not unique hardware measurements.

## Actionable findings

1. **Required: disclose SW-420 resampling in local-model training or remove the duplicated network-derived rows from its local fit.** `datasets.training_records()` includes `training_session.json`, then every non-primary node from all `network_*_train.json` files (`src/datasets.py:36-51`). For esp32-vib-002 this produces 2,540 records: 140 raw rows already merged into `training_session.json` plus 2,400 network rows sampled from the same single capture. Normal filtering leaves 1,940 records: 140 raw at-rest and 1,800 resampled normal rows. Isolation Forest fits all 1,940 as if rows (`train_isolation_forest.py:39-68`); sequence models form 1,758 overlapping windows. This heavily weights duplicated capture values and makes nominal sample size misleading. Prefer a per-device raw-session training source for physical devices, or explicitly tag augmented rows and report unique source-session/source-row support.

2. **Required: state that SW-420 held-out evidence is synthetic only.** In every network validation/test scenario, exactly 300 esp32-vib-002 rows are PENDING and excluded by benchmark masking. The nine SW-420-like simulated nodes remain scoreable, but they cannot validate physical SW-420 generalization. The older `results/simulator_validation/metrics.json` even labels SW-like nodes “UNVALIDATED (no real SW-420 capture yet)”; that text is historically stale because a capture now exists, yet the underlying limitation remains: the capture is train-only and the artifact predates it.

3. **Required: do not cite a virtual-generator validation result that is absent.** `scripts/validate_virtual_device_generator.py` exists and exits pass/fail, but `rg --files results` finds no generator-validation JSON/log artifact. The full-suite log proves unit invariants such as determinism, DFT snapping, derived crest factor, and session non-overlap; it does not contain the script's KS/covariance/temporal/discriminator/heterogeneity output. Run the validation separately and persist inputs, package versions, per-preset statistics, thresholds, and final status before making a “validated generator” claim.

4. **Required: qualify the validation statistics if/when recorded.** The generator estimates covariance, lag-1, centre, spread, and fault displacement from the same split-specific physical capture used to create virtual rows (`src/virtual_device_generator.py:114-194,266-298`). The validation script then compares detrended generated residuals with those same train residuals (`validate_virtual_device_generator.py:59-67,74-205`). KS p-values assume independent samples but these are temporal rows within short runs; five-fold row-level discriminator CV also splits correlated rows rather than holding out sessions/blocks. These are implementation/goodness-of-fit diagnostics, not evidence of new-device realism. Use block/session grouped CV and independent device captures when available; report effect sizes rather than treating `p>0.01` as proof of equality.

5. **Required: distinguish temporal continuity from independent support.** `normal_sequences()` correctly breaks on `(session_id, scenario, phase)` or any `source_tick` discontinuity and filters only authenticated normal rows (`src/datasets.py:62-86`). However, actual TRAIN construction yields for esp32-vib-001 4,070 eligible normal records in 1,046 runs, but only 244 length-8 windows because most synthetic `training_session.json` records are interleaved into runs of median length 3. For esp32-vib-002 it yields 1,940 records in 26 runs and 1,758 windows, dominated by two 600-tick resampled scenario runs plus twenty 30-tick blocks. Report these actual window counts, not merely normal-row counts. Consider ordering the primary session by device/session before sequence extraction or storing contiguous per-device sessions, because the current interleaving discards most primary-device temporal training support.

6. **Consider: refresh stale executable comments/tests around MPU6050 sampling.** Firmware currently declares 500 Hz/32 samples (`firmware/main.py:101-131`) and config is intended to match, while `feature_engineering.extract_features` still says “32 samples at 100Hz” (`src/feature_engineering.py:71-74`) and `TestFirmwareReferenceEquivalence` exercises the reference at 100 Hz (`tests/test_invariants.py:215-236`). The feature arithmetic generalizes, and separate sampling-contract tests may cover constants, but this stale test fixture/documentation makes a future rate mismatch harder to diagnose. Parameterize the equivalence test from config/firmware constants.

7. **Consider: add an end-to-end SW-420 canonical-HMAC test.** Both firmware implementations use the correct manual HMAC-SHA256 and sorted-key Python-default JSON spacing (`firmware/main.py:403-460`; `firmware/main_sw420.py:236-287`), matching gateway `json.dumps(payload, sort_keys=True)` and `hmac.compare_digest` (`src/gateway.py:135-156`). Existing canonicalization tests construct MPU6050 payloads (`tests/test_invariants.py:248-302`), while SW-420 tests cover feature maths and acquisition constants (`:944-1031`). A build-and-sign SW payload checked through `gateway.verify_signature` would lock the four-field shape and optional nonce path end to end.

## Feature contracts and firmware compatibility

The raw feature spaces are deliberately modality-specific:

- MPU6050 is five-dimensional in the exact order `rms, peak, crest_factor, kurtosis, dominant_freq` (`src/feature_engineering.py:24,86-105`). Firmware returns exactly those named fields (`firmware/main.py:321-329`) and signs them with boot/sequence/time/device identity (`:443-459`). Acquisition is 500 Hz × 32 samples, a 64 ms window and 15.625 Hz DFT bins (`:101-131`).
- SW-420 is four-dimensional in the exact order `trigger_rate, duty_cycle, burst_max_ms, inter_event_cv` (`src/feature_engineering_sw420.py:41,101-114`). Firmware samples 1,000 Hz × 256 binary values (`firmware/main_sw420.py:61-67,158-180`), computes those four features (`:183-233`), and signs them with the same identity/replay fields (`:268-287`).
- `feature_engineering.feature_vector()` dispatches from the reading key `trigger_rate`; the feature-name sets are currently disjoint and a test enforces that (`src/feature_engineering.py:86-105`; `tests/test_invariants.py:1025-1031`). This works for two modalities but is a fragile public boundary for a third modality with overlapping keys; device-registry dispatch would be safer.
- Local LSTM/Transformer input dimension is derived from `raw.shape[1]`, and metadata saves `feature_names`, avoiding a hard-coded five-feature model (`train_lstm_ae.py:54-75,95-104`; `train_transformer.py:63-82,110-119`).

HMAC compatibility is byte-sensitive but consistent in source: firmware sorts keys and uses `", "` / `": "`, matching CPython `json.dumps(..., sort_keys=True)` defaults; float formatting retains `.0` where required. The gateway rejects missing/placeholder secrets and uses constant-time digest comparison. The canonicalization invariant test covers 200 generated MPU payloads plus the optional nonce. Hardware captures themselves do not prove HMAC correctness because labelled files contain processed payload/readings, not retained canonical bytes plus signature verdict traces.

## Temporal and calibration separation

Physical session membership is disjoint by manifest, and unallocated sessions do not default into TRAIN (`src/splits.py:89-123`). Local IF/LSTM/Transformer trainers call `datasets.training_records()` and never read validation/test network files. The benchmark threshold sweep uses validation and reports test separately.

There are still three different meanings of “calibration” that should be named:

| Stage | Data used | What is fitted | Limitation |
|---|---|---|---|
| Local LSTM/Transformer preprocessing and score scaling | local TRAIN normal rows/windows | per-device mean/std and reconstruction-error mean/std | reconstruction baseline is in-sample on the same fitted windows (`train_lstm_ae.py:54-103`; `train_transformer.py:63-118`) |
| Isolation Forest score mapping | local TRAIN normals | training-normal raw-score median maps to 0.9 | also in-sample, though unsupervised (`train_isolation_forest.py:53-68`) |
| Fusion meta learner | `validation_session.json`, simulated seed 4242 | supervised fusion coefficients | distinct from base training, but the physical validation capture is not what this file contains (`train_fusion_meta_learner.py:13-21,50`) |
| Policy learner | `validation_policy_session.json`, simulated seed 4243 | adaptive policy/Q table | separate from fusion fit (`train_adaptive_pdp.py:21-22,54`) |
| M1–M9/GNN decision threshold | network validation split | max-F1 threshold/self-loop selection | test frozen afterward |

`training_session.json` contains 15,493 rows: 15,250 SIMULATED and only 243 REAL (103 MPU at-rest + 140 SW at-rest). `validation_session.json` and `validation_policy_session.json` each contain 3,050 SIMULATED rows and no REAL rows. `test_session.json` has 3,050 legacy rows without a `source_type` field. Thus “held-out calibration” is correct at session/seed level for the fusion/policy chain, but it is simulated calibration; do not imply it is physical cross-session calibration.

## Virtual generator equation, regimes, and limits

For free coordinates `[rms, peak, kurtosis, dominant_freq]`, the implemented virtual series is

`x_v(t) = scale_v * x_base(t) + bias_v + AR1_v(t) + drift_v(t) + anomaly_v(t)`

with `drift_v(t)=amplitude_v*sin(2πt/400+phase_v)` and optional `anomaly_v(t)=alpha_v*delta_fault(t-lag_v)` during event windows (`src/virtual_device_generator.py:331-373`). Crest factor is then re-derived as `peak/rms`, RMS is clipped to the physical range, and frequency is snapped to the 15.625 Hz grid (`:305-324`). The AR(1) innovation matrix is constructed as measured residual covariance times `(1-rho rho^T)` so its stationary target covariance matches the scaled empirical covariance (`:226-259`). Base trajectories wrap one contiguous real run rather than stitch sessions (`:266-277`).

| Preset | Scale ± | Bias SD multiple | Extra-noise fraction | Drift SD multiple | Fault severity | Max coordination lag |
|---|---:|---:|---:|---:|---:|---:|
| LOW | 1.0% | 0.25 | 0.10 | 0.15 | 0.85–1.15 | 1 tick |
| MEDIUM | 2.1% | 0.75 | 0.25 | 0.40 | 0.70–1.30 | 2 ticks |
| HIGH | 5.0% | 2.00 | 0.50 | 1.00 | 0.50–1.60 | 3 ticks |

Only empirical within-session covariance/lag and same-device fault trajectories are measured. Cross-device scale/bias/noise/drift and severity/lag ranges are controlled sensitivity parameters from `config/virtual_generator.json`, not learned device-to-device distributions. MEDIUM's 2.1% scale is a same-board between-session proxy. All virtual nodes derive from esp32-vib-001 MPU6050 telemetry; they say nothing about SW-420 heterogeneity. Wrapping short real runs repeats rows periodically, and virtual nodes can share source sessions/values; their cardinality is not physical sample size.

## Paper-safe statements

- The testbed has two physical sensing devices of different modalities, but held-out physical evaluation currently exists only for the MPU6050.
- Network experiments contain 20 declared nodes: two physical identities and eighteen simulated identities; scoreable validation/test physical data come from one identity because the SW-420 is pending.
- Session allocation prevents a physical acquisition session from appearing in multiple splits.
- Firmware and Python reference feature order/math are covered by invariants, and source-level canonical HMAC formatting matches the gateway.
- The virtual generator preserves selected empirical structure from one MPU6050 and explores declared sensitivity regimes; it does not estimate population-level device heterogeneity.
- Current virtual-generator validation evidence in the repository consists of unit invariants; the standalone statistical validation output is missing and should be generated and archived before citation.

> Final reconciliation: this is a point-in-time independent review. The canonical paper package supersedes its interim wording. A fresh generator diagnostic is now preserved. Current M9 dynamically pools20+5=25 columns; historical15-column docstrings are not implementation evidence. Additional GAT empty-query hardening and the corrected sensor-scope explanation run were completed after the initial boundary review.
