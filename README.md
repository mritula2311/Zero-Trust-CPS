# Zero-Trust CPS Starter Kit

A working implementation of the full Zero-Trust pipeline from
`docs/Zero_Trust_CPS_Project_Synopsis.docx` (the citable academic record)
and `CLAUDE.md` (the governing engineering brief). This is not a mockup —
real MQTT/TLS + a second secured transport, real **mutual** HMAC
authentication (device→gateway and gateway→device, both independently
verified), four real ML trust signals (rule-based, Isolation Forest,
LSTM-Autoencoder, GNN — GPU-accelerated when available) fused by a real
stacking meta-learner with a full per-signal SHAP breakdown, a real
offline-trained RL-adaptive policy, NIST SP 800-207 + IEC 62443 governance
mapping, and two real live dashboards — all logged to SQLite.

**First time here? Read `docs/09_project_report.md`** for the complete,
polished project report (architecture, methodology, results, governance,
and what's still pending real hardware), or **`SESSION_LOG.md`** for the
full blow-by-blow story of how this project got to its current state, in
order — including every bug found and fixed along the way. This README is
the quick-start; `docs/05_phase_status.md` is the point-in-time
architecture/compliance status.

## What this does right now

Three devices — one real (`esp32-vib-001`, MicroPython firmware on an
ESP32 + MPU6050 + vibration sensor) and two simulated (`sensor-002`,
`actuator-001`, carried over from the original starter kit) — publish
signed telemetry. The gateway verifies identity and signature, checks
message freshness (replay protection), runs the reading through three ML
anomaly scorers plus a rule-based check, fuses all four via a stacking
meta-learner (every signal's real SHAP contribution logged, not just the
top one, with a `confidence` measure), blends the result into a
continuously-updated trust score via EWMA, and makes an ALLOW / STEP_UP /
DENY decision using either static thresholds or an offline-trained RL
bandit — logging every step, tagged with which NIST SP 800-207 tenets and
IEC 62443 Foundational Requirements it's evidence for, to SQLite and two
live dashboards (Streamlit and a from-scratch local web dashboard). The
gateway signs its decisions back to the device too, so authentication is
genuinely mutual, not just device→gateway.

**Everything in Module 3's ML pipeline (Isolation Forest, LSTM-AE, GNN,
fusion, RL policy) is trained OFFLINE** (`scripts/train_*.py`) and only
ever runs inference at the gateway — this is a hard constraint, not a
suggestion (see `CLAUDE.md` Section 8). LSTM-AE and GNN training/inference
auto-detect and use a CUDA GPU if one is present (`torch.cuda.is_available()`
in `lstm_ae_scorer.py`/`gnn_scorer.py`), falling back to CPU cleanly if
not — no code changes needed either way.

Two ways to feed it telemetry:

- **Software simulation** (`src/device_simulator.py`) — no hardware
  needed, fastest way to see it work. Injects a forged signature, an
  out-of-range value, an in-range-but-anomalous shock, and a replayed
  message on a rotation, so you can watch the trust score react to each.
- **Real hardware** — one ESP32 + MPU6050 + vibration sensor running
  `firmware/main.py` (MicroPython), publishing as `esp32-vib-001`. See
  `docs/06_hardware_setup.md` for a complete beginner's guide (Thonny,
  wiring diagrams, everything).

See `docs/05_phase_status.md` for the full phase-by-phase status,
including the four documented substitutions (CoAP/DTLS → HTTPS; GNN's
graph choice; hand-rolled GCN vs. `torch-geometric`; mutual-but-not-
interactive-challenge-response authentication) and what's genuinely still
TODO (flashing real hardware, a real physical adversarial-testing
session) — see `docs/09_project_report.md`'s "Pending Hardware
Validation" section for the complete, explicitly-marked list of gaps.

## Setup

**Broker hardening (per-device credentials + topic ACLs, IEC 62443 FR5)**:
`certs/mosquitto_passwd`/`mosquitto_acl` are already generated and the
code auto-detects them — one manual step remains, needing your admin
PowerShell to edit `mosquitto.conf` itself. See
`docs/07_transport_zero_trust.md` for the exact diff and verification
steps. Everything below works with or without that step done; it's the
difference between the broker being *capable* of enforcing "no implicit
trust" at the transport layer and actually *doing* it.

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
see `docs/03_add_tls.md` for the exact `openssl` commands; both transports
share the same self-signed CA in `certs/`). Both `config.MQTT_USE_TLS` and
`config.COAP_ENABLED` auto-detect based on whether `certs/` is populated —
nothing to toggle manually once the certs exist.

**4. Train the offline models** (one-time, or whenever you regenerate
training data — takes under a minute either way; a CUDA GPU speeds up
LSTM-AE/GNN training if present, but is entirely optional — both fall
back to CPU automatically, see `requirements.txt`'s GPU install note if
you have an NVIDIA card and want it):

```bash
cd src   # scripts/ imports assume this
cd ../scripts
python generate_training_data.py
python train_isolation_forest.py
python train_lstm_ae.py
python train_gnn.py
python train_fusion_meta_learner.py
python train_adaptive_pdp.py
```

Run them in that exact order — each later script replays the training
session through the previously-trained models to build its own training
set (e.g. the fusion meta-learner needs Isolation Forest/LSTM-AE/GNN's
outputs as its own input features).

## Run it

Open two terminals in the `src/` folder:

```bash
# Terminal 1
python gateway.py

# Terminal 2 (a couple seconds later)
python device_simulator.py
```

Watch Terminal 1. Every ~2 seconds you'll see a line per device. Every
~12-15 ticks you'll see the simulator inject a bad reading, a forged
signature, or a replayed message — watch the trust score and decision
react. Stop both with Ctrl+C whenever you like.

Have real hardware? Skip `device_simulator.py` and flash `firmware/main.py`
instead — see `docs/06_hardware_setup.md`. The gateway doesn't change
either way; `device_simulator.py` still simulates `sensor-002`/`actuator-001`
fine alongside your real board.

Check what got logged:

```bash
python -c "import audit_log; [print(r) for r in audit_log.recent(10)]"
```

Or watch it live in a browser (Terminal 3, while the gateway + a telemetry
source are running):

```bash
streamlit run dashboard.py
```

The dashboard also shows a live NIST SP 800-207 governance-completeness
view (which proportion of logged decisions are traceable evidence for
each of the 7 tenets, currently 100%/7-of-7) and an IEC 62443-3-3
Foundational Requirements coverage view (FR1-FR7; FR1-4/6 implemented,
FR5/FR7 honestly marked **partial** — real transport-layer controls exist
for both, but full physical segmentation/redundancy don't, see that
view's gap notes) right below it, plus the SL-2 security-level
self-assessment.

**Prefer a more polished visual demo?** `webapp_server.py` (Terminal 3
instead of Streamlit) serves a from-scratch local rebuild of the earlier
Claude Design mockup — same dark cyan/amber aesthetic, but reading 100%
real live data instead of the mockup's client-side fake numbers (that
page was a claude.ai artifact, which can't reach `localhost` at all — see
`SESSION_LOG.md` §10 for why):

```bash
python webapp_server.py
```

Then open `http://localhost:8600`. It shows everything Streamlit's does,
plus the real trained RL Q-table. Both dashboards read the same
`audit_log.db` — run either one, or both side by side.

Note the ML scorers need `models/` populated (see Setup step 4) — without
trained artifacts, every scorer falls back to a neutral default and the
gateway console shows `(fusion model not trained yet)`. That's expected
before training, not a bug.

## Evaluate it (for the report)

Once the models are trained, `scripts/evaluate_*.py` produce the
synopsis Section 10.1 evaluation deliverables against a held-out test set:

```bash
cd scripts
python generate_test_data.py       # held-out set, different seed from training data
python evaluate_ablation.py        # fused score vs. each individual signal's accuracy
python evaluate_latency.py         # HMAC + full-pipeline latency on this machine
python evaluate_explainability.py  # SHAP top-feature vs. ground-truth cause
python evaluate_rl_policy.py       # static vs. RL reward, convergence trend
python evaluate_governance.py      # NIST SP 800-207 completeness report
python evaluate_iec62443.py        # IEC 62443-3-3 FR coverage + SL self-assessment
python evaluate_trust_responsiveness.py   # how fast the EWMA trust score reacts to each attack type
```

## Project structure

```
zt-cps-starter/
├── SESSION_LOG.md          <- the full story, in order (19 entries)
├── README.md               <- you are here
├── CLAUDE.md                <- governing engineering brief
├── requirements.txt          <- incl. GPU install note
├── docs/
│   ├── Zero_Trust_CPS_Project_Synopsis.docx   <- the citable academic record
│   ├── 01_getting_started.md
│   ├── 02_understand_the_pipeline.md
│   ├── 03_add_tls.md
│   ├── 04_next_phases.md          <- original Phase 6-9 plan (superseded, kept for reference)
│   ├── 05_phase_status.md         <- authoritative architecture/compliance status
│   ├── 06_hardware_setup.md       <- complete beginner's guide (Thonny, wiring, everything)
│   ├── 07_transport_zero_trust.md <- MQTT broker hardening (FR5/FR7), admin PowerShell steps
│   ├── 08_results_and_evaluation.md <- every real measured result, paper-ready
│   └── 09_project_report.md       <- READ THIS FIRST — the complete project report
├── implementation-docs/    <- module-by-module reference (Part A core + Part B design)
├── firmware/
│   └── main.py              <- MicroPython, runs on the real ESP32 (mutual-auth verified in software)
├── certs/                   <- self-signed CA + server cert + mosquitto_passwd/acl
├── models/                  <- offline-trained artifacts (scripts/train_*.py output)
├── data/collected/          <- training/test sessions (scripts/generate_*.py output)
└── src/
    ├── config.py                    <- all tunable settings
    ├── device_simulator.py          <- Modules 1, 2, 6 (software device stand-in, verifies mutual auth)
    ├── gateway.py                   <- ties everything together (run this first)
    ├── trust_engine.py              <- Module 3 (rule-based) + 4 (EWMA/continuous + replay/flood checks)
    ├── feature_engineering.py       <- Section 5.1's 5-feature vibration vector
    ├── isolation_forest_scorer.py   <- Module 3, Phase 6a (inference-only)
    ├── lstm_ae_scorer.py            <- Module 3, Phase 6b (inference-only, GPU-capable)
    ├── gnn_scorer.py                <- Module 3, Phase 6c (inference-only, GPU-capable)
    ├── fusion_engine.py             <- Module 3, Phase 7 — stacking + full per-signal SHAP (inference-only)
    ├── policy_engine.py             <- Module 5, Phase 5 static thresholds
    ├── adaptive_pdp.py              <- Module 5, Phase 8 RL bandit (inference-only)
    ├── nist_mapping.py              <- NIST SP 800-207 tenet mapping
    ├── iec62443_mapping.py          <- IEC 62443-3-3 zones/conduits + FR coverage + SL assessment
    ├── audit_log.py                 <- Module 7
    ├── dashboard.py                 <- Phase 9 live dashboard (Streamlit) + governance view
    ├── webapp_server.py             <- Phase 9, second live dashboard (stdlib HTTP + webapp/index.html)
    └── coap_server.py               <- Module 6's second secured transport (HTTPS)
└── scripts/
    ├── generate_training_data.py / generate_test_data.py
    ├── train_isolation_forest.py / train_lstm_ae.py / train_gnn.py
    ├── train_fusion_meta_learner.py / train_adaptive_pdp.py
    └── evaluate_ablation.py / evaluate_latency.py / evaluate_explainability.py
        / evaluate_rl_policy.py / evaluate_governance.py / evaluate_iec62443.py
        / evaluate_trust_responsiveness.py
```

## How this maps to your report

| Report section | Where it is in this code |
|---|---|
| 4.3 Module 1 — Device Identity | `config.DEVICE_REGISTRY` (hybrid: 1 real + 2 simulated), checked in `gateway.verify_signature()` |
| 4.3 Module 2 — Authentication | HMAC-SHA256, **mutual**: `device_simulator.sign()`/`firmware/main.py` (device→gateway) + `gateway._sign_decision()` verified by `device_simulator.verify_decision_signature()`/`firmware/main.py`'s `verify_decision_signature()` (gateway→device) |
| 4.3 Module 3 — Trust Evaluation | `trust_engine.rule_range_score()` + `isolation_forest_scorer` (6a) + `lstm_ae_scorer` (6b) + `gnn_scorer` (6c), combined by `fusion_engine.FusionEngine` (7) |
| 4.3 Module 4 — Continuous Verification | EWMA + time-decay + replay/freshness + flood checks, all in `trust_engine.score_message()`/`check_replay()`/`check_flood()` |
| 4.3 Module 5 — Access Control | `policy_engine.decide()` (Phase 5) or `adaptive_pdp.AdaptivePDP` (Phase 8) — toggle via `config.USE_RL_POLICY` |
| 4.3 Module 6 — Secure Communication | MQTT/TLS (+ per-device broker credentials/ACLs) + HTTPS (`coap_server.py` — see its docstring for why HTTPS substitutes for CoAP/DTLS) |
| 4.3 Module 7 — Monitoring | `audit_log.py` + `nist_mapping.py` + `iec62443_mapping.py` + `dashboard.py`/`webapp_server.py` |
| Figure 4.1 — Fusion Engine + SHAP | `fusion_engine.py` (full per-signal SHAP breakdown, not just the top feature) |
| Section 7.3 — Governance mapping | `nist_mapping.py` + `iec62443_mapping.py`, both dashboards' governance views, `scripts/evaluate_governance.py`/`evaluate_iec62443.py` |
| Section 10.1 — Evaluation | `scripts/evaluate_*.py` — results written up in `docs/08_results_and_evaluation.md` |

Next: **`docs/09_project_report.md`** for the complete report, or
`SESSION_LOG.md` for the full story, then `docs/05_phase_status.md` for
exact current status.
