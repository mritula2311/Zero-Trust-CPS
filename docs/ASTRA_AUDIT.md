# Astra audit — 2026-09-05

This is the current audit qualification of the stored research record. Original
datasets, trained models and result JSON files were preserved. A code fix is not
a new experiment: the saved metrics predate the temporal-training fix below.

## 1. Project understanding

ZT-Duo authenticates CPS telemetry while keeping cyber evidence and physical
process evidence separate. An authenticated physical disturbance should retain
its telemetry and raise an operations alert; forged or replayed messages are
rejected. A learned process ensemble, policy, explainability and tamper-evident
logging form a research gateway, not an established industrial safety system.

## 2. Current as-built pipeline

`gateway.py` runs MQTT, an HTTPS telemetry endpoint (historical filename
`coap_server.py`), the dashboard and a silence watchdog. A pipeline lock
serializes shared inference/state updates. Schema validation, identity,
revocation, HMAC, replay and timestamp checks precede device-state commitment.
Failed-signature cooldown suppresses repeated rejection logging without dropping
authentic traffic under the targeted identity.

Security Trust uses rate, step-up outcomes and elapsed time. Process Trust uses
Rule + per-device IF + LSTM-AE + the legacy GCN through logistic fusion. Both
scores are high-is-good and meet at policy evaluation only. `USE_RL_POLICY=True`
selects a frozen contextual bandit; the static table remains available, with
thresholds 0.6/0.6. Automatic quarantine is off. SHAP explains the fusion margin
in log-odds; feature/node perturbations provide Level 2 explanations.

The registry contains 12 identities: two configured physical identities, eight
network-research simulated identities, and two legacy scalar identities. Registry
membership is not evidence that any of those devices is currently publishing.
Only MPU6050 captures exist; SW-420 capture remains pending.

## 3. Current research candidate pipeline

Keep Rule + IF + LSTM-AE as the local baseline. Compare a newly fitted fusion of
these signals with one adding Set Transformer relational evidence, using the same
split, operational constraints and per-class/FPR reporting. Set Transformer is
an experimental candidate, not a deployed scorer. Concat MLP is the fixed-size
efficiency/calibration baseline; Deep Sets is a strong set baseline. GCN/GATv2
remain research baselines, temporal Transformer remains ablation-only, and NP-ST
remains a rejected ablation. Standalone rankings do not prove fusion benefit.

## 4. Positive findings

- Session allocation explicitly separates physical TRAIN/VALIDATION/TEST;
  fusion uses simulated seed 4242 and policy uses 4243, separate from base TRAIN.
- Model fitting and threshold selection are separate from TEST in the inspected
  main benchmark paths. MEDIUM/HIGH reuse LOW validation thresholds.
- Firmware/host feature equivalence, score separation, quarantine defaults and
  audit tampering have executable regression checks.
- Negative findings are retained: high hardware FPR, GCN collapse, calibration
  failures, NP-ST rejection and virtual-only's small F1 advantage.
- Seed-level paired contrasts test topology effects and the interaction directly.

## 5. Bugs and negative findings

| Priority | File | Problem | Why it matters | Fixed? |
|---|---|---|---|---|
| P0 | `src/gateway.py` | Malformed types/nonfinite readings could crash processing or mutate replay/trust before scoring failed; invalid UTF-8 escaped MQTT callback. | Availability and state integrity. | Fixed; isolated ingress regressions include valid controls. |
| P0 | `src/gateway.py` | Forged claims could activate a pre-HMAC identity cooldown and deny the real device. | Authentic-device availability. | Fixed: cooldown applies only after failed HMAC. |
| P0 | `src/trust_engine.py` | The supposedly pure replay predicate created state on a first rejected message. | Rejected-message state isolation. | Fixed: read-only lookup. |
| P0 | `scripts/train_lstm_ae.py`, `train_transformer.py` | Normal-first filtering and global tick sorting made windows across anomalies, sessions and scenarios. | Validity of learned temporal patterns. | Fixed for future training with `datasets.normal_sequences`; downstream results require rebuilding. |
| P1 | `scripts/merge_real_hardware_data.py` | Renumbering retained rest rows concealed gaps where physical events were removed. | Traceability of temporal discontinuities. | New merges retain `source_tick`; archived merged data is unchanged. |
| P1 | `src/isolation_forest_scorer.py`, `lstm_ae_scorer.py` | SW-420 explanations used MPU6050 names; LSTM attempted a fifth channel on a four-channel tensor. | Sensor compatibility and correct explanations. | Fixed with the existing per-device feature-name contract. |
| P1 | `scripts/benchmark_crossdevice_models.py::_eval_slice` | Zero-positive controls lost a defined FPR along with undefined F1; investigation serialized NaN. | Negative-control visibility and interoperable results. | Fixed for future evaluations: keep counts/FPR, null undefined detection, strict JSON and per-slice FPR. Existing JSON retained. |
| P0 | `RESULTS.md` 0.13.15–16 | TRAIN-only residual validation called held-out; two physical columns claimed although only one contributes; n=15 capability comparison not tested. | Defensibility of current research claims. | Interpretations withdrawn in 0.13.17; original values retained. |
| P1 | `evaluate_gnn_baselines.py::build_snapshots`, set/graph training | Pending node excluded from loss/metrics but neutral 0.9 placeholder still enters graph/attention/pooling. | Missing inputs can influence observed-node predictions. | Disclosed; current experiments use slots, not 10/15 observed streams. A matched masked benchmark requires redesign and regenerated evidence. |
| P1 | `generate_network_data.py::build` | Independently resampled physical rows create artificial LSTM trajectories. | Temporal evaluation no longer represents acquisition dynamics. | Disclosed; resampled feature evidence is not a continuous hardware capture. Contiguous network construction requires regenerated experiments. |
| P1 | `benchmark_crossdevice_models.py::validation_halves` | Calibration/selection tick halves share source readings and seven ticks of LSTM history. | Calibration uncertainty is understated. | Capped-FPR independence claim withdrawn; partition source runs before replay and purge/reset for a new comparison. |
| P1 | `generate_virtual_network_data.py` | Source/run/transform metadata discarded; lagged anomalies can have null event IDs. | Events and independent source observations cannot be reconstructed. | Disclosed; preserve history, add provenance/event metadata in the next generated-data version. |
| P1 | `device_simulator.py::make_reading` | Network registry expansion makes the legacy live simulator generate accelerometer features for switch profiles. | The generator crashes or emits the wrong sensor schema. | Fixed: live and legacy offline generation use the original three-device cohort; network generation stays separate. Repeated offline seeds reset the simulator walk. |
| P0 | `firmware/main.py::connect_mqtt`, config startup | Firmware explicitly disables certificate verification; host configuration can fall back to plaintext/placeholder credentials. | Transport peer identity is not established on firmware. | Host startup now refuses plaintext/unconfigured broker auth and template keys cannot authenticate. Firmware verification remains a deployment blocker on the actual MicroPython build. |
| P1 | `benchmark_crossdevice_models.py::mean_ci`, `_paired_t` | Small seed counts outside the lookup used a normal approximation; empty/single-seed cases emitted NaN. | Small-n uncertainty/significance can be misstated. | Fixed with exact Student-t quantiles and undefined intervals; new regressions reproduced the failure. |
| P1 | `src/coap_server.py::do_POST` | Unbounded Content-Length/read on a single-thread server exposes availability risk; input framing lacks robust limits. | One client can exhaust endpoint availability. | Open deployment hardening; no public-load readiness claim. |
| P1 | model files and dependency metadata | mtime checks do not establish training-input/config/code hashes or protect against copied stale artifacts. | Saved artifacts cannot be tied to their actual training recipe. | Audit snapshot hashes record current bytes only; historical training provenance remains uncertified. |
| P1 | M1 training, benchmark | MLP is not class-balanced like the other comparators; incomplete fairness claim. | Comparisons can confound architecture and weighting. | Disclosed; matched weighting comparison requires new results. |


## 6. Code changes

```text
file: src/gateway.py
old behavior: Malformed types and nonfinite readings reached stateful processing; cooldown preceded HMAC; placeholder keys worked.
new behavior: Validate before state mutation, apply cooldown only to failed HMAC, reject template keys and refuse unconfigured serving.
reason: Prevent input crashes, replay poisoning, identity-targeted denial and insecure startup.
```

```text
file: src/trust_engine.py
old behavior: First replay check created authentication state.
new behavior: Read-only lookup; cooldown contract now documents post-HMAC use.
reason: Rejected first messages must leave device state unchanged.
```

```text
file: src/datasets.py
old behavior: No common run-segmentation contract.
new behavior: normal_sequences preserves acquisition order and breaks on metadata, tick gaps, anomalous/invalid rows.
reason: Temporal adjacency must reflect intact normal runs.
```

```text
file: scripts/train_lstm_ae.py
old behavior: Filtered normals were globally sorted and windowed together.
new behavior: Build windows within normal_sequences runs; skip when no complete run exists.
reason: Prevent fabricated temporal transitions in future training.
```

```text
file: scripts/train_transformer.py
old behavior: Same filtered/sorted temporal construction.
new behavior: Use the same run contract, leaving architecture and fitting parameters intact.
reason: Keep the temporal ablation consistent with the corrected LSTM protocol.
```

```text
file: scripts/merge_real_hardware_data.py
old behavior: Renumbered ticks hid discarded-event gaps.
new behavior: New merges retain source_tick.
reason: Preserve discontinuities; old merged data still needs versioned rebuilding.
```

```text
file: src/isolation_forest_scorer.py
old behavior: Level-2 explanations used MPU6050 feature names for SW-420.
new behavior: Resolve names through feature_names_for(device_id).
reason: Explain the actual sensor channel.
```

```text
file: src/lstm_ae_scorer.py
old behavior: Five-channel perturbation on four-channel SW-420 data could crash.
new behavior: Perturb only the device-specific channels.
reason: Keep explanations compatible with heterogeneous sensors.
```

```text
file: src/device_simulator.py
old behavior: Registry expansion entered the original simulator with unsupported profiles.
new behavior: Use explicit legacy cohort minus configured physical IDs.
reason: Preserve live demo scope and avoid incorrect switch readings.
```

```text
file: scripts/generate_training_data.py
old behavior: Expanded registry caused expected_range KeyError; persistent random walk survived reseeding.
new behavior: Generate the original cohort and reset walk centres at each generation call.
reason: Restore generation and same-seed reproducibility without rewriting datasets.
```

```text
file: scripts/benchmark_crossdevice_models.py
old behavior: Single-class slices lost valid FPR; NaN JSON and small-n normal intervals.
new behavior: Keep defined counts/FPR, null undefined detection, strict JSON, per-slice FPR and Student-t seed intervals.
reason: Report negative controls and uncertainty honestly; saved results remain unchanged.
```

```text
file: src/config.py
old behavior: Comments described a runnable plaintext fresh clone and linked nonexistent guides.
new behavior: Comments distinguish offline imports from guarded serving and point to docs/07.
reason: Document actual startup behavior; configuration values were not changed.
```

```text
file: tests/test_gateway_input_validation.py, test_training_sequences.py, test_research_reporting.py, test_sensor_explanations.py, test_legacy_generation.py
old behavior: These regressions were absent from the 70-test baseline.
new behavior: Add 38 tests, including valid controls, captured model-input tensors and independent two-seed critical values.
reason: Verify behavior without training saved models or contacting live services.
```

The generic `gnn_score` name is retained: current fusion artifacts, audit fields,
explanation keys and dashboard consume that deployed GCN slot. A rename before a
second runtime scorer exists would add compatibility work without demonstrating
relational complementarity. Introduce a versioned relational interface with that
experiment, preserving the old artifact schema.

## 7. Documentation changes

| Markdown file | Problem found | Updated content |
|---|---|---|
| `README.md` | Stale runtime, Transformer and setup claims. | Runtime/research distinction, accurate test/reproduction instructions and limitations. |
| `METHODOLOGY.md` | Temporal/provenance and policy conclusions overstated. | Latest topology interpretation, M9/validation scope, policy constraints and temporal-training qualification. |
| `RESULTS.md` | Latest M9 interpretations exceed evidence. | Append 0.13.17; preserve all prior metrics and negative findings. |
| `ZERO_TRUST_CPS_KB.md` | Old operational and research statements persist. | Current operational/research status and instructions protecting the archived chain. |
| `docs/CLAIM_EVIDENCE_MATRIX.md` | Policy/topology/M9 claim statuses incomplete. | Update policy evidence; add topology, virtual generator, M9 and ablation claims with explicit support status. |
| `CLAUDE.md` | Stale commands, test count and credential guidance. | Current runner, dashboard, secrets location and research cautions. |
| `PRD.md` | Requirements statuses conflate configuration, validation and deployment. | As-built/candidate distinction, contributions, hardware limits and unmet deployment requirements. Acceptance thresholds retained. |
| `docs/00–13`, `EXPERIMENTAL_PROTOCOL`, `ENVIRONMENT`, `SECURITY_TRUST_SPEC`, `REVIEW_RESPONSE_TRACKER` | Design descriptions conflict with current code or evidence. | Scope-specific corrections and a current-audit reference; older design pseudocode remains labeled. |
| `docs/REPOSITORY_AUDIT.md`, `SESSION_LOG.md`, firmware guides/log | Historical narrative needs current qualifications. | Historical records retained, with forward pointers where needed. |


## 8. Research integrity

**Splits and leakage.** Physical session IDs do not overlap in the current
manifest. This does not establish independence of every generated row. The
temporal trainer defect is false temporal adjacency, not evidence of test rows
being fitted. The capped-FPR validation subdivision is not source-independent.
Repeated exploration of the same test split also limits a literal “test read
once” description across the project's history.

**Provenance.** Interpret legacy `REAL` as captured hardware values; network
replays resample these values. Interpret legacy `SIMULATED` as parametric
simulation (`LEGACY_SIMULATED`). `REAL_DERIVED_VIRTUAL` denotes perturbed,
wrapped trajectories from split-specific physical source pools. `HYBRID` is a
mixture, never a synonym for real. Pending rows have no observations. One split
and one captured MPU6050 cannot establish manufacturing variability.

**Generator.** LOW passes the existing in-source TRAIN resting-residual checks:
max correlation difference 0.086, max lag-1 difference 0.097, balanced logistic
discriminator accuracy 0.466. This is a limited consistency check, not held-out
realism validation, not equivalence established by nonsignificant KS tests, and
not validation of long anomalous streams. The row-level discriminator reuses
source structure and is only one classifier. MEDIUM/HIGH are OOD stress presets;
their marginal failures remain visible. Wrapping creates repeated observations
and seams; independent random seeds do not imply independent physical sources.

**Statistics and topology.** Stored paired changes reproduce GCN target-degree
−0.8160 (CI −0.850 to −0.782, 10/10 decrease), GCN peer-density +0.1895,
GATv2 target-degree −0.0655 (CI includes zero), and GATv2 peer-density −0.2733
(CI −0.477 to −0.069, 10/10 decrease). The model × intervention contrast is
−1.2132 (CI −1.583 to −0.843). These support different topology-sensitivity
patterns on this fixed dataset, not a strict double dissociation. GATv2's own
within-model contrast is not significant. The seed study uses ten refits, not
ten independent datasets or hardware populations. Overlapping hardware windows
also make Wilson intervals descriptive window-level summaries, not independent
session-level uncertainty. The archived script used a normal approximation outside its small t lookup.
The repaired reporting code uses Student-t at n−1 degrees of freedom for every
n≥2, and explicit undefined intervals for fewer seeds. Archived numbers remain
unchanged; ten-seed conclusions above use their saved rounded t multiplier.

**M9.** Saved F1 is 0.9671 on the existing hybrid test, 0.7563/0.5436/0.3060 on
LOW/MEDIUM/HIGH virtual tests; FPR is 0.1126/0.2956/0.7921 and AUC
0.9870/0.9578/0.6583. Thresholds come from the corresponding validation regime;
stress thresholds stay frozen. These describe calibration-dominated degradation
at MEDIUM and substantial discrimination loss at HIGH. They are window anomaly
F1, not the macro-F1 column from the earlier seven-model table.

Virtual-only achieves 0.9769 on the same existing hybrid test. It trained at
{2,3,5}; hybrid trained at {2,3,5,10,15} slots. Neither persisted study establishes
n=15 test performance. Both use a variable-cardinality architecture. The physical
output slice includes only one captured device's resampled rows and still uses
simulated context. The result therefore does not rule out simulator-context
effects and does not demonstrate a broader-coverage benefit from pooling.

**Hardware.** `esp32-vib-001` is MPU6050, `esp32-vib-002` is SW-420, whose capture
is pending. Earlier held-out hardware evidence remains 30/30 disturbance
detection and 5/12 resting false positives, with a wide 19.3–68.0% FPR interval.
These are saved-chain measurements, not measurements of models trained after
this audit's sequence correction. Bench disturbances are not industrial faults.

## 9. Model recommendation

Retain Rule, IF and LSTM-AE as the next local baseline, rebuilding temporal
models with valid sequences. Keep Set Transformer as the relational research
candidate, Deep Sets as its baseline and concat MLP as the fixed-size deployment
baseline. Do not promote M9 before a matched end-to-end fusion comparison.
The stored fusion coefficients are approximately [-0.018, 2.979, 4.500, 6.062];
Rule's coefficient is near zero and slightly negative, so strict monotonicity of
learned fusion is not proved by positive IF/LSTM/GCN coefficients.

P6 is the best feasible **static grid point** under ALERT recall ≥0.90 and
false-block ≤0.01, not the best constrained policy overall. On saved test data
P5 bandit has macro-F1 0.5271, ALERT recall 0.9600 and false-block 0.0000;
P6 has 0.2777/0.9900/0.0000. P2's 0.5614 F1 accompanies only 0.5850 ALERT
recall; P3's 0.6453 accompanies 0.1510 false-block. Compare all policy families
under the same validation constraints before changing the default. Keep the
combined-class blind spot and false actions in every report.

## 10. Simulation and hardware strategy

| Strategy | What it can establish | Recommendation |
|---|---|---|
| A. Fully simulated | Controlled failures, scaling, deterministic software regression | Retain as clearly simulated baseline. |
| B. Two physical devices only | Actual transport/acquisition and heterogeneous sensing after Device 2 capture | Required physical evidence, insufficient for 15-device scaling or same-sensor variation. |
| C. Physical sources + qualified virtual devices | Controlled scale anchored to measurements, with explicit source and regime limitations | Preferred research strategy after provenance, contiguous replay and missing-node issues are corrected. |

## 11. Tests and validation

Baseline: `pytest -q` unavailable on PATH; repository-native
`python -m unittest discover -s tests -v`: **70 passed**, no failures or skips,
24.013 seconds. Warnings: six unclosed-file ResourceWarnings in tests and three
SHAP PendingDeprecationWarnings. Final native suite: **108 passed**, no
failures or skips, 18.218 seconds; the same warning categories remain. The
intermediate full run passed 106 tests before two extra seed-statistics tests.
`--selfcheck` passes the threshold/tie and tick-halves checks; it does not prove
source-independent calibration. Python syntax and manifest verification are
recorded in `results/astra_audit/verification.json`: 66 Python files parse,
107 tracked artifacts are hashed and all 22 pre-existing user data/result
files match the initial backup. Raw test and validator
transcripts are in the same directory. No warning was suppressed to obtain a pass.

`python scripts/validate_virtual_device_generator.py` reproduced all LOW checks,
MEDIUM rms divergence and HIGH rms/peak divergence, with LOW < MEDIUM < HIGH
cross-node spread. Exit code **1** is the existing aggregate validator's
reporting of these stress failures; it was not changed to produce green output.

No full training, benchmark or live hardware attack was run. Those commands
overwrite historical artifacts or operate on hardware. Sequence-regression
tests instead inspect the tensors both trainers pass to a model using isolated
save sinks. Original stored results are preserved for later versioned comparison.

## 12. Git safety

Original branch `main`; starting commit
`f78c7f005f76d89e33383a8ad399f73eb313aaac`. Created/switched to `astra-audit`
before repository edits. No staged changes initially; ten modified tracked files
and six untracked entries (35 individual files including virtual datasets).
Baseline copies, SHA-256 hashes and the tracked patch are in the local sibling
directory `D:/zt-cps/astra-baseline-20260905`. They are not project artifacts.

Pre-existing modifications: `CLAUDE.md`, `METHODOLOGY.md`, `RESULTS.md`,
`ZERO_TRUST_CPS_KB.md`, `docs/04_module3_trust_evaluation.md`,
`docs/12_model_validation_and_justification.md`,
`docs/13_system_architecture_and_workflow.md`, `requirements.txt`,
`scripts/benchmark_crossdevice_models.py`, `src/virtual_device_generator.py`.
Untracked entries: `data/collected/virtual_network/`, the two M9 JSON results,
`generate_virtual_network_data.py`, `validate_virtual_device_generator.py`,
`tests/test_virtual_generator.py`. User work was preserved and changes layered
on top; the baseline permits attribution of every additional edit.

This audit agent issued no push, merge, rebase, reset, clean, stash or
branch-deletion command. During the shared session, Git changed independently:
commit `7388338` recorded the 35 pre-existing M9 files; the reflog then showed
a switch to main and a fast-forward from origin/main. Both branches pointed
to `7388338` when detected. The audit agent switched back to `astra-audit`
before further edits. Verified fixes are isolated in five local Astra commits:

- `3922db7` — ingress/state validation and serving configuration guard.
- `bcdfe4e` — acquisition-run temporal windows and merge provenance.
- `0dcef4b` — legacy generation scope and repeated-seed reproducibility.
- `2c953ab` — sensor-specific explanations.
- `432f4c1` — defined control metrics and valid seed intervals.

The final documentation/evidence commit is titled
`docs: synchronize audit findings and preserve review evidence`; its hash and
final clean working-tree check are reported in the handoff. The verification
manifest records the code HEAD before that documentation commit to avoid a
self-referential artifact hash. `main` remains at the pre-existing `7388338`.
No Astra changes were pushed or merged. We cannot attest that no other actor
pushed during the shared session. The complete filename inventory is in
`results/astra_audit/change_inventory.json`.

Review scope: repository inventory, high-risk runtime/training/evaluation traces,
saved result checks, fresh-context ingress/sequence regression work and an
independent research review. This is not a formal proof of every line or a fresh
hardware test. The requested manual external review has been prepared in
`docs/MANUAL_EXTERNAL_REVIEW.md`; no external model was contacted. Independent
review findings on context masking, source reuse, fairness and n=15 claims were
retained as blockers because correcting them requires a new experimental version.

## 13. Remaining blockers

- **Software:** firmware certificate verification/provisioning; missing-node
  masks; source/run provenance; HTTPS body-size/time limits and service capacity;
  archived artifacts lack training hashes. This is not deployment-ready.
- **Research:** corrected data/temporal chain and downstream reruns; independent
  calibration sources; matched M1 weighting; actual n=15 evaluation; matched
  fusion and constrained policy studies; fresh splits/captures after extensive
  exploration of the existing test split.
- **Documentation:** legacy numerical sections remain research history; binary
  manuscript/synopsis and previously exported figures were not rewritten and
  must be reviewed against this audit before publication.
- **Hardware-required:** SW-420 capture, second MPU6050 for manufacturing
  variation, longer independent rest runs, firmware CA verification, genuine
  industrial fault/field validation. Software tests cannot supply this evidence.

## 14. Next five actions

1. Repair and version network data construction: contiguous source runs,
   complete provenance, valid-node masks and source-independent calibration.
2. Rebuild the temporal/base-model chain and every dependent experiment in a
   separate artifact directory; retain and compare the archived baseline.
3. Evaluate hybrid and virtual-only at matched {2,3,5,10,15} observed nodes and
   regimes, then run local-only versus relational fusion under fixed FPR budgets.
4. Apply identical validation constraints to P1–P6 and retain all class recalls,
   false actions and calibration results before selecting a deployment policy.
5. Provision verified firmware TLS and harden HTTPS resource limits, then collect SW-420,
   independent MPU6050 rest/fault and same-model replication evidence.
