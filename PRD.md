# Product Requirements Document

## Current audit status — 2026-09-05

The runtime still uses Rule + IF + LSTM-AE + legacy GCN → logistic fusion;
Security Trust stays separate until static/contextual-bandit policy evaluation.
Set Transformer (M6/M8/M9) is a research candidate, concat MLP a fixed-size
deployment baseline, Deep Sets a set baseline, GCN/GATv2 research baselines,
temporal Transformer ablation-only and NP-ST a rejected ablation.

Saved metrics predate the Astra temporal-training correction. They remain the
historical evidence for their archived model chain, not a validation of models
trained with the corrected sequence builder. Read RESULTS.md §0.13.17
and `RESULTS.md` §0.13.17 before quoting them. Missing-node context, resampled
hardware trajectories and non-independent calibration halves qualify the network
experiments. M9 trains through 15 slots but has no persisted 15-node test; the
virtual-only advantage is retained, and broader-coverage benefit is unproved.

Only `esp32-vib-001` (MPU6050) has captures. `esp32-vib-002` is a configured SW-420
with capture pending; it does not test MPU6050 manufacturing variation. LOW passes
TRAIN resting-residual consistency checks (not held-out realism validation).
MEDIUM/HIGH remain OOD stress regimes. Production readiness is not established.
## Explainable Zero-Trust Trust Evaluation for Cyber-Physical Systems Using Ensemble Anomaly Detection and Graph Neural Networks

| | |
|---|---|
| **Document status** | Living document — tracks the as-built system |
| **Product** | Zero-Trust CPS Gateway (`zt-cps-starter`) |
| **Repository** | `github.com/mritula2311/Zero-Trust-CPS` |
| **Primary artifact** | Research paper + reference implementation |
| **Security target** | IEC 62443-3-3 SL-2 (stated, evidenced, not overclaimed) |
| **Companion documents** | `METHODOLOGY.md` (method + mathematics), `RESULTS.md` (measured evidence), `ZERO_TRUST_CPS_KB.md` (architecture decisions), `docs/00–13` (per-module reference) |

> **A note on this document's evidentiary standard.** Every quantitative claim
> below is measured on this repository and cited to the section of `RESULTS.md`
> that produced it. Where a requirement is only partially met, or a target is
> missed, this document says so and points to the honest number. Claims that
> cannot currently be substantiated are listed under §9 Future Scope, not folded
> into the requirements as if they were delivered.

---

## 1. Executive Summary

### 1.1 The problem

A cyber-physical system (CPS) — an industrial sensor, an actuator, a monitored
machine — is exposed to two categories of failure that are **indistinguishable to
a conventional intrusion-detection system yet demand opposite responses**:

- A **cyber compromise**: a device presenting forged or replayed credentials,
  possibly while reporting perfectly plausible sensor values. The correct response
  is to deny access, challenge, or revoke.
- A **physical fault**: a correctly-authenticated, uncompromised device whose
  underlying machine is failing — a worn bearing, a loosening mount, an imbalance.
  The correct response is the *opposite*: pass the data through and alert
  operations, because taking the device offline destroys the very telemetry needed
  to diagnose the fault.

A system that reduces trust to a single scalar cannot separate these. Averaging a
high identity score with a low physical-health score yields a middling number that
under-reacts to the compromise and over-reacts to the fault.

### 1.2 The product

A Zero-Trust gateway that scores every telemetry message on **two independent
axes** — **Security Trust** (cyber evidence: identity, message integrity, replay,
freshness, rate) and **Process Anomaly** (physical evidence: the sensor reading
only) — and combines them **only** at a final 2×2 policy decision, never before.
The physical axis is an ensemble of four complementary anomaly signals fused by a
learned meta-model; the cyber axis is a rule-based trust engine. Every decision is
written to a hash-chained, tamper-evident audit log and mapped to NIST SP 800-207
zero-trust tenets whose satisfaction is **independently validated and falsified**.

The system runs against **real hardware** — one ESP32 + MPU6050 accelerometer
publishing over TLS MQTT — alongside two simulated devices that supply graph
context, with a live operator dashboard.

### 1.3 Why it is novel

The machine-learning pipeline is competent but not the contribution. The
contributions are methodological and are enumerated in §8. In brief: a
demonstration that the standard perturbation-based explainability test is
structurally invalid for correlated multi-channel anomalies (with a proposed
replacement); compliance checks that are **falsifiable** rather than asserted;
quantified hardware-in-the-loop training; a sim-to-real calibration method that
survives cross-session drift; and a live adversarial test that found a real
vulnerability invisible to every offline evaluation.

---

## 2. Goals, Non-Goals, and Success Metrics

### 2.1 Goals

| # | Goal | Measured status |
|---|---|---|
| G1 | Separate cyber and physical trust so opposite failures get opposite responses | **Met** — proven live: a shaken authenticated board drives Process to 0.00001 while Security holds 0.895–0.909 (`RESULTS.md` §1, 0.10.17) |
| G2 | Detect physical process anomalies on real hardware | **Met** — 30/30 detection on the untouched TEST session, 95% CI [88.6%, 100%] (`RESULTS.md` §0.12.1, C4) |
| G3 | Keep false positives on a healthy device low | **Not met, reported honestly** — 5/12 = 41.7% on the untouched TEST session's 12 resting windows, Wilson 95% CI [19.3%, 68.0%]; the earlier 3.4% (1/29) was measured before session-level splitting and is withdrawn (`RESULTS.md` §0.12.1, C4) |
| G4 | Reject cyber attacks before any model runs | **Met** — 5/5 live adversarial attacks rejected at Module 1/2 (`RESULTS.md` 0.10.17) |
| G5 | Make every decision auditable and tamper-evident | **Met** — hash-chained log, O(tail) incremental + cached full verification (`RESULTS.md` §8) |
| G6 | Make governance claims falsifiable, not asserted | **Met** — 7/7 NIST tenets validated, 7/7 falsifiers injected and rejected (`RESULTS.md` 0.10.16) |
| G7 | Run on constrained real hardware within duty-cycle budget | **Met** — 172 ms on-device compute per 2000 ms cycle = 8.6% duty (`RESULTS.md` §13.1) |

### 2.2 Non-Goals

- **Confidentiality of the physical process.** The system authenticates and
  attributes; it does not encrypt sensor semantics beyond the TLS transport.
- **A general IDS.** It is scoped to registered devices with pre-shared per-device
  secrets, not open-network discovery.
- **SL-3/SL-4 assurance.** The evidenced target is SL-2; higher levels would
  require physical network segmentation the deployment does not have (§7).
- **Autonomous remediation beyond policy actions.** The gateway decides
  ALLOW/ALERT/STEP_UP/BLOCK and (optionally) auto-quarantines; it does not take
  control actions on the physical process.

### 2.3 Success metrics (acceptance thresholds)

| Metric | Threshold | Achieved |
|---|---|---|
| Real-hardware detection of physical disturbance | ≥ 95% | **100% (30/30 on untouched TEST session)** ✓ |
| Real-hardware false-positive rate (operator-marked rest) | ≤ 10% | **41.7% (5/12), 95% CI 19–68%** ✗ — target NOT met under session-level splitting (see below) |
| Live cyber attacks rejected before scoring | 100% | **100% (5/5)** ✓ |
| Two-score separation holds (Security unmoved by physical disturbance) | required | **Security 0.895–0.909 through a full shake** ✓ |
| NIST tenets validated with a working falsifier | 7/7 | **7/7 + 7/7 falsifiers** ✓ |
| On-device duty cycle | < 25% | **8.6%** ✓ |
| End-to-end gateway latency (PC-class) | < 100 ms | **2.93 ms mean, 14.48 ms p99 full pipeline** ✓ |

> **The false-positive threshold is not met, and this is reported rather than
> hidden.** The earlier "3.4% (1/29)" was measured while the test session's own
> at-rest rows were in the training set; with session-level train/validation/test
> splitting enforced, the honest figure on the 12 resting windows of the untouched
> TEST session is 5/12. The 12-window denominator makes the interval very wide.
> Detection is unaffected (`docs/CLAIM_EVIDENCE_MATRIX.md` C4). Reducing this rate
> — which the wide interval and the mounting-robustness capture (`docs/REVIEW_RESPONSE_TRACKER.md`
> D) are the levers for — is named as required future work, not claimed as met.

---

## 3. Users and Use Cases

### 3.1 Primary users

- **CPS/OT security engineer** — deploys the gateway in front of a device fleet,
  monitors the dashboard, responds to ALERT/STEP_UP/BLOCK.
- **Reliability/maintenance engineer** — consumes Process Anomaly ALERTs as
  early-fault indicators (the crest-factor and kurtosis features are chosen for
  bearing-damage signatures).
- **Auditor / compliance reviewer** — reads the hash-chained log and the NIST/IEC
  governance reports, and can independently re-run the falsifiability self-test.
- **Researcher** — reproduces every number via the scripted training and
  evaluation chain.

### 3.2 Representative use cases

1. **Legitimate physical fault.** An authenticated device's bearing begins to fail.
   Security Trust stays high; Process Anomaly falls; policy returns **ALERT**;
   telemetry keeps flowing; maintenance is notified. *(Verified on real hardware,
   §1 / 0.10.14.)*
2. **Credential compromise.** An attacker with stolen broker credentials but no
   HMAC secret impersonates a device. Every message fails HMAC and is **REJECTED**
   before any model runs, without touching the real device's state. *(Verified
   live, 0.10.17.)*
3. **Replay / stale message.** A captured message is re-sent, or a message arrives
   with an old timestamp. Boot-aware anti-replay and the freshness window reject
   it. *(Verified live, 0.10.17.)*
4. **Coordinated multi-device anomaly.** Several devices deviate together — a
   pattern no single-device model can represent. The GNN detects it (recall 0.974
   vs 0.308–0.316 for single-device signals). *(Measured, §2.)*
5. **Silent device.** A device stops publishing. The silence watchdog emits a
   SILENT audit row so the asset still appears in the governance coverage check
   (Tenet 5).

---

## 4. System Architecture

### 4.1 Pipeline

```
telemetry ─▶ identity ▶ revocation ▶ throttle ▶ HMAC-SHA256 ▶ boot/seq replay ▶ freshness
                                     │
                       any failure = REJECTED  (never reaches a model; never
                       mutates the CLAIMED device's own state)
                                     │
                                     ▼
        ┌──────────────────────────┴──────────────────────────┐
   SECURITY TRUST  s_sec                              PROCESS ANOMALY  s_proc
   rate · step-up outcome · silence          rule · IsolationForest · LSTM-AE · GNN
   (cyber evidence only)                                └──────▶ fusion ──────┘
        │                                                        │
        └────────────────▶  2×2 POLICY LOOKUP  ◀─────────────────┘
                          ALLOW · ALERT · STEP_UP · BLOCK
                                     │
                                     ▼
                    hash-chained, checkpoint-anchored audit record
```

### 4.2 Modules (mapped to `docs/`)

| Module | Responsibility | Reference |
|---|---|---|
| M1 Device Identity | Registry, per-device secrets, revocation | `docs/02` |
| M2 Authentication | HMAC-SHA256, boot-aware anti-replay, freshness, step-up challenge | `docs/03` |
| M3 Trust Evaluation | The two scores; the four-signal Process ensemble + fusion | `docs/04` |
| M4 Continuous Verification | Per-message re-scoring, staleness, silence watchdog | `docs/05` |
| M5 Access Control | The 2×2 policy, offline contextual-bandit policy, auto-quarantine | `docs/06` |
| M6 Secure Communication | TLS MQTT, per-device broker credentials + topic ACLs | `docs/07` |
| M7 Monitoring & Audit | Hash-chained log, NIST/IEC governance validation, dashboard | `docs/08` |

### 4.3 Deployment topology

- One physical **ESP32 + MPU6050** (`esp32-vib-001`), MicroPython firmware,
  publishing five on-device-computed vibration features every 2000 ms over TLS
  MQTT.
- Two **simulated devices** (`sensor-002`, `actuator-001`) providing graph context
  and scalar-device coverage.
- A **Mosquitto** broker with per-device credentials and least-privilege topic
  ACLs.
- The **gateway** (`src/gateway.py`), single-process, serving a live dashboard on
  `:8600`.

---

## 5. Functional Requirements

Each requirement carries a verification method and its current status.

### 5.1 Authentication and identity (M1/M2)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| FR-A1 | Every message MUST be HMAC-SHA256 authenticated against the claimed device's per-device secret before any scoring | live forged/tampered attacks → `hmac_mismatch` | **Met** (0.10.17) |
| FR-A2 | Unregistered device IDs MUST be rejected before HMAC | live `ghost-999` attack → `unknown_device_id` | **Met** |
| FR-A3 | Replayed messages MUST be rejected via boot-aware anti-replay (a lower boot_id, or a non-increasing seq within a boot session) | live captured-replay attack → `replay_of_superseded_boot_session` | **Met** |
| FR-A4 | Stale messages MUST be rejected via an independent freshness window | live stale attack → `stale_timestamp` | **Met** |
| FR-A5 | A failed-auth message MUST NOT mutate the claimed device's own trust or anti-replay state | `TestBootReplayStateIsolation`; regression from a real vulnerability (0.10.17) | **Met (after fix)** |
| FR-A6 | A failed-auth attempt MUST update `IdentityTargetingRisk` against the *claimed* ID only, never a registered device's score | `docs/03`; failed-HMAC cooldown suppresses repeated rejection bookkeeping, and malformed envelopes are dropped | **Partial: attributed rejection updates are implemented, but not every dropped attempt is counted** |
| FR-A7 | The gateway MAY issue a step-up nonce challenge and MUST record SUCCESS/TIMEOUT/MISMATCH | live step-up path | **Met** (firmware queue-drain fix, §9 history) |

### 5.2 Process anomaly detection (M3)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| FR-P1 | The physical axis MUST NOT consume any cyber evidence, and vice versa | `TestTwoScoreSeparation` (signature inspection) | **Met** |
| FR-P2 | The ensemble MUST include a relational signal (graph or set/concatenated alternative) capable of detecting cross-device anomalies | Cross-device information improves coordinated detection 0.4142 → 0.6567 (concat MLP). **The GNN specifically does not beat simpler models on identical information (Task 1 test F1: MLP 0.985 vs GNN 0.838); GNN-superiority is withdrawn** (`docs/CLAIM_EVIDENCE_MATRIX.md` C2/C3) | **Relational signal present; graph structure not shown superior** |
| FR-P3 | Detection of real physical disturbance MUST be ≥ 95% | 30/30 on untouched TEST session, 95% CI [88.6%, 100%] (C4) | **Met (100%)** |
| FR-P4 | Isolation Forest scores MUST be calibrated so a median-normal reading scores above the deployed threshold | `TestIsolationForestCalibration` | **Met** |
| FR-P5 | Per-signal score orientation MUST be consistent (1 = normal) so fusion composes correctly | fusion coefficients, ablation | **Met** |
| FR-P6 | The system MUST detect a sustained low-amplitude disturbance below a per-sample amplitude threshold | controlled test: 14/14 flagged vs 0/14 rest, amplitude-capped (0.10.14) | **Met below threshold; equal-amplitude case is future scope** |

### 5.3 Policy and access control (M5)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| FR-C1 | The policy MUST be a pure function of the two scores plus staleness | `decide()` signature enforced by test | **Met** |
| FR-C2 | The policy MUST be monotone: improving either score MUST NOT make the decision stricter | static-table invariant; learned Q-table has no monotonicity constraint | **Met for static policy; not established for bandit** |
| FR-C3 | A physically abnormal but authenticated device MUST receive ALERT, not BLOCK | policy table; live shake → ALERT | **Met** |
| FR-C4 | An adaptive policy MAY be trained offline; it MUST beat the *deployed* static table to be considered | Saved-chain bandit macro-F1 0.5271 vs static 0.2744. Unconstrained static 0.5614 loses physical recall (0.585); constrained static 0.2777 and bandit both meet the stated test constraints. These are not a matched constrained selection across policy families (`docs/CLAIM_EVIDENCE_MATRIX.md` C6). Not RL — a contextual bandit with sample-average action-value estimation | **Configured bandit remains live; P6 is only the best constrained static grid point; see current audit** |
| FR-C5 | No model MUST be trained or updated on the live path | `docs/04`; inference-only gateway | **Met** |

### 5.4 Governance and audit (M7)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| FR-G1 | Every decision MUST append a hash-chained audit row | chain verification over 78k+ rows | **Met** |
| FR-G2 | Chain verification MUST detect deletion/reordering, not just modification | genesis-anchored chaining | **Met** |
| FR-G3 | Each of the 7 NIST SP 800-207 tenets MUST be validated against the audit log | `evaluate_governance.py` → 7/7 | **Met** |
| FR-G4 | Each tenet's validator MUST be falsifiable — its own falsifier injected MUST make it fail | 7/7 falsifiers rejected | **Met (was 6/7; T5 corrected, 0.10.16)** |
| FR-G5 | The audit DB and its attesting checkpoint store MUST live in separate locations | `test_audit_db_and_its_checkpoint_store_are_not_co_located` | **Met** |

### 5.5 Explainability (M7)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| FR-E1 | Every decision MUST record which signal drove it (Level-1), via exact SHAP on the linear fusion | 200/200 attributions physically sensible | **Met (100%)** |
| FR-E2 | The system SHOULD attribute which feature within a signal drove it (Level-2) | perturbation flip test | **Met via the rank-aware metric (98%, ≥70% target); the single-channel test is 37% and is retained for literature comparability with its rank diagnosis (§8.1, `RESULTS.md` 0.10.20)** |

### 5.6 Platform (M6)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| FR-T1 | All device↔gateway traffic MUST use TLS | host startup now requires TLS; MPU6050 firmware uses CERT_NONE | **Partial: peer verification and hardware revalidation pending** |
| FR-T2 | Broker access MUST be per-device credentialled with least-privilege topic ACLs | `mosquitto_acl`, per-device passwords | **Met** |
| FR-T3 | On-device features MUST be computed identically to the gateway reference implementation | `TestFirmwareReferenceEquivalence` (differential test) | **Met** |

---

## 6. Non-Functional Requirements

| ID | Requirement | Target | Achieved |
|---|---|---|---|
| NFR-1 Performance (device) | On-device compute per message | < 25% duty | 172 ms / 2000 ms = **8.6%** |
| NFR-2 Performance (gateway) | Full pipeline latency, PC-class | < 100 ms | **22 ms mean** |
| NFR-3 Footprint | Device RAM headroom | comfortable | **14.8% of 115 KB used** |
| NFR-4 Reproducibility | All models rebuildable deterministically | required | **Partial:** seeds fixed, sequence construction corrected; saved chain and hash provenance need versioned rebuild |
| NFR-5 Robustness | Headline metrics stable across training seeds | required | fused 0.715 ± 0.002; RL 0.537 ± 0.002 |
| NFR-6 Recoverability | Device self-recovers from transient sensor/network faults | required | I²C re-init + MQTT reconnect verified live |
| NFR-7 Statistical honesty | Proportions reported with confidence intervals | required | Wilson intervals on all hardware rates |

---

## 7. Security Model and Assurance

**Threat model.** The adversary can observe and inject on the network and may hold
broker credentials (an insider or stolen-laptop scenario) but does **not** hold a
device's per-device HMAC secret. This is the profile IEC 62443 SL-2 addresses
("simple means, low resources").

**Evidenced defenses.** HMAC-SHA256 message authentication (FR1), boot-aware
anti-replay closing the captured-session blind spot, an independent freshness
window, per-device broker credentials with topic ACLs (FR5), and a
trust-poisoning-DoS-resistant attribution rule (failed auth never penalizes the
claimed device's own state).

**Assurance target: SL-2, stated honestly.** FR5 (Restricted Data Flow) and FR7
(Resource Availability) are marked *partial*, not *implemented*, because there is
no physical network segmentation. The paper claims SL-2 and states the evidence
for and against explicitly rather than asserting a higher level (`RESULTS.md` §5).

**Known residual risks** (§9): device-flash secret extraction, absence of key
rotation at scale, single-gateway root of trust, and the by-design
undetectability of `stealthy_forged_values` from single-node telemetry.

---

## 8. Novelty and Research Contributions

Enumerated with the measurement that substantiates each. Full detail in
`METHODOLOGY.md §6` and `RESULTS.md`.

### 8.1 Anomaly rank vs. instrument rank in perturbation explainability
The standard Level-2 test (perturb one feature channel, check the score recovers)
is shown to be **structurally invalid** for sequence models on correlated
multi-channel physical anomalies. On 136 real disturbance windows, single-channel
repair achieves a 3.7× error reduction where ~9,700× is required; three-channel
repair recovers 98% (178/182), minimal set `{peak, rms, crest_factor}`. A control
signal (GNN) passes the identical test at 100% because its anomaly is
single-source. A replacement diagnostic — the **minimal repair set / anomaly
rank** — is proposed and measured. *(0.10.14, §4.3.)*

### 8.2 Falsifiable compliance
Each NIST SP 800-207 tenet is validated against the hash-chained log, and each
tenet's own falsifier is injected to prove the check can fail (7/7). A previously
mis-excluded tenet was found and corrected by this self-test. *If a validation
check cannot fail, it is not a check.* *(0.10.16, §5.)*

### 8.3 Hardware-in-the-loop training, quantified
Real hardware is 3.0% of the training normals, yet withholding it and retraining
the whole chain **materially increases** operator-marked false positives with
detection unchanged — synthetic data alone cannot place the normal region where
the board actually sits. ⚠ The previously quoted magnitude (0/49 → 13/49) was
measured under the pre-split regime and its 0/49 baseline is the withdrawn leaky
figure; the *direction* is unaffected, but the exact synthetic-only magnitude must
be re-measured under session-level splitting before it is quoted again.
*(`docs/CLAIM_EVIDENCE_MATRIX.md` C14; 0.10.9.)*

### 8.4 Sim-to-real calibration sized on cross-session spread (ADR-18)
The same board's resting DC measured 1.041 / 1.056 / 1.011 g. Centring the
simulator on the newest median passed every offline test, then put the next live
resting board at −4.0σ. The method — size the normal region on cross-session
spread, not the latest median — is generalizable, and the negative result (offline
evaluation cannot detect over-fitting to captured sessions) is itself a
contribution. *(0.10.7.)*

### 8.5 Detection below the amplitude decision boundary
On windows a per-sample amplitude threshold cannot separate (all samples ≤ the
resting p99), the sequence model separates real disturbance from rest 14/14 vs
0/14 — evidence the sequence model contributes what an amplitude rule cannot.
*(0.10.14.)*

### 8.6 Two-score separation demonstrated on hardware
A violently shaken authenticated board drives Process to 0.00001 while Security
holds 0.895–0.909, one-message transition. *(§1.)*

### 8.7 Live adversarial testing that found a real vulnerability
Five hostile messages over the real transport, all rejected — and the exercise
exposed a state-mutation bug (a rejected stale message could advance anti-replay
state and lock out the real device, a DoS) invisible to every offline evaluation.
Fixed and regression-guarded. *(0.10.17.)*

---

## 9. Limitations and Future Scope

Stated because the boundary of a method is part of it. Honestly-reported
limitations are a design principle of this project, not an afterthought.

**Claims overturned by leakage-free re-measurement (2026-09-03/04), reported not hidden:**
- **The GNN does not beat simpler models on identical multi-device information.**
  Task 1 test F1: concat MLP 0.985, single-device 0.977, GNN 0.838 (at its own
  best swept self-loop weight). The defensible claim is about *cross-device
  information* (0.4142 → 0.6567), not graph structure. GNN-superiority is
  withdrawn (`docs/CLAIM_EVIDENCE_MATRIX.md` C3).
- **A validation-tuned static policy beats the adaptive policy.** Macro-F1:
  static-optimised 0.5614 > adaptive bandit 0.5271 (with materially different ALERT recall) > deployed static 0.2744. The
  adaptive policy improves on the *deployed* table but not on a well-tuned static
  one. It is a contextual bandit, not reinforcement learning (C6).
- **The real-hardware false-positive rate is 5/12, not 0/49.** The 0/49 was
  measured under session-level train/test leakage and is withdrawn; the honest
  figure on the untouched TEST session is 41.7% over 12 resting windows (C4).

**Reframed by measurement (not open defects):**
- GNN seed variance (accuracy sd 0.011) lives in aggregate accuracy, not in
  `coordinated` recall (stable 0.974–1.0), and changes zero decisions.
- Severity cannot be reduced to a single rank: disturbance classes differ on
  orthogonal physical axes; a peak-aware statistic does not order them. The system
  detects *whether* a disturbance is present, not a scalar *how severe*.

**Genuine future scope:**
- **Physical fault injection** — a worn bearing / imbalanced load, not a bench
  disturbance or an injected attack. All captured events are legitimate physical
  conditions; only transport-level attacks are real adversarial tests.
- **Physical replication** — SW-420 capture is pending and supplies another modality.
  A second MPU6050 is separately needed to test ADR-18 manufacturing variation.
- **Detection floor at equal amplitude** — currently measured below the amplitude
  *threshold* but not with amplitude held equal (bench windows carry ~2× within
  the below-ceiling band).
- **Tightening the false-positive interval** — the saved held-out interval is [19.3%, 68.0%] (the earlier [0.6%, 17.2%] was leaky); tightening it needs more independent clean
  resting samples; blocked while the bench carries a variable ~31 Hz source.
- **`stealthy_forged_values`** — undetectable from single-node telemetry by
  design; the transformer's apparent 0.970 recall was a stale-artifact and
  resolved to 0.606 when retrained.
- **Level-2 explainability, single-channel test** — 37% vs 70%. This is a
  *structural* limit of the single-channel instrument on a rank-3 anomaly, not a
  model defect (§8.1). The rank-aware metric meets the target at 98%; making the
  single-channel test itself pass would require a feature representation in which
  the anomaly is genuinely rank-1 — a model-architecture change, future work.
- **SL-3/4** — requires physical network segmentation the deployment lacks.
- **Device-secret protection and key rotation** — flash extraction defeats the
  identity layer; no rotation at fleet scale.

---

## 10. Reproducibility and Acceptance

The complete build and evaluation is scripted and deterministic. Acceptance =
these commands reproduce the numbers in this document.

```bash
# Research rebuild recipe; archive/version outputs first. Transformer is ablation-only.
python scripts/merge_real_hardware_data.py       # fold real at-rest rows into synthetic
python scripts/generate_validation_data.py
python scripts/generate_test_data.py
python scripts/train_isolation_forest.py
python scripts/train_lstm_ae.py
python scripts/train_transformer.py
python scripts/train_gnn.py
python scripts/train_fusion_meta_learner.py
python scripts/train_adaptive_pdp.py

# Evaluation
python scripts/evaluate_real_hardware.py         # operator-labelled hardware, with Wilson CIs
python scripts/evaluate_ablation.py              # per-signal, AT the deployed threshold (0.6)
python scripts/evaluate_governance.py            # 7/7 tenets + 7/7 falsifier injections
python scripts/attack_live_gateway.py            # live adversarial test (gateway must be running)
python -m unittest discover -s tests             # current count in RESULTS.md §0.13.17

# Figures
python scripts/generate_evaluation_graphs.py     # 17 pipeline-behaviour figures
python scripts/generate_paper_figures.py         # 4 claim-carrying figures (A–D)
```

`ZTCPS_SEED` (default 0) fixes the training RNG for every model, so the
seed-sensitivity analysis (`RESULTS.md` 0.10.11) is reproducible; `ZTCPS_GNN_LR`
and `ZTCPS_GNN_EPOCHS` expose the GNN training knobs.

---

## 11. Document Map

| Document | Contents |
|---|---|
| `PRD.md` (this file) | Requirements, goals, novelty, acceptance |
| `METHODOLOGY.md` | The method, every mathematical expression with its justification, novelty, limitations |
| `RESULTS.md` | Every measured number; §0.10.x is the chronological findings log |
| `ZERO_TRUST_CPS_KB.md` | Architecture decisions (ADRs), invariants, fragile areas |
| `SESSION_LOG.md` | Chronological record of why the system is the way it is, including reverted attempts |
| `README.md` | Quick start and orientation |
| `docs/00–13` | Per-module reference and the as-built architecture |
| `firmware/HARDWARE_SETUP.md` | Pinout and bring-up |
| `CLAUDE.md` | Engineering invariants for contributors and coding agents |

## 12. Current research contribution and delivery boundary

The contribution is dual-channel Zero Trust, evidence of architecture-specific
topology sensitivity, evaluation of set-based relational alternatives, controlled
mixed-cardinality research and deployment-constrained policy analysis. Merely
using a GNN is not novelty, and graph superiority is withdrawn. Rank-aware
explanations preserve physical feature meaning; the lower rank-1 score is retained.

Implemented: authenticated telemetry, separate scores, legacy GCN fusion,
contextual-bandit/static policy, audit/dashboard, virtual generator and M1–M9
experiment code. Validated within stated scopes: software invariants, MPU6050
captures on the saved chain, and LOW TRAIN residual consistency. Experimental:
set-model selection and mixed cardinality. Pending: corrected-chain results,
actual n=15 tests, fusion complementarity, SW-420 captures, same-sensor replication,
source-independent validation, and verified firmware TLS. This is a research
prototype with unmet production requirements, not a completed deployment claim.
