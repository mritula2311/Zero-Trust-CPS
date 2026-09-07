# Hardware Data Log -- esp32-vib-002

Session captured 2026-09-07 17:03:54 via `scripts/collect_hardware_session.py`. Raw records: `data/collected/hardware_session_20260907_165627_labelled.json`.

One physical MPU6050 over I2C, no separate vibration sensor (see firmware/HARDWARE_SETUP.md).

`fused_score`/`security_trust_score`/`decision` columns below are gateway.py's OWN live scoring of these same messages, joined back in from `audit_log.db` by timestamp (299/299 records matched within 3s) -- not recomputed by this script.

0 additional record(s) were excluded entirely (received during the first 5s of their phase, when handling disturbance from the PREVIOUS phase's transition is still settling) -- not counted above and not in the raw JSON. Even with this window, phase labels remain approximate, not precise ground truth (RESULTS.md Section 13.2).

## Per-phase observed feature ranges + live gateway scoring

| phase | n | burst_max_ms | duty_cycle | inter_event_cv | trigger_rate | avg security_trust | avg fused (process) | decisions |
|---|---|---|---|---|---|---|---|---|
| at_rest | 130 | 0.0000 - 47.0000 | 0.0000 - 0.2969 | 0.0000 - 0.7470 | 0.0000 - 19.5312 | 0.926 | 0.460099 | ALERT=36, ALLOW=94 |
| gentle_tap | 36 | 0.0000 - 46.0000 | 0.0000 - 0.2070 | 0.0000 - 1.6544 | 0.0000 - 66.4062 | 0.924 | 0.010825 | ALERT=36 |
| moderate_shake | 46 | 0.0000 - 64.0000 | 0.0000 - 0.3672 | 0.0000 - 1.5297 | 0.0000 - 50.7812 | 0.926 | 0.010825 | ALERT=46 |
| sharp_impact | 47 | 0.0000 - 94.0000 | 0.0000 - 0.5469 | 0.0000 - 2.3326 | 0.0000 - 93.7500 | 0.926 | 0.010825 | ALERT=47 |
| tilt_rotate | 40 | 0.0000 - 50.0000 | 0.0000 - 0.5234 | 0.0000 - 1.7111 | 0.0000 - 85.9375 | 0.926 | 0.010825 | ALERT=40 |

## Operator-marked intervals (labels recorded AT injection time)

Each interval below was marked by the operator pressing ENTER at the start and again at the stop, with 2s trimmed from each end for the keypress itself. Records outside every marked interval were discarded, not guessed at. `label_source` on every record is `operator_mark`.

- **at_rest**: 41.0s marked, 37.0s usable
- **gentle_tap**: 50.6s marked, 46.6s usable
- **at_rest**: 47.5s marked, 43.5s usable
- **moderate_shake**: 63.2s marked, 59.2s usable
- **at_rest**: 49.3s marked, 45.3s usable
- **tilt_rotate**: 55.9s marked, 51.9s usable
- **sharp_impact**: 65.0s marked, 61.0s usable
- **at_rest**: 48.4s marked, 44.4s usable

## Overall observed range (all phases combined)

- `burst_max_ms`: 0.0000 to 94.0000
- `duty_cycle`: 0.0000 to 0.5469
- `inter_event_cv`: 0.0000 to 2.3326
- `trigger_rate`: 0.0000 to 93.7500
