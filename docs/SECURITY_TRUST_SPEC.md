# Security Trust Score — Authoritative Specification

> **2026-09-05 audit update:** The score equations remain unchanged. Schema rejection now precedes state mutation, and cooldown cannot block authentic traffic under a forged claimed identity. Adaptive policy is another final combination point.
> Current evidence and limitations: RESULTS §0.13.17.

Reviewer concern **I**. The mechanism was fully implemented and correct, but
specified across scattered docstrings in `src/trust_engine.py` with no single
document stating it. This is that document; it was written by reading the
implementation, and every constant below is named from `src/config.py`.

Implementation: `src/trust_engine.py`, `RuleBasedTrustEngine.score_security_trust()`
(line ~419) and `SecurityTrustState`.

---

## 0. What this score is, and what it must never see

`s_sec ∈ [0,1]`, trust-style: **high = good**.

Its evidence is **cyber-behaviour only**:

- message rate / flood
- step-up challenge outcomes
- elapsed time since the last update (decay)

It **never** sees a physical sensor reading, a feature vector, a fused Process
Anomaly score, or an authentication-failure count for a claimed identity.
Enforced by `tests/test_invariants.py::TestTwoScoreSeparation::test_security_scoring_never_sees_a_sensor_reading`,
which inspects the function signature for forbidden parameter names.

The two scores meet only at final static (`policy_engine.decide`) or contextual-bandit (`adaptive_pdp.greedy_action`) policy evaluation.

---

## 1. Initial value

```
s_sec(t₀) = 0.8
```

`SecurityTrustState.score` default.

**Rationale.** Not 1.0 and not 0.5. A device that has just registered has
presented valid credentials but has no behavioural history, so it is
*provisionally* trusted — high enough to be `ALLOW`ed at
`SECURITY_THRESHOLD = 0.6` on its first message (a system that blocks every new
device until it accumulates history is not deployable), but below the ceiling,
so a device that behaves well still has somewhere to rise to and the score
carries information from message one.

---

## 2. When it updates

**Only on an accepted message.** `score_security_trust()` is called from
`gateway.py` after *every* authentication gate has passed: registered identity,
not revoked, valid HMAC, boot/seq non-replay, timestamp fresh.

A **rejected** message never touches it. This is load-bearing and is the
project's most consequential security invariant:

> Penalising the *claimed* device on a failed authentication is a trust-poisoning
> denial of service that requires no secret at all — anyone can send garbage
> claiming to be `esp32-vib-001`.

Failed authentications are attributed to `IdentityTargetingRisk`, keyed on the
**claimed** id, which is a separate signal about *who is being targeted*, not
about that device's own trustworthiness.

This is not only an anti-attack property. During a clock misconfiguration the
real board was rejected several hundred times consecutively, and its Security
Trust correctly never moved.

---

## 3. Update rule, in order

Given elapsed time `Δt = max(0, now − last_updated_at)`:

**3.1 Time decay (applied first, always)**

```
decay  = min(TRUST_DECAY_MAX, TRUST_DECAY_PER_SECOND · Δt)
s_sec ← max(0, s_sec − decay)
```

with `TRUST_DECAY_PER_SECOND = 0.01` and the decay clamped at `0.3` per update.

Two clamps, both deliberate:

- `max(0, now − last_updated_at)` — a **backward** wall-clock step (NTP
  correction, manual adjustment) would otherwise make `Δt` negative, hence
  `decay` negative, hence `s_sec − decay` an *increase*. Trust may decay with
  time; it must never **grow** from it.
- `min(0.3, …)` — a device silent for an hour must not have its score driven to
  0 by arithmetic alone. Silence is not evidence of compromise, and the
  staleness flag (§5) is the correct channel for "we have not heard from this
  device".

**3.2 Observation**

Exactly one branch fires, in this precedence order:

| Condition | observation | note |
|---|---|---|
| `step_up_result == "SUCCESS"` | `s_sec ← min(1, s_sec + 0.1)`, then `observation = s_sec` | bounded boost applied *directly*, then used as the observation |
| `step_up_result ∈ {TIMEOUT, MISMATCH}` | `max(0, 0.5 − 0.15·min(n_fail, 3))` | `n_fail` = cumulative step-up failures for this device |
| `is_flood` | `0.2` | messages arriving faster than `MIN_MESSAGE_INTERVAL_SECONDS = 0.5` |
| otherwise | `0.95` | authenticated, normal rate |

The step-up SUCCESS boost is applied to the decayed score *before* the EWMA
rather than being fed through it, because a single successful challenge should
not be diluted to 35% of its effect by the previous score; it is then used as
the observation too, so the blend confirms it rather than pulling it back down.

**3.3 EWMA blend and clamp**

```
s_sec ← α · observation + (1 − α) · s_sec        α = TRUST_EWMA_ALPHA = 0.35
s_sec ← round(clamp(s_sec, 0, 1), 3)
last_updated_at ← now
```

`α = 0.35` weights the newest observation about a third — one anomalous message
moves the score visibly but cannot by itself cross the threshold from a healthy
baseline, and roughly three consecutive flood observations are needed to drive a
healthy device below `SECURITY_THRESHOLD`.

---

## 4. Recovery

Recovery is the same EWMA, running in the other direction: a device that stops
flooding starts producing `observation = 0.95`, and

```
0.6  →  0.72  →  0.80  →  0.85  →  …
```

reaches `ALLOW` territory in roughly two messages and approaches 0.95
asymptotically. There is no separate recovery path, no reset, and no manual
clear — a device earns its score back through the same rule that lost it.

`STEP_UP_SUCCESS_SCORE_BOOST = 0.1` is the one exception: a successful
challenge-response is direct evidence of key possession *now*, so it is worth a
bounded jump. Bounded, so it can never fully launder a bad score.

---

## 5. Silence

Silence does **not** produce an update — `score_security_trust()` is only called
on an accepted message. What silence does:

- decay accrues and is applied at the **next** accepted message (§3.1), capped
  at 0.3;
- `is_stale(device_id)` returns true once `now − last_arrival > STALE_AFTER_SECONDS`
  (20 s), evaluated lazily at read time;
- `get_security_trust()` applies the same decay for a **read-only** peek
  (dashboard) without mutating state, so the displayed and stored semantics agree.

The **Process Anomaly** score has separate and deliberately different silence
handling: it is **retained exactly**, never decayed toward "normal". A device
reporting a severe anomaly and then going silent means the physical state is
*unknown*, not improving, and fading the score toward safe would be actively
dangerous. Only `status` flips `FRESH → STALE`.

---

## 6. Flood / rate handling

`check_flood()` keeps per-device gateway-arrival timestamps for the last 60 s
(`AuthenticatedBehaviourState.message_arrivals`, a pruned deque). A flood is
declared when the interval since the previous accepted message is below
`MIN_MESSAGE_INTERVAL_SECONDS = 0.5`.

Arrival times are the **gateway's own wall clock**, not the device's `ts` field.
A device-supplied timestamp is attacker-controlled; a flood detector that
trusted it could be silenced by lying about it.

---

## 7. Failed authentication — `IdentityTargetingRisk`

| | |
|---|---|
| Keyed on | the **claimed** device_id |
| Increment | one entry per rejected message, with reason |
| Decay | sliding 60 s window, pruned on read |
| Threshold | `IDENTITY_TARGETING_RISK_THRESHOLD_60S` |
| Cooldown | `IDENTITY_TARGETING_COOLDOWN_SECONDS = 30` |
| Effect | throttling of the *claimed* identity's inbound processing |
| Effect on `s_sec` | **none, ever** |

---

## 8. Threshold

```
SECURITY_THRESHOLD = 0.6
```

**How it was chosen, stated honestly:** it was not derived from an optimisation.
It is the midpoint between the provisional starting value (0.8) and the flood
observation (0.2), placed so that a healthy device sits comfortably above it and
roughly three consecutive flood observations cross it.

`scripts/evaluate_policy_comparison.py` now re-selects both thresholds on the
VALIDATION split by macro-F1 and reports the result against the deployed value —
see `results/policy_comparison/metrics.json`. The selected pair (0.7, 0.05)
scored higher macro-F1 on the synthetic class mix, but a `θ_proc` of 0.05 would
make the system nearly blind to process anomalies in deployment, which is why
the deployed value is unchanged and the discrepancy is reported rather than
adopted. **The selection objective is not the deployment objective**, and that
gap is the finding, not an oversight.

---

## 9. Constants, all in `src/config.py`

| Constant | Value | §|
|---|---|---|
| initial score | 0.8 | 1 |
| `TRUST_EWMA_ALPHA` | 0.35 | 3.3 |
| `TRUST_DECAY_PER_SECOND` | 0.01 | 3.1 |
| decay clamp per update | 0.3 | 3.1 |
| `STEP_UP_SUCCESS_SCORE_BOOST` | 0.1 | 3.2 |
| `MIN_MESSAGE_INTERVAL_SECONDS` | 0.5 | 6 |
| `STALE_AFTER_SECONDS` | 20 | 5 |
| `PROCESS_STALE_AFTER_SECONDS` | 20 | 5 |
| `SECURITY_THRESHOLD` | 0.6 | 8 |
| `IDENTITY_TARGETING_COOLDOWN_SECONDS` | 30 | 7 |

No magic constants remain in `trust_engine.py` except the observation values in
§3.2 (`0.95`, `0.2`, `0.5`, `0.15`), which are the semantic content of the rule
itself rather than tunables, and are tabulated above.
