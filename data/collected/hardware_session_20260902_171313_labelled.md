# Hardware Data Log -- esp32-vib-001 (real MPU6050)

Session captured 2026-09-02 17:13:13 via `scripts/collect_hardware_session.py`. Raw records: `data/collected/hardware_session_20260902_171313.json`.

One physical MPU6050 over I2C, no separate vibration sensor (see firmware/HARDWARE_SETUP.md).

`fused_score`/`security_trust_score`/`decision` columns below are gateway.py's OWN live scoring of these same messages, joined back in from `audit_log.db` by timestamp (152/152 records matched within 3s) -- not recomputed by this script.

0 additional record(s) were excluded entirely (received during the first 5s of their phase, when handling disturbance from the PREVIOUS phase's transition is still settling) -- not counted above and not in the raw JSON. Even with this window, phase labels remain approximate, not precise ground truth (RESULTS.md Section 13.2).

## Per-phase observed feature ranges + live gateway scoring

| phase | n | rms (g) | peak (g) | crest_factor | kurtosis | dominant_freq (Hz) | avg security_trust | avg fused (process) | decisions |
|---|---|---|---|---|---|---|---|---|---|
| at_rest | 59 | 1.0409 - 1.0603 | 0.0113 - 0.0349 | 0.0107 - 0.0335 | -1.2782 - 1.3059 | 15.6250 - 250.0000 | 0.909 | 0.789314 | ALERT=5, ALLOW=54 |
| gentle_tap | 28 | 0.7960 - 2.3391 | 0.0447 - 2.5420 | 0.0428 - 1.6694 | -1.5207 - 2.3844 | 15.6250 - 46.8750 | 0.909 | 0.000003 | ALERT=28 |
| moderate_shake | 33 | 0.6247 - 3.1850 | 0.1018 - 2.3731 | 0.0747 - 1.1248 | -1.6411 - 6.5729 | 15.6250 - 46.8750 | 0.909 | 0.000003 | ALERT=33 |
| tilt_rotate | 32 | 0.5455 - 2.9939 | 0.1402 - 2.1675 | 0.0684 - 1.4494 | -1.5947 - 6.0319 | 15.6250 - 78.1250 | 0.908 | 0.000003 | ALERT=32 |

## Operator-marked intervals (labels recorded AT injection time)

Each interval below was marked by the operator pressing ENTER at the start and again at the stop, with 2s trimmed from each end for the keypress itself. Records outside every marked interval were discarded, not guessed at. `label_source` on every record is `operator_mark`.

- **at_rest**: 41.7s marked, 37.7s usable
- **gentle_tap**: 66.8s marked, 62.8s usable
- **at_rest**: 44.0s marked, 40.0s usable
- **moderate_shake**: 76.9s marked, 72.9s usable
- **at_rest**: 56.2s marked, 52.2s usable
- **tilt_rotate**: 77.1s marked, 73.1s usable

## Overall observed range (all phases combined)

- `rms`: 0.5455 to 3.1850
- `peak`: 0.0113 to 2.5420
- `crest_factor`: 0.0107 to 1.6694
- `kurtosis`: -1.6411 to 6.5729
- `dominant_freq`: 15.6250 to 250.0000
