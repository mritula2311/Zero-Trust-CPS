# Zero-Trust CPS Starter Kit

A working implementation of the full Zero-Trust pipeline from
`docs/Zero_Trust_CPS_Project_Synopsis.docx` (the citable academic record),
`CLAUDE.md` (the governing engineering brief), and `docs/00_overview.md`
onward (the low-level design set). This is not a mockup — real MQTT/TLS +
a second secured transport, real **mutual** HMAC authentication
(device→gateway and gateway→device, both independently verified,
gateway→device now with a genuine step-up nonce/echo challenge round
trip), boot_id/seq anti-replay, **two permanently-separate scores**
(Security Trust + Process Anomaly — never blended into one number until
the final policy step), four real ML Process Anomaly signals (rule-based,
Isolation Forest, LSTM-Autoencoder, GNN — GPU-accelerated when available)
fused by a real stacking meta-learner with a full per-signal SHAP
breakdown, a real offline-trained RL-adaptive policy over the two-score
state, a hash-chained + independently-checkpointed audit log, NIST SP
800-207 + IEC 62443 governance mapping, and a real live dashboard (served
by `gateway.py` itself, no separate script) — all logged to SQLite.

**Coding agent, or new to the codebase? Start with
`ZERO_TRUST_CPS_KB.md`** — the single-source-of-truth knowledge base:
architecture, module boundaries (including what each module explicitly
does NOT do), data schemas, the full ADR decision log explaining why each
design is the way it is, measured evaluation numbers, and the known
limitations. It exists specifically so that a new engineer or an agent
does not "fix" an intended design.

**First time here? Read `docs/00_overview.md`** for the master overview of
the as-built architecture (start there, then the module files in numeric
order), **`RESULTS.md`** for every real measured number this project has
produced (with a reserved, clearly-marked section for hardware-in-the-loop
results once the physical board is flashed), or **`SESSION_LOG.md`** for
the full blow-by-blow story of how this project got to its current state,
in order — including every bug found and fixed along the way, most
recently the two-score rearchitecture. This README is the quick-start.

## What this does right now

Three devices — one real (`esp32-vib-001`, MicroPython firmware on an
ESP32 + MPU6050, one physical sensor, no separate vibration sensor) and
two simulated (`sensor-002`, `actuator-001`, carried over from the
original starter kit) — publish
signed telemetry, each with a `boot_id`/`seq` pair for anti-replay. The
gateway checks identity, HMAC, boot/seq freshness, and a secondary
timestamp window; anything that fails is REJECTED and routed to a
per-claimed-device `IdentityTargetingRisk` counter, never to that device's
own trust state (the fix for a real trust-poisoning vulnerability — see
`docs/03_module2_authentication.md` Section 5). Everything that passes is
scored on **two independent axes**: a lightweight rule-based **Security
Trust Score** (cyber-behaviour evidence only — rate/flood, step-up
outcomes, silence) and a **Process Anomaly Score** (physical sensor
evidence only — rule-based range check + Isolation Forest + LSTM-
Autoencoder + GNN, fused by a stacking meta-learner with a full per-signal
SHAP breakdown). The two scores meet **only** inside a 2×2 policy table
(static, or an offline-trained RL bandit reading the same two-dimensional
state) producing `ALLOW` / `ALERT` / `STEP_UP` / `BLOCK` — `STEP_UP` now
triggers a real gateway-issued nonce the device must echo back, not just a
label. Every step is logged, hash-chained (with a separately-stored,
separately-keyed checkpoint catching an attacker who rewrites the in-DB
chain consistently), and tagged with which NIST SP 800-207 tenets and IEC
62443 Foundational Requirements it's evidence for — to SQLite and a real
live dashboard, `gateway.py`-served, no separate script.

**Everything in Module 3's ML pipeline (Isolation Forest, LSTM-AE, GNN,
fusion, RL policy) is trained OFFLINE** (`scripts/train_*.py`) and only
ever runs inference at the gateway — this is a hard constraint, not a
suggestion (see `CLAUDE.md` Section 8). LSTM-AE, GNN, and the Transformer
ablation candidate (below) training/inference auto-detect and use a CUDA
GPU if one is present (`torch.cuda.is_available()` in
`lstm_ae_scorer.py`/`gnn_scorer.py`/`transformer_scorer.py`), falling back
to CPU cleanly if not — no code changes needed either way.

A fifth Process Anomaly candidate, a small Transformer encoder
(`transformer_scorer.py`/`train_transformer.py`), was added, fairly
evaluated against the LSTM-AE, and genuinely wins by a small margin — but
is **not** wired into the live fusion inputs; see `RESULTS.md` Section 2.2
for the full comparison and the reasoning for not adopting it.

Two ways to feed it telemetry:

- **Software simulation** (`src/device_simulator.py`) — no hardware
  needed, fastest way to see it work. Injects a forged signature, an
  out-of-range value, an in-range-but-anomalous shock, a replayed
  message, a device reboot, a rapid-fire flood burst (triggers a real
  step-up challenge), and a "stealthy" fully-valid-but-fabricated reading
  on a rotation, so you can watch both scores react (or, for the stealthy
  case, honestly fail to react — see
  `docs/04_module3_trust_evaluation.md` Section B.8).
- **Real hardware** — one ESP32 + MPU6050 running `firmware/main.py`
  (MicroPython), publishing as `esp32-vib-001`. **Flashed, authenticated,
  and running live** (not just software-verified) — `config.
  REAL_HARDWARE_DEVICE_IDS = {"esp32-vib-001"}` is set, so
  `device_simulator.py` skips this device and the real board is the sole
  source of its telemetry. **`firmware/HARDWARE_SETUP.md`** is the
  complete, step-by-step bring-up guide (parts list, wiring, Thonny
  flashing, secret provisioning, the critical first HMAC integration test,
  and folding real captured data back into the trained models via
  `scripts/collect_hardware_session.py`/`merge_real_hardware_data.py`) —
  see `RESULTS.md`'s hardware-in-the-loop section for the real measured
  before/after retraining numbers, and `SESSION_LOG.md` for the full
  bring-up story (every bug hit and fixed along the way).

**Start with `METHODOLOGY.md`** — it states the method, every mathematical
expression with the reason it is required rather than arbitrary, the evaluation
protocol, the novelty claims and the limitations. `RESULTS.md` holds the measured
numbers behind it.

See `SESSION_LOG.md` (append-only, read top-to-bottom) for the full,
narrated status — every substitution made (CoAP/DTLS → HTTPS; GNN's graph
choice; hand-rolled GCN vs. `torch-geometric`) and everything genuinely
still TODO. Operator-labelled hardware capture is **done**: four sessions,
429 records, six physical event classes (rest, gentle tap, tilt, moderate
shake, sharp impact, and a sustained no-contact fault), labels marked by the
operator at the moment of each action rather than inferred from a timetable.
Measured on it: detection of real physical disturbance **100% (103/103)**,
false positives on a genuinely resting board **1/29 (3.4%)**, Wilson 95% CI
[0.6%, 17.2%] (`RESULTS.md` 0.10.10). The real at-rest rows are only **3%**
of the training normals but they carry the result: retraining the whole
chain without them gives **13/49** false positives instead of 0/49,
detection unchanged (`RESULTS.md` 0.10.9).

**Adversarial testing is now live, not synthetic**: five hostile MQTT attacks
delivered over the real transport against a running gateway, all rejected at
Module 1/2 — and the exercise found and fixed a real state-mutation
vulnerability (`RESULTS.md` 0.10.17). Physical *fault* injection on hardware
(a worn bearing rather than a bench disturbance) remains genuine future work.
See `PRD.md` for the full product requirements and `docs/00_overview.md`
onward for the as-built architecture reference.

## Setup

**Broker hardening (per-device credentials + topic ACLs, IEC 62443 FR5)**:
`certs/mosquitto_passwd`/`mosquitto_acl` are already generated and the
code auto-detects them — one manual step remains, needing your admin
PowerShell to edit `mosquitto.conf` itself. See
`docs/07_module6_secure_communication.md` Section 3 for the exact
`mosquitto.conf` shape and verification steps. Everything below works with
or without that step done; it's the difference between the broker being
*capable* of enforcing "no implicit trust" at the transport layer and
actually *doing* it.

**1. Install a local MQTT broker** (one-time, on your own machine):

```bash
# Ubuntu/Debian/WSL:
sudo apt-get install mosquitto mosquitto-clients
sudo systemctl start mosquitto        # or just: mosquitto -d

# macOS:
brew install mosquitto
brew services start mosquitto

# Windows: download the installer from https://mosquitto.org/download/,
# or `winget install EclipseFoundation.Mosquitto`
```

**2. Install Python dependencies:**

```bash
python -m venv venv
source venv/bin/activate      # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

**3. TLS certs** (needed for MQTT/TLS and the HTTPS second transport —
see `docs/07_module6_secure_communication.md` Section 3 for the exact
`openssl` commands; both transports share the same self-signed CA in
`certs/`). Both `config.MQTT_USE_TLS` and
`config.COAP_ENABLED` auto-detect based on whether `certs/` is populated —
nothing to toggle manually once the certs exist.

**4. Train the offline models** (one-time, or whenever you regenerate
training data — takes under a minute either way; a CUDA GPU speeds up
LSTM-AE/GNN/Transformer training if present, but is entirely optional —
all fall back to CPU automatically, see `requirements.txt`'s GPU install
note if you have an NVIDIA card and want it):

```bash
cd src   # scripts/ imports assume this
cd ../scripts
python generate_training_data.py
python train_isolation_forest.py
python train_lstm_ae.py
python train_gnn.py
python train_fusion_meta_learner.py
python train_adaptive_pdp.py
python train_transformer.py   # optional -- ablation candidate only, see RESULTS.md Section 2.2;
                                # not a dependency of any other script, can be run in any order
```

Run the first six in that exact order — each later script replays the
training session through the previously-trained models to build its own
training set (e.g. the fusion meta-learner needs Isolation Forest/LSTM-AE/GNN's
outputs as its own input features).

## Run it

Open two terminals in the `src/` folder:

```bash
# Terminal 1
python gateway.py

# Terminal 2 (a couple seconds later)
python device_simulator.py
```

Watch Terminal 1. Every ~2 seconds you'll see a line per device, showing
both the Security Trust and Process Anomaly scores independently. Every
few ticks you'll see the simulator inject a bad reading, a forged
signature, a replayed message, a reboot, a flood burst (watch it trigger a
real step-up challenge), or a stealthy fabricated reading — watch both
scores and the decision react. Stop both with Ctrl+C whenever you like.

Have real hardware? Follow `firmware/HARDWARE_SETUP.md` end to end, then
add `esp32-vib-001` to `config.REAL_HARDWARE_DEVICE_IDS` so
`device_simulator.py` stops also publishing under that same identity (the
two would otherwise race on `boot_id`/`seq` and intermittently reject each
other's messages as replays) — `device_simulator.py` keeps simulating
`sensor-002`/`actuator-001` fine alongside your real board either way. The
gateway itself needs zero code changes either way — this has actually been
run against a real ESP32 + MPU6050, see `RESULTS.md` Section 13.

Check what got logged:

```bash
python -c "import audit_log; [print(r) for r in audit_log.recent(10)]"
```

For a NIST SP 800-207 governance-completeness view (which proportion of
logged decisions are traceable evidence for each of the 7 tenets,
currently 100%/7-of-7) and an IEC 62443-3-3 Foundational Requirements
coverage view (FR1-FR7; FR1-4/6 implemented, FR5/FR7 honestly marked
**partial** — real transport-layer controls exist for both, but full
physical segmentation/redundancy don't), run:

```bash
cd scripts
python evaluate_governance.py
python evaluate_iec62443.py
```

**`design/zero-trust-cps-command-center.html`** is served live by
`gateway.py` itself — no separate dashboard script. The whole page is
live: it polls the `/api/*` endpoints `gateway.py` serves and renders
per-device Security Trust + Process Anomaly scores with their SHAP
attribution, a rolling decision stream, chain-verification status, NIST
tenet coverage with the audit-row counts backing each number, IEC 62443 FR
status, Identity Targeting Risk, step-up activity, and the deployed RL
Q-table. Each panel carries a short "how to read this" note, so the page
explains itself without the design docs open.

There is no overlay-injection step any more, and no static canvas
underneath: the earlier 2.2MB flattened design-canvas export (whose device
names were a stale snapshot) has been deleted, and the page above replaces
it outright. The canvas *source* it was exported from is still in
`design/canvas.json` and `design/Main.dc.html` if it ever needs
regenerating.

Just run the gateway (Terminal 1 above) and open:

```text
http://localhost:8600
```

`gateway.py` also serves a `/figures` gallery page of every generated PNG
(see Evaluate it below), linked from the dashboard header.

Note the ML scorers need `models/` populated (see Setup step 4) — without
trained artifacts, every scorer falls back to a neutral default and the
gateway console shows `(fusion model not trained yet)`. That's expected
before training, not a bug.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

33 tests, stdlib `unittest` — no install needed. They do not chase coverage:
**every test guards a property that has already been broken once in this
repository**, and each docstring names the incident it protects against (the
Isolation Forest calibration, firmware-to-reference feature equivalence,
canonicalisation drift, GNN adjacency, the RL estimator and its static fallback,
audit tamper detection, quarantine escalation, and whether the governance checks
can actually fail). Tests touching the audit log work on a temp copy; the real
`data/audit_log.db` is never written to.

## Evaluate it (for the report)

**`RESULTS.md`** already has every number below, with full explanations,
caveats, and a reserved section for hardware results — read that first.
To reproduce or regenerate them yourself, once the models are trained,
`scripts/evaluate_*.py` produce the evaluation deliverables against a
held-out test set:

```bash
cd scripts
python generate_test_data.py       # held-out set, different seed from training data
python evaluate_ablation.py        # fused Process Anomaly score vs. each individual signal's accuracy
python evaluate_latency.py         # HMAC + full-pipeline latency on this machine
python evaluate_explainability.py  # Level 1: SHAP top-feature vs. ground-truth cause
python evaluate_explainability_level2.py  # Level 2: perturb the named feature, does the score recover?
python evaluate_rl_policy.py       # static vs. RL reward, multi-class confusion matrix, convergence trend
python evaluate_governance.py      # NIST SP 800-207 completeness report
python evaluate_iec62443.py        # IEC 62443-3-3 FR coverage + SL self-assessment
python evaluate_trust_responsiveness.py   # how fast each of the two scores reacts to each attack type
python generate_evaluation_graphs.py      # 20 individual PNG figures covering every comparison
                                            # above, plus governance coverage, RL convergence,
                                            # dataset balance, threshold sensitivity, and training
                                            # loss curves -> docs/figures/ (see RESULTS.md's Figure
                                            # Index for what each one is and which section it's from)
```

Read `docs/12_model_validation_and_justification.md` for a research-
methodology writeup of every model above (purpose, why that architecture,
what the validation actually establishes, what it doesn't) and
`docs/13_system_architecture_and_workflow.md` for the whole-system
diagrams. With the gateway running, `http://localhost:8600/figures` also
serves a gallery page of every generated PNG, linked from the dashboard
header.

## Project structure

```
zt-cps-starter/
├── SESSION_LOG.md          <- the full story, in order (24+ entries)
├── RESULTS.md               <- every real measured result, with explanations + a reserved hardware section
├── README.md                 <- you are here
├── CLAUDE.md                  <- governing engineering brief
├── requirements.txt            <- incl. GPU install note
├── docs/
│   ├── Zero_Trust_CPS_Project_Synopsis.docx   <- the citable academic record
│   │                                              (not yet updated for the two-score
│   │                                              rearchitecture — see SESSION_LOG.md)
│   ├── 00_overview.md             <- START HERE — master as-built architecture overview
│   ├── 01_simulation_and_hardware_abstraction.md
│   ├── 02_module1_device_identity.md
│   ├── 03_module2_authentication.md
│   ├── 04_module3_trust_evaluation.md
│   ├── 05_module4_continuous_verification.md
│   ├── 06_module5_access_control.md
│   ├── 07_module6_secure_communication.md
│   ├── 08_module7_monitoring_and_audit.md
│   ├── 09_integration_and_data_flow.md
│   ├── 10_testing_and_attack_simulation.md
│   ├── 11_project_structure_and_config.md   <- read its AS-BUILT note; real layout is below, not what it recommends
│   ├── 12_model_validation_and_justification.md   <- every model's purpose/why/validation, research-methodology writeup
│   ├── 13_system_architecture_and_workflow.md      <- whole-system diagrams (architecture, sequence, training pipeline)
│   └── figures/                              <- scripts/generate_evaluation_graphs.py's PNG output
├── design/
│   ├── zero-trust-cps-command-center.html   <- fully live dashboard, served by gateway.py (http://localhost:8600)
│   ├── Main.dc.html                          <- editable source (can't run standalone, missing runtime)
│   └── canvas.json
├── firmware/
│   ├── main.py               <- MicroPython, runs on the real ESP32 (flashed, authenticated, running live)
│   ├── HARDWARE_SETUP.md      <- step-by-step bring-up guide: parts, wiring, flashing, secrets, first-boot test
│   └── HARDWARE_DATA_LOG.md   <- latest real-data collection session summary (scripts/collect_hardware_session.py output)
├── certs/                   <- self-signed CA + server cert + mosquitto_passwd/acl
├── models/                  <- offline-trained artifacts (scripts/train_*.py output)
├── data/collected/          <- training/test sessions (scripts/generate_*.py output)
└── src/
    ├── config.py                    <- all tunable settings
    ├── device_simulator.py          <- Modules 1, 2, 6 (software device stand-in, verifies mutual auth)
    ├── gateway.py                   <- ties everything together (run this first)
    ├── trust_engine.py              <- Module 2 (boot/seq replay, IdentityTargetingRisk, step-up) +
    │                                    Module 3 Section A (Security Trust) + Module 4 (both scores' state store)
    ├── feature_engineering.py       <- Section 5.1's 5-feature vibration vector
    ├── isolation_forest_scorer.py   <- Module 3, Phase 6a (inference-only)
    ├── lstm_ae_scorer.py            <- Module 3, Phase 6b (inference-only, GPU-capable)
    ├── gnn_scorer.py                <- Module 3, Phase 6c (inference-only, GPU-capable)
    ├── transformer_scorer.py        <- Module 3, Section B.5b -- ABLATION CANDIDATE ONLY, not a
    │                                    fusion_engine.py input (inference-only, GPU-capable)
    ├── fusion_engine.py             <- Module 3 Section B — stacking + full per-signal SHAP (Level 1) -> Process Anomaly Score (inference-only)
    ├── explainability.py            <- Module 3 Section C.3/C.4 — Level-2 (per-signal feature/node) drill-down,
    │                                    orchestrates each scorer's level2_explain(), called from gateway.py
    ├── policy_engine.py             <- Module 5 — static 2x2 table (security_trust, process_trust -> ALLOW/ALERT/STEP_UP/BLOCK)
    ├── adaptive_pdp.py              <- Module 5 — RL bandit over the same 2x2 state (inference-only, live default)
    ├── nist_mapping.py              <- NIST SP 800-207 tenet mapping
    ├── iec62443_mapping.py          <- IEC 62443-3-3 zones/conduits + FR coverage + SL assessment
    ├── audit_log.py                 <- Module 7
    └── coap_server.py               <- Module 6's second secured transport (HTTPS)
└── scripts/
    ├── generate_training_data.py / generate_test_data.py
    ├── collect_hardware_session.py  <- captures a real esp32-vib-001 session. --labelled (the one to use)
    │                                    has the operator mark each event's start/stop; samples outside a
    │                                    marked interval are discarded, not guessed at. Also 5 timed phases
    │                                    or one --long free-form window. Joins in gateway.py's live scoring
    ├── merge_real_hardware_data.py  <- folds all collected real sessions into training_session.json
    │                                    alongside the synthetic data, idempotent, safe to re-run
    ├── train_isolation_forest.py / train_lstm_ae.py / train_gnn.py
    ├── train_fusion_meta_learner.py / train_adaptive_pdp.py
    ├── train_transformer.py   <- ablation candidate only, RESULTS.md Section 2.2
    ├── evaluate_ablation.py / evaluate_latency.py
    ├── evaluate_explainability.py / evaluate_explainability_level2.py   <- Level 1 / Level 2
    ├── evaluate_rl_policy.py / evaluate_governance.py / evaluate_iec62443.py
    ├── evaluate_trust_responsiveness.py
    └── generate_evaluation_graphs.py   <- individual PNG figures -> docs/figures/
```

## How this maps to your report

| Report section | Where it is in this code |
|---|---|
| 4.3 Module 1 — Device Identity | `config.DEVICE_REGISTRY` (hybrid: 1 real + 2 simulated), checked in `gateway.verify_signature()` |
| 4.3 Module 2 — Authentication | HMAC-SHA256, **mutual**: `device_simulator.sign()`/`firmware/main.py` (device→gateway) + `gateway._sign_decision()` verified by `device_simulator.verify_decision_signature()`/`firmware/main.py`'s `verify_decision_signature()` (gateway→device) |
| 4.3 Module 2 (cont.) — boot/seq replay + attribution | `trust_engine.check_boot_replay()`/`check_timestamp_freshness()`; `trust_engine.IdentityTargetingRisk` (failed attempts routed away from any device's own score, `gateway.py::_reject()`) |
| 4.3 Module 3 — Trust Evaluation | **Two independent scores.** Security Trust: `trust_engine.score_security_trust()` (rate/flood/step-up only). Process Anomaly: `trust_engine.rule_range_score()` + `isolation_forest_scorer` + `lstm_ae_scorer` + `gnn_scorer`, combined by `fusion_engine.FusionEngine` |
| 4.3 Module 4 — Continuous Verification | Security Trust: EWMA + time-decay in `score_security_trust()`. Process Anomaly: retained exactly on silence, only `FRESH`/`STALE` status changes (`update_process_anomaly()`/`get_process_anomaly()`) |
| 4.3 Module 5 — Access Control | `policy_engine.decide(security_trust, process_trust, process_status)` (2×2 table) or `adaptive_pdp.AdaptivePDP` (RL, live default) — toggle via `config.USE_RL_POLICY`; `STEP_UP` now triggers a real step-up challenge (`gateway.py::initiate_step_up()`) |
| 4.3 Module 6 — Secure Communication | MQTT/TLS (+ per-device broker credentials/ACLs, now including `cps/challenge/*`) + HTTPS (`coap_server.py` — see its docstring for why HTTPS substitutes for CoAP/DTLS) |
| 4.3 Module 7 — Monitoring | `audit_log.py` (hash-chained + independently checkpointed) + `nist_mapping.py` + `iec62443_mapping.py` |
| Figure 4.1 — Fusion Engine + SHAP | `fusion_engine.py` (full per-signal SHAP breakdown, not just the top feature) — feeds the Process Anomaly Score only |
| Section 7.3 — Governance mapping | `nist_mapping.py` + `iec62443_mapping.py`, the live dashboard's governance view, `scripts/evaluate_governance.py`/`evaluate_iec62443.py` |
| Section 10.1 — Evaluation | `scripts/evaluate_*.py` produce the numbers; **`RESULTS.md`** is the written-up, paper-ready record of all of them, including the hardware-in-the-loop results section |

Next: **`docs/00_overview.md`** for the complete as-built architecture
reference, or **`SESSION_LOG.md`** for the full narrated story and exact
current status.
