# METHODOLOGY — Zero-Trust CPS / ZT-Duo

**Paper title:** "Explainable Zero-Trust Trust Evaluation for Cyber-Physical Systems Using Ensemble Anomaly Detection and Graph Neural Networks" (working blueprint title: "ZT-Duo: Dual-Channel Trust Evaluation for Zero-Trust Security of IoT-Based Cyber-Physical Systems").

**Status as of 2026-09-07 (commit `1326db1`):** current-authority document, reconstructed after the prior `docs/paper/00–25` evidence set and root-level `METHODOLOGY.md`/`RESULTS.md`/`PRD.md`/`ZERO_TRUST_CPS_KB.md` were manually deleted. Every number in this document and in `RESULTS.md` is re-derived from frozen JSON under `results/`, from `scripts/build_paper_results.py` (the generator that used to render the deleted `docs/paper/13_RESULTS_MASTER_TABLES.md`), and from source code read directly — nothing here is transcribed from memory of the old prose. Where a claim cannot be grounded in a file on disk, it is marked `[UNVERIFIED — re-derive before citing]` rather than restated as fact.

**Reporting standard (non-negotiable):** report what was measured, including when it fails. Never swap a metric for one the system happens to pass. Where the system underperforms (Level-2 explainability 36% vs. a 70% target, `stealthy_forged_values` recall ≈ 0), the number stays in the record with its explanation.

---

## 1. Problem framing and the central design decision

A cyber-physical system (CPS) gateway that treats "is this message cryptographically valid?" and "is the physical process it describes behaving normally?" as one blended trust number cannot distinguish two operationally opposite situations:

- **Forged papers, normal cargo** — a compromised or spoofed identity reporting plausible physical values. Correct response: block/step-up on identity grounds.
- **Valid papers, machine shaking** — a real, authenticated device correctly reporting a real physical fault. Correct response: alert operations, keep the telemetry, do **not** treat the device as compromised.

A single EWMA'd trust score conflates these into the same low reading and prescribes the same response to both — wrong for at least one of them every time. The system's one central architectural commitment is to never let that conflation happen.

## 2. The two-score architecture

| | **Security Trust Score** | **Process Anomaly (Trust) Score** |
|---|---|---|
| Evidence | Identity, HMAC signature, freshness, boot/sequence replay state, rate/flood behaviour, step-up outcomes, silence | The physical sensor reading only |
| Computed by | `trust_engine.score_security_trust()` (Module 2/3A) | `trust_engine.rule_range_score()` + `isolation_forest_scorer` + `lstm_ae_scorer` + relational scorer → `fusion_engine.FusionEngine.combine()` (Module 3B) |
| Answers | "Is this identity behaving like itself, cryptographically and behaviourally?" | "Is the machine behaving normally, physically?" |
| Scale | Trust-style: **high = good**, for both scores | Trust-style: **high = good** (a deliberate, documented deviation from an anomaly-style high-is-bad scale — kept so the already-fitted fusion meta-learner's coefficients, verified positive-signed against held-out data, never had to change sign when the rearchitecture happened) |

The two scores are computed from **disjoint evidence** and are combined **exactly once**, in `policy_engine.decide()`'s 2×2 lookup table — never averaged, never blended into a third number before that point. This is enforced by `tests/test_invariants.py::TestTwoScoreSeparation`; a third evidence input into `decide()` is treated as proof the separation has leaked, not as an enhancement.

```python
def decide(security_trust_score, process_trust_score, process_status="FRESH"):
    security_high = security_trust_score >= SECURITY_THRESHOLD   # 0.6
    process_high  = process_trust_score  >= PROCESS_THRESHOLD    # 0.6
    if security_high and process_high:     return "ALLOW"
    if security_high and not process_high: return "ALERT"    # real fault, not an attack
    if not security_high and process_high: return "STEP_UP"
    return "BLOCK"                         # highest-risk: compromised device ALSO reporting abnormal data
```

`process_status` (`FRESH`/`STALE`) is threaded through for logging (`STALE_HIGH_ANOMALY_UNRESOLVED`), not as a branch: `ProcessAnomalyState.score` is retained exactly on silence, never faded toward "normal," so a stale-but-low score already carries the same unresolved-concern weight a fresh low score would.

## 3. Seven-module pipeline

```
Device (real ESP32+MPU6050 or simulator)
   │  MQTT/TLS or HTTPS
   ▼
Module 1  Device Identity        DEVICE_REGISTRY lookup (22 identities)
Module 2  Authentication         HMAC verify → boot/seq replay check → timestamp freshness →
                                  step-up challenge/response → IdentityTargetingRisk bookkeeping
                                  (a rejected message never touches the CLAIMED device's own state)
Module 3A Security Trust         trust_engine.score_security_trust() — rate/flood, step-up
                                  outcomes, silence
Module 3B Process Anomaly Trust  rule_range_score + IsolationForest + LSTM-AE + relational
                                  scorer (M6 Set Transformer, live) → FusionEngine.combine()
                                  → (trust, confidence, SHAP reason)
Module 4  Continuous Verify      per-device state store for BOTH scores; both recomputed on
                                  every authenticated message
Module 5  Access Control (PDP)   policy_engine.decide() (static 2×2) or adaptive_pdp
                                  (contextual bandit, USE_RL_POLICY toggle) — reads both scores,
                                  combines only through this lookup
Module 6  Secure Communication   MQTT/TLS (gateway.py) + HTTPS (coap_server.py — historical
                                  filename; implements HTTPS POST, not CoAP/DTLS — see §9)
Module 7  Monitoring & Audit     audit_log.log_decision() — hash-chained SQLite + separately
                                  keyed checkpoint file + NIST SP 800-207 / IEC 62443 tenet tags
```

A rejected verification never mutates the *claimed* device's trust state — this closes a trust-poisoning DoS where an attacker who knows nothing secret could otherwise degrade a real device's score just by spoofing its identity and failing auth repeatedly (load-bearing beyond the threat model: a real clock misconfiguration once rejected the genuine board hundreds of times, and its trust score correctly never moved).

## 4. Feature engineering (Module 3, `feature_engineering.py`)

Five vibration-analysis features computed from a 32-sample accelerometer-magnitude window, **identically** on the ESP32 firmware (MicroPython, on-device) and in this Python reference implementation the models are trained against:

| Feature | Formula | Physical meaning |
|---|---|---|
| `rms` | √mean(x²) | Overall vibration energy — primary severity indicator |
| `peak` | max(x) − min(x) | Peak-to-peak amplitude — shock events, impacts |
| `crest_factor` | peak / rms | Impulsiveness — high crest factor at normal RMS suggests early bearing damage |
| `kurtosis` | excess kurtosis (4th standardised moment) | Sensitivity to sharp, infrequent spikes RMS smooths over |
| `dominant_freq` | FFT peak-magnitude bin (DC excluded) | Frequency-domain fault signature (unbalance ≈1× running speed, misalignment ≈2×, bearing defects at characteristic frequencies) |

The acquisition chain — `SAMPLE_RATE_HZ=500` (feature-side `FEATURE_SAMPLE_RATE_HZ=500.0`), `WINDOW_SIZE=32`, `MPU6050_DLPF_CFG=1` (184 Hz anti-alias filter) — moves together as one decision: every learned `dominant_freq` is scaled by the sample rate, so changing any one of the three requires a full retrain across all six model stages. This exact firmware/host formula match is verified by differential test over randomised windows (`tests/test_firmware_hmac_source_contract.py` family), not by code review, because a silent formula drift here creates train/serve skew no offline evaluation can detect.

A second real sensor type, SW-420 (`esp32-vib-002`), has its own disjoint feature set (`feature_engineering_sw420.py`, keyed on `trigger_rate` rather than `rms`); `feature_vector()` dispatches on which keys a reading actually carries, not on a device-id parameter, so the two sensor types can coexist without threading a type flag through ~20 call sites.

## 5. Model zoo

### 5.1 Local per-device detectors (offline-trained, inference-only at runtime)

| Model | Role | Architecture | Trained by |
|---|---|---|---|
| Rule engine | Cheap sanity baseline | Hand-written range/threshold checks | n/a (no training) |
| Isolation Forest | Density-based outlier score, one feature vector at a time | `sklearn.ensemble.IsolationForest`, one model per device | `scripts/train_isolation_forest.py` |
| LSTM-Autoencoder | Sequence-level drift detector — catches gradual behavioural drift a single-message model can't see by construction | Per-device LSTM-AE, reconstruction error vs. learned per-device mean/std | `scripts/train_lstm_ae.py` |

### 5.2 Relational scorer — the multi-device signal

The relational scorer takes the concurrent local scores of every active device and produces one cross-device score per node, capturing coordinated (multi-device) anomaly patterns a purely local detector cannot see.

- **GCN (legacy, preserved as historical/comparator baseline — `gnn_scorer.py`).** Hand-rolled graph-convolution layer (plain PyTorch matrix multiply against a normalised adjacency, not `torch-geometric` — rejected because its compiled extensions are version-locked and a common source of broken installs, not worth the risk for a 3–20-node graph where a hand-rolled layer does identical math). Graph = hybrid device graph: nodes are `DEVICE_REGISTRY` entries, edges = "communicated with the gateway in the same `GNN_EDGE_WINDOW_SECONDS` window," node features = `[rule_score, isolation_forest_score, lstm_ae_score]`.
- **M6 Set Transformer (deployed relational scorer as of commit `3c827e8`, 2026-09-07 — `set_transformer_scorer.py`).** No declared graph at all: every active device attends to every other active device via self-attention; an inactive device is excluded via a `key_padding_mask` rather than a zero-weight edge. Permutation-equivariant by construction. Same node-feature vector as GCN, so the two are directly comparable, not scored on different inputs. `gnn_scorer.GNNScorer` remains importable under the class alias `SetTransformerScorer as GNNScorer` in `gateway.py` — the class name is a legacy alias, not a description of the deployed architecture.
- **M1–M9 offline benchmark family (`scripts/benchmark_crossdevice_models.py`, standalone protocol, not the runtime path):** concat-MLP (M1), gradient boosting (M2), Deep Sets (M3), GCN (M4), GATv2 (M5), Set Transformer (M6), NP-ST (M7, negative ablation result), mixed-cardinality Set Transformer (M8), mixed-provenance Set Transformer (M9, hybrid real+virtual training). See `RESULTS.md` §B/C for the full comparative table — M6 is the strongest single-seed row on this fixed 20-node hybrid test corpus.

### 5.3 Fusion (Module 3, Phase 7 — `fusion_engine.py`)

A `LogisticRegression` **stacking meta-learner**, fit offline (`scripts/train_fusion_meta_learner.py`) on `[rule_score, isolation_forest_score, lstm_ae_score, <relational>_score]` against real ground-truth labels, never on the live path. `combine()` returns `(trust, confidence, reason)`; before the meta-learner exists it falls back to a plain mean with confidence 0.5 (maximally uncertain), not a crash. Coefficients are kept trust-style-positive by construction (§2) so nothing about this layer changed sign when the relational scorer switched from GCN to M6.

### 5.4 Explainability (Module 3, Section C)

Two levels, deliberately separated:

- **Level 1** — `fusion_engine._explain()`, `shap.LinearExplainer` over the four fused sub-scores. Explains the model's raw linear margin (pre-sigmoid decision function), not the 0–1 probability `combine()` returns — direction (raised/lowered trust) is always correct since sigmoid is monotonic, but magnitude is in log-odds units, stated explicitly in the reason text and the audit log because this feeds a governance record where unit precision matters. `LinearExplainer` is exact and closed-form (no sampling), which is what keeps it affordable to run on every gateway message.
- **Level 2** — `explainability.level2_explain()`, orchestrated from `gateway.py` (not inside `fusion_engine.py`, so fusion's own job stays "fuse scores" rather than also "explain scores"). Given which of the four signals Level 1 named as dominant, drills into which raw feature or node *within* that signal actually drove it.

### 5.5 Policy (Module 5)

- **Static 2×2 table** (`policy_engine.decide()`, §2) — the default and, per the project's own measurement, currently the *stronger* policy (see §7 below).
- **Adaptive PDP** (`adaptive_pdp.py`) — a **contextual bandit**, explicitly not reinforcement learning or Q-learning (no discount, no bootstrapping across states). State = `(security_trust_bucket, process_trust_bucket)`; action space = `{ALLOW, STEP_UP, ALERT, BLOCK}`, matching `decide()`'s 2×2 outputs. `choose_action()` at runtime is pure epsilon-greedy **selection**, never `update()` — an online-learning PDP is treated as an attack surface (anyone who can generate traffic could otherwise move the model), so training happens exclusively offline in `scripts/train_adaptive_pdp.py`. Toggled via `config.USE_RL_POLICY`.

## 6. Training order (six stages — not optional, not five)

```
1. Isolation Forest  →  2. LSTM-AE  →  3. Relational scorer (M6/GCN)  →
4. Fusion meta-learner  →  5. Adaptive PDP  (offline only)
```

Each stage replays through the previous models' outputs; retrain all in order after any change to features, the simulator, or the merged dataset. This list previously omitted a Transformer-ablation stage that had been silently trained a day stale through ~6 full retrains of everything downstream — every number published about it was measured against superseded data (its accuracy read 0.694 where a current build reads 0.754, and an apparent 0.970 recall on `stealthy_forged_values` evaporated to 0.606 once retrained). `test_no_model_artifact_is_older_than_its_training_data` now fails on any stale artifact.

## 7. Evaluation protocol and statistical discipline

- **Session-level, leakage-free splitting** (2026-09-03/04 re-measurement). Real-hardware resting false-positive rate under the pre-split (leaky) protocol read 0/49 and 1/29; under a genuinely session-level split it is **5/12 (41.7%, Wilson 95% CI 19.3–68.0%)**. The leaky numbers are withdrawn as validation evidence and cited only for the *direction* of a since-superseded fix.
- **Held-out replay qualification.** Any comparative claim (GCN vs. M6, static vs. adaptive policy) is qualified "held-out-replay-qualified" only when measured on `test_session.json` under a matched, hash-pinned artifact pairing (`src/relational_pin.py`'s `RelationalPin`), never on validation-selected numbers.
- **Explicit artifact pinning (`src/relational_pin.py`).** A confirmed comparator bug (`evaluate_ablation_m6.py`/`evaluate_real_hardware.py`/`evaluate_policy_comparison.py`/`evaluate_explainability_level2.py` constructing a bare `FusionEngine()` that silently read whichever fusion artifact was *currently* ambient in `config.py`) meant every "GCN arm" measured after the M6 deployment secretly paired true GCN relational scores with M6-calibrated fusion coefficients. Fixed by three explicit, SHA-256-hash-verified `RelationalPin`s (`gcn`, `m6_deployed`, `m6_corrected`) that fail loudly (`ArtifactMismatchError`) rather than silently mixing model families. Any future evaluator must load models through a `RelationalPin`, never through ambient `config.*_MODEL_PATH` reads, when comparator correctness matters.
- **Deterministic offline replay.** `GNNScorer`/`SetTransformerScorer`'s active-neighbour window and `RuleBasedTrustEngine`'s Security Trust EWMA decay both accept an injectable `clock` (default `None` → `time.time()`, so live-gateway semantics are provably unchanged); offline replay passes each record's own `ts`, closing a non-determinism bug that had corrupted the deployed policy Q-table's own training run.
- **Ten-seed studies quantify optimizer/initialisation variability on one fixed dataset**, not population-level generalisation — reported as such (`results/crossdevice_benchmark/seed_study.json`, `m9_seed_study.json`), never presented as a confidence interval over new data.
- **The statistical unit is not "one row = one independent sample."** Reported per-row metrics are `(tick, node)` windows nested inside a small number of anomaly events and scenario streams with temporal overlap — descriptive of a fixed test corpus, not evidence for population-level error rates, per `results/final_verification/research_review.md`.
- **Provenance is reported, never averaged away.** `operator_mark` vs. `transcript_reconstruction` labels are different evidence grades and are kept in separate rows; reconstructed labels are measurably tail-contaminated.
- **Calibrate the simulator against measured reality, not a guess.** `REST_DC_CENTRE` is the measured median of real operator-marked at-rest samples; the simulator supplies ≈97% of training volume, so its constants define what "normal" means to every downstream model.

## 8. Security posture and audit trail (Modules 2, 6, 7)

- HMAC-signed, canonically-JSON-encoded telemetry; boot-id + monotonic sequence number is the **primary** anti-replay mechanism (does not depend on wall-clock time); wall-clock timestamp freshness is a secondary check, requiring NTP-synced firmware.
- `check_boot_replay` was found to mutate boot state *before* the freshness gate — a rejected stale message could lock out the real board. Fixed to a pure predicate, with `commit_boot_seq()` called only after every gate passes; guarded by `TestBootReplayStateIsolation`.
- Transport: MQTT/TLS for device telemetry; a second transport historically named `coap_server.py` implements HTTPS POST on the Python standard library (`http.server` + `ssl`), **not** CoAP/DTLS — `aiocoap`'s CoAP-over-TLS transport was tried and rejected after a reproducible defect (reports "ready," refuses every real connection, verified on native Windows and WSL/Linux, two `aiocoap` versions).
- Audit log: SQLite with a `prev_hash`/`this_hash` chain plus a **separately keyed, separate-file** checkpoint store — the chain alone only detects an attacker who edits one row without recomputing every hash after it; the checkpoint store catches the more sophisticated case (recomputed chain, but inconsistent with a previously stored checkpoint).
- Governance mapping: NIST SP 800-207 tenets 1–7 (`nist_mapping.py`, coverage/tagging) and IEC 62443 zones/conduits + Foundational Requirements FR1–FR7 (`iec62443_mapping.py`, coverage). A **separate validation layer** (`governance_validation.py`) checks whether a tagged claim actually holds against audit-log evidence, not just whether it was tagged — every check is written to be falsifiable and states its own falsifier; a check that cannot fail is reported `UNFALSIFIABLE`, not dressed up as a pass.

## 9. Novelty claims (see `RESULTS.md` and `results/final_verification/research_review.md` for evidence)

1. Anomaly-rank vs. instrument-rank framing in perturbation-based explainability.
2. A falsifiable (not tautological) NIST SP 800-207 compliance-validation methodology.
3. Quantified hardware-in-the-loop training contribution (3% of training rows, materially changes false-positive behaviour).
4. Sim-to-real calibration validated against cross-session sensor spread, not a single session's median.
5. Detection demonstrated below the amplitude threshold used for the headline detection-rate number.
6. A leakage-free re-measurement that withdrew the project's own previously-reported headline numbers.
7. Live adversarial testing that found and fixed a real state-mutation vulnerability (`check_boot_replay`, §8).
8. The two-score separation demonstrated end-to-end on real hardware, not only in simulation.

## 10. What this methodology explicitly does not claim

- No claim that the relational scorer (GCN or M6) beats simpler cross-device models *because* of graph/attention structure — the defensible claim is that cross-device information helps; see `RESULTS.md` §Task-1.
- No claim that the adaptive bandit beats a validation-tuned static policy on this state space — it does not, on the measurements taken so far.
- No claim of detecting `stealthy_forged_values`/`combined`-class attacks from single-node telemetry — architecturally excluded from policy training as unlearnable from a `(security_trust, process_trust)` state space.
- No certification to NIST or IEC standards — `nist_mapping.py`/`iec62443_mapping.py` are an implementation mapping and a falsifiable self-check, not third-party certification.
- No claim of SL beyond SL-2 — no physical network segmentation exists (FR5/FR7 partial, not implemented).
