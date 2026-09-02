# Hardware Data Log -- esp32-vib-001 (real MPU6050)

Session captured 2026-09-02 22:12:17 via `scripts/collect_hardware_session.py`. Raw records: `data/collected/hardware_session_20260902_221217_labelled.json`.

One physical MPU6050 over I2C, no separate vibration sensor (see firmware/HARDWARE_SETUP.md).

`fused_score`/`security_trust_score`/`decision` columns below are gateway.py's OWN live scoring of these same messages, joined back in from `audit_log.db` by timestamp (116/116 records matched within 3s) -- not recomputed by this script.

0 additional record(s) were excluded entirely (received during the first 5s of their phase, when handling disturbance from the PREVIOUS phase's transition is still settling) -- not counted above and not in the raw JSON. Even with this window, phase labels remain approximate, not precise ground truth (RESULTS.md Section 13.2).

## Per-phase observed feature ranges + live gateway scoring

| phase | n | rms (g) | peak (g) | crest_factor | kurtosis | dominant_freq (Hz) | avg security_trust | avg fused (process) | decisions |
|---|---|---|---|---|---|---|---|---|---|
| (pending mark) | 1 | 1.0639 - 1.0639 | 0.0173 - 0.0173 | 0.0162 - 0.0162 | 1.0145 - 1.0145 | 109.3750 - 109.3750 | 0.909 | 0.896049 | ALLOW=1 |
| at_rest | 55 | 1.0172 - 1.0619 | 0.0115 - 0.0768 | 0.0110 - 0.0746 | -1.2862 - 1.2622 | 15.6250 - 250.0000 | 0.909 | 0.589334 | ALERT=13, ALLOW=42 |
| fault_strong | 23 | 0.7827 - 3.0773 | 0.2963 - 2.1814 | 0.1053 - 1.6799 | -1.5097 - 5.1663 | 15.6250 - 31.2500 | 0.904 | 0.000033 | ALERT=23 |
| fault_weak | 37 | 0.9282 - 1.8959 | 0.0239 - 2.5165 | 0.0227 - 1.3319 | -1.6702 - 5.0571 | 15.6250 - 156.2500 | 0.904 | 0.000296 | ALERT=37 |

## Operator-marked intervals (labels recorded AT injection time)

Each interval below was marked by the operator pressing ENTER at the start and again at the stop, with 2s trimmed from each end for the keypress itself. Records outside every marked interval were discarded, not guessed at. `label_source` on every record is `operator_mark`.

- **at_rest**: 32.8s marked, 28.8s usable
- **fault_weak**: 100.5s marked, 96.5s usable
- **at_rest**: 54.3s marked, 50.3s usable
- **fault_strong**: 60.6s marked, 56.6s usable
- **at_rest**: 47.9s marked, 43.9s usable

## Overall observed range (all phases combined)

- `rms`: 0.7827 to 3.0773
- `peak`: 0.0115 to 2.5165
- `crest_factor`: 0.0110 to 1.6799
- `kurtosis`: -1.6702 to 5.1663
- `dominant_freq`: 15.6250 to 250.0000
