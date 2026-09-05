# Zero-Trust CPS — System Architecture & Knowledge Base

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

> Single source of truth for humans and coding agents. Every number in this
> document was measured on this repository, not estimated. Where a result is
> weak or a target is missed, it is stated as such.

---

## 1. Vision & Purpose

### The Problem

Industrial Cyber-Physical Systems (CPS) authenticate a device **once**, at
connection time, and then implicitly trust every message it sends for the rest
of the session. That model has two failure modes it structurally cannot see:

1. **A valid identity behaving badly.** A device holding genuine credentials
   that has been physically compromised, or is failing, keeps its access.
2. **A trust score that can itself be attacked.** In naive designs, anyone who
   merely *claims* a device's ID can drag that device's trust score down by
   sending garbage — a trust-poisoning denial of service requiring no secret.

Conventional IT zero-trust tooling does not transfer directly, because a CPS
device emits **physical** evidence (vibration, temperature, valve position)
alongside its **cyber** evidence (signatures, message rates). Collapsing both
into a single "trust number" destroys the distinction between *"this device is
lying about who it is"* and *"this machine is genuinely shaking."* Those demand
different responses.

### Why Now

IEC 62443 and NIST SP 800-207 are now procurement requirements in industrial
settings, but both are prose frameworks. Neither ships a reference
implementation that produces *auditable evidence* of compliance per decision.
This project treats governance as a measurable output, not a design document.

### Target Audience / Consumer

| Consumer | Interaction |
|---|---|
| A real ESP32 + MPU6050 board | Publishes signed vibration telemetry over MQTT/TLS |
| Two simulated devices | `sensor-002` (humidity), `actuator-001` (valve position) |
| Security analyst / operator | Live dashboard on `:8600`, hash-chained SQLite audit log |
| Auditor | NIST/IEC coverage reports generated from real logged decisions |
| Researcher | `scripts/evaluate_*.py` reproduce every published figure |

---

## 2. Core Concept & Mental Model

### Central Metaphor

**A border checkpoint with two independent inspectors who are never allowed to
average their opinions.**

- **Inspector A (Security Trust)** checks *papers*: signature validity, message
  rate, replay counters, response to a challenge. Cyber evidence only.
- **Inspector B (Process Anomaly)** checks *cargo*: is the physical sensor
  reading consistent with a healthy machine? Physical evidence only.

They report separately. A supervisor (the Policy Decision Point) reads **both
numbers** and looks up one cell in a 2×2 table. The scores meet at that lookup
and nowhere else. Averaging them into "trust = 0.7" would make a device with
perfect papers and violently abnormal cargo indistinguishable from one with
forged papers and perfectly normal cargo — two situations demanding opposite
responses.

### Design Philosophy

1. **Two scores, never blended.** Enforced structurally: `score_security_trust()`
   and the Process Anomaly fusion pipeline share no state and no inputs.
2. **Rejected traffic never touches the victim's state.** A failed
   authentication attempt updates an `IdentityTargetingRisk` counter for the
   *claimed* ID, never that device's own trust. This closes the trust-poisoning
   hole described above.
3. **Training is strictly offline.** The gateway only ever runs inference. No
   `.fit()` call exists on the live path. This is a hard constraint
   (`CLAUDE.md` §8), not a preference — an online-learning PDP is an attack
   surface, because an attacker who can generate traffic can move the model.
4. **Honest measurement over flattering numbers.** Where the system fails
   (`stealthy_forged_values` detection, Level-2 single-channel explainability at 37% against a
   70% target), the failure is reported and kept in the figures.
5. **Evidence, not assertion.** Every decision emits an audit row tagged with
   the NIST tenets and IEC FRs it is evidence for.

---

## 3. Architecture Overview

### System Topology

```
  ESP32 + MPU6050                  Simulated devices
  (firmware/main.py)               (src/device_simulator.py)
  100Hz x 32-sample window         sensor-002, actuator-001
  5 features computed ON-DEVICE    scalar readings
        |                                  |
        |  HMAC-SHA256 over canonical JSON, boot_id + seq
        +----------------+-----------------+
                         |
                 MQTT/TLS :8883  (per-device credentials + topic ACLs)
                 HTTPS    :5684  (second transport, coap_server.py)
                         |
        =================v==================================
        |            THE GATEWAY (src/gateway.py)          |
        |                                                  |
        |  M1 identity  -> DEVICE_REGISTRY lookup          |
        |  M1 revocation-> is_revoked()   [hard override]  |
        |  M2 throttle  -> IdentityTargetingRisk           |
        |  M2 HMAC      -> verify_signature()              |
        |  M2 replay    -> check_boot_replay(boot_id, seq) |
        |  M2 freshness -> check_timestamp_freshness(ts)   |
        |     ---- any failure above => _reject() ----     |
        |          (claimed device's own state UNTOUCHED)  |
        |                                                  |
        |  +-- SECURITY TRUST ------+  +-- PROCESS ANOMALY-+
        |  | flood / rate           |  | rule range check  |
        |  | step-up outcome        |  | Isolation Forest  |
        |  | silence                |  | LSTM-Autoencoder  |
        |  |                        |  | GNN (relational)  |
        |  |                        |  |   -> FusionEngine |
        |  +-----------+------------+  +---------+---------+
        |              |                         |
        |              +----> POLICY (2x2) <-----+
        |                 static | RL bandit          |
        |                        |                    |
        |     ALLOW / ALERT / STEP_UP / BLOCK         |
        =====================|============================
                             |
      +----------------------+-----------------------+
      |                      |                       |
  signed decision      hash-chained audit      live dashboard
  back to device       log (SQLite) +          :8600 + /figures
  (mutual auth)        separate checkpoints
```

### Execution Loop

`_process_telemetry()` in `src/gateway.py`, serialized under `_pipeline_lock`:

1. **Parse envelope.** Malformed → drop silently.
2. **Identity.** Unknown `device_id` → `_reject("unknown_device_id")`.
3. **Revocation.** Revoked → reject *before* HMAC (hard override).
4. **Throttle.** `IdentityTargetingRisk.is_throttled()` → drop.
5. **HMAC.** Current key first, then `secret_previous` inside the rotation
   grace window only.
6. **Replay.** `check_boot_replay(boot_id, seq)`.
7. **Freshness.** Secondary timestamp window.
   *Steps 2–7 failing means the message never reaches any scorer.*
8. **Security Trust** ← flood check + step-up resolution.
9. **Process Anomaly** ← rule + IF + LSTM-AE + GNN → `FusionEngine.combine()`.
10. **Explainability.** Level 1 (which signal, via SHAP), Level 2 (which raw
    feature or neighbour within that signal).
11. **Policy.** 2×2 lookup on `(security, process)`. A failed step-up forces
    `BLOCK` regardless.
12. **Emit.** Signed decision to the device, audit row, console line.

### Base Engine Rationale

| Engine | Why | Rejected alternative |
|---|---|---|
| Hand-rolled GCN (PyTorch matmul) | 3-node graph; identical math to a library layer | `torch-geometric` — version-locked compiled extensions, a common broken-install source, for zero benefit at this scale |
| Isolation Forest | Unsupervised, fast, needs only normal data | One-Class SVM — poorer scaling, more hyperparameter-sensitive |
| LSTM-AE | Captures *temporal* shape a point detector cannot | Transformer — fairly evaluated, lost the fair comparison (F1 0.882 vs 0.863); kept as an ablation, deliberately **not** wired in |
| Logistic-regression stacker | Interpretable coefficients, SHAP-friendly | Gradient boosting — opaque, overkill for 4 inputs |
| Tabular Q-learning bandit | 100 discrete states; exactly inspectable | Deep RL — unauditable for a security control |

---

## 4. Components & Module Boundaries

### `gateway.py` — Policy Decision & Enforcement Point
- **Ownership:** The entire live request path; the only process that talks to
  every other module. Also serves the dashboard and `/api/*`.
- **Inputs:** Telemetry envelopes from MQTT and HTTPS transports.
- **Outputs:** Signed decisions, audit rows, console lines, JSON APIs.
- **NOT:** Never trains. Never blends the two scores. Never mutates a claimed
  device's trust state on a rejected message.

### `trust_engine.py` — Security Trust + state store
- **Ownership:** Cyber-behaviour evidence: flood detection, step-up
  challenge/response, silence/staleness, boot/seq replay, key rotation,
  revocation, `IdentityTargetingRisk`.
- **Inputs:** `device_id`, flood flag, step-up result.
- **Outputs:** `(security_trust_score, reason)`; per-device state.
- **NOT:** Never looks at a sensor value. Contains no ML.

### `isolation_forest_scorer.py` / `lstm_ae_scorer.py` / `gnn_scorer.py`
- **Ownership:** One Process Anomaly sub-signal each. Inference only.
- **Inputs:** Feature vector (IF, LSTM-AE) or `(rule, if, lstm)` node features
  across the device graph (GNN).
- **Outputs:** A score in `[0,1]` where **1 = normal**, plus a Level-2
  explanation.
- **NOT:** Never call `.fit()`. Never see cyber evidence. Scalar devices
  (`sensor-002`, `actuator-001`) have no IF/LSTM model — their slots mirror
  `rule_score`, documented, not silently faked.

### `fusion_engine.py` — stacking meta-learner
- **Ownership:** Combines the 4 sub-signals; computes SHAP (Level 1).
- **NOT:** Does not compute Level-2 explanations — it lacks the scorer
  instances needed to drill in. That lives in `explainability.py`.

### `policy_engine.py` / `adaptive_pdp.py` — Access Control
- **Ownership:** The *only* place the two scores meet. Static 2×2 table, or an
  offline-trained Q-table bandit over the same 2-D state.
- **Outputs:** `ALLOW | ALERT | STEP_UP | BLOCK`.
- **NOT:** Never updates Q-values live (`update()` is training-only; the
  gateway calls `greedy_action()`).

### `governance_validation.py` — Governance validation
- **Ownership:** Independently checking that each NIST tenet's *claim* holds,
  as distinct from whether it was *tagged*.
- **Inputs:** A list of audit-log rows (nothing else).
- **Outputs:** Per-tenet `{status, claim, method, falsifier, evidence, checked,
  violations}`; `PASS | FAIL | UNFALSIFIABLE | INSUFFICIENT_DATA`.
- **NOT:** Never reads live in-memory state — an assertion that depends on
  trusting the running process is not independent of it. Never emits `PASS`
  for a claim it could not test: it returns `UNFALSIFIABLE` instead.

### `audit_log.py` — Monitoring
- **Ownership:** Hash-chained SQLite rows + a separately-keyed, separately-
  stored checkpoint file.
- **NOT:** Never deletes or rewrites a row.

### `firmware/main.py` — the physical device
- **Ownership:** Sampling, on-device feature extraction, HMAC signing,
  `boot_id` persistence, decision verification, step-up echo.
- **NOT:** No scoring, no policy. It emits evidence and obeys decisions.

---

## 5. Data, Memory & State Management

### Persistence Layer

| Store | Path | Purpose | Committed? |
|---|---|---|---|
| Audit log | `src/data/audit_log.db` | Hash-chained decision history | No (runtime) |
| Checkpoints | `data/checkpoint_log.jsonl` | Independent tamper detection | No (key-derived) |
| Audit key | `data/audit_key.bin` | HMAC key for checkpoints | **Never** |
| Sessions | `data/collected/*.json` | Training/test/hardware captures | Yes |
| Models | `models/*` | Trained artifacts | Yes |
| Device secrets | `src/secrets_local.py` | HMAC + MQTT credentials | **Never** |

> The checkpoint store is deliberately in a *different directory* from the
> audit DB and keyed with a *different* secret. An attacker who rewrites the
> in-DB chain consistently still fails the checkpoint cross-check.

### Data Schemas

Telemetry envelope (device → gateway):

```json
{
  "payload": {
    "device_id": "esp32-vib-001", "ts": 1788291422000,
    "boot_id": 18, "seq": 1182,
    "rms": 1.0244, "peak": 0.0164, "crest_factor": 0.016,
    "kurtosis": -0.7026, "dominant_freq": 9.375,
    "step_up_nonce_echo": "<optional>"
  },
  "signature": "<hex HMAC-SHA256 over json.dumps(payload, sort_keys=True)>"
}
```

Decision envelope (gateway → device), same signing scheme:

```json
{
  "payload": {"device_id":"sensor-002","decision":"ALLOW","ts":1788291521898,
              "gateway_boot_id":10,"decision_seq":1071},
  "signature": "<hex HMAC-SHA256>"
}
```

**Canonicalisation is the most fragile integration point in the system.** The
firmware must reproduce Python's `json.dumps(payload, sort_keys=True)`
byte-for-byte or every message is rejected. It builds the string manually
(`canonical_json()` + `format_py_float()`) rather than trusting MicroPython's
JSON encoder to match CPython's float formatting.

### State Lifecycle

- **Security/Process state:** in-memory per device, recomputed on every
  authenticated message (Module 4 continuous verification). Frozen — *not*
  decayed toward normal — when a device goes silent, so silence never looks
  like recovery.
- **`boot_id`:** persisted on device flash, one write per boot. `seq` is RAM
  only; a higher `boot_id` makes every prior `seq` stale.
- **Audit rows:** append-only, hash-chained, checkpointed every 100 rows.
- **Eviction:** none by design. Rotation produces `*.archived-*` files.

---

## 6. External Tooling & Integrations

| Dependency | Interface | Note |
|---|---|---|
| Mosquitto broker | MQTT/TLS :8883 | Per-device credentials + `certs/mosquitto_acl` topic ACLs |
| `paho-mqtt` | Gateway/simulator client | — |
| PyTorch | LSTM-AE, GNN, Transformer | Auto-detects CUDA, falls back to CPU |
| scikit-learn | Isolation Forest, stacker | — |
| SHAP | Level-1 explainability | — |
| MicroPython | ESP32 runtime | `umqtt.simple`, `ntptime`, `math`, `uhashlib` |

### Extensibility — registering a new device

1. Add an entry to `DEVICE_REGISTRY` in `src/config.py` with `kind`
   (`scalar` or `feature_vector`), expected ranges, and MQTT username.
2. Add its HMAC secret and MQTT password to `src/secrets_local.py`.
3. Regenerate `certs/mosquitto_passwd` and add ACL lines for the new user.
4. If `feature_vector`: retrain per-device models in this exact order —
   `train_isolation_forest` → `train_lstm_ae` → `train_gnn` →
   `train_fusion_meta_learner` → `train_adaptive_pdp`. Each later script
   replays through the earlier models, so order is not optional.
5. Add to `REAL_HARDWARE_DEVICE_IDS` if a physical board owns that identity,
   so the simulator stops racing it on `boot_id`/`seq`.

---

## 7. Tech Stack & Infrastructure Rationale

| Layer | Technology | Rationale & Why Chosen | Alternative Rejected |
|---|---|---|---|
| Device runtime | MicroPython on ESP32 | Rapid iteration on real hardware; `uhashlib` gives native SHA-256 | C/ESP-IDF — far slower iteration for a research prototype |
| Device auth | HMAC-SHA256 over canonical JSON | Symmetric, cheap on an MCU, no per-device PKI to manage | Per-device TLS client certs — heavy for the MCU, complex provisioning |
| Transport | MQTT over TLS | Standard industrial pub/sub, broker-enforced ACLs | Raw TCP — no ACL layer, no topic model |
| 2nd transport | HTTPS (`coap_server.py`) | Satisfies "two secured transports" with a stdlib server | **CoAP/DTLS — genuinely substituted**; documented, not hidden |
| Anomaly detection | 4-signal fusion | Each signal catches what the others structurally cannot | Any single model — see the per-event-type table in §11 |
| Policy | 2×2 table + tabular Q-learning | Fully inspectable, auditable | Deep RL — unauditable for a security control |
| Audit | SQLite + hash chain + separate checkpoints | Zero-ops, tamper-evident against two distinct attacker models | Plain log file — trivially rewritable |
| Dashboard | stdlib `http.server` | No framework dependency for ~10 endpoints | Flask/FastAPI — unnecessary weight |

---

## 8. Coding Conventions & Project Structure

```
zt-cps-starter/
├── src/                     # everything the LIVE gateway path imports
│   ├── gateway.py           # PDP/PEP + dashboard + /api  (the one process to run)
│   ├── config.py            # ALL tunables, registry, paths, thresholds
│   ├── trust_engine.py      # Security Trust + auth state machine
│   ├── policy_engine.py     # static 2x2 table
│   ├── adaptive_pdp.py      # RL bandit (inference live, training offline)
│   ├── *_scorer.py          # Process Anomaly sub-signals (INFERENCE ONLY)
│   ├── fusion_engine.py     # stacking meta-learner + SHAP
│   ├── explainability.py    # Level-2 orchestration
│   ├── audit_log.py         # hash-chained log + checkpoints
│   ├── nist_mapping.py      # NIST SP 800-207 tenet tagging
│   ├── iec62443_mapping.py  # IEC 62443 FR/zone/conduit model
│   ├── feature_engineering.py  # REFERENCE implementation of the 5 features
│   ├── device_simulator.py  # simulated devices
│   ├── coap_server.py       # HTTPS second transport
│   └── secrets_local.py     # gitignored; template in secrets_local.example.py
├── scripts/                 # OFFLINE only — never imported by the gateway
│   ├── train_*.py           # run in dependency order (see §6)
│   ├── evaluate_*.py        # every published number
│   └── generate_evaluation_graphs.py   # calls the SAME functions as evaluate_*
├── firmware/main.py         # MicroPython, real ESP32
├── models/                  # trained artifacts + calibration metadata
├── data/collected/          # training / test / real hardware sessions
├── docs/                    # 00–13 design docs + figures/
└── design/                  # live dashboard HTML
```

**Naming.** `*_scorer.py` = inference-only Process Anomaly signal.
`train_*.py` / `evaluate_*.py` = offline, never imported live. Config constants
are `UPPER_SNAKE` in `config.py` only — no magic numbers at call sites.
Device-facing IDs are kebab (`esp32-vib-001`); MQTT usernames match device IDs
so `pattern read cps/decisions/%u` scopes each device to itself.

**Error handling.** Fail *closed* on the auth path — any parse, identity, HMAC,
replay, or freshness failure rejects the message. Fail *neutral* on the ML
path — an untrained or unavailable scorer returns `0.9` ("no evidence, defer to
the others"), never a confident verdict.

**Logging.** One console line per decision; one audit row per decision with the
full score breakdown, SHAP values, both explainability levels, and the
NIST/IEC tags. Rejections log with `reason_category` and the identity-targeting
count.

---

## 9. Decision Log (ADRs)

> These are intended designs. Do not "fix" them without reading the rationale.

**ADR-1 — Two permanently separate scores.**
*Context:* A single blended trust number cannot distinguish "forged papers" from
"shaking machine."
*Chosen:* Two scores meeting only in a 2×2 lookup.
*Rejected:* Weighted average — destroys the distinction that drives the response.
*Evidence it holds:* measured — `high_rate` moves only Security (3.21 msgs to
break), `anomalous_shock`/`coordinated` move only Process (0.00/0.10). No leak.

**ADR-2 — Rejected messages never touch the claimed device's state.**
*Context:* A real trust-poisoning DoS: anyone could lower a device's score by
spamming its ID with garbage.
*Chosen:* `_reject()` updates only `IdentityTargetingRisk` for the claimed ID.
*Rejected:* Penalising the claimed device — that *is* the vulnerability.

**ADR-3 — All training offline.**
*Chosen:* `scripts/train_*.py` produce artifacts; the gateway only infers.
*Rejected:* Online learning — an attacker who can generate traffic could move
the model. Also makes runs non-reproducible.

**ADR-4 — Isolation Forest score calibration.**
*Context:* sklearn's `decision_function` is not a `[-0.5, 0.5]` score. With
`contamination=0.1` its inlier side is compressed into a narrow positive band
(measured: normal median `+0.079`, best case `+0.121`). The original mapping
`raw + 0.5` therefore capped a *perfectly normal* reading at **0.621** and put
the median normal at **0.579** — both under `PROCESS_THRESHOLD = 0.6`. The
signal could never say "normal," and dragged the fused score below threshold on
healthy telemetry, including the real ESP32 at rest.
*Chosen:* Two anchors taken from the **normal class only** (so training stays
unsupervised): `raw = 0 → 0.5` (sklearn's own inlier/outlier boundary) and
`raw = median(normal) → 0.9`. Linear, monotonic, clipped.
*Rejected:* Lowering `PROCESS_THRESHOLD` — hides the bug and shifts every other
signal's meaning.

**ADR-5 — Weighted GCN self-loop (`GNN_SELF_LOOP_WEIGHT = 3.0`).**
*Context:* With the textbook `A + I` and 3 active nodes, symmetric normalisation
gives a node's own evidence only 1/3 of its representation. One identical ESP32
reading scored fused **0.020 / 0.057 / 0.577** for 1 / 2 / 3 active devices —
the verdict depended on whether *unrelated* devices happened to be publishing.
*Chosen:* `A + 3I`, so self-weight is 0.6 vs 0.2 per neighbour.
*Rejected:* Dropping the GNN when isolated — within the deployed ensemble it is
the only signal that detects coordinated attacks (its cross-device view, not graph
structure specifically — C3), and abstention injects a strong implicit "normal" vote.

**ADR-6 — Isolated-topology training augmentation.**
*Context:* The only isolated-graph examples in training were merged real-hardware
rows, all labelled normal. The GCN learned "no neighbours ⇒ normal" and
saturated to **1.000** on a genuinely shaken board (`rms=2.5`, IF `0.00`,
LSTM `0.40`) — masking a real anomaly.
*Chosen:* Emit the isolated variant of every snapshot, covering that topology
with the same class balance. Labels are unchanged and remain correct per node.
*Rejected:* Special-casing at inference — trains one thing, deploys another.

**ADR-7 — Sample-average Q-values, not fixed-α EMA.**
*Context:* `α = 0.2` is an EMA with a ~5-visit memory. One state bucket holds a
*mixture* of ground-truth situations, so the stored value reflected visit order,
not the mean: every action in the high-trust states sat within 0.4 of every
other (state `9,8`: BLOCK `-0.3` vs ALLOW `-0.7`), making `argmax` effectively
random. The deployed policy answered **BLOCK** for a device at security `0.91`,
process `0.87` — where the static table correctly answers ALLOW.
*Chosen:* Incremental sample average (`α = 1/N`), the correct estimator for a
stationary contextual bandit.
*Rejected:* More episodes at fixed α — does not reduce EMA variance.

**ADR-8 — `combined`/`stealthy_forged_values` excluded from RL training.**
*Context:* This class is, by construction, drawn from the same feature
distribution as normal traffic (`docs/04` §B.8). Training a `(security,
process)`-keyed policy against it cannot teach detection — only to block the
region where normal traffic lives. Measured on state `9,8`: **3295 legitimate
messages vs 69 stealthy**, a 48:1 majority, which the 22.66× inverse-frequency
weight flipped to 1564 vs 948 of reward mass.
*Chosen:* Exclude it from what the policy *trains* on. Confusion matrices still
score it, because failing to detect it is a result worth reporting.
*Rejected:* Unweighted rewards — collapses to ALLOW even at process `0.05`.

**ADR-9 — Real trig in firmware.**
*Context:* A hand-rolled truncated-Taylor `_sin()` had **7.5e-2** max error over
`[0, 2π]`, selecting the wrong `dominant_freq` bin in **57/300** windows (19%),
off by up to 46.9 Hz — a silent train/serve skew present only on real telemetry.
*Chosen:* `math.sin`/`math.cos` (present in every standard ESP32 build).
Firmware now reproduces `feature_engineering.dominant_frequency()` exactly
(**0/300** mismatches).
*Rejected:* Keeping the approximation — it saved nothing measurable.
*Follow-up (a regression this caused):* the same change removed a hardcoded
`machine.RTC().datetime(...)` line, which broke the next flash — every message
was rejected as `stale_timestamp`, the board measuring **+19,784s ≈ 5h30m**
ahead. This deployment has no NTP route, so the RTC holds whatever last set it,
and Thonny syncs **local** time (`local_rtc: True`) while the firmware assumes
UTC. Repaired with `RTC_LOCAL_UTC_OFFSET_SECONDS`, applied only when
`sync_time()` reports NTP failed — an offset does not rot the way a pinned date
does, and a working NTP route bypasses it automatically. **Do not "simplify"
this back to a fixed timestamp.**

**ADR-10 — HTTPS substituted for CoAP/DTLS.**
*Chosen:* A stdlib HTTPS server as the second secured transport.
*Rejected:* A real CoAP/DTLS stack — documented openly as a substitution rather
than claimed as CoAP.

**ADR-11 — Threading + caching on the dashboard server.**
*Context:* The dashboard polls seven `/api/*` endpoints every 2s. On a
single-threaded `HTTPServer`, one full refresh cost **~1.99s of serial time**
once the audit log reached ~14k rows (`/api/chain` re-verifies the whole hash
chain: 0.66s, O(rows), and rows only grow). At ~100% saturation refreshes
overlapped, queued, and endpoints returned **empty** responses — the page froze
on its last good render, which presented as "the dashboard shows static values".
*Chosen:* `ThreadingHTTPServer` (safe: `audit_log` opens a fresh sqlite
connection per call and guards writes with its own lock), a 10s TTL cache on
chain verification, a 5s TTL on the NIST/IEC tallies, and tiered client polling.
Refresh cycle 1990 ms → ~690 ms; `/api/chain` 0.66 s → 0.004 s.
*Rejected:* Trimming `/api/decisions`' payload — the detail is the point of the
page, and it was not the bottleneck.
*Do not revert to a plain `HTTPServer`* to "avoid concurrency": the concurrency
is already safe, and serial handling is what broke the page.

**ADR-12 — The LSTM-AE Level-2 counterfactual stays single-channel and
flat-mean (a better-looking alternative was measured and reverted).**
*Context:* The LSTM-AE Level-2 flip rate is 0/122. The obvious hypothesis is
that substituting a channel's flat training mean hands the autoencoder an
out-of-distribution input (a perfectly constant channel never occurs in
training), so splicing a real normal *trajectory* should recover better.
*Chosen:* It was implemented — `train_lstm_ae.py` saving reference windows, the
scorer splicing them — measured, and **reverted**: 33.63 vs 33.70 median
counterfactual error, better in only 9/40 windows. No material gain for real
added complexity.
*Rejected:* Keeping it anyway because it is more "methodologically correct" —
it changed nothing measurable, and unused complexity misleads the next reader.
*What the experiment established:* the ceiling is the **single-channel
restriction**, not the fill value. A shock moves `rms`, `peak`, `crest_factor`
and `kurtosis` together; the best single-channel repair reaches ~33.7 against
the ≤4.28 needed. Re-deriving this is wasted effort — the diagnosis is printed
by `evaluate_explainability_level2.py` itself.

**ADR-13 — Governance coverage and governance validation are reported
separately, and coverage is labelled tautological where it is.**
*Context:* `tenets_for_decision()` tags tenets 1/3/4/5/6 on every decision
unconditionally. Reporting the resulting "100% coverage" as evidence of
compliance overstates it: the number is 100% because the tagger always writes
it, and no arrangement of the system could change that.
*Chosen:* Keep coverage (it is the metric the synopsis names), but add
`governance_validation.py` alongside it — falsifiable per-tenet checks over the
audit log only — and state plainly in every surface (script output, dashboard
panel, `RESULTS.md` §5.3) that coverage measures tagging while validation
measures compliance. A falsifiability self-test injects each check's own
falsifier and requires it to FAIL, so no check can be silently vacuous.
*Rejected:* Making the tagger conditional so coverage drops below 100% and
"looks earned" — that would corrupt the synopsis's own defined metric to flatter
a different one, and still would not prove the claims hold.
*Do not "simplify" this into one number.* The two answer different questions,
and a reader who only sees the merged figure cannot tell which they are getting.

**ADR-14 — Policy decisions enforce via revocation, and ship disabled.**
*Context:* `BLOCK` was advisory. Measured: 1,112 BLOCK decisions logged, and
after the last one the same device sent 6,264 more messages, all accepted and
scored. `docs/06` promised "Block / quarantine"; nothing quarantined.
*Chosen:* Escalate a run of `AUTO_QUARANTINE_CONSECUTIVE_BLOCKS` (default 20)
**consecutive** BLOCKs into `trust_engine.revoke_device()` — the enforcement
primitive that already exists and is already checked before HMAC. Any non-BLOCK
decision resets the run. Recovery is manual only. Applied after the triggering
decision is published and logged, so the device receives the BLOCK that
quarantined it and the audit trail always explains the revocation.
*Default OFF, on evidence:* during the Isolation Forest defect the physically
healthy ESP32 produced 953 BLOCKs — 108 runs of ≥3, 20 runs of ≥10, one run of
50. Auto-quarantine at any threshold up to 50 would have revoked live hardware
because of a scoring bug, and `is_revoked()` is a hard override. Establish the
false-positive rate first, then arm enforcement.
*Rejected:* device-side enforcement. A compromised device ignores the
instruction, so it provides no guarantee, and silencing a suspicious device
destroys the evidence trail. Enforcement must not depend on the adversary.

**ADR-15 — Chain verification is three checks at two periods, and the full scan
is never dropped.**
*Context:* `/api/chain` re-verified the whole hash chain per poll, O(rows) and
growing — the saturation behind ADR-11.
*Chosen:* An incremental tail check every poll, plus the full scan and the
checkpoint check on a longer period, with the full scan's **age displayed**.
*Rejected:* replacing the full scan with the incremental one. That was
implemented first and **proved unsound by testing it**: checkpoints attest a
chain-hash *value* (stored vs stored), so they miss a naive edit entirely, and a
tail check skips it by definition. Only the full scan recomputes an old row's
hash from its fields. The measured attack matrix is in §12.
*Do not "optimise" the full scan away.* Its interval is the detection latency
for naive tampering, which is why the UI shows it.

**ADR-16 -- Acquisition rate, anti-alias filter and window are one decision.**
*Context:* `sample_window()` ran unpaced at ~1231 Hz while declaring 100 Hz, so
`dominant_freq` was scaled by a constant 12.3x wrong.
*Chosen:* 500 Hz deadline-paced sampling, MPU6050 DLPF at 184 Hz (66 Hz below
the 250 Hz Nyquist), 32-sample window.
*Rejected:* (a) 100 Hz with a 44 Hz filter -- only 6 Hz of margin, and 38% of
samples still landed in the top three bins from the filter's gradual rolloff;
(b) 100 Hz with a 21 Hz filter -- clean, but throws away most of the vibration
band; (c) keeping 100 Hz at all -- it was never a requirement, it came from a
comment describing a loop that did not exist.
*Confirmed on device, not just in the constants:* the firmware's own
`ticks_ms()` instrumentation reads sampling at an invariant **64 ms** (= 32/500 Hz)
at `boot_id = 33`, against 26-30 ms before the fix. The variance disappearing is
the evidence that matters -- the old spread was I2C jitter in a free-running loop,
and a deadline-paced loop is supposed to absorb exactly that. Feature extraction
97-101 ms, signing 9 ms, ~172 ms total, 8.6% duty cycle (`RESULTS.md` 13.1).
*The trap, recorded because it cost two regressions:* at ~1231 Hz Nyquist was
615 Hz, above the sensor's 260 Hz passband, so **there was no aliasing to see**.
Correcting the rate is what created it. Do not change one of these three without
the other two, and do not change any of them without retraining -- every
`dominant_freq` the models learned is scaled by the rate.

**ADR-17 -- The simulator models the real board's physics, not white noise.**
*Context:* The synthetic baseline was `random.gauss(1.0, 0.006)`. White noise
puts the dominant DFT bin roughly uniformly across the band; a real resting board
is low-frequency weighted and carries its state between windows. Measured
consequence: the Isolation Forest scored synthetic normals 0.900 and the real
resting board **0.000**, even with the real samples inside its own training set.
*Chosen:* low-frequency drift over a smaller white floor, drift frequency drawn
per window, resting DC drawn from a range, and the resting state
**mean-reverting** between windows so the sequence has the temporal continuity a
real board has.
*Rejected:* a free random walk for that state -- unanchored (the mean drifted and
clamped) and far too persistent (lag-1 0.89 against the real 0.26).
*Honest limitation:* the temporal fix did **not** resolve the residual false
positives. It is kept for fidelity -- the simulator now matches the real board on
a property it previously got wrong -- not because it fixed the symptom it aimed at.
*Do not revert to white noise for simplicity.* It is simpler and measurably wrong.


**ADR-18 -- The resting normal region is sized by cross-session spread, not by
one session's median.**
*Context:* the same board's resting rms median measured 1.041 g, 1.056 g and
1.011 g on three different occasions -- a 0.045 g spread against a within-session
std of 0.009 g. Accelerometer bias and resting orientation both move it.
*Chosen:* centre `REST_DC_CENTRE` on the midpoint of the observed range (1.036)
and widen the stationary spread to ~0.020 (`REST_DC_WALK` 0.019,
`REST_DC_MIN/MAX` 0.975/1.10), so all three observed states sit within ±1.3 sigma.
*Rejected:* centring on the latest measured median (1.053). It was implemented and
measured -- real-hardware false positives went 2/49 to 0/49 (pre-split figures,
now withdrawn as leaky per C4 — cited here only to show the *movement*) -- and then
the next live resting board read 1.011 g, i.e. **-4.0 sigma** under the model that
had just "improved". Tuning the centre optimises for the last session captured.
*Verified on the opposite case, because widening a normal region is exactly the
change that can destroy detection:* real-hardware detection stayed 94/94, the
same session's disturbed readings stayed pinned at `iso` 0.000, synthetic
`anomalous_shock` recall stayed 1.000 and `coordinated` 0.974, GNN accuracy rose
0.907 to 0.915.
*Do not re-tune `REST_DC_CENTRE` onto a single session's median.* A disturbed
board reconstructs at 7,000-62,000 sigma of baseline error, so the resting
tolerance has room; the centre does not.


---

## 10. Roadmap & Milestones

- **Current:** Real hardware in the loop; four-signal fusion; RL policy;
  governance reporting; hash-chained audit.
- **Upcoming:** A formal, structured physical adversarial session with
  human-labelled ground truth (two real faults have already been found by
  informal live manipulation). Firmware-side latency instrumentation via
  `time.ticks_ms()`. Raising Level-2 explainability toward its 70% target.
- **Explicitly out of scope — will never be supported:**
  - Online/continuous learning on the live gateway (ADR-3).
  - Blending the two scores into one number (ADR-1).
  - Detecting a perfectly-executed `stealthy_forged_values` attack from
    single-node telemetry — information-theoretically out of reach for this
    design, and reported rather than engineered around.
  - Hardware secure-element key storage; secrets are plaintext constants, an
    accepted prototype simplification (`CLAUDE.md` §8).

---

## 11. Evaluation, Testing & Verification

### Strategy

Verification is by **reproducible offline evaluation against a held-out test
set** (`generate_test_data.py`, different seed) plus **live hardware
observation**. `generate_evaluation_graphs.py` calls the *same functions* as the
`evaluate_*.py` scripts, so a figure and its script's printed numbers cannot
silently drift apart.

### Held-out results (2933 authenticated messages)

| Signal | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| rule_score | 0.921 | 0.921 | 1.000 | 0.959 |
| isolation_forest_score | 0.949 | 0.959 | 0.987 | 0.973 |
| lstm_ae_score | 0.776 | 0.953 | 0.796 | 0.867 |
| gnn_score | 0.915 | 0.987 | 0.920 | 0.952 |
| fused_score | 0.747 | 0.990 | 0.732 | 0.842 |

Per-event-type recall — **why four signals exist**:

| Signal | anomalous_shock | coordinated | stealthy |
|---|---|---|---|
| rule_score | 0.000 | 0.000 | 0.000 |
| isolation_forest | 1.000 | 0.316 | 0.000 |
| lstm_ae | 1.000 | 0.222 | 0.515 |
| **gnn** | 1.000 | **1.000** | 0.000 |
| fused | 1.000 | 0.974 | 0.515 |

Within the deployed ensemble the GNN is the only signal that detects `coordinated`
attacks — because it is the only one with a cross-device view. Isolation Forest
and LSTM-AE are *structurally* blind to them — they only ever see one device's
own vector. The benefit is the cross-device *information*, not graph structure
specifically: given the same multi-device input a concat MLP matches or beats the
GNN, so no GNN-necessity or -superiority claim follows (C3).

### Verification scenarios

1. **Healthy board must be ALLOWed.** Clean ESP32 normals (no anomaly within
   the 8-sample LSTM window): fused median **0.888**, false-positive rate at
   `PROCESS_THRESHOLD=0.6` of **0.0%** (n=84).
2. **Real physical disturbance must be caught.** Live board, shaken:
   **19/19 readings (rms>1.2) → ALERT, zero ALLOW**; at rest → ALLOW; with a
   short ALERT recovery tail while the LSTM window flushes.
3. **GNN must respond to neighbours alone.** Own evidence pinned at
   `(0.9, 0.9, 0.9)`, neighbours degraded `0.90 → 0.30`: GNN `0.647 → 0.316`.
   Level-2 correctly names whichever neighbour degraded.
4. **Two-score separation must not leak.** Verified — see ADR-1.
5. **Mutual authentication.** 10/10 gateway→device decisions verified HMAC-valid
   by recomputing with the device's own secret; **0** cross-device leakage.
6. **Least privilege is enforced, not just configured.** A client holding
   *gateway* credentials is refused a subscription to `cps/decisions/#`
   (write-only ACL) — observed live.
7. **Audit integrity.** Hash chain intact and checkpoint cross-check passing
   over 5516 rows.
8. **Firmware ≡ reference maths.** All five features match
   `feature_engineering.py` exactly across 300 windows in 3 signal regimes.

### Governance

Two distinct claims, deliberately not conflated:

- **Coverage** (`nist_mapping`) — **7/7 tenets at 100%** across every logged
  decision. This measures *tagging*, and tenets 1/3/4/5/6 are tagged
  unconditionally, so 100% there is true by construction, not a finding.
- **Validation** (`governance_validation`) — **7/7 PASS** over 10,000 audit
  rows. This measures whether the claim *holds*, reading only the hash-chained
  log and naming what would falsify each check. Sharpest evidence: ALLOW rate
  15% below the process threshold vs 91% above, and 0% vs 88% on the security
  axis (tested per axis, so each score is shown to move the outcome on its own);
  213 rejected rows, none of which reached an access decision; the learned
  fusion moved the score away from the rule-only baseline on 100% of rows.
- **Falsifiability self-test** — **6/6** checks reject their own falsifier when
  it is injected as synthetic rows. Tenet 5 is excluded rather than assumed
  (its falsifier is missing data, not a constructible row).
- **IEC 62443-3-3:** FR1–FR4, FR6 **implemented** (100% of 8524 logged
  decisions); FR5, FR7 honestly **partial** — real transport controls exist,
  physical segmentation and redundancy do not.
- **Security Level: SL-2**, argued with evidence both for and against.

### Performance

| Measurement | Value |
|---|---|
| HMAC verification | median **0.005 ms** |
| Full pipeline (auth + 4 scorers + fusion + policy) | median **26.85 ms**, p95 **36.09 ms** |
| Level-1 explainability | **200/200 (100%)** SHAP attributions physically sensible |

---

## 12. Known Limitations & Open Risks

> Each entry says whether it is **resolved**, an **accepted design limit**, or
> still **open**. An accepted limit is not a TODO — it is a boundary with a
> reason, and "fixing" it would trade away something that matters more.

### Resolved since first writing

**Dashboard chain verification is no longer O(all rows) per poll.** *(was: a
live outage — ADR-11.)* Verification now runs at three tiers, because the two
existing checks turn out to catch **different** attacks and neither subsumes
the other. Measured on a copy of a real 39k-row log:

| Attack | Full scan | Checkpoints | Incremental tail |
|---|---|---|---|
| Naive edit — row changed, hashes left alone | **DETECTED** | missed | missed |
| Consistent rewrite — every following hash recomputed | missed | **DETECTED** | missed |

The tail check is bounded by `CHECKPOINT_INTERVAL_ROWS` and runs every poll;
the full scan is the *only* thing that catches a naive edit, so it still runs —
just every `CHAIN_FULL_SCAN_TTL_SECONDS` (300 s) instead of every 10 s. **That
interval is therefore the detection latency for a naive edit**, and the
dashboard displays its age rather than implying continuous coverage. Cost: a
full `/api/chain` build went 925 ms → 32 ms warm.

An earlier version of this change was **unsound and was caught by testing it**:
it anchored the tail check at the newest checkpoint and claimed the checkpoints
attested everything before it. They do not — a checkpoint attests a chain-hash
*value*, comparing stored against stored, so it misses a naive edit entirely. The
claim was removed rather than the speed kept quietly.

**BLOCK can now actually enforce.** *(was: the decision was advisory — 1,112
BLOCKs logged, and the same device sent 6,264 more messages after the last one.)*
`config.AUTO_QUARANTINE_ENABLED` escalates a sustained run of BLOCKs into a real
revocation through `trust_engine.revoke_device()`, which is checked before HMAC.
**It ships disabled**, on evidence rather than caution: during the Isolation
Forest defect the physically healthy ESP32 produced 953 BLOCKs, including one
unbroken run of 50, and auto-quarantine at any threshold up to 50 would have
revoked live hardware because of a scoring bug. Establish your false-positive
rate first, then arm it. See ADR-14.

**There is an automated test suite.** *(was: verification was only
`evaluate_*.py` plus live observation.)* `tests/test_invariants.py`, 33 tests,
stdlib `unittest` so it needs no install:

```
python -m unittest discover -s tests -v
```

It deliberately does not chase coverage. **Every test corresponds to a property
that has already been broken once in this repository**, and its docstring names
the incident. It guards the two-score separation, policy monotonicity, the IF
calibration anchors, firmware↔reference feature equivalence, canonicalisation
drift, GNN adjacency, the RL sample-average estimator and its static fallback,
audit tamper detection (both attacks, against a temp copy — the real log is
never written), quarantine escalation, and the governance checks' falsifiability.

The suite found a real defect on its first run: `TestAuditIntegrity` reloads
`audit_log` against a temp database and was leaking those paths into later
tests. That is exactly the class of cross-test contamination that makes a suite
untrustworthy, and it was fixed rather than worked around.

**Firmware-side latency is instrumented.** *(was: recorded here as
"unmeasured".)* `firmware/main.py` prints `sampling` / `feature_extraction` /
`sign` per publish, using `time.ticks_diff()` — the wraparound-correct
comparison, where naive subtraction would be wrong. The numbers appear on the
board's serial console (Thonny's Shell) and have **not yet been transcribed into
`RESULTS.md`**; that is the remaining step, not the measurement.

### Accepted design limits — not defects

**`stealthy_forged_values` is not reliably detected** (recall 0.515). A
compromised device reporting deliberately innocuous, in-range values is drawn
from the same feature distribution as normal traffic. This is
information-theoretically out of reach for single-node telemetry, and the honest
consequence is documented rather than engineered around — including its exclusion
from RL training, where chasing it would only teach the policy to block the
region where normal traffic lives (ADR-8).

**Aggregate fused accuracy (0.747) is below the best single signal (0.949).**
Deliberate. The meta-learner is class-weighted so the rare `coordinated` class
survives — unweighted, fused recall on it was 0.261, *worse* than the GNN alone
at 0.870. Aggregate accuracy is the wrong single number for a security system
where missing a rare coordinated attack costs more than extra alerts.

**Level-2 explainability misses its 70% target at 37%** (100% GNN, 0% LSTM-AE).
The ceiling is measured, not assumed: a flagged window reconstructs with error
~46–62 and recovery needs ≤ 4.28, but an impulsive shock moves `rms`, `peak`,
`crest_factor` and `kurtosis` together, so the best single-channel repair reaches
only ~33.7. Splicing a real normal trajectory instead of a flat mean was
implemented, measured (33.63 vs 33.70), and **reverted** as complexity that
bought nothing — which is what locates the limit in the single-channel
restriction rather than the fill value. The attribution stays sound:
`kurtosis` is named in 110/122 cases. Closing this needs a
multi-channel counterfactual, a different validation design from the one the
method specifies.

**The device does not enforce its own BLOCK, and should not.** Enforcement that
depends on the adversary complying is not enforcement, and silencing a
suspicious device destroys the evidence you most want. See `docs/06` §2.0.2.

### Still open

**The pipeline cannot rank anomaly SEVERITY, and the score mapping is not the
reason.** `_error_to_score` pins to exactly 0.000 at z >= 3.6, which looks like
the cause -- but measured on real hardware, `sharp_impact` (max peak 2.968 g) has
the LOWEST median reconstruction-error z of the four disturbance classes (10392)
while `gentle_tap` sits at 18745. The obstacle is duty cycle: 29% of
`sharp_impact` samples are physically indistinguishable from rest (brief impulses
with pauses) against 0% for continuous shaking, and error is averaged over the
8-message window. **Window-averaged error measures how much of the window is
disturbed, not how violently.** A compressive score map was proposed and NOT
implemented, because it would produce a number that looks like severity and is
not -- and on this data there is nothing to grade regardless: rest sits at z ~ 0,
every real disturbance at z = 4,200-48,000, the middle empty. Ranking severity
needs a peak-aware statistic alongside the sequence model. See `RESULTS.md`
0.10.9.

**Real hardware is 3.0% of training and materially reduces false positives.**
Measured by withholding it and retraining the whole chain
(`merge_real_hardware_data.py --synthetic-only`): synthetic-only gave **13/49**
operator-marked false positives, adding the real at-rest rows gave **0/49**, with
detection unchanged. ⚠ **Both figures here are pre-split and the 0/49 baseline is
withdrawn** — this ablation was measured before session-level train/test splitting
was enforced (see the resting-FP entry below and `docs/CLAIM_EVIDENCE_MATRIX.md`
C4/C14). The *direction* — the real rows materially reduce false positives — is
unaffected and load-bearing, but the exact synthetic-only magnitude must be
re-measured under the corrected splits before "13/49 vs 0/49" is quoted again.
Synthetic data alone cannot place the normal region where the real board actually
sits, however well calibrated.
*Do not treat the real rows as a rounding error because they are 3% of the count.*

**A rejected message COULD mutate anti-replay state -- found by live adversarial
test, now fixed.** `check_boot_replay` advanced `last_seen_boot_id` as a side
effect and ran BEFORE the freshness gate, so a validly-signed stale message with an
inflated boot_id bumped the baseline and was then rejected -- a rejected message
mutating device state, and it locked the real board out as
`replay_of_superseded_boot_session`. Now `check_boot_replay` is a pure predicate
and `commit_boot_seq()` advances the baseline only after every gate passes, called
from gateway.py after the freshness check. Guarded by `TestBootReplayStateIsolation`.
The exploit needed the HMAC secret, but the same ordering fires on a real device
during clock skew, which this project has hit before. See `RESULTS.md` 0.10.17.

**Synthetic test-set attack density makes the blended accuracy misleading.**
95.0% of esp32-vib-001's "normal" test rows sit within `LSTM_SEQ_LEN` of an
injected attack, because attacks land every 12-30 ticks against an 8-message
window. Result: the real device shows **73.0%** false positives on all normals but
**0/40 (0.0%)** on genuinely clean ones -- every failure is window residue. The
simulated devices show no such effect (9.3% vs 11.3%) because they mirror
`rule_score` and have no window to contaminate. *The blended fused accuracy of
0.717 is a property of the injection schedule, not of the models*, and the
dedicated real-hardware evaluation on operator-marked resting windows is the
trustworthy one (now **5/12** under session-level splitting, superseding the
withdrawn 1/29 — see the resting-FP entry below). Keep injection density low
relative to the sequence window in any dataset extension. See `RESULTS.md` 0.10.15.

**Governance is 7/7 tenets and 7/7 falsifiers.** Tenet 5 was excluded from the
falsifiability count for a long time as "not injectable -- its falsifier is missing
data". Wrong: the check compares devices present in the rows against
`DEVICE_REGISTRY`, so a row set covering fewer devices falsifies it, which is an
ordinary row list. Corrected, and built from the live registry so it cannot drift.
See `RESULTS.md` 0.10.16.

**A stale model artifact is silent, and one cost every Transformer number
published for a day.** `models/transformer_ae_esp32-vib-001.pt` sat at the
previous day's build through ~6 full retrains because the documented training
order named five steps and the Transformer was the sixth. Measured on the stale
artifact it read accuracy **0.694** and **0.970** recall on
`stealthy_forged_values` -- against the deployed fusion's 0.606, which looked like
a free fix for this design's acknowledged blind spot and triggered a full
evaluation of folding it into fusion. Retrained on current data: accuracy 0.754,
stealthy recall **0.606**, statistically indistinguishable from the LSTM-AE
(correlation 0.998, 4/1050 flag disagreements). *A comparison is only valid if
every arm was trained on the same data*, and nothing enforced that until
`test_no_model_artifact_is_older_than_its_training_data` was written. Training
order is now **IF -> LSTM-AE -> Transformer -> GNN -> fusion -> RL**. See
`RESULTS.md` 2.2 and 0.10.13.

**The Isolation Forest is the weakest of the four signals, and that is now
measured rather than suspected.** It swings 0.000-1.000 across physically
near-identical resting samples (25-28 of 121 below 0.6) and produced the only
live resting dip (`proc` 0.474 with `lstm` healthy at 0.780). Three hypotheses
were tested: a single dominant feature (**wrong** -- all abs(rho) <= 0.19),
estimator variance (**wrong** -- IQR ~0.37 across `n_estimators` 100-1000 and
`max_samples` 256-4088), and `contamination=0.1` misplacing the threshold (real,
but lowering it trades resting dips for missed anomalies: 0.005 gives 8/121
resting dips but 15/192 missed disturbances against 8/192 today). It stays at
0.1. Fusion still absorbs most of the weakness (detection unaffected), but note
the resting false-positive rate is **5/12 on the untouched test session under
session-level splitting**, not the pre-split 0/49 quoted in the original entry
(withdrawn — see the resting-FP entry below) -- so this is margin plus a real,
reported residual FP cost, not a fully-clean signal. See `RESULTS.md` 0.10.8.

**Level-2 explainability: two metrics, both reported.** The single-channel flip
test (literature-comparable, [21]'s method) is **37%** and stays. What it measures
on this signal is channel correlation: repairing the best single channel drops
reconstruction error 26825 -> 7157 (3.7x) where ~9700x is needed, while repairing
the anomaly's **minimal sufficient set** (rank 3, `{peak, rms, crest_factor}`)
clears it in **178/182 (98%)** windows. The anomaly has **rank ~3 and a rank-1
instrument cannot undo it**; `gnn_score` passes the single-channel test at 100%
because its anomaly genuinely is single-source. The **rank-aware metric (98%) is
reported as a first-class result that meets the 70% target** -- legitimate, not
goalpost-moving, precisely because the same rank-aware test leaves single-source
anomalies at rank 1 (the GNN control proves it). *Do not report ONLY the higher
number and do not delete the 37% -- both are printed together, and making the
single-channel test itself pass is a model-architecture change (a rank-1 feature
representation), which is future work.*

**Resting-board false positives: 5/12 (41.7%) on the untouched TEST session under
session-level splitting, detection 30/30.** ⚠ **This supersedes and withdraws the
earlier 1/29 (3.4%) and 0/49 headlines**, which were measured while the test
session's own at-rest rows were in the training set (`docs/REPOSITORY_AUDIT.md`
§2.2). With TRAIN/VALIDATION/TEST split by session (`src/splits.py`,
`data/splits/session_split.json`), the honest figures are: TEST
(`20260902_221217`) detection **30/30**, 95% CI [88.6%, 100%], resting FP **5/12
(41.7%)**, 95% CI [19.3%, 68.0%]; VALIDATION (`20260902_173108`) detection 14/14,
FP 0/3. The 12-window denominator makes the interval very wide, and the jump from
0/49 is direct evidence the learned normal region may be session- or
mounting-specific — the mounting-robustness capture (`docs/REVIEW_RESPONSE_TRACKER.md`
D) is the highest-value outstanding experiment for it. Reducing this rate is
required future work, not a solved item. See `docs/CLAIM_EVIDENCE_MATRIX.md` C4,
`RESULTS.md` §0.12.1.

*(Historical, retained for the reasoning:* the pre-split correction from a warm-up
rule that dropped enough records to FILL the LSTM window but left the block's own
settling disturbance inside it — corrected to drop `2*LSTM_SEQ_LEN-1` — is what
moved the leaky figure from 10/83 to 1/29; both are now withdrawn as leaky. See
`RESULTS.md` 0.10.10.)*

The hypothesis this entry used to carry -- that short per-phase blocks deny the
autoencoder its steady run -- was **tested and refuted**. Control for input sigma
and block position explains nothing: 0/50 resting windows below 5 sigma failed at
every position, 10/11 at or above 5 sigma failed. The real mechanism is the hard
cliff in `_error_to_score` (`clip(0.9 - 0.25*max(z,0))` pins to exactly 0.000 at
z >= 3.6), which is why the signal is bimodal rather than continuous.

**The detection floor is measured below the amplitude THRESHOLD, not at equal
amplitude.** An unplanned periodic source (96% of `dominant_freq` in one 93.75 Hz
bin, against 15 scattered bins and a 21% top bin at rest) let this be tested:
windows built only from samples at or below the operator-marked resting ceiling
(p99 = 0.0411 g) separate **14/14 flagged against 0/14** -- perfect separation on
windows a per-sample amplitude threshold cannot separate at all. That is the first
evidence the sequence model earns its place. *The claim is bounded:* within the
below-ceiling band the live windows still carry ~2x the amplitude (0.0403 vs
0.0190 max-peak-in-window), so amplitude is capped, not held equal. See
`RESULTS.md` 0.10.14. The superseded statement follows.

**Previously recorded, now partly closed:** Every detected event -- including the
sustained phone-vibrate fault -- exceeds the resting band by a wide margin
(`fault_weak` peak median 0.2557 g against a resting p99 of 0.0411 g). Of 30
scored fault windows, **zero** have all 8 messages at or below the resting
ceiling, so detection is still carried by amplitude, not by sequence structure a
threshold would miss. Measuring the floor needs a continuous low-amplitude source
(small DC motor with an unbalanced mass), not a phone: phone vibrate couples
strongly through a desk and is intermittent rather than continuous.

**The `dominant_freq` axis is only as good as the acquisition chain.** Now
correct (500 Hz, DLPF 184 Hz, 66 Hz of anti-alias margin), but three successive
defects lived here and each was invisible until the previous was fixed. Rate,
filter and window size are ONE decision -- `firmware/main.py` records the full
sequence so the next reader does not repeat it.

**GNN response is not monotonic in neighbour health -- measured, and justified
rather than fixed.** 25 violations across a 51-point sweep, confined to the
saturated regions (0.00-0.20 and 0.70-1.00); the transition between them is sharp
and correct. It matters more than it looks because the GNN carries the largest
fusion coefficient (leakage-free set `[rule −0.003, iso +2.97, lstm +5.97, gnn
+8.33]`, concern H / C13) -- so the decision-level question
was asked directly: worst fused excursion **0.00295**, one decision change across
the sweep and it is in the correct direction, **zero** cases of a verdict getting
stricter as a neighbourhood improves. Ripple inside a saturated region, not a
defect. *Not being fixed:* the only available fix is fabricating neighbour
training data for input combinations the live system never produces, which is
risk for no decision-level benefit. `TestTwoScoreSeparation` now pins the property
that matters instead. See `RESULTS.md` 0.10.12.

**The GNN does not beat simpler models on identical multi-device information --
measured against fair baselines, and the superiority claim is withdrawn.**
`scripts/evaluate_gnn_baselines.py` runs five comparators on byte-identical inputs
(single-device, concatenated logistic regression, a small MLP, a coordinated rule,
and the GNN), fit on TRAIN, all selection on VALIDATION (self-loop weight swept
`{1,2,3,5}`), TEST read once. Task 1 (per-node anomaly, test F1): concat MLP
**0.9852**, single-device 0.9771, **GNN 0.8381**, concat logistic 0.7785, rule
0.6156. Task 2 (coordination pattern, test accuracy): concat MLP **0.6567**,
logistic 0.6433, **GNN 0.6058**, node-count 0.4142. The GNN loses *at its own best
swept setting*. **The defensible claim is about cross-device information**
(node-count 0.4142 → concat 0.6567), **not graph structure.** Bounded: one
topology, one graph size, one GCN architecture, one testbed, node 02 absent — this
shows the GNN did not help *here*, not that graph learning cannot help. The GNN
stays in the deployed fusion (it carries real weight there); what is withdrawn is
any claim that graph structure is architecturally necessary. See
`docs/CLAIM_EVIDENCE_MATRIX.md` C2/C3, `RESULTS.md` §0.13.3.

**A validation-tuned static policy beats the adaptive policy -- reported as a
negative result.** `scripts/evaluate_policy_comparison.py` scores five policies on
identical inputs on the untouched test split. Macro-F1: static-optimised
**0.5879**, decision tree 0.5834, **adaptive bandit 0.5329**, multiclass LR
0.4355, deployed static 0.2744. The adaptive policy clearly beats the *deployed*
static table but is beaten by the same table with thresholds selected on
validation. **Terminology corrected: it is a contextual bandit with sample-average
action-value estimation, not reinforcement learning** (no discount factor, no
next-state bootstrapping; `RL_*` config names retained only to avoid a ~20-site
rename). Caveat on the tuned static winner: its selected `θ_proc = 0.05` would make
the deployed system nearly blind to process anomalies — the selection objective is
not the deployment objective, so deployed thresholds stay 0.6/0.6. See
`docs/CLAIM_EVIDENCE_MATRIX.md` C6/C7, `RESULTS.md` §0.13.6.

**The transformer is NOT a fusion input, and that was re-tested rather than
inherited.** It recalls `stealthy_forged_values` at 0.970 against the deployed
fusion's 0.606, which looks like a free fix for the one attack class this design
admits it cannot see. Adding it as a 5th input was measured offline: synthetic
stealthy recall 0.636 -> 0.970 for +6.3 points of false positives, but on REAL
hardware resting FP went **5/29 -> 15/29** and detection **92/92 -> 87/92** (the
/29 denominator is the pre-split corpus, now superseded by session-level splitting
— the *direction*, adding the transformer worsens real FP, is what the decision
rests on). Rejected before shipping. The transfer failure is the signature of a model keying
on an artefact of how `stealthy_forged_values` is *generated* rather than a
property of stealthy attacks -- inference, not proof, since no real-hardware
stealthy data exists. *Read the ablation table's per-class recalls with that in
mind: a class measured only on generated attacks can reward recognising the
generator.* See `RESULTS.md` 0.10.13.

**Seed sensitivity is measured, not assumed.** `TRAINING_SEED` (env `ZTCPS_SEED`)
threads through all five models. Across seeds 0-4: `fused` 0.715 +/- 0.002, the
adaptive policy (**a contextual bandit, not RL** — no discount factor, no
next-state bootstrapping; C6/concern N) macro-F1 0.537 +/- 0.002 against the
*deployed* static table 0.278 +/- 0.001. ⚠ **The "beats static" claim is now
qualified and partly withdrawn:** on the leakage-free test split the bandit
(0.5329) beats the *deployed* static table (0.2744) but is **beaten by a
validation-tuned static table (0.5879)** — so it does not outperform a well-tuned
static baseline (`docs/CLAIM_EVIDENCE_MATRIX.md` C6, `RESULTS.md` §0.13.6). **The
GNN is the seed-sensitive component** at +/- 0.011, ~10x the fused spread, while
also being the heaviest-weighted input. `lstm_ae` and `transformer` show
+/- 0.000, which was verified rather than trusted: seeds 11 and 12 produce weights
differing by up to 1.40 per tensor, so they genuinely converge to the same
held-out accuracy from different initialisations. Headline rates carry Wilson
intervals — **resting FP is now 5/12 (41.7%), 95% CI [19.3%, 68.0%]** on the
untouched test session (the tight-looking 1/29 [0.6%, 17.2%] was leaky and is
withdrawn, C4). See `RESULTS.md` 0.10.11, §0.12–§0.13.

**`data/` and `src/data/` split -- deliberate, and now guarded.** The audit
database lives under `src/data/`; the checkpoint store that ATTESTS it lives at
the repository root. Co-locating them would put the evidence and its witness in
one directory, so a single `rm -rf` or one mis-scoped restore takes out both --
and the checkpoint store exists precisely to detect tampering with the database.
Previously recorded as "partly deliberate, partly historical"; it is now just
deliberate, documented at both constants in `config.py`, and pinned by a test.
*Do not consolidate them.*

**Audit chain full-scan cost -- a budget with a trigger, not a worry.** Measured
at 78,546 rows: incremental tail verification **46.7 ms** on every request, full
O(rows) scan **2,539 ms** (32.3 us/row) cached for 300 s, i.e. a 0.85% duty cycle.
The scan interval IS the naive-tamper detection latency, so it is deliberate.
Projection: **~32 s at 1M rows**, the point at which a 300 s cache stops hiding it
and a checkpoint-anchored partial scan becomes worth building.

### Fragile areas — where to be careful

- **Canonicalisation** (`firmware/main.py` ↔ `json.dumps(sort_keys=True)`). Any
  change to payload fields or float formatting breaks **all** authentication.
  Now guarded by `TestCanonicalisationContract`, but the guard is a
  transcription of the firmware maths, so it must be updated alongside it.
- **Training order.** `train_*.py` must run in dependency order; each replays
  through the earlier models.
- **`normalized_adjacency()`** is shared by training and inference. Changing it,
  or `GNN_SELF_LOOP_WEIGHT`, without retraining silently invalidates the GNN.
  `TestGNNAdjacency` pins the properties but cannot detect a stale artifact.
- **On-device feature maths.** Signature validity proves the envelope, never the
  contents. `TestFirmwareReferenceEquivalence` is the guard.

## 13. Glossary

- **Security Trust Score** — `[0,1]`, cyber-behaviour evidence only (rate,
  step-up outcome, silence). 1 = trustworthy.
- **Process Anomaly Score** — `[0,1]`, physical sensor evidence only, fused
  from 4 sub-signals. 1 = normal. Never blended with Security Trust.
- **PDP / PEP** — Policy Decision Point / Policy Enforcement Point; both live in
  `gateway.py`.
- **IdentityTargetingRisk** — per-*claimed*-ID counter of failed verification
  attempts. The mechanism that makes trust-poisoning impossible (ADR-2).
- **Step-up** — a gateway-issued nonce the device must echo inside a signed
  message. Failure forces `BLOCK`.
- **boot_id / seq** — anti-replay pair. `boot_id` persists across reboots
  (one flash write per boot); `seq` is per-session.
- **Level 1 / Level 2 explainability** — which *signal* dominated (SHAP over the
  4 fusion inputs) / which *raw feature or neighbour* within that signal.
- **Coordinated attack** — multiple devices individually in-range but jointly
  anomalous. Only the GNN can see it.
- **stealthy_forged_values** — a compromised device reporting deliberately
  innocuous in-range values behind valid credentials. Not reliably detectable.
- **Window-contaminated normal** — a genuinely normal message arriving within
  the 8-sample LSTM window of a real anomaly. Correctly scored low; excluded
  when measuring the true false-positive rate.
- **Fused score / meta-learner** — the logistic-regression stacker combining the
  4 Process Anomaly sub-signals.
- **FR (IEC 62443)** — Foundational Requirement, FR1–FR7.
- **Tenet (NIST SP 800-207)** — one of the 7 zero-trust principles; every audit
  row is tagged with those it evidences.

## Astra operational handoff — 2026-09-05

The current audit section at the start and RESULTS 0.13.17 supersede earlier
model-selection and policy headlines; ADRs and historical measurements above
remain traceable. The full findings, exact stored topology/M9 values, P1–P6
constraint interpretation and remaining blockers are in RESULTS.md §0.13.17.

Do not overwrite archived model/result files to make the new temporal tests
green. New model builds must consume contiguous normal runs and newly merged
source ticks, then rebuild GCN, fusion, policy and research inputs in a versioned
output location. Do not claim SHA-256 hashes captured now prove historical
training provenance. Do not rename gnn_score until a runtime relational interface
has artifact-schema compatibility and end-to-end complementarity evidence.

The current runtime uses a bandit with frozen learned values. P6 is not an
overall policy winner; the saved P5 result also meets the stated test constraints.
Preserve all-negative controls with FPR and undefined detection F1. Preserve
physical feature names and correlated rank-aware explanations.
