# Integration and Interactions — How the Seven Modules Work Together

This document is the one to read when you need to understand the *system*,
not any individual module. It covers the dependency graph, the exact
sequence one message travels through, a fully worked numeric example, the
consolidated interface contracts, and what breaks (and how gracefully) at
each failure point.

## 1. Module Dependency Graph

```
Module 1 (Device Identity) ──┐
                              ├──► Module 2 (Authentication) ──► Module 3 (Trust Evaluation) ◄──► Module 4 (Continuous Verification)
Module 1 (expected_range) ───┘                                          │
                                                                          ▼
                                                              Module 5 (Access Control)
                                                                          │
                                              ┌───────────────────────────┼───────────────────────────┐
                                              ▼                                                        ▼
                                    Module 6 (Secure Comm — publish decision)              Module 7 (Monitoring — log everything)
```

Key relationships worth naming explicitly:

- **Modules 1 → 2 is a hard dependency.** Module 2 cannot run at all
  without Module 1 first resolving whether the claimed `device_id` exists
  and, if so, what its secret is.
- **Module 4 is not a separate node in this graph** — as explained in
  `04_module_continuous_verification.md`, it is a property of *how* Module
  3 is invoked (every message, plus time-decay), not a distinct processing
  step. It's shown here as bidirectional with Module 3 to represent that
  relationship, not a literal function call.
- **Module 7 depends on everything upstream of it, and nothing depends on
  Module 7 in the real-time path.** It is a pure sink for the live pipeline
  (though it becomes a *source* for offline processes — see Section 5
  below).
- **Module 6 appears twice** — once implicitly, carrying the inbound
  message that triggers this whole sequence, and once explicitly,
  publishing Module 5's decision back out.

## 2. The Full Per-Message Sequence

This is the same flow shown as Figure 6.1 in your report, expressed here as
an explicit call sequence rather than a diagram, matching the actual code in
`gateway.py::on_message`:

```
1.  MQTT message arrives on TELEMETRY_TOPIC           [Module 6]
2.  Parse JSON -> {payload, signature}                 [gateway.py]
     └─ if malformed: DROP, no further processing, nothing logged
3.  Extract device_id, value from payload
4.  Module 1: DEVICE_REGISTRY.get(device_id)
     └─ if not found: auth_ok = False (Module 2 short-circuits)
5.  Module 2: recompute HMAC, compare_digest(expected, signature) -> auth_ok
6.  Module 3+4: trust_engine.score_message(device_id, value, auth_ok)
     a. apply time-decay since last_seen
     b. compute observation from auth_ok (+ value range if auth_ok=True)
     c. EWMA-blend observation into running trust_score
     d. return (trust_score, reason)
7.  Module 5: policy_engine.decide(trust_score) -> decision
8.  Module 6: publish {device_id, decision} on DECISION_TOPIC
9.  Module 7: audit_log.log_decision(device_id, auth_ok, trust_score, decision, reason)
10. Console line printed (human-readable mirror of step 9)
```

Notice step 4's failure branch: an unknown device does **not** stop the
pipeline. It flows all the way through to Module 7, arriving there with
`auth_ok=False` and consequently a heavily penalised trust score and (very
likely) a `DENY` decision. **This is deliberate.** A system that silently
drops messages from unrecognised devices produces no audit trail of the
attempt — and "an unregistered device tried to talk to the gateway" is
exactly the kind of event a governance reviewer needs visibility into. The
only case that's dropped silently (step 2) is a message so malformed it
doesn't even parse — there's no `device_id` to attribute an audit record to
in that case.

## 3. Worked Example — One Message, Start to Finish

Let's trace an actual injected anomaly from the starter kit's simulator, with
real numbers, so the abstract sequence above becomes concrete.

**Scenario:** `sensor-002` (expected range 20.0–80.0) has been running
normally for a while (`trust_score = 0.86`, `last_seen` 2 seconds ago), and
the simulator injects its scheduled bad-value anomaly.

```
Device side (Modules 1, 2, 6):
  payload   = {"device_id": "sensor-002", "value": 579.76, "ts": 1755590000.0}
  signature = sign("s3cr3t-key-002", payload)   # a VALID signature -- the
                                                  # simulator forges the VALUE,
                                                  # not the signature, for this anomaly
  → published to "cps/telemetry"

Gateway (Module 1): DEVICE_REGISTRY["sensor-002"] found
  secret = "s3cr3t-key-002"
  expected_range = (20.0, 80.0)

Gateway (Module 2):
  expected_sig = HMAC-SHA256("s3cr3t-key-002", canonical_payload)
  expected_sig == signature?  → YES → auth_ok = True

Gateway (Module 3+4), trust_engine.score_message("sensor-002", 579.76, True):
  elapsed = 2.0s → decay = min(0.3, 0.01 * 2.0) = 0.02
  trust_score = max(0, 0.86 - 0.02) = 0.84            (step a: decay applied)

  auth_ok=True → observation starts at 0.9
  value=579.76, range=(20.0, 80.0) → 579.76 NOT in range
  → observation = 0.15                                  (step b/c: value-range rule fires)
  reason = "authentication ok; value 579.76 outside expected range [20.0, 80.0]"

  EWMA blend: trust_score = 0.35 * 0.15 + 0.65 * 0.84
            = 0.0525 + 0.546
            = 0.5985 ≈ 0.60                               (step d)

  → returns (0.60, "authentication ok; value 579.76 outside expected range [20.0, 80.0]")

Gateway (Module 5): decide(0.60)
  0.60 < THRESHOLD_ALLOW (0.70)
  0.60 >= THRESHOLD_STEP_UP (0.40)
  → "STEP_UP"

Gateway (Module 6): publish {"device_id": "sensor-002", "decision": "STEP_UP"} to "cps/decisions"

Gateway (Module 7): audit_log.log_decision(
    device_id="sensor-002", auth_ok=True, trust_score=0.60,
    decision="STEP_UP", reason="authentication ok; value 579.76 outside expected range [20.0, 80.0]"
)
```

This exact sequence is what produced the real console line you'd see
running the starter kit:

```
sensor-002     | value=  579.76 | auth=OK  | trust= 0.60 | STEP_UP | authentication ok; value 579.76 outside expected range [20.0, 80.0]
```

Notice `auth=OK` — this example deliberately traces the *value*-anomaly
path rather than the *signature*-forgery path, to show that Module 3 acts on
more than just Module 2's output. If you want to trace the other failure
mode (`actuator-001`'s forged-signature injection), the only change is at
Module 2: `auth_ok = False`, which produces a steeper trust penalty via the
`consecutive_auth_failures` escalation described in
`03_module_trust_evaluation.md`.

## 4. Consolidated Interface Contract Table

| Producer | Data | Consumer(s) | Format |
|---|---|---|---|
| Module 1 | `secret` | Module 2 | `str` |
| Module 1 | `expected_range` | Module 3 | `tuple[float, float]` |
| Module 2 | `auth_ok` | Module 3 | `bool` |
| Module 2 | `consecutive_auth_failures` (state) | Module 3 (internal) | `int`, held in `DeviceTrustState` |
| Module 3 | `trust_score` | Module 5, Module 7 | `float ∈ [0,1]` |
| Module 3 | `reason` | Module 7 (→ Module 3 Part B: SHAP replaces this with a richer string) | `str` |
| Module 3 (Part B only) | `confidence` | Module 5 (Part B), Module 7 | `float ∈ [0,1]` |
| Module 5 | `decision` | Module 6, Module 7 | `str`, one of `"ALLOW" \| "STEP_UP" \| "DENY"` |
| Module 7 | historical rows (via `recent()`) | Offline: Module 3 Part B's meta-learner training, Module 5 Part B's reward computation, governance reports | `list[dict]` |

The last row is worth dwelling on: Module 7's data becomes an **input** to
Modules 3 and 5 once you build their advanced (Part B) versions — but only
*offline*, during training, never in the live per-message path. This is the
same "train offline, infer at runtime" principle from Report Section 5.2,
and it's why Module 7 is drawn as a pure sink in Section 1's graph above:
that graph describes the **live** pipeline specifically.

## 5. How Interfaces Change as You Build Out Phases 6–9

The core (Part A) interfaces are deliberately narrow so that upgrading any
one module doesn't ripple through the others. Concretely:

| When you add... | The interface that changes | What stays identical |
|---|---|---|
| Isolation Forest, LSTM-AE, GNN (Module 3, Phase 6) | Internal to Module 3 only — new scorer classes | `score_message(device_id, value, auth_ok) -> (trust_score, reason)` signature unchanged until fusion is wired in |
| Fusion + SHAP (Module 3, Phase 7) | `score_message()` now also returns `confidence`; `reason` becomes SHAP-generated | Module 5 and Module 7's *call sites* need one new field consumed, but the call itself is still one function call, same position in the pipeline |
| RL-adaptive PDP (Module 5, Phase 8) | Internal to Module 5 only — `decide()` becomes a class method with training/update calls added *outside* the live pipeline | `decide(trust_score) -> decision` signature unchanged in the live path |
| TLS (Module 6, `docs/03_add_tls.md`) | Connection setup only (`client.tls_set(...)`) | Topic structure, message format, and every other module's code — completely untouched |
| Dashboard (Module 7, Phase 9) | Purely additive — a new consumer of `audit_log.recent()` | The write path (`log_decision()`) is untouched |

This table is itself worth including in your report or thesis as evidence
of good modular design — the fact that four major upgrades each touch
exactly one module's internals, with no cascading changes elsewhere, is a
direct, demonstrable payoff of the interface contracts documented above.

## 6. Concurrency and Timing Considerations

- The gateway processes messages from `on_message` essentially serially per
  the paho-mqtt client's default threading model — this is actually
  convenient for correctness (no risk of two messages for the same device
  racing on `DeviceTrustState`), but means gateway throughput is bounded by
  how long Module 3's scoring takes per message. Rule-based scoring (Part
  A) is fast enough this never matters at prototype scale; once GNN
  inference (Part B) is in the live path, measure per-message latency
  explicitly (Report Section 10.1) rather than assuming it's still
  negligible.
- The background decay sweep proposed in `04_module_continuous_verification.md`
  runs on a separate thread and **does** introduce genuine concurrent
  access to `trust_engine.state` — if you add it, wrap access to that
  dictionary in a `threading.Lock` to avoid a race between the sweep and
  `on_message` both mutating the same `DeviceTrustState` object.

## 7. Summary — the One-Sentence Version of Each Module's Job

Useful as a viva/interview cheat sheet:

1. **Device Identity** — is this device_id one we know about?
2. **Authentication** — can it prove it, cryptographically, for this exact message?
3. **Trust Evaluation** — given everything we know, how much do we trust it right now?
4. **Continuous Verification** — and are we re-asking that question constantly, not just once?
5. **Access Control** — given that trust level, what are we actually going to allow?
6. **Secure Communication** — and is the channel itself private and tamper-evident?
7. **Monitoring** — and can we prove, after the fact, that all of the above actually happened?
