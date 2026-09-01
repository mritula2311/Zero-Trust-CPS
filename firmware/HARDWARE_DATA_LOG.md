# Hardware Data Log -- esp32-vib-001 (real MPU6050)

Session captured 2026-09-01 12:54:02 via `scripts/collect_hardware_session.py`. Raw records: `data/collected/hardware_session_20260901_125402.json`.

One physical MPU6050 over I2C, no separate vibration sensor (see firmware/HARDWARE_SETUP.md).

`fused_score`/`security_trust_score`/`decision` columns below are gateway.py's OWN live scoring of these same messages, joined back in from `audit_log.db` by timestamp (127/127 records matched within 3s) -- not recomputed by this script.

## Per-phase observed feature ranges + live gateway scoring

| phase | n | rms (g) | peak (g) | crest_factor | kurtosis | dominant_freq (Hz) | avg security_trust | avg fused (process) | decisions |
|---|---|---|---|---|---|---|---|---|---|
| free_form_mixed | 127 | 0.7803 - 3.4386 | 0.0087 - 2.8058 | 0.0082 - 1.9252 | -1.6517 - 12.2369 | 3.1250 - 43.7500 | 0.909 | 0.109513 | ALERT=36, ALLOW=88, BLOCK=3 |

## Phase instructions (what the operator was doing)

- **free_form_mixed** (280s): Continuously vary the board's physical state for the whole session: alternate between resting, tapping, shaking, and tilting. No need to follow a strict schedule -- just keep varying it.

## Overall observed range (all phases combined)

- `rms`: 0.7803 to 3.4386
- `peak`: 0.0087 to 2.8058
- `crest_factor`: 0.0082 to 1.9252
- `kurtosis`: -1.6517 to 12.2369
- `dominant_freq`: 3.1250 to 43.7500
