# Implementation Documentation — Zero-Trust Security Framework for IoT-Based CPS

This set of documents explains **how each of the seven modules is actually
built**, and how they interact with each other, at a level of detail one
step below the source code itself. Where the code in the starter kit already
implements a module, these docs walk through that code line-by-line and
explain the reasoning. Where a module's full design (per Report Sections 4.3
and 4.4) goes beyond what's shipped in the starter kit — the multi-model
fusion engine, the RL-adaptive policy — these docs give the complete
architecture and a concrete code sketch, clearly marked as the extension
target rather than presented as already-running code.

## How to read these

| File | Module | Status |
|---|---|---|
| `01_module_device_identity.md` | 1 — CPS Device Identity | Core implemented |
| `02_module_authentication.md` | 2 — Authentication | Core implemented |
| `03_module_trust_evaluation.md` | 3 — Trust Evaluation | Core implemented (rule-based) + full fusion design (extension) |
| `04_module_continuous_verification.md` | 4 — Continuous Verification | Core implemented |
| `05_module_access_control.md` | 5 — Access Control | Core implemented (static threshold) + RL-adaptive design (extension) |
| `06_module_secure_communication.md` | 6 — Secure Communication | Core implemented (MQTT) + TLS design (extension) |
| `07_module_monitoring.md` | 7 — Monitoring | Core implemented (SQLite log) + dashboard/governance design (extension) |
| `08_integration_and_interactions.md` | All | How the seven modules connect, in what order, with what data — includes a full worked trace of one message |

Read them in order once, then use them as reference documentation while you
extend the code phase by phase (Report Section 9).

## System at a glance

```
CPS DEVICE                          ZERO-TRUST GATEWAY                    GOVERNANCE
┌──────────┐    signed msg    ┌─────────────────────────────┐
│  Sensor/ │ ───────────────► │ 1. Device Identity lookup    │
│ Actuator │   (Module 6:     │ 2. Authentication (HMAC)     │
│  Node    │    MQTT/TLS)     │ 3. Trust Evaluation (fusion) │
└──────────┘                  │ 4. Continuous Verification   │
     ▲                        │ 5. Access Control (RL-PDP)   │
     │   decision              │ 6. Secure Comm (publish out) │──┐
     └──────────────────────  │ 7. Monitoring / Audit Log    │  │
                               └─────────────────────────────┘  │
                                                                  ▼
                                                       ┌───────────────────┐
                                                       │ NIST SP 800-207   │
                                                       │ tenet-mapped audit│
                                                       │ trail (governance)│
                                                       └───────────────────┘
```

Every module document below follows the same structure: **Purpose →
Design Rationale (literature grounding) → Data Structures → Implementation
Walkthrough → Interface Contract (inputs/outputs) → Failure Modes →
Extension Path**. This consistency is intentional — it mirrors how you
should structure the corresponding chapter in your thesis or final report.
