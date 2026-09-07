# PRD — Zero-Trust CPS / ZT-Duo

**Status:** research testbed, active build. Reconstructed 2026-09-07 after the prior root-level `PRD.md` was manually deleted; requirements below are re-derived from the current codebase (`config.py`, `iec62443_mapping.py`, `nist_mapping.py`, module docstrings), not from memory of the deleted file's prose.

---

## 1. Problem statement

Cyber-physical systems (CPS) — industrial sensors/actuators talking to a gateway — need access control that can tell apart two situations a conventional trust score conflates: **a compromised identity** (attack) and **a genuine physical fault reported by a legitimate device** (operations issue). A system that blends "is this message authentic?" and "is the physical process healthy?" into one number necessarily gets one of those two cases wrong, because the correct response (block vs. alert-and-keep-telemetry) is opposite in each case. This project builds a gateway that keeps those two questions — and their two scores — separate all the way to a policy decision, and evaluates the design against real ESP32+MPU6050 hardware, not simulation alone.

## 2. Target audience / consumers

- **Primary:** the project author, as a research deliverable — a paper and reproducible artifact evaluating a two-score, explainable Zero-Trust architecture for CPS telemetry.
- **Secondary:** downstream readers of the paper/repo — security researchers evaluating CPS Zero-Trust architectures, and engineers evaluating whether the two-score pattern (or the M6 Set Transformer relational scorer) transfers to their own device fleets.
- **Direct system consumers:** the ESP32+MPU6050 real device (`esp32-vib-001`), a second real SW-420 vibration sensor (`esp32-vib-002`, TRAIN-only capture so far), 18 network-research simulated devices, and 2 legacy scalar simulated devices (`sensor-002`, `actuator-001`) — 22 identities total in `DEVICE_REGISTRY`. A real actuator consuming `cps/decisions/<device_id>` and refusing to act unless its own latest decision is `ALLOW` is designed for but not deployed against a physical actuator in this build.

## 3. Scope

**In scope:** telemetry authentication, dual anomaly/security scoring, policy decision, explainability, hash-chained audit logging, NIST SP 800-207 / IEC 62443 governance mapping, offline model training and evaluation, a live dashboard, and a static demo build of the same UI.

**Out of scope (see METHODOLOGY.md §10 and §7 below):** physical network segmentation, multi-instance gateway redundancy, third-party security certification, detection of `stealthy_forged_values`/`combined`-class attacks from single-node telemetry, and any claim that this system is production-hardened rather than a research prototype.

## 4. Functional requirements

Mapped 1:1 to IEC 62443-3-3 Foundational Requirements (`src/iec62443_mapping.py`), because that mapping is computed from real audit-log evidence rather than asserted, and because it is the honest existing statement of what this system does and does not do.

| ID | Requirement | Status | Implementation | Evidence |
|---|---|---|---|---|
| FR1 | Identification and Authentication Control | **Implemented** | `DEVICE_REGISTRY` + HMAC-SHA256 `verify_signature()` (Modules 1/2) | `governance_validation.py` T1/T6 falsifiable checks |
| FR2 | Use Control | **Implemented** | `policy_engine.decide()` (static 2×2) / `adaptive_pdp.AdaptivePDP.greedy_action()` (Module 5) | Policy comparison, `RESULTS.md` §5 |
| FR3 | System Integrity | **Implemented** | Four-signal Process Anomaly fusion + boot_id/seq anti-replay (`trust_engine.check_boot_replay()`) + secondary timestamp-freshness check | `TestBootReplayStateIsolation`; `RESULTS.md` §3/§4 |
| FR4 | Data Confidentiality | **Implemented** | MQTT/TLS (port 8883) + HTTPS (`coap_server.py`, port 5684) — both encrypted, no plaintext fallback once `certs/` is populated | Gateway startup refuses plaintext MQTT / unconfigured broker auth |
| FR5 | Restricted Data Flow | **Partial** | Per-device MQTT broker credentials + topic ACLs (`certs/mosquitto_passwd`, `certs/mosquitto_acl`) — each device publishes only its own telemetry, reads only its own `cps/decisions/<device_id>` | **Gap, stated explicitly:** no physical/VLAN network segmentation between zones — a compromised host would still see all traffic regardless of broker ACLs |
| FR6 | Timely Response to Events | **Implemented** | Every decision logged with a reason (`audit_log.py`) + live dashboard (~2s refresh, port 8600) | — |
| FR7 | Resource Availability | **Partial** | Per-device flood/rate detection (`check_flood()`) + Identity Targeting Risk cooldown + Mosquitto connection/message-size limits + `scripts/run_gateway_supervised.py` restart-on-crash | **Gap, stated explicitly:** one gateway process (crash-resilient, not load-balanced); rate limiting is connection/message-count based, not per-client token-bucket |

## 5. Non-functional requirements

| Requirement | Target / current state | Evidence |
|---|---|---|
| Security level (IEC 62443-3-3 SL) | **SL-2** — "protection against intentional violation using simple means, low resources, generic skills, low motivation" | Design-time self-assessment (`iec62443_mapping.SECURITY_LEVEL_ASSESSMENT`); not a certification |
| Two-score separation | Never blended before `policy_engine.decide()`'s 2×2 lookup | `tests/test_invariants.py::TestTwoScoreSeparation` |
| Offline-only model training | No `.fit()`/`.update()` on the live gateway path, for any of six model stages | `CLAUDE.md` §4 "Never train on the live path" |
| Audit tamper-evidence | Hash-chained SQLite rows + separately keyed checkpoint file, catching both single-row edits and a fully-recomputed-but-inconsistent chain | `audit_log.py` `verify_chain_integrity()` / `verify_against_checkpoints()` |
| Standalone relational-scorer latency | GCN ≈1.08 ms mean; M6 ≈1.92–2.08 ms mean — both "a small fraction of the previously measured end-to-end pipeline latency" | `results/gcn_m6_corrected_comparison/latency_comparison.json` |
| Explainability | Two-level (SHAP fusion-level + feature/node drill-down); measured single-channel recovery **36%** against a 70% target — reported, not hidden | `RESULTS.md` §6 |
| Reproducibility | Every comparative evaluation loads models through a SHA-256-hash-verified `RelationalPin`, failing loudly (`ArtifactMismatchError`) on artifact drift rather than silently mixing model families | `src/relational_pin.py` |
| Test coverage | 193/193 tests passing at last verification gate | `python -m unittest discover -s tests` |

## 6. Hardware requirements

- **Primary sensor:** MPU6050 accelerometer (I2C address `0x68`) on an ESP32, MicroPython firmware. Pinout: `VCC→3.3V` (not 5V), `GND→GND`, `SDA→GPIO21`, `SCL→GPIO22`, `AD0→GND`. Sampling: 500 Hz, 32-sample windows, DLPF config 1 (184 Hz anti-alias).
- **Secondary sensor:** SW-420 vibration switch on a second ESP32 (`esp32-vib-002`) — TRAIN, VALIDATION, and TEST captures all exist as of 2026-09-07 (`data/splits/session_split.json`); held-out results: 0/108 resting FP, 115/115 detection (`RESULTS.md` §7.1).
- **Broker:** Mosquitto, TLS-enabled, per-device credentials and topic ACLs provisioned via `certs/`.
- **Gateway host:** any machine running the Python stack (`requirements.txt`); GPU optional (CUDA auto-detected, falls back to CPU with no code change).

## 7. Explicit non-goals / known-unimplemented requirements

- **No physical network segmentation** (FR5 partial) — do not claim SL beyond SL-2 or full zones-and-conduits enforcement.
- **No multi-instance gateway redundancy** (FR7 partial) — a single gateway process, crash-resilient but not load-balanced.
- **No certification claim** — `nist_mapping.py`/`iec62443_mapping.py` are an implementation mapping with a falsifiable self-check (`governance_validation.py`), not third-party certification.
- **No detection claim for `stealthy_forged_values`/`combined`-class attacks** from single-node telemetry — architecturally excluded from policy training as unlearnable from the `(security_trust, process_trust)` state space; BLOCK recall is measured at 0/33 for every policy arm tried.
- **No claim that the adaptive (contextual-bandit) policy outperforms a validation-tuned static policy** on this state space — the opposite is measured.
- **No claim of graph-structure superiority** for the relational scorer in the abstract — the defensible claim is that cross-device information helps, and specifically that the M6 Set Transformer architecture measurably outperforms the GCN architecture on identical information, not that "graphs help" as a general proposition.
- **No production-deployment readiness claim** — this is a research testbed; firmware TLS peer-certificate verification is explicitly unresolved (`CERT_NONE` in the MPU6050 firmware) and must be provisioned/validated before any real deployment.

## 8. Success criteria

A change or new capability is accepted only if it can be stated as one of:

1. A **measured** improvement on a metric already tracked in `RESULTS.md`, on the same held-out protocol, with the comparator hash-pinned via `RelationalPin` where a relational-model swap is involved.
2. A **new falsifiable governance check** in `governance_validation.py` that can actually fail on this system's own audit data (a check that cannot fail is reported `UNFALSIFIABLE`, not counted as a pass).
3. A **fix to a defect already caught by a named test** in `tests/test_invariants.py` and the other suites under `tests/`, with the fix's regression test kept.

A change is rejected if it improves a headline number by re-tuning against the same data it is evaluated on (see `CLAUDE.md` §4, "the resting normal region is sized by spread, not by the latest median" — a documented instance of exactly this failure mode, and its fix).

## 9. Stakeholder / decision record for the current architecture

| Decision | Owner | Rationale |
|---|---|---|
| M6 Set Transformer promoted over legacy GCN as deployed relational scorer (2026-09-07, `PROMOTE_CORRECTED_M6`) | Project author | Confirmed training defect in previously-deployed checkpoint; corrected retrain wins on fusion/Task-2/policy under a clean, hash-pinned comparison; zero hardware regression; see `RESULTS.md` §4–§5 |
| Contextual bandit kept as an available (non-default-preferred) policy, static table remains the stronger measured option | Project author | Measured, not assumed — `RESULTS.md` §2, §5 |
| HTTPS substituted for CoAP/DTLS in the second transport | Project author | `aiocoap`'s CoAP-over-TLS transport reproducibly failed to accept real connections on two platforms and two library versions; HTTPS on the Python standard library removes the dependency entirely |
| Hand-rolled GCN layer instead of `torch-geometric` | Project author | `torch-geometric`'s compiled extensions are version-locked and a common source of broken installs; not worth the risk for a 3–20-node graph |
