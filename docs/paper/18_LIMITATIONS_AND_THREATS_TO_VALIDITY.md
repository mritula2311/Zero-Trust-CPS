# Limitations and threats to validity

## Internal validity

Model and threshold fitting use designated splits, but the project has evolved after inspecting test results. The repository cannot prove preregistration or absence of human test-informed redesign. Pending masking and 10→20-node composition changes were not a matched factorial experiment. Some benchmark JSONs lack code/input/checkpoint fingerprints. Offline replay filters stored authentication labels rather than verifying original wire envelopes, and some stateful replays use execution wall time. These limits prevent a blanket “leakage-free and fully reproducible” assertion.

## External validity

Only one MPU6050 physical source has held-out evaluation. SW-420 is a different sensing modality and has only TRAIN data. Eighteen benchmark identities are parametrically simulated; five separate virtual streams are derived from the same MPU source. Network cardinality is not independent-device support. Hand-induced motion on an ESP32 sensor is not a representative industrial failure population.

## Construct validity

Scores estimate normality under constructed labels, not physical safety or an adversary's intent. Scenario classification in Task 2 can exploit indexed patterns and differs from relational anomaly detection. B0 there is a global count, and the named GNN embeddings are scalar node scores. SW-420 zero activity cannot distinguish rest from a disconnected/misadjusted sensor. Implemented crest factor is peak-to-peak/RMS. The historical graph permutation test changes feature-to-topology assignment rather than graph labels.

## Statistical conclusion validity

Ten-seed intervals estimate refit variability on fixed data. Adjacent windows, events, node rows and generated trajectories are dependent. Generator KS tests and row-wise discriminator folds do not provide independent hardware realism tests. Single-seed M1–M9 point differences are not significance evidence. Hardware Wilson intervals are descriptive small-sample summaries and do not remove session dependence. Multiple tests are not documented as multiplicity-adjusted.

## Hardware limitations

The post-warm-up MPU replay has 5/12 false resting alarms despite 30/30 disturbance detection. Board/build/firmware hash and calibrated clock measurements are absent. SW validation/test sessions, potentiometer documentation and independent-device repeats are pending. Early captures with an obsolete acquisition chain are excluded and preserved.

## Generated-data limitations

Real-source network rows are resampled with replacement. Current SW local training counts 1,940 normal rows but only 140 original resting capture rows; temporal generated ticks are not physically contiguous raw acquisition. Primary temporal training is fragmented and yields only 244 length-eight windows. Virtual trajectories wrap short runs and share source sessions. LOW is an internal residual-consistency regime; MEDIUM/HIGH fail marginal diagnostics and show downstream false-alarm degradation. Mixed-provenance historical conclusions remain confounded.

## Deployment limitations

Current runtime uses GCN fusion, not M6. Missing model artifacts can trigger neutral/mean fallback despite valid transport startup. Firmware broker-certificate verification is incomplete/unvalidated across modalities. Replay state and revocation durability are limited; the 600-second freshness tolerance is a demonstration accommodation. Simulation keys are deterministically derived public research credentials and unsuitable as production identities. HTTPS is substituted for CoAP. Historical stage latency excludes network transit, acquisition and SQLite persistence. Standards mappings are not certification.

These constraints bound the claims in [17](17_CLAIM_EVIDENCE_MATRIX.md) and generate the prioritized actions in [25](25_OPEN_ITEMS_BEFORE_SUBMISSION.md). They must remain explicit in the paper rather than being softened by aggregate benchmark accuracy.
