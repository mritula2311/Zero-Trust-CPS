# Process features and preprocessing

[VERIFIED] The sensor schemas are distinct and ordered; a common three-score representation is constructed only after local detection. See [MPU reference](../../src/feature_engineering.py), [SW reference](../../src/feature_engineering_sw420.py) and [saved metadata](../../results/final_verification/model_metadata.json).

| Modality | Ordered features | Meaning / units |
|---|---|---|
| MPU6050, width 5 | rms; peak; crest_factor; kurtosis; dominant_freq | RMS acceleration magnitude (g); peak-to-peak magnitude (g); peak-to-peak/RMS ratio; excess standardized fourth moment; non-DC DFT peak (Hz) |
| SW-420, width 4 | trigger_rate; duty_cycle; burst_max_ms; inter_event_cv | Rising edges/s; fraction of binary samples high; longest high run (ms); population-SD/mean inter-edge gaps, or zero if fewer than three edges |

The implemented crest factor uses **peak-to-peak/RMS**, not the conventional absolute peak/RMS. Preserve this exact definition in equations. MPU feature extraction uses magnitude windows, population standard deviation, excess kurtosis minus three, mean removal and exclusion of the DC spectral bin; constant/degenerate cases return finite defaults. Features are rounded to four decimals. MPU firmware uses 500 Hz, 32 samples and DLPF configuration 1; SW firmware uses 1,000 Hz, 256 binary samples. The MPU spectral bin width is 15.625 Hz. These are declared acquisition settings, not calibrated clock or sensor-accuracy measurements.

`gateway._extract_reading` uses registry `feature_names_for(device_id)` before `feature_vector` dispatches on the disjoint `trigger_rate` key. LSTM/Transformer input dimensions and saved feature names follow the modality. Gateway validates finite numeric fields before any accepted state update. Firmware canonicalization sorts JSON keys with CPython-compatible spaces and optional nonce fields. Existing differential tests verify MPU formula/signature equivalence; SW reference math and schema tests are separate.

## Training and sequence construction

`datasets.training_records` selects primary merged TRAIN plus non-primary `network_*_train.json` rows. `normal_sequences` traverses acquisition order before filtering, closes a run on non-normal/auth-failed/absent readings, changed `(session_id,scenario,phase)` or nonconsecutive `source_tick` (fallback `tick`). Training scripts build length-eight windows within each run, then compute normalization from TRAIN normals and fit reconstruction models. This prevents windows across removed event rows and observable reset/gap/session boundaries. It cannot detect an acquisition boundary never recorded in metadata.

The current construction yields 4,070 eligible primary MPU normals, 1,046 runs and 244 eight-step windows. Interleaved data fragments much of the eligible primary stream. SW-420 has 1,940 nominal normals and 1,758 windows, but 1,800 normals are resampled network rows derived from only 140 unique at-rest capture rows. Generated consecutive ticks represent synthetic chronology, not contiguous physical acquisition. Do not claim that these are independent raw physical temporal windows. A raw-session-only physical training comparison is [REQUIRES CONTROLLED FOLLOW-UP]; changing it requires rebuilding downstream models in order.

Local score baselines are in-sample TRAIN mappings, not held-out probability calibrations. LSTM/Transformer store mean/std and reconstruction-error mean/std; zero feature spread is replaced with a safe scale. Network models consume [rule,IF,LSTM] scores rather than heterogeneous raw channels. Pending content is now canonicalized before set-model arithmetic; GCN invalid nodes are excluded from adjacency normalization and masked before model arithmetic. See [masking tests](../../tests/test_nonfinite_relational_boundaries.py), [sequence tests](../../tests/test_training_sequences.py), and [independent review](../../results/final_verification/hardware_temporal_review.md).
