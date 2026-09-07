# SW-420 (esp32-vib-002) real hardware VALIDATION/TEST — summary

**Date:** 2026-09-07. **Board:** real ESP32 + SW-420 vibration switch (`esp32-vib-002`), HMAC-signed telemetry over MQTT/TLS, gateway-verified live (`[decision] << verified gateway decision: ALLOW` observed during capture). **Protocol:** identical to `esp32-vib-001`'s (`scripts/collect_hardware_session.py --labelled`, operator-marked 8-block sequence: at_rest → gentle_tap → at_rest → moderate_shake → at_rest → tilt_rotate → sharp_impact → at_rest, `MARK_MARGIN_S` trimmed from both ends of every marked interval).

## What this closes

Until this pass, `esp32-vib-002` had exactly one labelled real-hardware capture (`20260905_162002`, TRAIN-only) and zero held-out VALIDATION/TEST sessions — every prior SW-420 claim in this repository was "pending." Two independent new capture sessions were collected and registered in `data/splits/session_split.json`:

| Session | Split | Records | Intervals marked | Matched to gateway decision |
|---|---|---|---|---|
| `20260907_165627` | VALIDATION | 299 | 8/8 | 299/299 |
| `20260907_170639` | TEST | 343 | 8/8 | 343/343 |

## A real, live bug this exposed and fixed

`scripts/evaluate_real_hardware.py` had a hardcoded module constant `DEVICE = "esp32-vib-001"` used throughout scoring, and `src/splits.py::labelled_session_paths()` is (by design) split-based, not device-based — it returns every labelled session file allocated to a split, regardless of which physical device produced it. The moment `20260907_170639` (SW-420) was registered into the same `test_sessions` list as `20260902_221217` (MPU6050), `evaluate_real_hardware.py --split test` would have silently concatenated both devices' rows and scored the SW-420 rows (`trigger_rate`/`duty_cycle`/`burst_max_ms`/`inter_event_cv`) through the MPU6050's Isolation Forest/LSTM-AE models — a feature-vector shape mismatch, not a graceful fallback, and it would have corrupted the published `esp32-vib-001` headline numbers (30/30 detection, 5/12 resting FP). Fixed by threading an explicit `--device` argument through `load_sessions()`/`score_all()`/`main()` and filtering rows to the target device before scoring. **Verified no regression**: rerunning the default (no `--device` flag) reproduces the exact preserved `esp32-vib-001` numbers — FP 5/12 (41.7%, CI 19.3–68.0%), detection 30/30 (100%, CI 88.6–100%) — byte-for-byte, with the new SW-420 session correctly reported as "0 records for 'esp32-vib-001', skipped."

A second, smaller fix: the "quiet windows" diagnostic (`rest_max_peak = max(r["reading"]["peak"] ...)`) assumed every device has a `peak` field, which is MPU6050-specific — the SW-420 has no amplitude/peak concept at all (`feature_engineering_sw420.py`'s docstring: "There is no amplitude, no axis, and no calibrated units"). Generalized via a per-device `AMPLITUDE_KEY` map (`peak` for `esp32-vib-001`, `trigger_rate` for `esp32-vib-002` — each device's own documented primary activity indicator; a resting SW-420 reads `trigger_rate == 0` by construction, the direct analogue of a low peak).

## Results

| Split | Pin | Resting FP | Detection |
|---|---|---|---|
| VALIDATION | gcn | **0/70 (0.0%)**, Wilson 95% CI [0.0%, 5.2%] | **109/109 (100%)**, CI [96.6%, 100%] |
| TEST | gcn | **0/108 (0.0%)**, Wilson 95% CI [0.0%, 3.4%] | **115/115 (100%)**, CI [96.8%, 100%] |
| TEST | m6_corrected (deployed) | **0/108 (0.0%)**, identical to gcn | **115/115 (100%)**, identical to gcn |

No regression/difference between the GCN and the actually-deployed corrected-M6 relational pin on this device either — consistent with the same finding already established for `esp32-vib-001` (`results/gcn_m6_corrected_comparison/hardware_comparison.json`).

**Read alongside `esp32-vib-001`'s numbers, not as a replacement for them.** SW-420's 0% resting FP is a *better* number than MPU6050's 41.7%, and should not be read as "SW-420 is a better sensor" without qualification: the SW-420 is a binary switch (`trigger_rate` is exactly 0 on a still desk by construction, per its own feature-engineering docstring), so its resting class has essentially no measurement noise to produce a false positive from — a structurally easier discrimination problem, not evidence of a better-calibrated pipeline. The Isolation Forest sub-score (`iso`) is flat at 0.500 across every phase for this device, i.e. not discriminating at all on this data volume (321 TRAIN + 299 VALIDATION records, far less than the ~ thousands MPU6050 accumulated) — the fused decision here is carried mostly by `lstm`/`gnn`, reported honestly rather than smoothed over.

## What remains open

- Two independent sessions is the minimum for a real held-out claim, not a large sample — like `esp32-vib-001`'s 5/12, treat these Wilson intervals as wide-uncertainty, not tight.
- No fault-injection, mount-robustness, or coordinated (`--devices esp32-vib-001,esp32-vib-002`) sessions exist yet for this device — only the same at_rest/gentle_tap/moderate_shake/tilt_rotate/sharp_impact protocol run for `esp32-vib-001`.
- The Isolation Forest's flat 0.500 sub-score is a genuine, reportable finding (likely undertrained on ~321 TRAIN rows vs. MPU6050's larger corpus), not fixed here — retraining `esp32-vib-002`'s Isolation Forest on more data is future work, not done as part of this pass.

Source: `results/sw420_real_hardware/hardware_evaluation.log`; producer `scripts/evaluate_real_hardware.py --device esp32-vib-002` (now generalized from an `esp32-vib-001`-only script — see "A real, live bug" above); session allocation `data/splits/session_split.json`.
