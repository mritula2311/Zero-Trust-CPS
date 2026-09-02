# Hardware Data Log -- esp32-vib-001 (real MPU6050)

Session captured 2026-09-02 17:31:08 via `scripts/collect_hardware_session.py`. Raw records: `data/collected/hardware_session_20260902_173108_labelled.json`.

One physical MPU6050 over I2C, no separate vibration sensor (see firmware/HARDWARE_SETUP.md).

`fused_score`/`security_trust_score`/`decision` columns below are gateway.py's OWN live scoring of these same messages, joined back in from `audit_log.db` by timestamp (0/47 records matched within 3s) -- not recomputed by this script.

0 additional record(s) were excluded entirely (received during the first 5s of their phase, when handling disturbance from the PREVIOUS phase's transition is still settling) -- not counted above and not in the raw JSON. Even with this window, phase labels remain approximate, not precise ground truth (RESULTS.md Section 13.2).

## Per-phase observed feature ranges + live gateway scoring

| phase | n | rms (g) | peak (g) | crest_factor | kurtosis | dominant_freq (Hz) | avg security_trust | avg fused (process) | decisions |
|---|---|---|---|---|---|---|---|---|---|
| at_rest | 18 | 1.0424 - 1.0519 | 0.0111 - 0.0341 | 0.0106 - 0.0324 | -0.9085 - 1.2296 | 15.6250 - 250.0000 | n/a (no gateway match) | n/a (no gateway match) | n/a (no gateway match) |
| sharp_impact | 29 | 0.8242 - 3.1388 | 0.0098 - 2.9677 | 0.0096 - 1.1956 | -1.6950 - 1.0674 | 15.6250 - 78.1250 | n/a (no gateway match) | n/a (no gateway match) | n/a (no gateway match) |

## Operator-marked intervals (labels recorded AT injection time)

Each interval below was marked by the operator pressing ENTER at the start and again at the stop, with 2s trimmed from each end for the keypress itself. Records outside every marked interval were discarded, not guessed at. `label_source` on every record is `operator_mark`.

- **sharp_impact**: 67.9s marked, 63.9s usable
- **at_rest**: 42.1s marked, 38.1s usable

## Overall observed range (all phases combined)

- `rms`: 0.8242 to 3.1388
- `peak`: 0.0098 to 2.9677
- `crest_factor`: 0.0096 to 1.1956
- `kurtosis`: -1.6950 to 1.2296
- `dominant_freq`: 15.6250 to 250.0000
