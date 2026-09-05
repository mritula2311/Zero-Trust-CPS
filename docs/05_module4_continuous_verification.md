# 05 — Module 4: Continuous Verification

> **2026-09-05 audit update:** MQTT, HTTPS and watchdog share a pipeline lock. Process evidence is retained on silence and flagged stale. Research benchmark snapshots do not establish live deployment behavior.
> Current evidence and limitations: [ASTRA_AUDIT.md](ASTRA_AUDIT.md), RESULTS §0.13.17.

> **AS-BUILT NOTE:** the corrected silence-handling logic in Section 2.2
> is implemented as specified —
> `trust_engine.ProcessAnomalyState`/`update_process_anomaly()`/
> `get_process_anomaly()` retains the Process Anomaly Score exactly and
> only flips `FRESH`→`STALE` on silence.
>
> **The lazy-evaluation reasoning below this line originally justified
> NOT building the `background_decay_task()` this section's own pseudocode
> calls for — that turned out to be a real bug, not a safe simplification,
> found live against real hardware.** Staleness was evaluated lazily
> (checked at read-time), but `get_process_anomaly()`'s only call site in
> `gateway.py` always ran immediately AFTER `update_process_anomaly()`
> refreshed the very timestamp being checked — so "whenever a dashboard
> queries it" was never actually true (nothing else called it; `is_stale()`
> on the Security side had zero call sites anywhere). Verified against a
> genuine ~753-second silence in the real board's session: the first
> message after it logged `process_status: 'FRESH'`, never `'STALE'`. The
> gateway now runs exactly the background task this section originally
> specified — `gateway.py::start_silence_watchdog()`, a background thread
> (`SILENCE_CHECK_INTERVAL_SECONDS`, default 5s) checking every registered
> device's staleness independent of message arrival, logging a real audit
> row on both the silence-start and return-to-normal transition. Verified
> end to end: simulated a device going silent, confirmed the score stayed
> frozen (not decayed) while `status` correctly flipped to `STALE`, and
> confirmed the resulting audit row and hash chain both check out. See
> `RESULTS.md` Section 14's "sixth issue" writeup for the full story.

## 1. Purpose

Make sure both scores from Module 3 are genuinely re-checked on every single message — never cached, never treated as valid until the next "login" — and make sure a device that goes silent is treated as gradually less trustworthy over time rather than left at whatever score it last had.

**Literature grounding:** [1], [2] (the core Zero-Trust principle that nothing stays trusted just because it passed a check once), [10] (Badhib et al.'s continuous re-authentication design, which this module's silence-decay logic is modelled after).

## 2. Two Distinct Behaviours

### 2.1 Per-Message Re-Scoring (Reactive)

This is mostly already satisfied by Module 3's design if it is implemented correctly: Module 3 must never store "last score, valid until told otherwise" — every incoming, successfully-authenticated message triggers a fresh call to both the Security Behaviour Engine and the Process Anomaly Engine. This module's job is to own the **state store** both engines read/write rolling-window features from, and to guarantee that store is always queried fresh, never memoized incorrectly across messages.

Note that Module 4 does not correspond to a separate function or class —
this is intentional, not an oversight. Continuous verification is not a
discrete pipeline step; it is a *property* of how Module 3 is invoked and
how its internal state behaves over time. Contrast this with a
conventional session-token architecture, where a device authenticates
once, receives a token, and every subsequent request is validated only by
checking token validity, not by re-evaluating behaviour — that pattern is
exactly what Zero Trust rejects, and exactly what this system does not do:
there is no code path anywhere in this system where a score is read
without first being recomputed from the current message.

```
DeviceState (in-memory, one per device_id, backed by periodic snapshot to disk
             so state survives a gateway restart):
  device_id                : string
  security_trust_score      : float          # most recent value
  process_anomaly_score     : float          # most recent value
  last_scored_at            : timestamp
  rolling_window_buffers    : dict            # the actual data Module 3's feature
                                               # vectors are computed from
```

### 2.2 Silence Handling: Decay for Security, Staleness for Process Anomaly

**This section was corrected after a design review identified a real logic error in the first draft.** The original design decayed *both* scores toward a neutral value on silence — including pulling a high Process Anomaly Score back down over time. That is wrong: if a device reports severe vibration (Process Anomaly Score = 0.92, meaning a real physical problem is very likely underway) and then goes silent, the correct interpretation is that the current physical state is **unknown**, not that it is **becoming normal**. Silently fading a 0.92 back toward some capped value would make a genuinely dangerous situation look progressively safer purely because the device stopped reporting — backwards, and dangerous if this system were ever driving a real operational response.

The two scores are therefore handled differently on silence:

```
DeviceState (extended from Section 2.1):
  security_trust_score            : float
  security_trust_last_updated_at   : timestamp

  process_anomaly_score             : float          # RETAINED as-is on silence — never
                                                        # decayed toward normal, never capped
  process_anomaly_status              : enum(FRESH, STALE)
  process_anomaly_last_updated_at      : timestamp

Background task, ticking every DECAY_TICK_SECONDS (default: 10s):

    for each device in device_state_store:
        silence_duration = now() - device.security_trust_last_updated_at

        if silence_duration > SILENCE_GRACE_PERIOD (default: 60s):
            # Security Trust MAY decay — a device going silent is itself mildly
            # suspicious from a "can we still vouch for this device" standpoint.
            decay_amount = DECAY_RATE_PER_SECOND * (silence_duration - SILENCE_GRACE_PERIOD)
            device.security_trust_score = max(
                device.security_trust_score - decay_amount,
                MINIMUM_DECAYED_SCORE   # default 0.3
            )

            # Process Anomaly Score is NEVER modified here. Only its status changes.
            device.process_anomaly_status = STALE

        write_audit_log_if_score_crossed_threshold(device, reason="silence_decay")
```

`process_anomaly_score` itself is only ever written by Module 3's Process Anomaly Engine, in response to an actual new reading — this background task must never write to that field, only to `process_anomaly_status`. This guarantees the last known physical reading is preserved exactly, with staleness surfaced as separate metadata rather than blended into the value itself.

### 2.3 How Module 5 Must Treat a Stale Process Anomaly Score

This directly affects the 2×2 decision table in `06_module5_access_control.md`. A `STALE` status must never be silently treated as equivalent to a fresh, low reading. Concretely: if a device goes silent while its last known Process Anomaly Score was high, Module 5 must continue treating that as the high-anomaly case (typically `ALERT` or `BLOCK`, depending on the paired Security Trust Score) rather than falling back to `ALLOW` just because no new data has arrived. See `06_module5_access_control.md` Section 2 for the exact rule.

## 2.4 Failure Modes

| Scenario | Behaviour | Note |
|---|---|---|
| Device silent, then returns | Decay-since-last-update is applied retroactively on the next message, so Security Trust drops appropriately even though it was "invisible" while silent | Correct behaviour by design — see the AS-BUILT note above on why this is lazy, not ticked live |
| `SILENCE_GRACE_PERIOD`/staleness threshold set too low relative to a device's normal reporting interval | Devices constantly flagged stale between their normal ~2-second reporting cycle | Tune relative to the device's actual reporting frequency, not a fixed default across every device kind |
| Device silent forever with a high last-known Process Anomaly Score | Score stays frozen at that high value indefinitely, status `STALE` | Correct, not a bug — see Section 2.2's reasoning; the alternative (decaying it down) is the exact error this section corrects |

## 2.5 AS-BUILT: the silence watchdog is what makes any of §2.2 observable

Everything in §2.2 describes what should happen when a device goes quiet — but
none of it can be *detected* by the message-triggered path, for a structural
reason worth stating plainly: **the event that needs detecting is the absence of
an event.** `trust_engine`'s staleness checks are lazy, evaluated when something
asks. If a device stops publishing and nothing else ever asks about it, nothing
evaluates it, and the device simply stops appearing — indistinguishable from a
device that is fine and idle.

`gateway.py._silence_watchdog_loop()` closes that. It sweeps **every registered
device** on a timer (`config.SILENCE_CHECK_INTERVAL_SECONDS = 5`), independent of
any incoming message, and is the only thing that exercises
`is_stale()`/`get_process_anomaly()`'s lazy checks for a device that has gone
quiet.

Three properties of the as-built implementation that are deliberate:

1. **It writes real audit rows on both transitions**, silence-start *and*
   silence-end, with `decision="SILENT"` and
   `reason_category="device_silent"`. "This device went quiet for N seconds" is
   therefore queryable history rather than a console line that scrolls away —
   which is exactly the visibility a device that was powered off, disconnected,
   or deliberately silenced by an attacker would otherwise leave none of.
2. **It alerts once per episode, not once per sweep.** `_silence_alerted` tracks
   which devices are currently flagged, so a device offline for an hour produces
   two rows, not 720.
3. **It holds `_pipeline_lock` across the entire per-device block**, not just the
   staleness read. `get_process_anomaly()` mutates `status` (FRESH→STALE) and
   `get_security_trust()` reads state that the MQTT/HTTPS path writes
   concurrently, so holding the lock through the `log_decision()` call too means a
   `SILENT` row can never be written against a half-updated snapshot of a
   device's own scores.

**This is also what makes NIST tenet 5 validatable.** That tenet claims every
registered asset is monitored, and its falsifier is "a registered device with no
audit rows at all". Without the watchdog, a device that stopped publishing would
produce exactly that — so the check would fail, correctly, because the claim
would be false. See `08_module7_monitoring_and_audit.md` §5.2.

**Scores are frozen, never decayed toward normal.** A silent device keeps its
last known scores. The alternative — drifting them back toward "normal" while no
evidence is arriving — would mean an attacker could launder a bad reputation
simply by going quiet. The console line states this explicitly: *"last known
scores frozen, not decayed toward normal or spiked toward anomalous."* Neither
direction is safe to assume from silence alone, and the design says so rather
than picking one.

## 3. Interface Contract

| Consumer | What It Reads | What It Writes |
|----------|---------------|-----------------|
| Module 3 | Rolling-window buffers (to compute fresh features) | Updated `security_trust_score`, `process_anomaly_score`, `process_anomaly_status = FRESH` after each scoring pass |
| Module 5 | `security_trust_score`, `process_anomaly_score`, `process_anomaly_status` | — (read-only) |
| Module 7 | Score-crossing events and staleness transitions (for audit logging) | — (read-only) |

## 4. Configuration Parameters

```yaml
continuous_verification:
  decay_tick_seconds: 10
  silence_grace_period_seconds: 60
  decay_rate_per_second: 0.01
  minimum_decayed_security_score: 0.3
```

## 5. Acceptance Criteria

- Send 50 genuine messages, then 1 forged message: the Security Trust Score visibly drops on the very next message, not after any delay or batch interval.
- Stop sending messages entirely for a simulated device with a **low** Process Anomaly Score: confirm the background task lowers Security Trust Score over time and marks `process_anomaly_status = STALE`, while `process_anomaly_score` itself does not change value.
- **Staleness-preserves-high-anomaly test (direct regression test for the corrected bug):** drive a simulated device to a high Process Anomaly Score (e.g., via `"physical_spike"`), then stop sending messages entirely. Confirm that after several decay ticks, `process_anomaly_score` is still at (or extremely close to) its last computed value, `process_anomaly_status` has become `STALE`, and Module 5's decision for that device does not fall back to `ALLOW`.
- Restart the gateway process mid-test: confirm device state (scores, status flags, rolling buffers) survives via the periodic snapshot, rather than resetting every device to a neutral score on every restart.

Continue to `06_module5_access_control.md`.
