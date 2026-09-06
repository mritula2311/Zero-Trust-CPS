# Hardware, data and provenance

[VERIFIED: captured evidence] Two physical identities exist: one ESP32/MPU6050 and one ESP32/SW-420. Exact ESP32 variant, MicroPython build and capture-to-firmware commit identity are [UNKNOWN]. Firmware source is available, but source availability alone does not attest which binary was flashed. [Raw capture review](../../results/final_verification/hardware_temporal_review.md) and [split manifest](../../data/splits/session_split.json) support the following table.

| Session | Device | Raw rows | Phases | Allocation / grade |
|---|---|---:|---|---|
| 20260902_102448 | vib-001 / MPU6050 | 114 | rest 44; tap 16; shake 14; impact 16; tilt 24 | TRAIN, transcript reconstruction |
| 20260902_171313 | vib-001 / MPU6050 | 152 | rest 59; tap 28; shake 33; tilt 32 | TRAIN, operator-marked |
| 20260902_173108 | vib-001 / MPU6050 | 47 | rest 18; impact 29 | VALIDATION, operator-marked |
| 20260902_221217 | vib-001 / MPU6050 | 116 | pending mark 1; rest 55; weak 37; strong 23 | TEST, operator-marked |
| 20260905_162002 | vib-002 / SW-420 | 321 | rest 140; tap 43; shake 52; impact 35; tilt 51 | TRAIN, operator-marked |

All session filenames are `data/collected/hardware_session_<session>_labelled.json`. Four older captures (20260901_112219/113103/115152/125402; 56/95/102/127 rows) use an obsolete unpaced acquisition chain and are excluded from current splits. Their evidence remains preserved. SW-420 VALIDATION/TEST physical sessions do not exist; “all SW capture pending” is therefore wrong, as is “SW held-out validation complete.”

## Every node in the constructed benchmark

“Physical source” means the identity is backed by a real capture. Network rows for these identities are resampled from split-specific capture pools, not twenty devices publishing together. REAL_DERIVED_VIRTUAL is reserved for the separate affine/AR(1) virtual generator.

| Node | Sensor modality | Provenance | Physical/generated and base | Validity / role |
|---|---|---|---|---|
| esp32-vib-001 | MPU6050 | REAL_HARDWARE source | Generated resampling of physical capture | Valid all splits; physical reference |
| esp32-vib-002 | SW-420 | REAL_HARDWARE source | Generated resampling of 20260905_162002 | TRAIN valid; VAL/TEST pending, excluded |
| esp32-sim-03 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-04 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-05 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-06 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-07 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-08 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-09 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-10 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-11 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-12 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-13 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-14 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-15 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-16 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-17 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-18 | MPU6050-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-19 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |
| esp32-sim-20 | SW-420-like | LEGACY_SIMULATED | Parametric simulator profile | Valid; benchmark peer |

Counts: 20 declared identities = 2 REAL_HARDWARE source identities + 18 LEGACY_SIMULATED; 10 MPU6050-type + 10 SW-420-type. REAL_DERIVED_VIRTUAL=0 and OTHER_GENERATED=0 as additional identity categories in this canonical network. The network as a whole is HYBRID; those categories must not be double-counted. In held-out splits only 19 identities have valid rows. Separately M9 uses five real-derived MPU6050 virtual streams; these are not additional physical devices.

Each of four TRAIN scenarios contains 600 ticks ×20 nodes; each held-out scenario 300×20. Across scenarios: 48,000 TRAIN rows; 24,000 each VALIDATION/TEST, of which 22,800 are valid. The physical sample count is the raw capture count, not the resampled network count. Sources: [network generator](../../scripts/generate_network_data.py), [node profiles](../../config/simulated_nodes.json), [topology](../../config/graph_topology.json), [network artifacts](../../data/collected/network).
