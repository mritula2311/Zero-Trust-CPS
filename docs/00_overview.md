# Zero-Trust Security Framework for IoT-Based CPS
## Low-Level Design — Master Overview

> **AS-BUILT STATUS (read this before anything else in this file).** This
> 12-file set was originally written as a from-scratch build guide, assuming
> no existing code. It was reconciled against an already-working, already-
> evaluated codebase (17+ prior sessions — see `SESSION_LOG.md`) rather
> than used to rebuild from zero. The core architectural principle below —
> two scores, never blended before the policy step — is now **actually
> implemented**, along with this doc set's `boot_id`/`seq` anti-replay
> scheme, `IdentityTargetingRisk` attribution fix, real step-up
> challenge/response, and hash-chained audit log. Eight deliberate
> deviations from what follows, each with a stated reason, not an
> oversight:
> 1. **Process Anomaly Score stays trust-style (high = normal)**, not the
>    anomaly-style (high = bad) scale this doc set uses — kept so the
>    already-trained, already-ablation-verified fusion meta-learner's
>    coefficients didn't need to change sign. `policy_engine.py`'s 2×2
>    table is written for this scale throughout.
> 2. **Device registry is hybrid** — one real-hardware-shaped device
>    (`esp32-vib-001`, a 5-feature vibration vector, not raw 6-channel
>    accel+gyro) plus two legacy scalar devices (`sensor-002`,
>    `actuator-001`), not a uniform fleet of MPU6050 nodes. See
>    `CLAUDE.md` Section 2 for why.
> 3. **Flat `src/` + `config.py`** kept instead of this doc set's
>    `src/simulation|identity|auth|trust|...` package layout and
>    `config.yaml` — cosmetic, no functional benefit, only merge risk
>    against a large existing codebase.
> 4. **RL (`adaptive_pdp.py`) and the GNN are live defaults**, not the
>    "optional stretch goal" / "conditional on ablation" framing below —
>    both are already trained and evaluated; RL's live path
>    (`greedy_action()`) is a frozen, no-exploration Q-table lookup with
>    no live reward-signal dependency, which is what makes it safe as a
>    default (see `06_module5_access_control.md`'s note).
> 5. **`stealthy_forged_values`** (Section B.8 below, attack-matrix row 11)
>    is implemented and measured, not hypothetical — its honestly-low
>    detection rate is the intended, reported result.
> 6. **A Transformer sub-signal was added, tuned, and fairly evaluated**
>    (`src/transformer_scorer.py`, `docs/04_module3_trust_evaluation.md`
>    Section B.5b) — not in this doc set at all. Genuinely edges out the
>    LSTM-AE on a corrected, undiluted comparison (+0.010 F1,
>    `RESULTS.md` Section 2.2), but the margin is too small relative to
>    ~6x the parameters to justify adopting it — same keep/drop bar the
>    GNN (deviation 4) already had to clear before it became a live
>    default. Ablation-only; not one of `fusion_engine.py`'s inputs.
> 7. **Real hardware is MPU6050-only** — the originally-planned separate
>    vibration sensor was dropped (the real board only had 2 GND pins
>    available, and all 5 Section-5.1 features were already derived
>    entirely from the MPU6050's accelerometer; the vibration sensor's raw
>    ADC reading was carried in the payload but never consumed by scoring
>    logic, confirmed before removing it). The board has since been
>    flashed, authenticated, and run live — see `RESULTS.md` Section 13
>    and `SESSION_LOG.md` §29 for the real bring-up bugs found/fixed and
>    the real-data retraining results. **The dashboard is now served by
>    `gateway.py` itself, not a separate script** — `webapp_server.py` was
>    first removed entirely (on explicit user instruction), then its live-
>    `/api/*`/`/figures`-gallery logic was merged directly into
>    `gateway.py` (its Module 9 extension section,
>    `start_dashboard_server()`, same background-thread pattern
>    `coap_server.py`'s second transport already used) once the user asked
>    for the live functionality back without a second script. One process
>    (`python gateway.py`) now runs MQTT + the HTTPS second transport + the
>    live dashboard together; `design/zero-trust-cps-command-center.html`
>    remains the one dashboard file, just served live again — verified
>    end to end (main page, every `/api/*` endpoint, `/figures`) against
>    real hardware telemetry. See `SESSION_LOG.md` §29/§30. A third
>    dashboard (`dashboard.py`, Streamlit) referenced throughout the
>    original docs was found during this work to never have existed in the
>    repo at all — stale documentation, not a real feature that was removed.
> 8. **All five of `RESULTS.md` Section 14's known limitations are now
>    resolved**, plus a sixth found while closing them: key rotation/
>    device revocation and decision-channel replay implemented (as
>    additive `DEVICE_REGISTRY`/`gateway.py` state, not the SQLite
>    `devices` table `02_module1_device_identity.md` originally specified
>    — see that file's own AS-BUILT note); Level-2 explainability and the
>    `high_rate` Process-score question were already resolved/explained,
>    not new work; and `trust_engine.is_stale()`/`get_process_anomaly()`'s
>    staleness checks, real in the design but never actually reachable in
>    the live message-triggered path, now run on a genuine background
>    watchdog thread (`05_module4_continuous_verification.md`'s own
>    AS-BUILT note has the full story — this is the
>    `background_decay_task()` that section's pseudocode always called
>    for, previously skipped as an unnecessary simplification). Two
>    further real hardware faults found by physically manipulating the
>    board (MPU6050 disconnected; VCC removed entirely) each surfaced and
>    closed one more real gap — an `rms` rule-bound floor and an I2C-vs-
>    MQTT exception-handling bug — both re-verified live after fixing, not
>    just fixed and assumed. Full detail in `RESULTS.md` Section 13.2/14
>    and `SESSION_LOG.md`'s final entries.
>
> Read `SESSION_LOG.md`'s final entry for the full reconciliation
> narrative. Everything else in this file describes the architecture as it
> now actually exists, not a future target.

This is the entry point to the as-built architecture. It is one of 14 documents (the original 12, plus `12_model_validation_and_justification.md` and `13_system_architecture_and_workflow.md`, added once every model had been individually validated and the system's shape was worth drawing out explicitly). Read this file first, then `01_simulation_and_hardware_abstraction.md`, then `13_system_architecture_and_workflow.md` for the whole-system picture, then the module files in numeric order, then `12_model_validation_and_justification.md` once you've read Module 3. Each module file is self-contained enough to read on its own, but assumes the abstractions defined in `01` already exist.

---

## 1. What This Project Is

A Zero-Trust security framework for IoT-based Cyber-Physical Systems (CPS). Instead of trusting a device permanently after it authenticates once, the system re-checks every device on every single message, using two independent scores:

- **Security Trust Score** — built entirely from cyber-behaviour evidence (authentication failures, replay attempts, message timing/rate). Answers: *"does this device's network behaviour look compromised?"*
- **Process Anomaly Score** — built entirely from physical sensor evidence (accelerometer/gyroscope readings). Answers: *"does this device's physical reading look abnormal?"*

These two scores are **never blended into one number**. They are combined only at the final policy-decision step, through a 2×2 table, specifically so that a genuine physical fault (e.g., a motor bearing failing) is never mistaken for a cyberattack. This separation is the single most important architectural decision in the whole project — see `04_module3_trust_evaluation.md` for the full reasoning.

## 2. The Critical Constraint This Design Solves: No Hardware Yet

The physical hardware (ESP32 + MPU6050) is not yet available. Every module in this project must therefore be built against a **Device Data Source abstraction** (defined in `01_simulation_and_hardware_abstraction.md`) rather than against real hardware directly. Concretely:

- Right now: a **Simulated Device** generates realistic MPU6050-shaped telemetry and can inject any attack from the attack matrix on command.
- Later, when one ESP32 + MPU6050 arrives: a **Hardware Device** reads the same message schema from the same MQTT topics. Nothing downstream of the message broker changes.
- The switch between the two is a single configuration value (`DEVICE_MODE: simulation | hardware`), never a code change in any of Modules 1–7.

**This is not optional scaffolding — it is the primary design principle every module must respect.** If a module's implementation ever needs to know whether it is talking to a real ESP32 or a simulator, that module's design is wrong and should be revisited against `01`.

## 3. The Seven Modules

| # | Module | One-Line Job | Spec File |
|---|--------|--------------|-----------|
| 1 | Device Identity | Give every device a unique, registry-checked ID and secret key | `02_module1_device_identity.md` |
| 2 | Authentication | Prove a message really came from that device, unmodified, and is not a replay | `03_module2_authentication.md` |
| 3 | Trust Evaluation | Produce the Security Trust Score and Process Anomaly Score | `04_module3_trust_evaluation.md` |
| 4 | Continuous Verification | Re-run scoring on every message; decay trust when a device goes silent | `05_module4_continuous_verification.md` |
| 5 | Access Control | Turn both scores into Allow / Step-Up / Alert / Block via the 2×2 policy table | `06_module5_access_control.md` |
| 6 | Secure Communication | Carry every message over encrypted MQTT | `07_module6_secure_communication.md` |
| 7 | Monitoring | Tamper-evident audit log, live dashboard, NIST SP 800-207 alignment mapping | `08_module7_monitoring_and_audit.md` |

Supporting documents:

| File | Purpose |
|------|---------|
| `01_simulation_and_hardware_abstraction.md` | The device abstraction layer — read this before any module |
| `09_integration_and_data_flow.md` | How all seven modules connect end-to-end; consolidated data schemas |
| `10_testing_and_attack_simulation.md` | Attack matrix, dataset generation, evaluation metrics, ablation methodology |
| `11_project_structure_and_config.md` | Repo layout, dependencies, config file, recommended build order |

## 4. High-Level Data Flow

```
                    ┌─────────────────────────────┐
                    │   DEVICE DATA SOURCE          │   ← Module 01 abstraction
                    │  (Simulated OR Hardware)       │      (same interface either way)
                    └──────────────┬──────────────┘
                                   │  raw telemetry + HMAC + seq + timestamp
                                   ▼
                    ┌─────────────────────────────┐
                    │ Module 6: Secure Comm         │   MQTT/TLS transport
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ Module 1: Device Identity     │   is this device_id known?
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ Module 2: Authentication      │   HMAC valid? sequence fresh?
                    └──────────────┬──────────────┘
                                   ▼
              ┌────────────────────┴────────────────────┐
              ▼                                          ▼
  ┌───────────────────────┐              ┌───────────────────────────┐
  │ Module 3a: Security    │              │ Module 3b: Process         │
  │ Behaviour Engine       │              │ Anomaly Engine              │
  │  → Security Trust Score│              │  → Process Anomaly Score    │
  └───────────┬───────────┘              └─────────────┬─────────────┘
              │                                          │
              └────────────────────┬─────────────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ Module 4: Continuous          │   re-run every message;
                    │ Verification                   │   decay on silence
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ Module 5: Access Control       │   2×2 table → decision
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │ Module 7: Monitoring           │   hash-chained log, dashboard
                    └─────────────────────────────┘
```

## 5. Glossary

| Term | Meaning |
|------|---------|
| Security Trust Score | 0–1 score from cyber-behaviour evidence only; 1 = clean, 0 = likely compromised device |
| Process Anomaly Score | 0–1 score from physical sensor evidence only; 0 = normal, 1 = highly abnormal |
| HMAC | Hash-based Message Authentication Code — a shared-secret integrity/origin check. **Not** a digital signature. |
| Replay window | The time tolerance (e.g., ±30s) within which a message's timestamp is considered fresh |
| Step-up authentication | A challenge-response check the gateway can demand mid-session when trust is borderline |
| Meta-learner | The small logistic-regression model that fuses Rule/Isolation-Forest/LSTM-AE/(GNN) scores into one Process Anomaly Score |
| Two-level SHAP | Level 1 explains which signal drove a score; Level 2 explains which raw feature drove that signal |
| Hash chain | Each audit-log row stores a hash of the previous row, making silent edits to old rows detectable |
| Checkpoint | A periodic, separately-stored, separately-signed hash chain anchor that catches an attacker who has rewritten the in-database chain to stay internally consistent (see `08`, Section 3.2) |
| boot_id | A small counter, incremented once per device reboot and persisted in flash, that lets the anti-replay check correctly accept a fresh session after a legitimate restart without accepting a replayed old one (see `01`, Section 2.1) |
| IdentityTargetingRisk | Risk tracked per *claimed* device_id from failed/rejected authentication attempts. Deliberately never allowed to lower a real device's own Security Trust Score — see `03`, Section 5 |
| STALE (process_anomaly_status) | Marks that no fresh sensor reading has arrived recently; the last known Process Anomaly Score is retained exactly, never faded toward normal — see `05`, Section 2.2 |
| DEVICE_MODE | The single config switch: `simulation` or `hardware` |

## 6. Recommended Build Order

This mirrors the phased plan in the project synopsis. Build in this order so there is always a working system, even if later phases run out of time:

1. `01` Simulation abstraction (must exist before anything else can be tested)
2. `02` Device Identity + `03` Authentication
3. `07` Secure Communication (can run against simulated transport first, real broker second)
4. `04` Trust Evaluation — Section A (Security Behaviour Engine) + Section B rule-based/Isolation-Forest only
5. `05` Continuous Verification + `06` Access Control (basic 2×2 table) — **core system complete here**
6. `04` Trust Evaluation — LSTM-Autoencoder, then conditionally the GNN
7. `04` Trust Evaluation — fusion meta-learner + two-level SHAP
8. `06` Access Control — optional adaptive policy stretch goal
9. `08` Monitoring dashboard + governance mapping + `10` full evaluation

Continue to `01_simulation_and_hardware_abstraction.md` next.
