# Module 4 — Continuous Verification

**Status:** Core implemented (embedded within `src/trust_engine.py`)
**Report grounding:** Section 4.3 Module 4; literature refs [22], [S1]

## Purpose

This module enforces the specific NIST SP 800-207 tenet that gives Zero
Trust its name: **no session, once established, is ever implicitly trusted
for its duration.** Every other module in this system could technically be
implemented in a way that only checks identity, authentication, and trust
*once*, at first contact, and then coasts on that judgement — Module 4
exists specifically to prevent that.

## Design Rationale

Reference [22] (a device-to-device continuous-authentication protocol,
IEEE Access) is the direct precedent for this module: it demonstrates that
re-verification can happen within IoT devices' energy and latency budgets
*without* requiring a full re-authentication handshake on every single
message. This project follows the same principle: re-verification does not
mean re-running Module 2's full HMAC check redundantly (it already runs on
every message by construction) — it means ensuring **trust itself** is
never a cached, stale value.

## An Important Architectural Note

Unlike Modules 1, 2, 3, 5, 6, and 7, Module 4 does **not** correspond to a
separate function or class in the starter kit. This is intentional, not an
oversight: continuous verification is not a discrete step in the pipeline —
it is a *property* of how Module 3 is invoked and how its internal state
behaves over time. Specifically, two mechanisms inside
`RuleBasedTrustEngine.score_message()` (documented fully in
`03_module_trust_evaluation.md`) together constitute Module 4's
implementation:

### Mechanism 1 — Re-scoring on every message

```python
def score_message(self, device_id: str, value: float, auth_ok: bool):
    ...
```

This method is called from `gateway.on_message()` for **every single
incoming message**, with no exceptions and no session concept that would
let a device skip evaluation because it was "already checked." There is no
code path anywhere in this system where a device's trust score is read
without first being recomputed. Contrast this with a conventional
session-token architecture, where a device authenticates once, receives a
token, and every subsequent request is validated only by checking token
validity (not by re-evaluating behaviour) — that pattern is exactly what
Zero Trust rejects, and exactly what this system does not do.

### Mechanism 2 — Time-decay independent of new messages

```python
elapsed = now - st.last_seen
decay = min(0.3, TRUST_DECAY_PER_SECOND * elapsed)
st.trust_score = max(0.0, st.trust_score - decay)
```

This runs as the *first* step of every scoring call, before the new
message's content is even considered. It captures a subtler continuous-
verification requirement: trust should degrade even in the **absence** of
new messages. A device that goes silent for an extended period is not
"still trusted at its last-known level" — it's increasingly unverifiable,
and the trust score should reflect that.

## The Missing Piece — a True Background Sweep

As implemented, Mechanism 2 only fires when a *new* message arrives (decay
is calculated relative to `last_seen`, but only applied when
`score_message()` is next called). A device that goes completely silent
forever will never have its trust score updated at all — it simply stops
appearing in the audit log. For a genuinely gapless continuous-verification
guarantee (worth calling out explicitly in your report's evaluation
section as a known limitation, or fixing before final submission), add an
independent background sweep:

```python
import threading
import time

def background_decay_sweep(trust_engine, interval_seconds=5):
    """Runs independently of message arrival, so silence itself is
    continuously evaluated, not just noticed retroactively."""
    while True:
        time.sleep(interval_seconds)
        now = time.time()
        for device_id, state in trust_engine.state.items():
            elapsed = now - state.last_seen
            if elapsed > interval_seconds:
                decay = min(0.3, TRUST_DECAY_PER_SECOND * elapsed)
                state.trust_score = max(0.0, state.trust_score - decay)
                if trust_engine.is_stale(device_id):
                    # A device this stale should probably be flagged to
                    # Module 7 even without a new message triggering it
                    audit_log.log_decision(
                        device_id, auth_ok=True, trust_score=state.trust_score,
                        decision="STALE", reason=f"no contact for {elapsed:.0f}s"
                    )

# started alongside the MQTT client in gateway.run():
threading.Thread(target=background_decay_sweep, args=(trust_engine,), daemon=True).start()
```

This is a small, self-contained addition — it doesn't change any other
module's interface, since it only writes to the same `DeviceTrustState`
objects Module 3 already owns.

## Interface Contract

Module 4 has no distinct external interface — it is a *behavioural
guarantee* about how Module 3 is invoked and how its state evolves, not a
separate data pipeline. The one function it does expose is a query, not a
scoring operation:

```python
def is_stale(self, device_id: str) -> bool:
    st = self.state.get(device_id)
    if st is None:
        return False
    return (time.time() - st.last_seen) > STALE_AFTER_SECONDS
```

| Direction | Data | From/To |
|---|---|---|
| Query | `device_id` | Can be called by Module 5 (should a stale device ever get `ALLOW`, regardless of its last-known trust score?) or Module 7 (dashboard "is this device currently reachable" indicator) |

## Failure Modes

| Scenario | Behaviour | Note |
|---|---|---|
| Device silent forever, no background sweep | Trust score frozen at last value, never decays further | This is the limitation described above — add the background sweep to close it |
| Device silent then returns | Decay is applied retroactively on the next message (Mechanism 2), so trust drops appropriately even though it was "invisible" while silent | Correct behaviour, no fix needed |
| `STALE_AFTER_SECONDS` set too low relative to normal message interval | Devices constantly flagged stale between their normal ~2-second reporting cycle | Tune this relative to your actual device reporting frequency, not a fixed default |

## Extension Path

1. Add the background sweep above.
2. Feed `is_stale()` into Module 5's policy directly — a stale device
   arguably should never receive `ALLOW` even if its last computed trust
   score was high, since "high trust, but I haven't verified that in a
   while" is exactly the situation Zero Trust is designed to distrust.
3. Once the fusion engine (Module 3, Part B) is in place, continuous
   verification extends naturally to *model drift* too — periodically
   re-scoring a device's recent history against a freshly-retrained
   Isolation Forest, not just decaying a scalar over time.
