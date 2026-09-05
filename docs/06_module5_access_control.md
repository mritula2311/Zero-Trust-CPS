# 06 — Module 5: Access Control

> **2026-09-05 audit update:** The live default is a contextual bandit (USE_RL_POLICY), not full RL. P6 is only the best constrained static grid point; P5 also meets the saved test bounds and scores higher macro-F1. Quarantine remains off.
> Current evidence and limitations: [ASTRA_AUDIT.md](ASTRA_AUDIT.md), RESULTS §0.13.17.

> **AS-BUILT NOTE:** the 2×2 table (Section 2) is implemented exactly in
> `src/policy_engine.py::decide()`, on the trust-style Process Anomaly
> scale (see `04`'s AS-BUILT note — "process high" means "process anomaly
> LOW" throughout this file). Section 3's `STEP_UP` behaviour (hold, call
> `initiate_step_up()`, bounded score boost on success, escalate to BLOCK
> on timeout/mismatch) is implemented in `gateway.py`, not this file's
> module — same logic, split across `gateway.py`/`trust_engine.py` rather
> than one `access_control.py`. **Section 4's "optional stretch goal" is
> not optional here — it is the live default** (`config.USE_RL_POLICY =
> True`). This is deliberate, not a scope-creep accident: the reward-signal
> concern Section 4 raises ("a live deployment may not always have an
> immediate, reliable signal telling it whether a past decision was
> actually correct") is resolved by construction — `adaptive_pdp.AdaptivePDP.greedy_action()`,
> the ONLY method the live gateway calls, is a frozen Q-table lookup with
> no exploration and no `update()` call; it needs no live reward signal at
> all, since it never learns online. Training (`scripts/train_adaptive_pdp.py`)
> happens entirely offline against known synthetic ground truth
> (`situation_for_event_type()`, weighted by inverse class frequency —
> the RL analogue of Module 3's `class_weight="balanced"` fix). Measured
> result on held-out data (re-measured after the dataset scale-up,
> `RESULTS.md` Section 12): RL macro-F1 0.583 vs. the static table's 0.269
> — see `10_testing_and_attack_simulation.md`'s confusion matrix.

## 1. Purpose

Read the Security Trust Score and Process Anomaly Score together and decide what happens to the message: Allow, Step-Up Authentication, Alert, or Block. This is the **only** place in the whole system where the two scores are combined — and even here, they are combined through a lookup table, not blended into a single number.

**Literature grounding:** [5] (Zero-Trust access control as a core pillar), [7] (Federici et al.'s fine-grained, least-privilege industrial access control design).

## 2. The 2×2 Policy Table

| Security Trust | Process Anomaly | Recommended Result |
|---|---|---|
| High | Low | Allow |
| High | High | Allow data through + Alert operations team (likely a real physical/process problem) |
| Low | Low | Step-up authentication → restrict if step-up fails |
| Low | High | Block / quarantine + priority security review |

These four rows are mutually exclusive and collectively exhaustive over `{High, Low} × {High, Low}` — there is no fifth case and no overlap between rows.

```
DecisionOutcome = enum(ALLOW, STEP_UP, ALERT, BLOCK)

decide(security_trust_score: float, process_anomaly_score: float,
       process_anomaly_status: FRESH | STALE) -> DecisionOutcome:

    security_high = security_trust_score  >= SECURITY_THRESHOLD    # default 0.6
    anomaly_high  = process_anomaly_score  >= ANOMALY_THRESHOLD     # default 0.6

    if security_high and not anomaly_high:
        return ALLOW
    if security_high and anomaly_high:
        return ALERT      # likely a REAL physical/process problem — do not block,
                            # this is exactly the case a single-score design would
                            # have wrongly silenced
    if not security_high and not anomaly_high:
        return STEP_UP     # device behaviour looks off; sensor data looks fine —
                            # ask for extra proof before deciding further
    if not security_high and anomaly_high:
        return BLOCK        # highest-risk combination: possibly compromised device
                            # ALSO reporting abnormal data
```

Note this is a simplified two-level (high/low) table for clarity; if the tuned thresholds during Phase 5 suggest a third tier (e.g., "borderline" between high and low) is useful, extend to a 3×3 table using the same structure — document any such change and the validation-set evidence that motivated it.

### 2.0 AS-BUILT: what these four outcomes actually DO — and what they do not

The "Recommended Result" column above describes intent. This is the enforcement
reality, stated plainly because the gap between the two is easy to overclaim:

| Outcome | What actually happens |
|---|---|
| `ALLOW` | Decision signed, sent to the device, logged, displayed |
| `ALERT` | Same. There is no separate alerting channel — the "alert" is the audit row and the dashboard |
| `STEP_UP` | **Genuinely enforced.** A real nonce is issued, the device must echo it inside its next signed payload, and a failed or timed-out echo forces `BLOCK` regardless of what the table said |
| `BLOCK` | Decision signed, sent, logged, displayed — and, unless auto-quarantine is armed, **nothing else** |

**The decision is advisory by default.** It is computed, signed, delivered,
verified by the device, logged and rendered, but neither side acts on it: the
firmware verifies `payload["decision"]` and *prints* it — the value is never
stored and never branched on, so the publish loop is unaffected. Measured on
this repository's audit log: **1,112 BLOCK decisions**, and after the last one
the same device sent **6,264 more messages**, all accepted and scored.

**Enforcement does exist — at Module 2, not here.** A revoked device is rejected
before HMAC; an identity over the `IdentityTargetingRisk` threshold has its
messages dropped; nothing unauthenticated ever reaches scoring (validated: NIST
tenet 6, 0 violations across 10,000 rows). So the system enforces
*authentication* decisions unconditionally, and *policy* decisions advisorily.

### 2.0.1 Closing the gap: `AUTO_QUARANTINE_ENABLED`

`config.AUTO_QUARANTINE_ENABLED` escalates a sustained run of BLOCKs into a real
revocation, via `trust_engine.revoke_device()` — the enforcement primitive that
already exists and is already checked before HMAC. It is a policy on top of a
tested mechanism, not new machinery.

- Trigger: `AUTO_QUARANTINE_CONSECUTIVE_BLOCKS` (default **20**) **consecutive**
  BLOCKs for one device. Any non-BLOCK decision resets the run, so it fires on
  sustained conviction rather than scattered BLOCKs.
- Effect: the device is revoked. Every subsequent message is rejected before
  HMAC. A dedicated audit row is written with
  `reason_category="auto_quarantine"` and `policy_source="ENFORCEMENT"`.
- Recovery: **manual only** — `trust_engine.reinstate_device()`. A quarantine
  that expires by itself is not a quarantine.
- Ordering: applied *after* the triggering decision is published and logged, so
  the device receives the BLOCK that quarantined it and the log always explains
  the revocation that follows.

**It ships DISABLED, and that default is evidence-based rather than cautious.**
During the Isolation Forest calibration defect (`RESULTS.md` §0.1) the real,
physically healthy ESP32 accumulated **953 BLOCK decisions** — including 108
runs of ≥3 consecutive, 20 runs of ≥10, and one unbroken run of **50**.
Auto-quarantine armed at any threshold up to 50 would have revoked live hardware
because of a *scoring bug*, and since `is_revoked()` is a hard override the board
would have stayed dead until a human intervened.

The order of operations that follows from that: establish your false-positive
rate first (`RESULTS.md` §0.6 — currently 0.0% on clean held-out normals), then
arm enforcement. Not the reverse.

### 2.0.2 Why the DEVICE does not enforce its own BLOCK

A tempting third option — have the firmware stop publishing when blocked — is
deliberately **not** implemented, and should not be:

1. **It provides no security guarantee.** A compromised device simply ignores
   the instruction. Enforcement that depends on the adversary's cooperation is
   not enforcement, and the entire premise here is that the device is untrusted.
2. **It destroys evidence.** A suspicious device is exactly the one whose
   telemetry you most want to keep receiving and logging.

Enforcement therefore belongs on the side that does not need the device's
consent — the gateway, and ultimately the broker ACLs.

### 2.1 Staleness Overrides the Naive Table Lookup

`process_anomaly_status` (from `05_module4_continuous_verification.md` Section 2.2) is a required input to `decide()`, not an afterthought, because feeding a stale score into the table above as if it were fresh can produce exactly the wrong answer. Apply this rule **before** the table lookup:

```
if process_anomaly_status == STALE and process_anomaly_score >= ANOMALY_THRESHOLD:
    # The last known physical state was concerning, and we have not heard
    # from the device since — do NOT let this quietly resolve to ALLOW as
    # connectivity is lost. Treat it as at least as serious as the fresh
    # high-anomaly case, and additionally flag the connectivity loss itself.
    outcome = ALERT if security_high else BLOCK
    log_additional_flag(device_id, "STALE_HIGH_ANOMALY_UNRESOLVED")
    return outcome

# Otherwise, proceed with the normal table lookup above using whatever
# process_anomaly_score is currently stored (a STALE-but-low score is treated
# as low, since there is no outstanding concern to preserve).
```

## 3. What Each Outcome Actually Does

```
ALLOW:
    - Message is passed through to whatever consumes telemetry downstream
      (e.g., the dashboard's live feed).
    - Logged normally (Module 7).

STEP_UP:
    - Message's telemetry payload is HELD, not yet passed through, pending
      step-up result.
    - Module 2's initiate_step_up(device_id) is called.
    - On STEP_UP_SUCCESS (Module 2 Section 6): release the held message,
      treat as ALLOW, and apply a small positive adjustment to
      security_trust_score (bounded, does not let step-up alone fully
      restore a badly compromised score).
    - On STEP_UP_TIMEOUT or STEP_UP_MISMATCH: escalate to BLOCK, and this
      failure count feeds back into Module 3's SecurityFeatureVector
      (step_up_failures_total) for future scoring.

ALERT:
    - Message IS passed through (the data is real and needed — see the
      2x2 table's ALERT reasoning above).
    - A distinct, high-visibility audit log entry and dashboard notification
      is raised, tagged for operations/maintenance attention rather than
      security attention.

BLOCK:
    - Message is dropped entirely — not passed through to any downstream
      consumer.
    - Logged with full detail (both scores, both Level-1/Level-2
      explanations from Module 3) for security review.
```

## 4. Optional Stretch Goal — Adaptive Policy

**This section is explicitly optional.** No paper in the project's literature review directly builds or validates a reinforcement-learning-style access policy for this kind of system, and a live deployment may not always have an immediate, reliable signal telling it whether a past decision was actually correct. Attempt this only after Sections 1–3 are fully working and tested.

```
Epsilon-greedy bandit sketch:

  state = (security_bucket, anomaly_bucket)   # discretized score buckets
  actions = [ALLOW, STEP_UP, ALERT, BLOCK]
  Q_table[state][action] initialized from the fixed-threshold policy's behaviour

  On each decision:
    with probability epsilon: choose a random action (explore)
    otherwise: choose argmax(Q_table[state])                (exploit)

  Reward signal (this is the hard part — be honest about where it comes from):
    In simulation, ground truth is known (we injected the scenario), so
    reward = +1 if the action matched the correct response for that
    injected scenario, -1 otherwise. In a real deployment, there usually is
    no equivalent ground-truth signal on every message — this is precisely
    why this component is a stretch goal and not part of the core system.

  Evaluation: replay the held-out test set through both the fixed-threshold
  policy and the trained bandit policy; compare F1-score / mistake count.
  Report the result honestly — "the bandit did not beat the fixed policy"
  is a valid, useful finding.
```

### Q-value estimator: incremental sample average, not a fixed learning rate

`AdaptivePDP.update()` uses `α = 1/N` for the N-th visit to a given
`(state, action)` pair — the textbook incremental sample average — rather than a
fixed-α exponential moving average.

This is not a stylistic choice. A single state bucket holds a **mixture** of
ground-truth situations (the same `(security, process)` bucket is reached by
genuinely normal messages and by attack messages alike), so `Q(s,a)` is
estimating an *expectation over that mixture*, and the target is stationary. A
fixed `α = 0.2` EMA tracks only the last ~5 visits, which leaves the stored
value dominated by visit **order** rather than by the mixture's mean. Measured
on the previously-trained table: every action in the high-security/high-process
states sat within 0.4 of every other (state `9,8`: `BLOCK -0.3` vs
`ALLOW -0.7`), so `argmax` was effectively arbitrary — and the deployed policy
answered `BLOCK` for a device at security `0.91`, process `0.87`, where the
static table correctly answers `ALLOW`. A sample average converges to the true
expected reward, which is what a greedy `argmax` needs to mean anything. See
`RESULTS.md` §0.3.

## 4.1 Failure Modes (RL Policy)

| Scenario | Static table (Section 2) | RL policy (Section 4, live default) |
|---|---|---|
| Both scores exactly at a threshold/bucket boundary | Deterministic, always the same decision | Depends on the trained Q-values for that bucket — a decision may differ from the static table's for a borderline state; log these distinctly for evaluation since the RL policy — a contextual bandit, not RL (C6) — is meant to have learned a genuinely different, more sensitive boundary here than the *deployed* static table's (it does not beat a validation-tuned one), not to be arbitrary |
| A `(security_bucket, process_bucket)` state that was rare or ABSENT in training | N/A | **Absent is safe, rare is the real risk — they are different cases.** For a state never visited at all, `AdaptivePDP._get_q()` SEEDS the state from the static 2×2 table (`policy_engine.decide()`), giving the static-correct action 1.0 and the rest 0.0, so `greedy_action()` returns exactly what the static policy would. It does not pick arbitrarily by dictionary order, and it does not fail open — verified: at `security 0.05–0.55` with `process 0.95` both policies return `STEP_UP`. The live dashboard's RL panel labels these rows `static fallback` and shows `--` rather than a misleading `0.00`. A state visited only a FEW times is the genuinely unreliable case, since its sample average is estimated from too few visits; `situation_weights()`'s inverse-frequency weighting mitigates but does not eliminate it, so check which states are sparsely covered before trusting behaviour there. |
| Live reward signal | N/A | Not a live concern by construction — `greedy_action()` is the only method the live gateway calls, and it never updates online (Section 4 above) |

## 5. Interface Contract

| Consumer | What It Reads | What It Writes |
|----------|---------------|-----------------|
| Module 4 | `security_trust_score`, `process_anomaly_score`, `process_anomaly_status` | — |
| Module 2 | — | Calls `initiate_step_up()` when outcome is `STEP_UP` |
| Module 7 | — | Every decision, with both scores, `process_anomaly_status`, and both explanation levels, written to audit log |
| Module 3 | — | `step_up_failures_total` incremented on step-up failure (feeds back into next scoring pass, via `AuthenticatedBehaviourState` — see `03_module2_authentication.md` Section 5) |

## 6. Configuration Parameters

```yaml
access_control:
  security_threshold: 0.6
  anomaly_threshold: 0.6
  step_up_success_score_boost: 0.1   # bounded positive adjustment, not a full reset
  adaptive_policy_enabled: false      # stretch goal, off by default
```

## 7. Acceptance Criteria

- All four outcomes (Allow, Step-Up, Alert, Block) are reachable and independently testable by feeding the four score-quadrant combinations directly into `decide()`.
- A simulated physical-fault scenario (high security score, high anomaly score) results in `ALERT`, and the message is confirmed to still reach the downstream consumer — not silently dropped, which is exactly the failure mode this design exists to prevent.
- A simulated compromised-device-plus-abnormal-data scenario results in `BLOCK`, and the message is confirmed to be dropped.
- **Stale-high-anomaly regression test:** drive a device to a high Process Anomaly Score, then let it go silent long enough for `process_anomaly_status` to become `STALE` (per `05_module4_continuous_verification.md`). Confirm `decide()` still returns `ALERT` or `BLOCK` (matching the current Security Trust Score) and does **not** fall back to `ALLOW`, and confirm `STALE_HIGH_ANOMALY_UNRESOLVED` is flagged.
- A manual step-up test end-to-end: `STEP_UP` outcome → challenge issued → correct echo → message released and logged as effectively allowed.
- (If attempted) the adaptive policy comparison against the fixed policy is recorded, whichever way it comes out.

Continue to `07_module6_secure_communication.md`.
