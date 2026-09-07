# Zero-Trust CPS / ZT-Duo — System Architecture & Knowledge Base

**Reconstructed 2026-09-07** after every project Markdown file was manually deleted. This document is built from the live codebase (`src/`, `scripts/`, `tests/`, `config.py`, `firmware/`), frozen evidence under `results/`, and `scripts/build_paper_results.py`'s own source — not from memory of the deleted files. Where a fact could not be verified against a file on disk in this session, it is marked `[UNVERIFIED]` rather than stated as settled.

---

## 1. Vision & Purpose

**The problem.** A Zero-Trust gateway for a cyber-physical system (CPS) must decide, on every message, whether to trust it — but "trust" is really two unrelated questions: *is this identity authentic and well-behaved* (a cybersecurity question), and *is the physical process it describes healthy* (an operations/safety question). Every conventional trust-score design blends these into one number, and that blend is provably wrong on at least one of the two situations that matter most: a compromised device reporting plausible physical values (should be blocked on identity grounds, regardless of how "normal" the physics looks), and a legitimate device correctly reporting a real fault (should be alerted-on and kept, not treated as an intrusion). Blending guarantees the same response to both.

**Why now.** Zero-Trust architectures are increasingly mandated for CPS/OT deployments (NIST SP 800-207, IEC 62443), but published implementations rarely evaluate against real hardware, rarely report negative/overturned results, and rarely make their comparator protocol reproducible enough that a claimed model improvement can be told apart from a benchmarking bug. This project treats those three gaps as the actual contribution: a real ESP32+MPU6050 device in the loop, a policy of reporting failures as prominently as successes, and a hash-pinned comparator (`src/relational_pin.py`) that turns "which checkpoint was this number measured against?" from a documentation problem into a verifiable one.

**Target audience / consumers.** The project author (research author of record, `mritulashankar@gmail.com`), readers of the resulting paper, and — as literal runtime consumers — the 22 identities in `DEVICE_REGISTRY`: one real MPU6050 vibration sensor (`esp32-vib-001`), one real SW-420 vibration sensor (`esp32-vib-002`, TRAIN/VALIDATION/TEST captures all exist as of 2026-09-07), 18 network-research simulated devices, and 2 legacy scalar simulated devices (`sensor-002`, `actuator-001`).

---

## 2. Core Concept & Mental Model

**Central metaphor.** Two independent witnesses testifying about the same event: a **notary** who only ever checks papers (identity, signature, freshness — never looks at the cargo) and an **inspector** who only ever checks the cargo (physical sensor reading — never looks at the papers). Neither is allowed to see the other's evidence while forming their opinion. A judge (`policy_engine.decide()`) hears both opinions and is the *only* place their testimony is combined — via a fixed rulebook (the 2×2 table), never by averaging their confidence.

**Design philosophy:**
- **Two-score separation is inviolable.** Never blend Security Trust and Process Anomaly Trust before the policy lookup — this is the one property every other design decision in the system is subordinate to.
- **Offline-only learning.** Every model trains in `scripts/train_*.py`, never on the live gateway path. An online-learning policy is treated as an attack surface, not a feature.
- **Report what you measured, including failure.** Level-2 explainability at 36% against a 70% target, `stealthy_forged_values` recall near zero, the adaptive bandit losing to a static policy — all stay in the record with their explanation. A metric is never swapped for one the system happens to pass.
- **A check that cannot fail is not a check.** Every governance-validation tenet names its own falsifier (`governance_validation.py`); "unfalsifiable" is a reported status, not silently upgraded to "pass."
- **Deterministic, hash-pinned comparisons.** Any claim that Model A beats Model B is only as trustworthy as the guarantee that A and B were actually evaluated against matched artifacts — enforced by `RelationalPin.verify()` raising loudly on drift rather than silently mixing model families.

---

## 3. Architecture Overview

**System topology (narrative).** A telemetry-producing device — real (ESP32 + MPU6050, MicroPython firmware) or simulated (`device_simulator.py` / `virtual_device_generator.py`) — publishes an HMAC-signed, canonically-JSON-encoded reading over MQTT/TLS (or HTTPS, via `coap_server.py`) to `gateway.py`, the single process that is both Policy Decision Point and Policy Enforcement Point. The gateway authenticates the envelope, computes a Security Trust Score from purely cyber evidence and a Process Anomaly Score from purely physical evidence (fusing four independent detectors), looks the two scores up in a fixed 2×2 table (or an offline-trained contextual-bandit policy) to get one of `ALLOW`/`ALERT`/`STEP_UP`/`BLOCK`, and writes a hash-chained, NIST/IEC-tagged audit row before optionally publishing a decision back to the device's own decisions topic. A live dashboard (served by `gateway.py` on port 8600) and a separate offline evaluation/paper pipeline (`scripts/evaluate_*.py`, `scripts/build_paper_results.py`) both read from this same audit trail and the same frozen model artifacts.

**Execution loop (per message):**
1. Parse envelope → look up claimed `device_id` in `DEVICE_REGISTRY`.
2. Verify HMAC-SHA256 signature over the canonical JSON payload.
3. Verify boot_id/sequence freshness (`check_boot_replay` — primary anti-replay, does not depend on wall-clock) then timestamp freshness (secondary, NTP-dependent).
4. **On any failure above:** reject. Update `IdentityTargetingRisk` only for the *claimed* device_id — never mutate the claimed device's actual trust state. Log and return.
5. **On success:** compute Security Trust (rate/flood, step-up outcomes, silence — `trust_engine.score_security_trust()`).
6. Compute the four Process Anomaly sub-scores (rule range check, per-device Isolation Forest, per-device LSTM-AE, relational scorer over the current active device set) and fuse them (`FusionEngine.combine()`) into one Process Anomaly Score + confidence + SHAP reason.
7. Look up `(security_trust, process_trust, process_status)` in `policy_engine.decide()` or `adaptive_pdp.AdaptivePDP.greedy_action()` → one of `ALLOW`/`ALERT`/`STEP_UP`/`BLOCK`.
8. `STEP_UP` issues a nonce challenge the device must echo in its next message. Automatic quarantine is disabled by default.
9. Write one hash-chained audit row (both scores, decision, SHAP reason, NIST/IEC tenet tags). Periodically checkpoint the chain to a separately keyed file.
10. Dashboard and downstream evaluation scripts read this same audit trail; nothing is computed twice.

**Base engine / primary rationale.** The relational (cross-device) scorer is the one component the project has actively swapped: a hand-rolled GCN (PyTorch, no `torch-geometric`, over a hybrid device graph) was the original choice, superseded on 2026-09-07 by an M6 Set Transformer (self-attention over the active device set, no declared graph, permutation-equivariant by construction) after a hash-pinned, held-out-replay-qualified comparison showed a modest but consistent win on fusion, Task-1/Task-2, and policy metrics, with zero hardware regression. GCN is preserved as a historical/comparator baseline, not deleted — see ADR-1 in §9.

---

## 4. Components & Module Boundaries

### `gateway.py` — Zero-Trust Gateway (Policy Decision + Enforcement Point)
- **Ownership:** orchestrates every other module per-message; owns the MQTT client, the HTTPS handler (via `coap_server.py`), the dashboard HTTP server, and the silence watchdog thread. Shared pipeline state is serialized by a lock.
- **Inputs & Outputs:** input = one device telemetry message (MQTT or HTTPS POST); output = one audit row + (optionally) a decision published to `cps/decisions/<device_id>` + a step-up challenge to `cps/challenge/<device_id>`.
- **Explicit boundaries:** does **not** train any model (inference only); does **not** compute scores itself (delegates to `trust_engine`/`fusion_engine`/relational scorer); does **not** blend the two scores itself (delegates to `policy_engine`/`adaptive_pdp`).

### `trust_engine.py` — Security Trust Score + per-device state store (Modules 2/3A/4)
- **Ownership:** cyber-behaviour evidence only (rate, flood, step-up outcomes, silence, boot/seq replay bookkeeping, Identity Targeting Risk). Also owns the per-device `ProcessAnomalyState` store (both scores' staleness/retention semantics), though it never computes the Process Anomaly value itself.
- **Inputs & Outputs:** input = per-message auth outcome + timing; output = `security_trust_score` (0–1, trust-style) + `process_status` (`FRESH`/`STALE`).
- **Explicit boundaries:** does **not** read or influence the Process Anomaly Score's value (only stores/retains it). Does **not** decide access (that is `policy_engine`).

### `feature_engineering.py` / `feature_engineering_sw420.py` — reference feature implementations (Module 3)
- **Ownership:** the five MPU6050 vibration features (`rms`, `peak`, `crest_factor`, `kurtosis`, `dominant_freq`) and the disjoint SW-420 feature set. The single reference every scorer, every `train_*.py`, and the on-device firmware math are checked against.
- **Inputs & Outputs:** input = raw sample window + sample rate; output = a fixed-order feature dict/vector.
- **Explicit boundaries:** pure functions, no state, no I/O. Does **not** know about devices, scoring, or policy — only about converting a sample window into numbers.

### `isolation_forest_scorer.py` / `lstm_ae_scorer.py` / `gnn_scorer.py` / `set_transformer_scorer.py` — local & relational detectors (Module 3, Phases 6a/6b/6c/M6)
- **Ownership:** each wraps exactly one trained artifact and exposes inference only. Isolation Forest scores one feature vector against a learned density; LSTM-AE scores a short sequence for gradual drift; GNN/Set Transformer score the current cross-device set for coordinated anomalies.
- **Inputs & Outputs:** input = feature vector(s) (+ current active-device context for the relational scorers); output = one score per device, 0–1.
- **Explicit boundaries:** none of the four ever calls `.fit()`/`.update()` in the live path — training lives exclusively in the matching `scripts/train_*.py`. `gnn_scorer.py`/`set_transformer_scorer.py` do **not** decide which one is "deployed" — that is `config.py`'s ambient path constants, and for comparator code, `src/relational_pin.py`.

### `fusion_engine.py` — stacking meta-learner + Level-1 explainability (Module 3, Phase 7)
- **Ownership:** combines the four Process Anomaly sub-scores into one trust value + confidence + SHAP-grounded reason string.
- **Inputs & Outputs:** input = `[rule_score, if_score, lstm_score, relational_score]`; output = `(trust: float, confidence: float, reason: str)`, plus `last_shap` (the full 4-signal SHAP vector, for the audit log/dashboard).
- **Explicit boundaries:** never blended with Security Trust — that only happens in `policy_engine`/`adaptive_pdp`. Does **not** hold references to the individual scorer instances (Level-2 explainability, which needs those, lives in `explainability.py` instead, deliberately kept out of this file).

### `explainability.py` — Level-2 explainability orchestration (Module 3, Section C)
- **Ownership:** given which of the four fused signals Level 1 named dominant, drills into which raw feature/node within that signal actually drove the score.
- **Inputs & Outputs:** input = dominant signal name + feature vector + the live scorer instances; output = `(level2_dominant_feature, level2_summary)`.
- **Explicit boundaries:** does **not** compute Level-1 SHAP itself (reads `fusion_engine.last_shap`). Does **not** run inference — only interprets outputs already computed by `gateway.py`.

### `policy_engine.py` — static Access Control Point (Module 5)
- **Ownership:** the single 2×2 lookup table that is the *only* place Security Trust and Process Anomaly meet.
- **Inputs & Outputs:** input = `(security_trust_score, process_trust_score, process_status)`; output = one of `ALLOW`/`ALERT`/`STEP_UP`/`BLOCK`.
- **Explicit boundaries:** takes **exactly** those three inputs — a fourth evidence input is architecturally forbidden (enforced by `TestTwoScoreSeparation`). Does **not** learn, adapt, or retain state across calls.

### `adaptive_pdp.py` — contextual-bandit Access Control Point (Module 5, RL-adaptive variant)
- **Ownership:** an alternative to `policy_engine.decide()`, selected via `config.USE_RL_POLICY`. Learns a Q-table offline; at runtime only ever *selects* (`greedy_action()`, pure exploitation) — never updates.
- **Inputs & Outputs:** input = `(security_trust_bucket, process_trust_bucket)` state key; output = one of the same four decisions.
- **Explicit boundaries:** `update()` exists only for `scripts/train_adaptive_pdp.py` to call. The live gateway and every `evaluate_*.py` script call `greedy_action()` only — never `update()`. Not reinforcement learning (no discount, no bootstrapping) — a contextual bandit, stated as such throughout.

### `audit_log.py` — hash-chained monitoring & audit (Module 7)
- **Ownership:** persists every trust score and decision to SQLite with a `prev_hash`/`this_hash` chain, plus a separately keyed, separate-file checkpoint store.
- **Inputs & Outputs:** input = one decision record; output = a durable, tamper-evident row + periodic checkpoint.
- **Explicit boundaries:** append-only — no update or delete path for existing rows (rows cannot be deleted to tidy up, even in tests, which must redirect `AUDIT_DB_PATH` to a temp directory instead).

### `nist_mapping.py` / `iec62443_mapping.py` / `governance_validation.py` — governance layer (Module 7 extensions)
- **Ownership:** `nist_mapping.py` tags each decision with which of NIST SP 800-207's 7 tenets it touches (coverage/tagging). `iec62443_mapping.py` maps the architecture to IEC 62443 zones/conduits and scores Foundational Requirements FR1–FR7 (implemented/partial/not_implemented). `governance_validation.py` independently checks whether a tagged claim actually *holds* against real audit-log evidence — a falsifiable check, not a tautology.
- **Explicit boundaries:** none of the three constitute certification. `governance_validation.py` reads only the audit log (the same evidence an external auditor would get), never live in-memory state — an assertion that depends on trusting the running process is not independent of it.

### `device_simulator.py` / `virtual_device_generator.py` — synthetic telemetry (Modules 1/3 support)
- **Ownership:** generate realistic multi-device telemetry (normal + attack scenarios) calibrated against measured real-hardware statistics (`REST_DC_CENTRE` etc.), for training and for populating the live demo without real hardware present.
- **Explicit boundaries:** simulator output is training/demo data, never treated as held-out validation evidence for hardware-specific claims — real-hardware sessions are evaluated separately and explicitly (`RESULTS.md` §7).

### `relational_pin.py` — comparator artifact pinning (cross-cutting, evaluation-only)
- **Ownership:** names a relational checkpoint + its matched fusion artifact together, by explicit SHA-256-verified path, for any script that needs to compare model families fairly.
- **Explicit boundaries:** not used by `gateway.py` at runtime (the gateway reads ambient `config.py` paths directly, by design — this module exists specifically to stop *comparator* scripts from silently doing the same thing when correctness of the comparison depends on not doing that).

### `firmware/main.py` — on-device client (MicroPython, ESP32)
- **Ownership:** samples the MPU6050/SW-420, computes the same five/N features as the Python reference implementation, signs and publishes over MQTT/TLS, handles boot_id persistence and step-up nonce echo.
- **Explicit boundaries:** does **not** decide anything — pure sensor-and-publish client. Firmware TLS peer-certificate verification is explicitly `[UNRESOLVED]` (`CERT_NONE` in the shipped MPU6050 firmware) — must be provisioned and validated before any real deployment.

---

## 5. Data, Memory & State Management

**Persistence layer:**

| Store | Format | Contents |
|---|---|---|
| `data/audit_log.db` | SQLite | Hash-chained decision rows (Module 7) |
| `data/audit_key.bin` | Raw key material | HMAC key for the checkpoint store — never shared with any device registry entry |
| `data/checkpoint_log.jsonl` | JSON Lines | Periodic chain checkpoints, independent of the SQLite file |
| `data/collected/` | JSON | Real-hardware sessions (`training_session.json`, `test_session.json`, `*_labelled.json`) |
| `data/splits/` | JSON | Train/validation/test split definitions |
| `config/` | JSON | `graph_topology.json`, `simulated_nodes.json`, `virtual_generator.json` — simulator/topology configuration, not runtime secrets |
| `certs/` | PEM/CRT/KEY, Mosquitto ACL/passwd files | TLS material and per-device broker credentials/ACLs |
| `models/` | `.joblib` (sklearn), `.pt` (PyTorch state dicts), `.json` (Q-tables + metadata sidecars), `.npy` (SHAP background samples) | Every offline-trained artifact, plus `*_meta.json`/`.meta.json` calibration and lineage sidecars |
| `results/` | JSON + `.log` + `.md` | Frozen evaluation evidence, one subdirectory per evaluation pass, never overwritten in place — see the naming convention in §8 |

**Key data schemas:**

Audit log row (`audit_log.py`, `log_decision()`):
```
{ device_id, timestamp, security_trust_score, process_trust_score, process_status,
  trust_score,           # legacy alias, populated with security_trust_score
  decision,               # ALLOW / ALERT / STEP_UP / BLOCK / REJECTED / SILENT
  reason, reason_category, nist_tenets,   # comma-separated tenet numbers
  transport,              # "mqtt" / "https" / "" (empty for gateway-originated rows)
  auth_ok, prev_hash, this_hash }
```

Relational-pin lineage sidecar (`models/*.meta.json`, written by `train_adaptive_pdp.py`):
```
{ pin_name, relational_checkpoint_sha256, fusion_model_sha256,
  seed, clock_protocol, training_config, commit_hash }
```

Feature vector (Module 3, `feature_engineering.py`):
```
{ rms: float, peak: float, crest_factor: float, kurtosis: float, dominant_freq: float }
```
(SW-420 devices instead carry `{ trigger_rate, ... }` — the two sets are disjoint by design, so `feature_vector()` dispatches on which keys are present.)

**State lifecycle:**
- **Write:** every authenticated message updates `trust_engine`'s per-device store (both scores) and appends one audit row. A rejected message updates only `IdentityTargetingRisk` for the claimed identity — never the claimed device's actual trust state.
- **Read:** the dashboard and every `evaluate_*.py`/`build_paper_results.py` script read the audit log / frozen `results/*.json` — never live in-process state, so evaluation is reproducible from artifacts alone.
- **Update:** no in-place update of any audit row (append-only, hash-chained). Model artifacts are versioned by filename suffix (`_corrected`, `_gcn_backup`, `_m6_variant`) rather than overwritten — a promoted artifact's predecessor stays on disk, byte-identical, reachable via `relational_pin.py`.
- **Invalidation/eviction:** `ProcessAnomalyState.score` is retained exactly (never faded) on silence — there is no implicit eviction of an unresolved anomaly. Rotated audit-log files are archived with a `.archived-<timestamp>` suffix, which `.gitignore` must match explicitly (`*.db` alone does not match `audit_log.db.archived-…`).

---

## 6. External Tooling & Integrations

**Third-party dependencies and integration interfaces** (`requirements.txt`):

| Dependency | Used for | Note |
|---|---|---|
| `paho-mqtt>=2.0` | MQTT/TLS transport (Module 6) | — |
| `numpy>=1.24` | Feature engineering, GNN/LSTM scorers | Direct import, not just transitive |
| `scikit-learn>=1.3` | Isolation Forest, `LogisticRegression` fusion meta-learner | Pulls in `scipy` (used directly for `ks_2samp` in the generator validator) |
| `joblib>=1.4` | Saving/loading sklearn artifacts | — |
| `torch>=2.0` | LSTM-AE, hand-rolled GCN, Set Transformer | CPU/GPU auto-detected; GCN training is batched per-epoch (not per-sample) after a measured ~6.5× GPU slowdown from unbatched kernel-launch overhead was found and fixed |
| `shap>=0.52` | Level-1 fusion explainability (`LinearExplainer`) | Must be ≥0.46-ish for NumPy 2.x; an old cached 0.44.1 install crashes on import |
| `matplotlib>=3.7` | Figure generation only | Not a runtime dependency |
| ~~`aiocoap`~~ | **Not used** — tried, rejected | CoAP-over-TLS transport reproducibly failed to accept real connections (verified on native Windows and WSL/Linux, two library versions); replaced with an HTTPS endpoint on the Python standard library |

**Extensibility — registering a new device:**
1. Add an entry to `DEVICE_REGISTRY` in `config.py` (secret, `kind`, expected range or feature set, MQTT credentials).
2. If it is a new *sensor type* (feature names disjoint from existing sets), add a `feature_engineering_<type>.py` module and extend `feature_vector()`'s key-based dispatch.
3. Provision per-device MQTT broker credentials + topic ACL (`certs/mosquitto_passwd`, `certs/mosquitto_acl`).
4. If it is a real device: implement/port `firmware/main.py`'s HMAC + canonical-JSON signing for its target hardware, verify formula parity against the Python reference feature module by differential test, not code review.
5. Retrain the six-stage chain in order (§8 below) so per-device Isolation Forest/LSTM-AE artifacts and the relational scorer's node-feature slot exist for the new device.
6. Add the device to any simulator/topology config (`config/graph_topology.json`, `config/simulated_nodes.json`) if it should also be reachable via simulation.

**Extensibility — registering a new relational-scorer candidate (e.g., a future M10):**
1. Implement inference class + shared training-time architecture module, mirroring `gnn_scorer.py`/`set_transformer_scorer.py`'s split (`_GCN`/`_SetTransformer` importable by both the scorer and its `train_*.py`).
2. Add a `scripts/train_<name>.py`, offline-only.
3. Add a `RelationalPin` entry in `src/relational_pin.py` with a recorded SHA-256 hash — do not compare it against an existing arm without this.
4. Run the comparator suite (`evaluate_ablation_m6.py`-equivalent, `evaluate_real_hardware.py --relational-model`, `evaluate_policy_comparison.py`) pinned explicitly to both arms.
5. Only promote to `config.py`'s ambient paths after a documented decision record (see ADR pattern in §9) — never by editing the ambient path without a comparison.

---

## 7. Tech Stack & Infrastructure Rationale

| Layer | Technology | Rationale & why chosen | Alternative rejected |
|---|---|---|---|
| Language | Python 3 | Single language across gateway, training, and evaluation; rich ML ecosystem | — |
| On-device firmware | MicroPython (ESP32) | Small footprint, direct hardware I2C/WiFi access, fast iteration | A C/C++ ESP-IDF firmware would be faster but far slower to iterate on for a research prototype |
| Local anomaly detectors | `sklearn.IsolationForest`, hand-rolled LSTM-Autoencoder (`torch`) | Cheap, well-understood baselines for per-device density/sequence anomaly; no need for a heavier model at this data volume | — |
| Relational (cross-device) scorer | M6 Set Transformer (self-attention, `torch`, hand-rolled) — deployed; GCN — historical/comparator | Set-based attention needs no declared graph and is permutation-equivariant by construction; measured to modestly beat GCN on fusion/Task-1/Task-2/policy under a hash-pinned comparison, zero hardware regression | `torch-geometric` (rejected — version-locked compiled extensions, common install breakage, not worth the risk for a ≤20-node graph); GCN alone (superseded, not deleted — kept as historical baseline) |
| Fusion | `sklearn.LogisticRegression` stacking meta-learner + `shap.LinearExplainer` | Simple, interpretable, exact closed-form SHAP (affordable per-message); coefficients kept sign-stable across relational-scorer swaps by deliberately keeping both fused scores trust-style | A neural fusion layer would remove the closed-form SHAP guarantee and complicate the explainability story for no measured accuracy benefit |
| Policy | Static 2×2 table (default, currently stronger) + contextual bandit (offline-trained alternative) | The static table is simple, auditable, and currently the better-measured option; the bandit is retained as a documented, honestly-reported negative result, not removed | Full reinforcement learning (rejected — no natural multi-step reward signal in this problem; the bandit framing fits the actual decision structure) |
| Transport | MQTT/TLS (primary), HTTPS on stdlib `http.server`+`ssl` (secondary) | Both encrypted, no plaintext fallback once `certs/` is populated; HTTPS needs zero extra dependency | CoAP/DTLS via `aiocoap` (rejected — reproducible connection-acceptance failure across two OS/library-version combinations) |
| Audit storage | SQLite + hash chain + separately keyed checkpoint file | Durable, embedded, no server process; hash chain + independent checkpoint store catches both single-row tampering and a fully-recomputed-but-inconsistent chain | A write-only external log service would add an operational dependency this research prototype doesn't need |
| Governance mapping | Custom NIST SP 800-207 / IEC 62443 tagging + independent falsifiable validation | No off-the-shelf tool computes tenet coverage *and* validates the claim against this system's own audit evidence | Asserting compliance in prose only (rejected — the whole point is that a claim without a falsifier is not evidence) |

---

## 8. Coding Conventions & Project Structure

**Directory layout:**

```
src/            gateway.py, trust_engine.py, policy_engine.py, adaptive_pdp.py,
                fusion_engine.py, explainability.py, feature_engineering{,_sw420}.py,
                config.py, audit_log.py, nist_mapping.py, iec62443_mapping.py,
                governance_validation.py, relational_pin.py, coap_server.py,
                device_simulator.py, virtual_device_generator.py, datasets.py, splits.py,
                {isolation_forest,lstm_ae,transformer,gnn,set_transformer}_scorer.py,
                secrets_local.py (gitignored), secrets_local.example.py
firmware/       main.py (MicroPython, on-device), HARDWARE_SETUP.md, HARDWARE_SETUP_SW420.md
scripts/        train_*.py, evaluate_*.py, generate_*.py, benchmark_crossdevice_models.py,
                collect_hardware_session.py, merge_real_hardware_data.py,
                build_paper_results.py, verify_paper_package.py
models/         trained artifacts + *_meta.json / *.meta.json calibration+lineage sidecars
data/           audit_log.db, checkpoint_log.jsonl, audit_key.bin, collected/, splits/
config/         graph_topology.json, simulated_nodes.json, virtual_generator.json
certs/          TLS material, Mosquitto ACL/credentials
results/        one subdirectory per evaluation pass (frozen JSON/log/summary.md evidence)
design/         static demo build of the dashboard UI (no live gateway required)
tests/          19 focused test files, stdlib unittest (no pytest)
```

**Naming conventions:**
- Model artifacts: `<architecture>_<variant>.{pt,joblib}` — `_gcn_backup`, `_m6_variant`, `_m6_corrected_variant`, `_corrected` suffixes mark provenance explicitly; a bare name (no suffix) means "currently ambient/ ever-deployed."
- Result directories: `results/<evaluation_name>/` — one directory per evaluation pass, never reused for a re-run with different findings (a repaired comparator gets a new directory, e.g. `gcn_m6_corrected_comparison`, not an overwrite of the old one).
- Test files: `test_<subsystem_or_invariant>.py`, one class per invariant under test (e.g. `TestTwoScoreSeparation`, `TestBootReplayStateIsolation`).
- Config constants: `SCREAMING_SNAKE_CASE` in `config.py`; every constant whose value affects trained-model correctness (sample rate, window size, thresholds) is a single source of truth read by both training scripts and the live gateway — never duplicated as a literal elsewhere.

**Error handling strategy:** fail loudly on artifact/provenance mismatches (`ArtifactMismatchError` in `relational_pin.py`) rather than silently falling back to a plausible-looking wrong artifact. Fall back gracefully only where "not trained yet" is a legitimate, expected state (`FusionEngine.combine()`'s plain-mean fallback before the meta-learner exists). Reject-and-log, never reject-and-drop, for authentication failures — every rejection is an audit row.

**Logging & observability:** every decision is a structured audit-log row (§5) carrying both scores, the decision, a human-readable + machine-tagged reason, and NIST/IEC tenet tags. A live dashboard (served by `gateway.py`, port 8600, ~2s refresh) renders this in real time. There is no separate structured-logging framework beyond the audit log itself and console output — the audit log *is* the observability surface, deliberately, since it is also the governance-evidence artifact.

---

## 9. Decision Log (ADRs)

**ADR-1: Promote M6 Set Transformer over GCN as the deployed relational scorer (2026-09-07).**
- **Context:** A confirmed class-weight training defect (7.2× overweight on the suspicious class, from computing inverse-frequency weights over an unmasked tensor when the loss only trains on the masked subset) made the originally-deployed M6 checkpoint's standalone score badly miscalibrated (Macro-F1 0.0736). A comparator bug independently meant every prior "GCN vs. M6" comparison had silently mixed model families.
- **Chosen path:** Fix both bugs; retrain M6 (`set_transformer_corrected.pt`); compare under hash-pinned, held-out-replay-qualified protocol; promote on a clean gate sweep (lineage, fusion, policy, 193/193 tests, zero hardware regression, latency within budget). Preserve every previously-deployed artifact byte-identical on disk.
- **Rejected alternatives:** (a) revert to GCN outright — rejected, since GCN itself scores worse on Task-1/Task-2 and is not architecturally superior, just not affected by this particular bug; (b) redeploy the flawed M6 checkpoint anyway on standalone-score grounds alone — explicitly rejected per the promotion record ("not decided on standalone Macro-F1 alone").

**ADR-2: Never blend Security Trust and Process Anomaly Trust before `policy_engine.decide()`.**
- **Context:** A blended score cannot distinguish "forged papers, normal cargo" from "valid papers, machine shaking" — opposite correct responses.
- **Chosen path:** Two independently computed, trust-style scores, combined only via a fixed 2×2 lookup (or its bandit equivalent), enforced by a dedicated invariant test.
- **Rejected alternatives:** a single EWMA'd trust score (the system's own prior design, explicitly rearchitected away from); a weighted-average combination (rejected for the same reason — averaging still conflates the two failure modes, just with tunable knobs).

**ADR-3: Offline-only model training; no online learning in the live gateway path.**
- **Context:** An online-learning PDP would let anyone who can generate traffic move the model.
- **Chosen path:** All six model stages train exclusively in `scripts/train_*.py`; `gateway.py` and `adaptive_pdp.AdaptivePDP.greedy_action()` never call `.fit()`/`.update()`.
- **Rejected alternatives:** continual/online fine-tuning of the relational scorer or policy against live traffic — rejected as an unacceptable attack surface, not a performance tradeoff.

**ADR-4: Hand-rolled GCN instead of `torch-geometric`; HTTPS instead of CoAP/DTLS.**
- **Context:** Both are dependency-risk decisions.
- **Chosen path:** Plain-PyTorch matrix-multiply GCN layer; stdlib `http.server`+`ssl` for the second transport.
- **Rejected alternatives:** `torch-geometric` (version-locked compiled extensions, common install breakage, not worth it for ≤20 nodes); `aiocoap`'s CoAP-over-TLS (reproducible connection-refusal defect on two OS/library-version combinations, verified before rejecting).

**ADR-5: Explicit, hash-verified artifact pinning for comparator scripts (`src/relational_pin.py`).**
- **Context:** Four evaluator scripts silently read whichever fusion artifact was *currently* ambient in `config.py`, which was correct only until the M6 deployment changed what "ambient" meant — every subsequent "GCN arm" measurement was actually comparing GCN relational scores against M6-calibrated fusion coefficients, undetected until audited.
- **Chosen path:** `RelationalPin` dataclasses naming both a relational checkpoint and its matched fusion artifact by explicit path, hash-verified, failing loudly on mismatch.
- **Rejected alternatives:** documenting the correct artifact pairing in a comment (rejected — this is exactly the kind of drift comments don't catch; the whole prior failure happened despite the code being readable).

**ADR-6: Keep both trust scores on a "high = good" scale, including Process Anomaly.**
- **Context:** The literal module-docstring naming in early design docs implied Process Anomaly should be "high = bad" (anomaly-style).
- **Chosen path:** Keep both trust-style, so the already-fitted fusion meta-learner's coefficients (verified positive-signed against real held-out data) never had to change sign across the rearchitecture.
- **Rejected alternatives:** inverting Process Anomaly to anomaly-style and re-deriving fusion coefficients — rejected as unnecessary churn with no measured benefit, and a documented, deliberate naming deviation rather than an oversight.

---

## 10. Roadmap & Milestones

**Current phase:** post-promotion stabilization of the corrected-M6 deployment (commit `1326db1` and its immediate predecessors) — reconciling every stale GCN-runtime reference project-wide, regenerating the paper figure set against the corrected-M6 evidence, and (this document) rebuilding the deleted Markdown knowledge base from source.

**Upcoming phase (genuine future scope — do not claim as solved):**
- `esp32-vib-002`/SW-420's held-out results (0/108 resting FP, 115/115 detection, `RESULTS.md` §7.1, captured 2026-09-07) rest on two sessions — a real minimum, not a large sample; widening it needs more independent captures, the same way `esp32-vib-001`'s 5/12 does.
- Physical fault injection on real hardware — all captured hardware events to date are legitimate physical conditions; only transport-level attacks have been tested against the real device.
- Tightening the resting false-positive confidence interval (currently 5/12, Wilson CI 19.3–68.0%, on a small dependent-window sample) — needs many more clean resting sessions; mounting-robustness capture is the highest-value next experiment.
- A second sensor to test whether resting-DC spread is a sensor property (ADR-18 in the deleted historical log assumed this; one unit cannot prove it).
- A decision on whether to redeploy `set_transformer_corrected.pt`'s *training recipe* more broadly, versus leaving the current promoted checkpoint as the operating point.

**Explicit out-of-scope (this project will never claim):**
- Physical/VLAN network segmentation between zones (FR5 stays "partial" by design boundary, not by oversight).
- Multi-instance gateway redundancy/failover (FR7 stays "partial").
- Third-party security certification of any kind.
- Detection of `stealthy_forged_values`/`combined`-class attacks from single-node telemetry (architecturally excluded, not an open bug).
- A claim that graph/attention structure is inherently superior to simpler cross-device models in general — only the specific, measured claim that M6 beats GCN and simpler baselines *on this system's data* is made.
- A claim that the adaptive bandit outperforms a validation-tuned static policy on this state space.

---

## 11. Evaluation, Testing & Verification

**Testing strategy:** stdlib `unittest`, no pytest, 19 test files under `tests/` (`python -m unittest discover -s tests`), 193/193 passing at the last verification gate. Coverage spans: two-score separation, boot/replay state isolation, firmware HMAC/TLS contract parity, policy-training determinism, relational-comparator pinning, GNN/Set-Transformer pending-node masking (three separate files — GCN baseline, GNN pending-node, Set-model pending-node), credential-scanner regression, dashboard hash normalization, coAP/HTTPS hardening, gateway input validation, and general invariants.

**Verification scenarios that define correctness (each guards a property that has already been broken once):**
- A rejected message must never change the claimed device's actual trust state (`TestBootReplayStateIsolation` and related).
- The two scores must never be combinable through a third evidence channel (`TestTwoScoreSeparation`).
- No model artifact may be older than its training data (`test_no_model_artifact_is_older_than_its_training_data`) — catches silent staleness like the Transformer-ablation incident that invalidated ~6 retrains' worth of published numbers.
- `config.FEATURE_SAMPLE_RATE_HZ` must exactly match the firmware's own sampling rate — a mismatch here is invisible to every offline evaluation and only shows up as train/serve skew on real hardware.
- Filling the LSTM window must drop `2*LSTM_SEQ_LEN-1` records per block, not `LSTM_SEQ_LEN-1` — dropping too few leaves settling disturbance inside the first "clean" scored window.
- Every NIST governance tenet check must be able to fail on this system's own data, or it is reported `UNFALSIFIABLE`, never silently counted as passing.
- A relational/fusion comparator must fail loudly (`ArtifactMismatchError`) on any artifact-hash drift, never silently substitute a different checkpoint.

**Statistical discipline (see `METHODOLOGY.md` §7 for full detail):** session-level (leakage-free) splits, hash-pinned matched comparisons, deterministic offline-replay clocks, ten-seed studies reported as optimizer-variance-only (not population CIs), and explicit acknowledgment that reported per-row metrics are `(tick, node)` windows nested in a small number of anomaly events, not independent trials.

---

## 12. Known Limitations & Open Risks

**Fragile areas (do not "fix" without re-reading why they are this way — see `CLAUDE.md` §4 for the full incident list this section summarizes):**
- The acquisition chain (`SAMPLE_RATE_HZ`, `WINDOW_SIZE`, DLPF config) moves as one unit — changing any one without a full retrain silently invalidates every `dominant_freq` the models learned.
- `REST_DC_CENTRE` must be sized by the *spread* of observed resting values across sessions, not the latest session's median — re-tuning it onto one session has already caused a real board to land at −4.0σ from "normal."
- `feature_engineering.py` is a reference implementation the firmware must match exactly; verify by differential test over randomised windows, never by code review alone.
- Window-averaged reconstruction error is not severity — a peak-aware statistic does not trivially fix this (tried; Spearman ρ 0.781→0.723).

**Performance/measurement bottlenecks:**
- Real-hardware resting false-positive rate (5/12, 41.7%) has a wide confidence interval (19.3–68.0%) from a small, dependent-window sample — not yet tight enough for a strong deployment claim.
- Level-2 explainability recovers only 36% of flagged cases against a 70% target — structurally, a rank-1 instrument explaining a rank-3 anomaly signal, not a bug awaiting a fix.
- M9 (mixed-provenance relational scorer) degrades sharply in precision/FPR under heterogeneity stress (F1 0.68→0.30 LOW→HIGH) despite retaining near-1 recall — a calibration failure that must always be reported with FPR/precision, never recall alone.

**Technical debt / open items:**
- **[CLOSED 2026-09-07]** SW-420 (`esp32-vib-002`) now has held-out VALIDATION (0/70 FP, 109/109 detection) and TEST (0/108 FP, 115/115 detection) real-hardware results — `RESULTS.md` §7.1, `results/sw420_real_hardware/summary.md`. Closing this exposed and fixed a real bug: `evaluate_real_hardware.py` had `DEVICE` hardcoded to `esp32-vib-001`, and once an `esp32-vib-002` session entered the same split, the evaluator would have silently scored SW-420 rows through the MPU6050's models. Fixed with an explicit `--device` argument and per-device row filtering; verified `esp32-vib-001`'s published numbers reproduce byte-identically with the fix in place. Still only two independent sessions — a real minimum, not a large sample.
- **[HARDENED, not flash-verified, 2026-09-07]** Firmware TLS peer-certificate verification (`CERT_NONE` default) now fails loudly on three distinct failure modes instead of silently downgrading or crashing opaquely when `MQTT_CA_CERT_FILE` opt-in verification is requested (`firmware/main.py::connect_mqtt()`), and `HARDWARE_SETUP.md` §13 has a concrete one-line command to generate the DER CA cert. Still not flash-tested against real hardware — `ussl.wrap_socket`'s `ca_certs` support varies by MicroPython build, so this remains a real gap until verified on a board.
- **[FIXED 2026-09-07]** `evaluate_rl_policy.py` and two call sites in `generate_evaluation_graphs.py` were silently defaulting to the GCN pin regardless of which relational model the ambient-deployed policy Q-table was actually trained against — the same silent-mismatch failure class the fusion comparator bug was. Fixed via `resolve_deployed_pin()`, which reads the Q-table's own metadata sidecar and hash-verifies it through `relational_pin.verify_policy_lineage()` before use, failing loudly on an unpinned table (exactly the legacy `adaptive_pdp_qtable.json`/`*_corrupted_provenance` case). Verified end-to-end and the full 193-test suite still passes.

---

## 13. Glossary

- **Security Trust Score** — trust-style (high=good) score computed from cyber evidence only (identity, HMAC, freshness, rate, step-up outcomes, silence).
- **Process Anomaly (Trust) Score** — trust-style (high=good) score computed from physical sensor evidence only, fused from four sub-detectors.
- **Two-score separation** — the architectural invariant that the two scores above are never blended before the policy lookup.
- **PDP / PEP** — Policy Decision Point / Policy Enforcement Point; both roles are implemented in the single `gateway.py` process.
- **RelationalPin** — a hash-verified pairing of a relational-scorer checkpoint and its matched fusion artifact, used by comparator scripts to prevent silent model-family mixing (`src/relational_pin.py`).
- **M6** — the Set Transformer relational-scorer architecture; the currently deployed relational scorer as of 2026-09-07.
- **GCN** — the legacy graph-convolutional relational scorer; preserved as a historical/comparator baseline, not deployed.
- **M1–M9** — the offline cross-device benchmark model family (`scripts/benchmark_crossdevice_models.py`): concat-MLP, gradient boosting, Deep Sets, GCN, GATv2, Set Transformer, NP-ST, mixed-cardinality ST, mixed-provenance ST.
- **Fusion meta-learner** — the `LogisticRegression` stacking model combining the four Process Anomaly sub-scores.
- **Level-1 / Level-2 explainability** — SHAP over the four fused sub-scores (Level 1) and a drill-down into the dominant sub-score's own driving feature/node (Level 2).
- **Contextual bandit (adaptive PDP)** — the offline-trained, epsilon-greedy-selected alternative policy; explicitly not RL/Q-learning.
- **Held-out-replay-qualified** — a comparison measured on the untouched `test_session.json` under a matched, hash-pinned artifact pairing.
- **Session-level split** — a train/validation/test split that keeps entire recording sessions on one side of the split, preventing the leakage that produced the withdrawn 0/49 and 1/29 resting-FP figures.
- **Identity Targeting Risk** — a per-claimed-identity cooldown counter that throttles repeated failed-auth attempts against one device_id, without ever touching that device's actual trust state.
- **Hash chain / checkpoint store** — the two-layer audit-log tamper-evidence mechanism: in-row `prev_hash`/`this_hash` linking, plus an independent, separately keyed periodic checkpoint file.
- **FR1–FR7** — IEC 62443-3-3 Foundational Requirements; this system scores FR1/FR2/FR3/FR4/FR6 "implemented" and FR5/FR7 "partial" (see `PRD.md` §4).
- **SL-2** — the IEC 62443-3-3 Security Level this system targets ("protection against intentional violation using simple means, low resources, generic skills, low motivation") — a design-time self-assessment, not a certification.
- **Stealthy forged values / combined class** — the attack pattern this system's policy layer architecturally cannot learn to BLOCK from a `(security_trust, process_trust)` state space alone; reported as a negative result, not hidden.
