# 09 — Integration and Data Flow

> **AS-BUILT NOTE:** Section 1's sequence matches the live `gateway.py::process_telemetry()`
> flow, with one addition: step-up resolution (`check_step_up_response()`)
> is checked immediately after Module 2's authentication succeeds and
> before Module 3 Section A scores, so a resolved challenge's bounded
> trust adjustment is visible to that same message's policy decision.
> Section 5's recommended package layout (`src/simulation/`, `src/identity/`,
> etc.) and `config.yaml` are **not used** — this codebase keeps the flat
> `src/*.py` + `config.py` layout it already had, deliberately, to avoid
> restructuring risk against a large existing codebase (see `00_overview.md`'s
> AS-BUILT callout). The module boundaries and interfaces themselves are
> respected; only the file/package organization differs. Step 7's
> explanation-computation trigger is also AS-BUILT-different from the
> design below — see that step's own note for the verified-no-cost
> reasoning.

This document is the single place to look when a change in one module seems like it might affect another. Read it after all seven module files, as a consistency check before or during integration.

## 1. End-to-End Sequence for One Message

```
1.  [Device Layer]     A device (simulated or real) reads its sensor, builds a
                        TelemetryMessage, computes HMAC over the canonical
                        payload, publishes to cps/telemetry/{device_id}.
                        → 01_simulation_and_hardware_abstraction.md

2.  [Module 6]          Gateway's MQTT subscriber receives the message over TLS.
                        → 07_module6_secure_communication.md

3.  [Module 1]          Look up device_id in the registry. Unknown → reject,
                        and route the event to IdentityTargetingRisk for that
                        claimed ID (Module 2, Section 5) — never to any
                        registered device's own Security Trust Score, since
                        there is no registered device to attribute it to.
                        → 02_module1_device_identity.md

4.  [Module 2]          Check revocation status, verify HMAC (current or
                        previous key), check boot_id + sequence number, check
                        timestamp. Any failure → reject with a specific
                        reason, log it, and route it to IdentityTargetingRisk
                        for the claimed device_id (never directly to that
                        device's own Security Trust Score — see Module 2
                        Section 5 for why this separation is required).
                        On success → call update_last_seen(), continue to
                        Module 3 Section A with the message now treated as
                        genuinely authenticated.
                        → 03_module2_authentication.md

5.  [Module 3, Sec A]   Recompute SecurityFeatureVector from rolling counters
                        (now including this message's outcome), compute
                        Security Trust Score.

6.  [Module 3, Sec B]   Recompute ProcessFeatureVector from the raw readings,
                        run all enabled sub-signals, fuse via meta-learner,
                        compute Process Anomaly Score.

7.  [Module 3, Sec C]   Compute Level-1 and Level-2 explanations.
                        AS-BUILT DEVIATION: this step's original design
                        (this file) said to compute explanations only for
                        near-threshold/non-ALLOW messages, to avoid the
                        "wasteful" cost of explaining every normal
                        message. The live gateway.py computes both levels
                        UNCONDITIONALLY on every authenticated message
                        instead -- verified, not assumed, that this costs
                        nothing meaningful in practice (RESULTS.md Section
                        6 re-measured full-pipeline latency before/after:
                        44.037ms -> 43.499ms, within run-to-run noise, not
                        a regression) at this model scale (the Level-2
                        perturbation forward passes are a handful of
                        extra calls against 3K-18K-parameter models).
                        Kept unconditional for the simpler code path and
                        so every audit_log row carries a real explanation,
                        not just the ones that happened to be near a
                        threshold at the time.
                        → 04_module3_trust_evaluation.md

8.  [Module 4]          Update DeviceState with the fresh scores and
                        last_scored_at. (The silence-decay background task
                        runs independently of this per-message path.)
                        → 05_module4_continuous_verification.md

9.  [Module 5]          decide(security_trust_score, process_anomaly_score)
                        → ALLOW / STEP_UP / ALERT / BLOCK. Execute the
                        corresponding action (pass through, hold pending
                        challenge, pass through + flag, or drop).
                        → 06_module5_access_control.md

10. [Module 7]          Write one audit_log row capturing everything above:
                        both scores, the decision, both explanation levels,
                        the hash-chain fields. Update the dashboard's live
                        view.
                        → 08_module7_monitoring_and_audit.md
```

## 2. Consolidated Data Schemas (Quick Reference)

| Schema | Owning Module | Defined In |
|---|---|---|
| `TelemetryMessage` (now includes `boot_id`) | Device layer / Module 6 | `01`, Section 2 |
| `DeviceRegistryEntry` | Module 1 | `02`, Section 2 |
| `VerificationResult` | Module 2 | `03`, Section 4 |
| `AuthenticatedBehaviourState` (feeds Security Trust Score) | Module 2 | `03`, Section 5 |
| `IdentityTargetingRisk` (never feeds any device's own score) | Module 2 | `03`, Section 5 |
| `SecurityFeatureVector` / `SecurityTrustResult` | Module 3, Section A | `04`, Section A |
| `ProcessFeatureVector` / `ProcessAnomalyResult` | Module 3, Section B | `04`, Section B |
| `TwoLevelExplanation` | Module 3, Section C | `04`, Section C |
| `DeviceState` (now includes `process_anomaly_status: FRESH \| STALE`) | Module 4 | `05`, Section 2 |
| `DecisionOutcome` | Module 5 | `06`, Section 2 |
| `audit_log` row / `CheckpointRecord` | Module 7 | `08`, Section 2 |

## 3. Module Dependency Graph

```
Module 1 (Identity)  ──┐
                        ├──► Module 2 (Authentication) ──┬──► Module 3a (Security Behaviour)
Module 6 (Secure Comm) ┘                                  │
                                                             ├──► Module 4 (Continuous Verification) ──► Module 5 (Access Control) ──► Module 7 (Monitoring)
Raw sensor data ─────────────────────────────────────────► Module 3b (Process Anomaly) ──┘
                                                             │
                                                        Module 3c (Explainability, reads from 3a+3b)
```

No module has a circular dependency. Module 3's two engines (Sections A and B) run in parallel and do not read each other's internal features — they only meet inside Module 5's decision table. **If, during implementation, you find yourself passing a Process Anomaly feature into the Security Behaviour Engine's scoring function (or vice versa), stop — that breaks the core architectural principle and should be redesigned, not patched.**

Key relationships worth naming explicitly:

- **Modules 1 → 2 is a hard dependency.** Module 2 cannot run at all
  without Module 1 first resolving whether the claimed `device_id` exists
  and, if so, what its secret is.
- **Module 7 depends on everything upstream of it, and nothing depends on
  Module 7 in the live, real-time path.** It is a pure sink there — though
  it becomes a *source* for offline processes (model training, governance
  reports), never in the live per-message path (Section 4 above).
- **Module 6 appears twice** — once implicitly, carrying the inbound
  message that triggers this whole sequence, and once explicitly,
  publishing Module 5's decision (and, for `STEP_UP`, the challenge nonce)
  back out.

### 3.1 Concurrency and Timing

The gateway processes messages from `on_message` essentially serially, per
the MQTT client's default threading model — convenient for correctness (no
risk of two messages for the same device racing on its trust/anomaly
state), but it means gateway throughput is bounded by how long Module 3's
scoring takes per message. Rule-based scoring is fast enough this never
matters at prototype scale; once GNN inference is in the live path (as it
is, live default — Section B.5), measure per-message latency explicitly
(`docs/10_testing_and_attack_simulation.md`) rather than assuming it's
still negligible.

> **AS-BUILT — the serial assumption above is no longer true, and the gateway
> defends against that explicitly.** `gateway.py` runs several threads that
> reach the same unlocked mutable state: the MQTT loop, the HTTPS second
> transport (`coap_server.py`), and the silence watchdog. Both transports call
> `process_telemetry()`, and the watchdog reads and mutates per-device trust
> state on its own timer. The "single-threaded pipeline" assumption that
> `fusion_engine.py` and `trust_engine.py` were written against therefore does
> not hold on its own.
>
> `_pipeline_lock` restores it. It serialises the **whole** telemetry pipeline,
> not just individual reads, because the state at risk is not one variable but
> several that must stay mutually consistent: `FusionEngine.last_shap` (read
> immediately after `combine()` to log it), the LSTM-AE's per-device rolling
> window, the GNN's `last_features`/`last_seen` arrays, and
> `check_boot_replay()`'s `last_seen_seq`. Two interleaved in-flight messages
> would corrupt all four. The silence watchdog holds the same lock across its
> entire per-device block, so a `SILENT` row can never be written against a
> half-updated snapshot of a device's own scores.
>
> Lock ordering is fixed and documented: `_pipeline_lock` → `audit_log`'s own
> chain lock, never the reverse, so the two cannot deadlock.
>
> Measured per-message cost with the full pipeline (auth + 4 scorers + fusion +
> policy): **median 26.85 ms, p95 36.09 ms**; HMAC verification alone is
> **0.005 ms**. So the serialisation is not currently a throughput problem at
> three devices publishing every 2 s, but the measurement is the point — §3.1's
> advice to measure rather than assume is what produced these numbers.

### 3.1b The dashboard and `/api/*` layer — a second concurrency domain

The dashboard runs on its own `ThreadingHTTPServer` in a background thread and
is **deliberately outside** `_pipeline_lock`. It never mutates pipeline state; it
only reads the audit log, which opens a fresh SQLite connection per call and
guards writes with its own lock. Keeping it outside the pipeline lock is what
stops a slow HTTP client from stalling telemetry processing.

Threading here is load-bearing rather than incidental, and the reason is worth
recording because the failure was subtle:

The page polls seven `/api/*` endpoints every 2 s. On the original
single-threaded `HTTPServer`, one full refresh cost **~1.99 s of serial server
time** once the audit log reached ~14k rows — `/api/chain` alone re-verifies the
entire hash chain, at 0.66 s and growing with every logged decision. Against a
2 s poll interval that is ~100% saturation: refreshes overlapped, queued, and
endpoints began returning **empty** responses, so the page silently kept its last
good render. The symptom presented as "the dashboard shows static values", which
points at the UI, while the cause was entirely server-side.

Three changes fixed it, and they are complementary:

| Change | Effect |
|---|---|
| `ThreadingHTTPServer` | Requests no longer queue behind one another |
| 10 s TTL cache on chain verification | `/api/chain` **0.66 s → 0.004 s** |
| 5 s TTL cache on the NIST/IEC tallies + tiered client polling | Heavy, slow-changing panels stop being recomputed twice a second |

Full refresh cycle: **1990 ms → ~690 ms**.

The underlying cost is unchanged: chain verification is O(rows) and rows only
grow. The cache defers that, it does not remove it. A substantially larger audit
log will eventually need incremental verification — verifying only rows added
since the last checkpoint — rather than a full re-scan.

**A verification lesson from the same incident:** the server-side fix was real
and measured, but the page still rendered *nothing*, because an escaping error in
the same edit had produced a JavaScript `SyntaxError`. A `curl` loop over the
endpoints reported everything healthy. Only loading the actual page revealed it.
Endpoint checks verify the API; they do not verify the client that consumes it,
and for a browser-delivered surface both need testing. `node --check` on the
extracted script is now the cheap static gate, and a real page load is the
functional one.

### 3.2 The Seven Modules, One Sentence Each

Useful as a quick recap or viva cheat sheet:

1. **Device Identity** — is this `device_id` one we know about?
2. **Authentication** — can it prove it, cryptographically, for this exact message, and is the claim itself (not just the message) genuinely fresh?
3. **Trust Evaluation** — given everything we know, how much do we trust its cyber-behaviour, and separately, how normal does its physical reading look?
4. **Continuous Verification** — and are we re-asking both of those questions on every message, not just once, while treating silence correctly for each?
5. **Access Control** — given both trust levels together, what are we actually going to allow?
6. **Secure Communication** — and is the channel itself private and tamper-evident, in both directions?
7. **Monitoring** — and can we prove, after the fact, that all of the above actually happened, and that the record of it hasn't been quietly altered?

## 4. Consolidated Configuration File

All per-module `yaml` snippets shown throughout Modules 1–7 belong in one file, `config.yaml`, at the project root. See `11_project_structure_and_config.md` for the full assembled version.

## 5. Recommended Python Package Layout

```
src/
  simulation/          # 01 — SimulatedDevice, scenario injection, multi-node orchestration
  identity/            # 02 — device registry
  auth/                # 03 — HMAC verification, anti-replay, step-up
  trust/
    security_engine.py # 04 Section A
    process_engine.py  # 04 Section B (rule, isolation_forest, lstm_ae, gnn submodules)
    explain.py          # 04 Section C
  verification/        # 05 — continuous re-scoring state, silence decay
  access_control/       # 06 — 2x2 policy, step-up orchestration, optional adaptive policy
  comms/                 # 07 — MQTT client wrappers, TLS config
  monitoring/            # 08 — audit log, hash chain, dashboard
  gateway.py             # wires steps 2-10 of Section 1 together as the main event loop
config.yaml
```

(This is a naming suggestion for consistency with the module numbering in this LLD set — adjust freely as long as the module boundaries and interfaces above are respected.)

Continue to `10_testing_and_attack_simulation.md`.
