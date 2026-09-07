# Hardware Data Log -- esp32-vib-002

Session captured 2026-09-07 17:15:23 via `scripts/collect_hardware_session.py`. Raw records: `data/collected/hardware_session_20260907_170639_labelled.json`.

One physical MPU6050 over I2C, no separate vibration sensor (see firmware/HARDWARE_SETUP.md).

`fused_score`/`security_trust_score`/`decision` columns below are gateway.py's OWN live scoring of these same messages, joined back in from `audit_log.db` by timestamp (343/343 records matched within 3s) -- not recomputed by this script.

0 additional record(s) were excluded entirely (received during the first 5s of their phase, when handling disturbance from the PREVIOUS phase's transition is still settling) -- not counted above and not in the raw JSON. Even with this window, phase labels remain approximate, not precise ground truth (RESULTS.md Section 13.2).

## Per-phase observed feature ranges + live gateway scoring

| phase | n | burst_max_ms | duty_cycle | inter_event_cv | trigger_rate | avg security_trust | avg fused (process) | decisions |
|---|---|---|---|---|---|---|---|---|
| at_rest | 168 | 0.0000 - 0.0000 | 0.0000 - 0.0000 | 0.0000 - 0.0000 | 0.0000 - 0.0000 | 0.925 | 0.587780 | ALERT=12, ALLOW=156 |
| gentle_tap | 53 | 0.0000 - 256.0000 | 0.0000 - 1.0000 | 0.0000 - 0.8152 | 0.0000 - 35.1562 | 0.926 | 0.010825 | ALERT=53 |
| moderate_shake | 36 | 0.0000 - 171.0000 | 0.0000 - 0.8867 | 0.0000 - 1.2208 | 0.0000 - 66.4062 | 0.926 | 0.010825 | ALERT=36 |
| sharp_impact | 43 | 2.0000 - 75.0000 | 0.0078 - 0.3984 | 0.0000 - 2.2000 | 3.9062 - 85.9375 | 0.926 | 0.010825 | ALERT=43 |
| tilt_rotate | 43 | 0.0000 - 56.0000 | 0.0000 - 0.5508 | 0.0000 - 1.9905 | 0.0000 - 121.0937 | 0.926 | 0.010825 | ALERT=43 |

## Operator-marked intervals (labels recorded AT injection time)

Each interval below was marked by the operator pressing ENTER at the start and again at the stop, with 2s trimmed from each end for the keypress itself. Records outside every marked interval were discarded, not guessed at. `label_source` on every record is `operator_mark`.

- **at_rest**: 57.5s marked, 53.5s usable
- **gentle_tap**: 72.4s marked, 68.4s usable
- **at_rest**: 81.5s marked, 77.5s usable
- **moderate_shake**: 50.8s marked, 46.8s usable
- **at_rest**: 41.1s marked, 37.1s usable
- **tilt_rotate**: 59.6s marked, 55.6s usable
- **sharp_impact**: 59.8s marked, 55.8s usable
- **at_rest**: 54.0s marked, 50.0s usable

## Overall observed range (all phases combined)

- `burst_max_ms`: 0.0000 to 256.0000
- `duty_cycle`: 0.0000 to 1.0000
- `inter_event_cv`: 0.0000 to 2.2000
- `trigger_rate`: 0.0000 to 121.0937
