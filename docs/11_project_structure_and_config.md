# 11 — Project Structure and Configuration

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
