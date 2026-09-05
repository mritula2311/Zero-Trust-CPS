# 03 — Module 2: Authentication

> **2026-09-05 audit update:** Typed, finite telemetry validation precedes state commitment. Replay checking does not create state. Claimed-ID cooldown suppresses repeated failed-HMAC logging only; it cannot deny authentic traffic.
> Current evidence and limitations: RESULTS §0.13.17.

> **AS-BUILT NOTE:** this file's design is implemented closely as
> specified — `src/trust_engine.py::check_boot_replay()` /
> `check_timestamp_freshness()` for Section 4, `IdentityTargetingRisk` for
> Section 5 (including the gateway-level cooldown, Section 5.1,
> `config.IDENTITY_TARGETING_RISK_THRESHOLD_60S`), and a real
> `initiate_step_up()`/`check_step_up_response()` for Section 7. Two
> implementation notes this file doesn't anticipate: (1) a step-up
> mismatch is only counted as a MISMATCH if the device actively echoes a
> *wrong* nonce — a message that simply hasn't received the challenge yet
> (no echo field at all) is treated as "still waiting," not an immediate
> failure, since the challenge arrives asynchronously and may postdate the
> device's very next scheduled publish; (2) `IdentityTargetingRisk`'s
> counter and cooldown live in `trust_engine.py` alongside the Security
> Trust Score, not a separate module file — same file, clearly separated
> classes. Live-verified: 50+ forged-signature attempts against a
> registered device left its own state completely untouched; a genuine
> reboot was accepted and a subsequent replay of a pre-reboot message was
> rejected. The step-up flow's full round trip is now verified live for
> BOTH outcomes: TIMEOUT/MISMATCH, and — after `certs/mosquitto_acl` was
> given `cps/challenge/*` rules and the broker restarted — SUCCESS,
> observed directly in the gateway log (`FLOOD detected` → `STEP_UP` →
> `step-up SUCCESS (bounded trust boost applied)` → `ALLOW`, Security
> Trust Score rising across the exchange). See `RESULTS.md` and
> `SESSION_LOG.md` for the full record.

## 1. Purpose

Prove that a message really came from the device it claims to be from, was not altered in transit, and is not a replay of an old message. This is deliberately built from a **Message Authentication Code (HMAC)**, not a digital signature — HMAC uses a shared secret both parties already know, which is far cheaper to compute than public-key cryptography and is exactly the primitive [10] validates formally for this class of device.

**Literature grounding:** [9], [10] (lightweight HMAC/hash/XOR-based continuous authentication, formally verified), [11] (behavioural signals feeding a trust decision alongside identity checks), [12].

### 1.1 Design Rationale — Why HMAC, Not Asymmetric Crypto

The literature on lightweight constrained-device authentication ([12], [14])
converges on symmetric-key, hash-based schemes specifically because they
avoid the computational cost of asymmetric cryptography (RSA/ECC key
operations) on devices that may not have a hardware crypto accelerator.
HMAC-SHA256 needs only a hash function, which every modern microcontroller
toolchain supports natively; it authenticates the **payload itself**, not
just the connection, so even if Module 6's transport layer were somehow
compromised or downgraded, a forged payload still fails this check. This is
**application-layer** authentication, deliberately independent of whatever
**transport-layer** security Module 6 provides — defence-in-depth, not
redundancy; see `docs/07_module6_secure_communication.md` Section on "Why
Both Module 2 AND Module 6 Encrypt/Authenticate."

### 1.2 Mutual Authentication — the Gateway Also Signs Its Decisions

Section 4 below covers device→gateway authentication. The reverse direction
is also cryptographically verified, using the same per-device secret Module
1 already provisions (no separate key-provisioning step needed): the
gateway signs every `cps/decisions/<device_id>` message with that device's
secret (`gateway.py::_sign_decision()`), and the device independently
verifies it before acting on it
(`device_simulator.py::verify_decision_signature()`, mirrored in
`firmware/main.py::verify_decision_signature()`). Verified live: a
forged/tampered/wrong-secret decision message is rejected by the device
(`!! REJECTED decision message`, the device does not act on it) while a
genuine gateway decision passes (`<< verified gateway decision: ALLOW`) —
see `SESSION_LOG.md`.

**This gap is now closed** (`RESULTS.md` Section 14 item 3): the decision
channel has its own `boot_id`/`seq`-style anti-replay, exactly as this
section originally proposed — `gateway.py` persists its own incrementing
`gateway_boot_id` (`src/data/gateway_boot_id.txt`, gitignored, same
treatment as a device's own `boot_id.txt`) and a per-device `decision_seq`
counter, both signed into every decision payload;
`firmware/main.py::check_decision_replay()` mirrors `check_boot_replay()`'s
logic (strictly-higher boot_id always wins; same boot_id needs a
strictly-higher seq). Verified byte-for-byte that the canonical string
construction matches the gateway's `json.dumps(payload, sort_keys=True)`
exactly, and that the full HMAC signature matches end to end.

A move to mTLS (once client certs are added to `coap_server.py`) or
ECC-based challenge-response for devices with a crypto accelerator
([21], [36]) both remain real, buildable future work beyond HMAC+seq for
this direction if a stronger mechanism is ever wanted — either would be a
drop-in replacement behind the same
`device_id, payload, signature -> auth_ok`-shaped interface, not a
redesign.

## 2. What HMAC Does and Does Not Prove

State this explicitly in code comments and documentation wherever authentication is discussed, because getting this wrong was flagged directly in project review:

- **HMAC proves:** the message was not altered after signing, and the sender knows the shared secret associated with `device_id`.
- **HMAC does NOT prove:** the message is new. A captured, validly-signed message can be replayed verbatim and will still pass HMAC verification. That gap is closed by the sequence number and timestamp checks in Section 4, not by HMAC itself.
- **HMAC is not a digital signature.** It provides no non-repudiation (the gateway, which also holds the secret, could itself have produced a valid HMAC) and no public verifiability by a third party. Do not describe it as a "signature" anywhere in code, comments, or documentation.

## 3. Canonical Payload and HMAC Computation

```
canonical_payload(msg: TelemetryMessage) -> bytes:
    # 1. Take all fields of TelemetryMessage EXCEPT `hmac`.
    # 2. Serialize as JSON with keys sorted alphabetically, separators=(',', ':')
    #    (no spaces), UTF-8 encoded.
    # 3. This exact byte string is what gets HMAC'd, and must be reproduced
    #    identically by: the simulator (Python), the eventual firmware
    #    (MicroPython ujson), and the gateway verifier (Python). Any divergence
    #    here is the single most likely integration bug — test it explicitly
    #    the moment real hardware exists (see 01_simulation_and_hardware_abstraction.md
    #    Section 5.2).

compute_hmac(payload_bytes: bytes, secret_key: bytes) -> str (hex):
    return hmac.new(secret_key, payload_bytes, hashlib.sha256).hexdigest()
```

## 4. Verification Procedure (Gateway Side)

```
verify_message(msg: TelemetryMessage) -> VerificationResult:

    entry = device_registry.get_device(msg.device_id)

    # Check 1 — identity known at all
    if entry is None:
        return REJECT("unknown_device_id")

    # Check 2 — revocation is a hard override, checked before HMAC
    if entry.status == "revoked":
        return REJECT("device_revoked")

    # Check 3 — HMAC, tried against current key, then previous key if in grace period
    payload = canonical_payload(msg)
    if msg.key_version == entry.key_version_current:
        expected = compute_hmac(payload, entry.secret_key_current)
    elif entry.secret_key_previous is not None and msg.key_version == entry.key_version_current - 1:
        expected = compute_hmac(payload, entry.secret_key_previous)
    else:
        return REJECT("unknown_key_version")

    if not constant_time_compare(expected, msg.hmac):
        return REJECT("hmac_mismatch")

    # Check 4 — anti-replay, boot-aware (see Section 4.1 below for the reasoning)
    if msg.boot_id > entry.last_seen_boot_id:
        pass   # new, higher boot session — accept regardless of msg.seq value,
               # then record this boot_id and treat msg.seq as the new baseline
    elif msg.boot_id == entry.last_seen_boot_id:
        if msg.seq <= entry.last_seen_seq:
            return REJECT("replay_or_stale_sequence")
    else:  # msg.boot_id < entry.last_seen_boot_id
        return REJECT("replay_of_superseded_boot_session")

    # Check 5 — anti-replay: timestamp freshness window
    if abs(gateway_clock_now() - msg.timestamp) > REPLAY_WINDOW_SECONDS:  # default 30s
        return REJECT("stale_timestamp")

    # All checks passed
    device_registry.update_last_seen(msg.device_id, msg.boot_id, msg.seq, msg.timestamp)
    return ACCEPT()
```

### 4.1 Why the Anti-Replay Check Is Boot-Aware

A device that reboots restarts its `seq` counter at 1. A naive "seq must always strictly increase, forever" rule would reject every message after a legitimate reboot, since the new session's `seq=1` is smaller than whatever the previous session last reached. `boot_id` (from `01_simulation_and_hardware_abstraction.md` Section 2.1) fixes this: a strictly higher `boot_id` always resets the trusted sequence baseline, while a *repeated or lower* `boot_id` is either checked against the existing baseline (same session) or rejected outright (an old, already-superseded session being replayed — this closes a replay variant that persisting only `seq` would miss entirely, since an attacker who captured a whole old boot session could otherwise replay it in full after a legitimate reboot moved the device onto a new session).

Use constant-time comparison for the HMAC check (`hmac.compare_digest` in Python), not `==`.

## 5. Attribution: Failed Attempts Must Not Poison the Real Device's Trust

**This is the most important correction in this file.** The first draft of this design fed every `hmac_mismatch`, every `replay_or_stale_sequence`, and every `unknown_device_id` event directly into the *claimed* device's own Security Trust Score. That is a real vulnerability: an attacker who does not know a legitimate device's secret can send any number of garbage-HMAC messages claiming to be that device's `device_id`, and if every failure lowers that device's own score, the attacker can poison a perfectly innocent device's trust without ever compromising it — a trust-poisoning / denial-of-service attack, and a genuinely different problem from actually compromising the device.

The fix is to track two separate things, and to be explicit that only one of them is allowed to touch a real device's Security Trust Score:

```
AuthenticatedBehaviourState (per REGISTERED device_id, updated ONLY by messages
that reach the end of verify_message() successfully — i.e., messages we actually
know came from that device):
    message_rate_60s
    step_up_failures_total
    seconds_since_last_authenticated_message
    → this, and only this, feeds the Security Trust Score in
      04_module3_trust_evaluation.md Section A.

IdentityTargetingRisk (per CLAIMED device_id string — tracked even for IDs that
are not registered at all — updated by every REJECTED verification attempt):
    failed_attempts_60s        (all rejection reasons pooled)
    hmac_mismatch_60s
    replay_attempts_60s
    unknown_id_attempts_60s
    → this NEVER feeds any registered device's Security Trust Score.
    → it feeds a separate, clearly-labelled dashboard/audit indicator
      (Module 7) and MAY trigger a gateway-level protective action —
      see Section 5.1 — but that action is a defence against the traffic,
      not a judgement about the real device's behaviour.
```

State the rule plainly, in code comments wherever this boundary is implemented: *a failed authentication attempt claiming device_id X is evidence about whoever sent it, not evidence about X. It must never be blended into X's own Security Trust Score.* The one case this does NOT cover — an attacker who has actually stolen device X's real secret key — is handled correctly by design already: that attacker's messages would *pass* HMAC verification (they have the real key), so their malicious behaviour shows up as authenticated-but-suspicious activity (abnormal rate, repeated step-up failures) inside `AuthenticatedBehaviourState`, which is exactly where it belongs.

### 5.1 Optional Gateway-Level Protective Response

After a failed HMAC, a claimed-ID cooldown may suppress repeated rejection logging. HMAC is checked first: an attacker-controlled claimed ID must never make the gateway skip authentic traffic. This bounds rejection-log amplification for known IDs; it is not transport-level rate limiting. Rejected messages never change the claimed device's own trust or replay state.

## 6. Every Rejection Reason and Where It Is Routed

| Rejection Reason | Attack Matrix Row | Routed To |
|---|---|---|
| `unknown_device_id` | Unknown device ID | `IdentityTargetingRisk` for the claimed ID (Section 5) — never a registered device's own score, since by definition there is no registered device here |
| `device_revoked` | — | `IdentityTargetingRisk`, plus an immediate high-priority audit log entry (Module 7) — a revoked device's key being used at all is independently significant |
| `hmac_mismatch` | Incorrect HMAC / altered payload | `IdentityTargetingRisk` for the claimed ID (Section 5) — **not** that device's Security Trust Score |
| `replay_or_stale_sequence` | Replayed valid packet | `IdentityTargetingRisk` for the claimed ID — a replay is evidence about whoever captured and resent the packet, not about the real device |
| `replay_of_superseded_boot_session` | Replayed valid packet (variant) | `IdentityTargetingRisk`, same reasoning |
| `stale_timestamp` | Replayed valid packet (variant) | `IdentityTargetingRisk` |

Only messages that reach `ACCEPT()` update `AuthenticatedBehaviourState` and therefore can ever influence a registered device's own Security Trust Score, per Section 5.

## 7. Step-Up Authentication (Challenge-Response)

This is the concrete mechanism behind the "Step-Up" outcome in Module 5's policy table — deliberately specified in detail here because the design review flagged the first draft for leaving it vague.

```
Gateway side:
    initiate_step_up(device_id):
        nonce = random_bytes(16)
        store_pending_challenge(device_id, nonce, issued_at=now(), expires_in=10s)
        mqtt_publish(f"cps/challenge/{device_id}", {"nonce": nonce.hex()})

    # On the device's NEXT authenticated message (must still pass all of Section 4's
    # checks — step-up does not bypass normal verification):
    check_step_up_response(device_id, msg: TelemetryMessage):
        pending = get_pending_challenge(device_id)
        if pending is None:
            return  # no challenge outstanding, nothing to check
        if now() > pending.expires_at:
            clear_pending_challenge(device_id)
            return STEP_UP_TIMEOUT   # feeds back into Module 5 as a failed step-up
        if msg.step_up_nonce_echo == pending.nonce.hex():
            clear_pending_challenge(device_id)
            return STEP_UP_SUCCESS
        return STEP_UP_MISMATCH        # wrong nonce echoed — treat as failure

Device side (simulation now, firmware later):
    on receiving cps/challenge/{device_id}:
        store nonce locally, include it as an extra field `step_up_nonce_echo`
        in the next outgoing telemetry message (still fully HMAC'd as normal).
```

Add `step_up_nonce_echo: string | null` as an optional field on `TelemetryMessage` (Section 2 of `01_simulation_and_hardware_abstraction.md`) — it is included in the canonical payload and therefore covered by the HMAC like every other field, so a step-up response cannot be forged without the real secret either.

## 8. Configuration Parameters

```yaml
authentication:
  replay_window_seconds: 30
  key_rotation_grace_period_messages: 500   # in simulation, measured in messages;
                                             # in hardware, measured in wall-clock hours
  step_up_challenge_timeout_seconds: 10
  identity_targeting_risk_threshold_60s: 20   # triggers the optional gateway-level
                                                # rate-limit response in Section 5.1
```

### 8.1 AS-BUILT: `replay_window_seconds` is 600, not 30 — and why that is a *deployment* accommodation, not a weakening

`config.REPLAY_WINDOW_SECONDS = 600`. The design value above is 30 s, and the
widening is deliberate, bounded, and reversible:

- **What it does not weaken.** This is the *secondary* freshness check. The
  **primary** anti-replay mechanism is the boot-aware `boot_id`/`seq` check
  (§4 Check 4, §4.1), which is entirely independent of wall-clock time and is
  unaffected by this value. A replayed packet is caught by `check_boot_replay()`
  regardless of the freshness window, because its `seq` has already been seen.
  What the window actually bounds is how far a *fresh* message's self-reported
  clock may drift from the gateway's before it is refused.
- **Why it had to widen.** The real board sits on an isolated laptop hotspot
  with **no route to an NTP server**, so `ntptime.settime()` always fails and
  its RTC is set manually. A manually-set RTC drifts by minutes; 30 s refuses
  legitimate traffic within the hour.
- **How to revert it.** Share the laptop's internet connection to the hotspot
  (enable ICS) so the board gets real NTP time, then set this back to 30.

### 8.2 The clock trap this check exposes on real hardware

`check_timestamp_freshness()` compares the device's self-reported `ts` against
the gateway's own `time.time()`. Both sides must therefore agree on **which
epoch and which timezone** `ts` is expressed in, and on MicroPython neither is
automatic:

1. **Epoch.** MicroPython's `time.time()` counts seconds from **2000-01-01**,
   not the Unix epoch. The firmware adds a fixed `946684800` s, or every message
   appears roughly 30 years stale.
2. **Timezone.** When NTP fails, the RTC holds whatever last wrote to it. Thonny
   sets the ESP32 clock on every connect with `local_rtc: True` — i.e. **local**
   time, not UTC. An uncorrected local RTC puts every message exactly one
   timezone offset into the *future*.

The second was observed live: the board measured **+19,784 s** ahead of the
gateway — precisely IST's +5:30 — and every message was rejected as
`stale_timestamp`. Note the failure signature is informative: a constant offset
that exactly equals a timezone is a clock-reference bug, whereas a slowly
growing offset would be drift and a ~30-year offset would be the epoch bug.

The as-built firmware resolves this with `RTC_LOCAL_UTC_OFFSET_SECONDS`, applied
**only when `sync_time()` reports that NTP failed**. A successful NTP sync yields
a true UTC clock and a zero offset, so a board with a working route needs no
configuration. Post-fix the measured delta is **+2.3 s to +21.3 s**, with zero
`stale_timestamp` rejections across 46 consecutive rows.

> **A rejected design:** pinning the clock with a hardcoded
> `machine.RTC().datetime(...)` constant. It works on the day it is written and
> then silently rots — drifting a day further out every day, and failing with a
> *plausible-looking* wrong time rather than an obviously wrong one, which is the
> harder failure to diagnose. An offset stays correct as long as the timezone
> does. See `RESULTS.md` §0.5b.

### 8.3 What a `stale_timestamp` rejection routes to

Per §6's table, `stale_timestamp` routes to `IdentityTargetingRisk` for the
*claimed* device — **not** to that device's own trust state. That property held
during the clock incident above and is worth noting as evidence the attribution
fix (§5) behaves correctly under a fault that is not an attack: the board was
rejected hundreds of times by its own misconfigured clock, and its Security
Trust Score was never touched. A design that penalised the claimed device would
have buried the real device's reputation for a clock bug.

## 9. Acceptance Criteria

- 100 deliberately forged messages (wrong HMAC) → 0 accepted, and none of them alter the claimed device's own `AuthenticatedBehaviourState` or Security Trust Score — only `IdentityTargetingRisk` for that claimed ID changes.
- 1 genuine message replayed verbatim → rejected with `replay_or_stale_sequence`; the replayed device's own Security Trust Score is unaffected.
- A message with an altered field but the original (now-invalid) HMAC → rejected with `hmac_mismatch`.
- A message signed with the previous key version, sent during the rotation grace period → accepted.
- The same message, sent after the grace period ends → rejected.
- A manual step-up test: gateway issues a challenge, simulated device echoes it correctly → `STEP_UP_SUCCESS`; a second test where the device ignores the challenge past the timeout → `STEP_UP_TIMEOUT`.
- **Reboot test:** run a simulated device, let it send several messages, then trigger the `"reboot"` scenario (`01_simulation_and_hardware_abstraction.md` Section 4.3). Confirm the first post-reboot message (`boot_id` incremented, `seq` reset to 1) is `ACCEPT`ed, not rejected as a replay.
- **Superseded-boot replay test:** capture a message from before a reboot, and attempt to replay it after the reboot has happened → rejected with `replay_of_superseded_boot_session`.
- **Trust-poisoning test:** send 50 `bad_hmac` messages claiming a real, registered device's ID, then send one genuine, correctly-signed message from that same device. Confirm the genuine message is still evaluated on a clean `AuthenticatedBehaviourState` (i.e., the 50 forged attempts did not lower its Security Trust Score) — only `IdentityTargetingRisk` for that device_id should reflect the attack.

Continue to `04_module3_trust_evaluation.md`.
