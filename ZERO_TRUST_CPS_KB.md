# Zero-Trust CPS — System Architecture & Knowledge Base

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
   (`stealthy_forged_values` detection, Level-2 explainability at 39% against a
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
*Rejected:* Dropping the GNN when isolated — it is the only signal that detects
coordinated attacks, and abstention injects a strong implicit "normal" vote.

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

The GNN is the only signal that detects `coordinated` attacks. Isolation Forest
and LSTM-AE are *structurally* blind to them — they only ever see one device's
own vector.

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

**Level-2 explainability misses its target.** 78/200 (**39%**) of perturbation
tests flip the score back, against a ≥70% target — **100%** for the GNN (78/78)
and **0%** for the LSTM-AE (0/122). The mechanism is measured, not guessed: a
flagged window reconstructs with error ~46–62 (z = 20–27), and recovering to a
0.5 score requires error **≤ 4.28**. An impulsive shock moves `rms`, `peak`,
`crest_factor` and `kurtosis` together, so the best possible single-channel
repair only reaches ~33.7 — an order of magnitude short. Splicing a real normal
*trajectory* into the channel instead of its flat training mean was implemented
and measured (33.63 vs 33.70 median, better in 9/40 windows), then **reverted**
as complexity that bought nothing; that experiment is what locates the limit in
the single-channel restriction rather than the fill value. The **attribution**
is sound regardless: `kurtosis` is named in 110/122 cases, physically correct
for an impulsive spike. `evaluate_explainability_level2.py` prints this
diagnosis alongside the number so the figure never travels without it.

**`stealthy_forged_values` is not reliably detected** (recall 0.515). Stated as
a design limit, not a bug (§10).

**GNN response is not perfectly monotonic at the extreme.** Neighbours at 0.30
→ 0.316 but at 0.10 → 0.363 — a small wobble far from the training region.
Directionally correct across the realistic range.

**Aggregate fused accuracy (0.747) is below the best single signal (0.949).**
Deliberate: the meta-learner is class-weighted so the rare `coordinated` class
is not discarded (unweighted fused recall on it was 0.261, *worse* than the GNN
alone at 0.870). Aggregate accuracy is the wrong single number for a security
system where missing a rare coordinated attack costs more than extra alerts.

**Dashboard load grows with the audit log.** `/api/chain` re-verifies the
entire hash chain, so its cost is O(rows) and rows only ever grow. This was a
live outage once (see ADR-11): at ~14k rows a full 7-endpoint refresh cost
~1.99s of serial time against a 2s poll interval, saturating a single-threaded
server until endpoints returned empty and the page froze on its last render.
Now mitigated by `ThreadingHTTPServer`, a 10s cache on chain verification, a 5s
cache on the governance tallies, and tiered client polling (refresh cycle
~690 ms, `/api/chain` 0.004 s). The underlying O(rows) verification cost is
unchanged, so a very large audit log will eventually need incremental
verification rather than a full re-scan.

**Fragile areas.**
- *Canonicalisation* (`firmware/main.py` ↔ `json.dumps(sort_keys=True)`). Any
  change to payload fields or float formatting breaks **all** authentication.
- *Training order.* `train_*.py` must run in dependency order; each replays
  through earlier models.
- *`normalized_adjacency()`* is shared by training and inference. Changing it
  without retraining silently invalidates the GNN.

**Technical debt.**
- `data/` and `src/data/` split — the audit DB sits under `src/`, the checkpoint
  store at the repo root. Partly deliberate (separate stores), partly historical.
- No automated test suite; verification is via `evaluate_*.py` and live
  observation.
- Firmware-side latency is unmeasured.

---

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
