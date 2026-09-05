# 11 — Project Structure and Configuration

> **2026-09-05 audit update:** Authoritative implementation is flat src/, scripts/, JSON config and gateway-served dashboard. Network profiles and legacy runtime identities are separate experimental scopes. No standalone webapp_server.py exists.
> Current evidence and limitations: RESULTS §0.13.17.

> **AS-BUILT NOTE — this file's layout is NOT what's actually used.** The
> real repository keeps its original flat layout: `src/*.py` (one file per
> module/concern — `trust_engine.py`, `policy_engine.py`, `adaptive_pdp.py`,
> `fusion_engine.py`, `audit_log.py`, `gateway.py`, etc.), `scripts/*.py`
> for offline training/evaluation, `models/` for trained artifacts,
> `data/collected/` for generated datasets, `certs/` for TLS/broker
> credentials, `firmware/main.py` for the MicroPython firmware — see
> `README.md`'s "Project structure" section for the real, current tree.
> Configuration is `src/config.py` (Python, not `config.yaml`) — every
> setting below exists, just as a Python constant (e.g.
> `SECURITY_THRESHOLD`, `PROCESS_THRESHOLD`, `REPLAY_WINDOW_SECONDS`,
> `IDENTITY_TARGETING_RISK_THRESHOLD_60S`, `CHECKPOINT_INTERVAL_ROWS`) with
> an inline comment explaining its role, not a YAML tree. This is a
> deliberate, permanent deviation (see `00_overview.md`'s AS-BUILT
> callout), not a TODO — restructuring a large, already-tested codebase
> into packages/YAML for aesthetic consistency with this file was judged
> pure risk, no functional benefit. Section 5's "when hardware arrives"
> steps are accurate as written. **Section 2's dependency list below is
> NOT fully accurate** (corrected, not just flagged): no `torch-geometric`
> — `gnn_scorer.py`'s own docstring states the deliberate choice of a
> hand-rolled GCN instead (a 3-node graph doesn't need it, and the
> package's compiled extensions are a common source of broken installs);
> no `pyyaml` — there is no `config.yaml` to load, per this note's own
> first sentence. Two real, current dependencies missing from Section 2
> entirely: `joblib` (saving/loading every `sklearn`-based model) and
> `matplotlib` (`scripts/generate_evaluation_graphs.py`'s individual
> per-model comparison figures, `docs/figures/`). See `requirements.txt`
> for the authoritative, currently-accurate list.

## 1. Design-Time Repository Layout (not the real one — see note above)

```
zt-cps/
├── config.yaml                  # single source of truth, Section 3 below
├── requirements.txt              # Section 2 below
├── src/
│   ├── simulation/                # 01
│   ├── identity/                  # 02
│   ├── auth/                       # 03
│   ├── trust/                       # 04 (security_engine.py, process_engine.py, explain.py)
│   ├── verification/                # 05
│   ├── access_control/               # 06
│   ├── comms/                         # 07
│   ├── monitoring/                     # 08
│   └── gateway.py                       # main event loop wiring everything together
├── firmware/                     # empty for now — reserved for MicroPython code once
│                                    hardware arrives (see 01, Section 5)
├── data/
│   ├── audit.db                   # Module 7's SQLite file
│   └── datasets/                    # generated baseline/attack/train/val/test splits
├── certs/                          # 07 — CA and broker TLS certificates
├── tests/                            # one test module per src/ package, mirroring structure
└── docs/                              # this LLD set, kept alongside the code it describes
```

## 1.1 AS-BUILT: the real `src/` module inventory

One file per module or concern, flat, no packages. Every one of these is
imported by `gateway.py` on the live path **except** `device_simulator.py`
(a client, not part of the gateway) and `transformer_scorer.py` (an ablation
candidate deliberately not wired into fusion — see `04_module3_trust_evaluation.md`
§B.5b).

| Module | Lines | Role |
|---|---|---|
| `gateway.py` | 925 | PDP/PEP, both transports, dashboard + `/api/*`, silence watchdog |
| `config.py` | 571 | Every tunable, the device registry, all paths and thresholds |
| `trust_engine.py` | 491 | Security Trust + auth state (replay, step-up, silence, rotation, revocation, `IdentityTargetingRisk`) |
| `audit_log.py` | 338 | Hash-chained SQLite log + independent checkpoints |
| `device_simulator.py` | 316 | The two simulated devices (client side) |
| `governance_validation.py` | 260 | **NIST tenet validation** — falsifiable compliance checks, distinct from coverage |
| `iec62443_mapping.py` | 218 | IEC 62443 zones, conduits, FR status and coverage |
| `transformer_scorer.py` | 195 | Ablation candidate only — *not* a live fusion input |
| `gnn_scorer.py` | 179 | Relational Process Anomaly signal (hand-rolled GCN) |
| `adaptive_pdp.py` | 172 | RL bandit over the two-score state (inference live, training offline) |
| `lstm_ae_scorer.py` | 168 | Temporal Process Anomaly signal |
| `isolation_forest_scorer.py` | 117 | Point-anomaly Process Anomaly signal |
| `coap_server.py` | 114 | HTTPS second transport (substitutes for CoAP/DTLS) |
| `fusion_engine.py` | 109 | Stacking meta-learner + SHAP (Level 1) |
| `feature_engineering.py` | 89 | **Reference implementation** of the 5 features — firmware is checked against this |
| `explainability.py` | 81 | Level-2 orchestration across the scorers |
| `nist_mapping.py` | 56 | NIST tenet tagging (coverage) |
| `policy_engine.py` | 51 | The static 2×2 table |
| `secrets_local.py` | 31 | **Gitignored.** Real HMAC secrets + MQTT passwords; template is `secrets_local.example.py` |

Two boundaries in that table are load-bearing and easy to erase by accident:

- **`nist_mapping.py` vs `governance_validation.py`.** The first *tags* a
  decision with the tenets it is evidence for; the second *independently checks*
  whether the tagged claim holds. Coverage and validation answer different
  questions and are reported separately on purpose — merging them would hide
  which one a reader is getting. See `08_module7_monitoring_and_audit.md`.
- **`feature_engineering.py` is the reference, not just a helper.** The firmware
  computes the same five features on-device, and the models are trained against
  *this* file. Changing a formula here without re-verifying the firmware against
  it silently creates a train/serve skew that no offline evaluation can see
  (`01_simulation_and_hardware_abstraction.md` §5.2b).

## 2. Dependencies

```
paho-mqtt          # MQTT client (simulator, gateway)
scikit-learn        # Isolation Forest, logistic regression meta-learner, metrics
torch                # LSTM-Autoencoder
torch-geometric       # GNN (conditional)
shap                   # two-level explainability
streamlit                # dashboard
pyyaml                    # config.yaml loading
cryptography or pyOpenSSL  # certificate handling if not done purely via the openssl CLI
```

(MicroPython-side dependencies — `umqtt.simple`, `uhashlib` — are firmware concerns for later, not part of this Python dependency list.)

## 3. Consolidated `config.yaml`

This assembles every per-module snippet shown across Modules 1–7 into the one file the whole system actually reads.

```yaml
device_mode: simulation   # simulation | hardware — the ONLY switch between the two modes

simulation:
  num_devices: 3
  message_interval_seconds: 2
  time_scale: 1              # set higher (e.g. 100) during baseline generation to
                               # compress simulated days into real minutes

authentication:
  replay_window_seconds: 30
  key_rotation_grace_period_messages: 500
  step_up_challenge_timeout_seconds: 10

trust_evaluation:
  security_behaviour:
    rolling_window_seconds: 60
  process_anomaly:
    feature_window_size: 20   # AS-BUILT: 32 -- these design-time NUMBERS have also drifted from
    isolation_forest:          # config.py's real values, not just the yaml-vs-Python structure
      min_baseline_messages_before_training: 500   # AS-BUILT: n/a (offline training, not continuous)
      retrain_every_n_messages: 10000                # AS-BUILT: n/a (same reason)
    lstm_autoencoder:
      hidden_size: 24   # AS-BUILT: 16 (verified-not-assumed capacity-vs-overfitting result, SESSION_LOG.md §19)
      window_size: 20   # AS-BUILT: 8  (LSTM_SEQ_LEN)
    gnn:
      enabled: false   # AS-BUILT: true, live default (00_overview.md deviation #4) -- see
                         # 04_module3_trust_evaluation.md Section 2 for the full corrected block,
                         # including the new Transformer ablation-candidate config this file predates
      graph_mode: single_node_fallback   # AS-BUILT: multi_node (hybrid device-graph, gnn_scorer.py)

continuous_verification:
  decay_tick_seconds: 10
  silence_grace_period_seconds: 60
  decay_rate_per_second: 0.01
  minimum_decayed_security_score: 0.3
  maximum_decayed_anomaly_score: 0.7

access_control:
  security_threshold: 0.6
  anomaly_threshold: 0.6
  step_up_success_score_boost: 0.1
  adaptive_policy_enabled: false

secure_communication:
  broker_host: "localhost"
  broker_port_tls: 8883
  broker_port_plaintext: 1883
  ca_cert_path: "./certs/ca.crt"
  qos: 1

monitoring:
  db_path: "./data/audit.db"
  chain_verification_schedule_seconds: 300
  dashboard_refresh_seconds: 2
```

## 3.1 AS-BUILT: configuration constants that carry non-obvious consequences

Every setting is a Python constant in `src/config.py`. These particular ones
have caused real, measured failures when set wrong, so they are documented here
rather than left to an inline comment:

| Constant | Value | Why it matters |
|---|---|---|
| `PROCESS_THRESHOLD` | `0.6` | The live decision boundary for the Process Anomaly axis. **Note it is 0.6, while `scripts/evaluate_ablation.py` thresholds at 0.5** — a defect that only bit at 0.6 was therefore invisible to that evaluation (`RESULTS.md` §0.7). |
| `SECURITY_THRESHOLD` | `0.6` | Same for the Security Trust axis. |
| `REPLAY_WINDOW_SECONDS` | `600` | Widened from 30 because the board has no NTP route. Bounds only the *secondary* freshness check; `boot_id`/`seq` remains primary (`03_module2_authentication.md` §8.1). |
| `GNN_SELF_LOOP_WEIGHT` | `3.0` | Adjacency is `A + wI`. At the textbook `w=1` with 3 active nodes, a node's own evidence carries only 1/3 of its representation and neighbours dominate its verdict. Shared by training and inference — changing it without retraining silently invalidates the GNN. |
| `ISOLATION_FOREST_CONTAMINATION` | `0.1` | Defines where sklearn puts `decision_function == 0`, which is the anchor the score calibration is built on. Changing it requires retraining so the saved `raw_normal_median` anchor is regenerated. |
| `USE_RL_POLICY` | `True` | Selects the RL bandit over the static 2×2 table. Both are always available; the bandit *seeds unvisited states from the static table*, so the static policy is never fully out of the picture (`06_module5_access_control.md` §4.1). |
| `LSTM_SEQ_LEN` | `8` | The rolling window. Explains the ALERT "recovery tail" after a real disturbance: normal readings arriving within 8 samples of an anomaly still contain it, and are correctly scored low. Excluding these is what makes a false-positive rate meaningful (`RESULTS.md` §0.6). |
| `SILENCE_CHECK_INTERVAL_SECONDS` | `5` | The watchdog sweep. Nothing else makes staleness observable — the message-triggered path cannot detect a device that has stopped sending (`05_module4_continuous_verification.md`). |
| `CHECKPOINT_INTERVAL_ROWS` | `100` | How often an independent checkpoint is written. Sets the granularity at which the stronger tamper attacker is caught. |
| `DASHBOARD_ROWS_TO_FETCH` | `300` | The window the governance/IEC/decision panels summarise. A window this size can leave a validation check untestable (e.g. no rows below threshold on either axis) — the validator reports that rather than passing silently. |

### Model artifacts and their metadata sidecars

`models/` holds more than weights, and the sidecars are not optional:

| Artifact | Contains |
|---|---|
| `isolation_forest_<device>.joblib` | The fitted forest |
| `isolation_forest_<device>_meta.json` | **`raw_normal_median`** — the calibration anchor mapping `decision_function` to `[0,1]`. Without it the scorer falls back to the legacy mapping, which cannot express "normal" (`RESULTS.md` §0.1). |
| `lstm_ae_<device>.pt` | Autoencoder weights |
| `lstm_ae_<device>_meta.json` | Per-feature `mean`/`std` and the baseline reconstruction-error distribution used to turn error into a score |
| `gnn.pt` | GCN weights — **must** be regenerated if `normalized_adjacency()` or `GNN_SELF_LOOP_WEIGHT` changes |
| `fusion_meta_learner.joblib` + `fusion_background.npy` | The stacker and its SHAP background sample |
| `adaptive_pdp_qtable.json` | The trained Q-table; unvisited states are simply absent and are seeded from the static table at read time |

## 4. Build Order (Repeated From `00_overview.md` for Convenience)

1. `01` Simulation abstraction
2. `02` Device Identity + `03` Authentication
3. `07` Secure Communication
4. `04` Section A (Security Behaviour Engine) + Section B rule-based/Isolation-Forest only
5. `05` Continuous Verification + `06` Access Control — **core system complete**
6. `04` Section B — LSTM-Autoencoder, then conditionally the GNN
7. `04` Section B fusion meta-learner + Section C explainability
8. `06` optional adaptive policy stretch
9. `08` dashboard + governance mapping + `10` full evaluation

## 5. When Hardware Arrives

**AS-BUILT: the firmware itself is already written and the step-by-step
bring-up guide already exists** — see `firmware/HARDWARE_SETUP.md` for the
actual parts list, wiring, flashing, and first-boot verification steps;
the design-level summary below is superseded by that file for anything
hands-on.

1. Implement the firmware behaviour specified in `01_simulation_and_hardware_abstraction.md` Section 5.
2. Run the single integration test in Section 5.2 of that file first, before anything else — confirm the gateway's independently computed HMAC matches what the firmware sends for one real message.
3. Provision the device per `02_module1_device_identity.md` Section 4.2.
4. **AS-BUILT: no `device_mode` flag exists** — instead, add the device's
   id to `config.REAL_HARDWARE_DEVICE_IDS` (e.g.
   `{"esp32-vib-001"}`), which tells `device_simulator.py` to stop also
   publishing under that same identity (see `firmware/HARDWARE_SETUP.md`
   Section 11). No other file changes.
5. Re-run the Phase 1–9 acceptance criteria from each module file against the real device, alongside (not instead of) the simulated devices — the simulator remains useful afterward for generating attack scenarios that would be impractical to physically stage.

This is the last file in this set. Return to `00_overview.md` for the full index if needed.
