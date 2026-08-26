# 02 — Understanding the Pipeline

This traces exactly what happens to ONE telemetry message, matching Figure
6.1 in your report (the workflow diagram). Read this alongside the code.

## The device side (`device_simulator.py`)

1. `make_reading(device_id)` generates a plausible sensor value.
2. `sign(secret, payload)` computes an HMAC-SHA256 signature over the payload
   using the device's pre-shared secret. **This is Module 2 (Authentication)**
   — the device is proving "I know the secret associated with this identity"
   without ever sending the secret itself over the network.
3. The signed envelope `{payload, signature}` is published to the
   `cps/telemetry` MQTT topic. **This is Module 6 (Secure Communication)** —
   MQTT/TLS (port 8883) by default once `certs/` is populated, or HTTPS
   (port 5684, `coap_server.py`) as the second secured transport — see that
   file's docstring for why HTTPS substitutes for the originally-planned
   CoAP/DTLS. Both are live; there's no unencrypted fallback once certs exist.

## The gateway side (`gateway.py` → `on_message`)

4. The message arrives and is parsed. If it's malformed, it's dropped
   immediately — an attacker can't even get partial credit for a broken
   message.
5. `verify_signature()` looks the `device_id` up in `DEVICE_REGISTRY`
   (**Module 1 — Device Identity**: if the ID isn't registered, this fails
   immediately, satisfying "no implicit trust") and recomputes the expected
   HMAC to compare against the one the device sent (**Module 2 —
   Authentication**).
6. Before trust scoring, `gateway.py` computes `rule_score` via
   `trust_engine.rule_range_score()` (was authentication OK? is the value
   within physical bounds?) and, if authentication passed, three ML
   anomaly scores in parallel: `isolation_forest_scorer` (Phase 6a, per-value
   distribution), `lstm_ae_scorer` (6b, per-device sequence
   pattern), and `gnn_scorer` (6c, cross-device graph context). All three
   are **inference-only at the gateway** — they load model artifacts that
   `scripts/train_*.py` already trained offline (CLAUDE.md Section 8's hard
   constraint: no `.fit()`/`.backward()`/`.update()` reachable from this live
   path). All four scores (rule + the three ML scorers) feed
   `fusion_engine.FusionEngine.combine()` (**Phase 7**), which blends them
   with a small offline-trained `LogisticRegression` stacking meta-learner
   (or a plain average if `models/` isn't populated yet) into one fused
   observation, explained via SHAP.
7. `trust_engine.score_message()` is called with that fused observation.
   This is where **Modules 3 and 4** happen together:
   - First, trust *decays* based on how long since we last heard from this
     device (`TRUST_DECAY_PER_SECOND`) — a device going quiet isn't neutral,
     it's mildly suspicious.
   - The fused observation from step 6 becomes the new "how good does this
     message look" signal (a physically-out-of-range value or a failed
     signature both override it — see `trust_engine.py`'s comments on why).
   - That observation is blended into the *running* trust score using an
     exponentially-weighted moving average (`TRUST_EWMA_ALPHA`), not simply
     overwritten. This is deliberate: it means trust changes smoothly based
     on a *pattern* of behaviour, and a single bad message can't be perfectly
     cancelled out by the next good one — sustained bad behaviour compounds.
   - Because this function runs on **every single message**, not once at
     login, this is what "continuous verification" (Module 4) means in
     practice — there is no point where a device is verified once and then
     implicitly trusted for the rest of the session.
8. The current trust score goes to **Module 5 — Access Control**:
   `policy_engine.decide()` (Phase 5's fixed thresholds) or
   `adaptive_pdp.AdaptivePDP.greedy_action()` (Phase 8's offline-trained
   contextual bandit, active by default via `config.USE_RL_POLICY`) — both
   share the same `trust_score -> decision` contract, so gateway.py doesn't
   need to know or care which one is active. Note it's `greedy_action()`
   (pure exploitation) at the gateway, not `choose_action()` (which adds
   epsilon-exploration) — exploration only pays for itself paired with an
   `update()` call, and the live path never calls `update()` per the same
   offline-training constraint as step 6 above; `choose_action()` is used
   only by `scripts/train_adaptive_pdp.py`.
9. The decision is published back out on `cps/decisions` (**Module 6** again
   — a real actuator would subscribe to this topic and refuse to act on a
   command unless its own device_id's most recent decision is `ALLOW`).
10. `audit_log.log_decision()` writes the full record — timestamp, device,
    auth result, trust score, decision, which policy engine decided it, the
    SHAP-derived reason, and every individual scorer's raw output — to
    SQLite. **This is Module 7 — Monitoring.** `dashboard.py` (**Phase 9**)
    polls this same table for a live view instead of reading raw rows.

## Why this ordering matters

Notice identity/auth (1–2) always happens *before* trust scoring (3–4), which
always happens *before* the access decision (5). This ordering is the Zero
Trust principle itself: you cannot skip straight to "is this behaviour normal"
without first establishing "do I know who this is and can they prove it" —
an unauthenticated device gets its trust score punished hard specifically so
it can never reach `ALLOW` through good behaviour alone.
