"""
Module 2 (Authentication extensions: boot/seq replay, step-up, Identity
Targeting Risk) + Module 3 Section A (Security Behaviour Engine) + Module 4
(Continuous Verification: per-device state store, silence handling for
both scores).

TWO-SCORE REARCHITECTURE (see SESSION_LOG.md for the session that did
this): this file used to blend authentication signal, replay/flood
signal, AND physical sensor value/ML-fusion output into one EWMA
`trust_score`. That blending is exactly what
docs/00_overview.md Section 1 calls out as the one thing this
architecture must never do -- a genuine physical fault (high process
anomaly) and a compromised device (low security trust) need to stay
distinguishable all the way to the policy step, or a real bearing failure
and a real intrusion become indistinguishable from each other. This file
now owns only the SECURITY TRUST SCORE (cyber-behaviour evidence: rate,
flood, step-up outcomes, silence) plus the bookkeeping Module 2 needs
(boot/seq replay, Identity Targeting Risk) and the per-device STORE for
both scores (Module 4). The PROCESS ANOMALY SCORE itself is still computed
entirely by fusion_engine.py's already-trained rule+IsolationForest+LSTM-
AE+GNN stack (zero retraining needed for this rearchitecture) -- this file
just holds the resulting value/staleness per device (ProcessAnomalyState)
and never computes or adjusts it.

Kept trust-style (high = good) for BOTH scores rather than switching
Process Anomaly to an anomaly-style (high = bad) scale -- a deliberate,
documented deviation from docs/04_module3_trust_evaluation.md's literal
naming, chosen specifically so the already-trained, already-ablated fusion
meta-learner's coefficients (verified positive-signed against real held-out
data, see SESSION_LOG.md Section 17) don't need to change at all. The 2x2
table in policy_engine.py is written for this scale: "process high" means
"process anomaly LOW".
"""

import time
from collections import deque
from dataclasses import dataclass, field

from config import (
    TRUST_EWMA_ALPHA,
    TRUST_DECAY_PER_SECOND,
    STALE_AFTER_SECONDS,
    PROCESS_STALE_AFTER_SECONDS,
    DEVICE_REGISTRY,
    REPLAY_WINDOW_SECONDS,
    MIN_MESSAGE_INTERVAL_SECONDS,
    STEP_UP_CHALLENGE_TIMEOUT_SECONDS,
    STEP_UP_SUCCESS_SCORE_BOOST,
    IDENTITY_TARGETING_RISK_THRESHOLD_60S,
    IDENTITY_TARGETING_COOLDOWN_SECONDS,
    KEY_ROTATION_GRACE_SECONDS,
)


# ---------------------------------------------------------------------------
# Module 1, docs/02_module1_device_identity.md Sections 2-3: key rotation /
# device revocation. The schema (`status`, `key_version`, `secret_previous`,
# `key_rotated_at`) lives on DEVICE_REGISTRY entries themselves
# (config.py) -- these are the operations that mutate it, mirroring the
# doc's register_device()/revoke_device()/rotate_key() spec. DEVICE_REGISTRY
# is a plain, mutable, shared dict (the one object every module imports),
# so mutating it here is visible everywhere immediately, no restart needed
# -- the same "config.py holds all state, no separate database" pattern
# Module 1 already uses (docs/02's AS-BUILT note).
# ---------------------------------------------------------------------------

def revoke_device(device_id: str) -> None:
    """Sets status=revoked. gateway.py's process_telemetry() checks this
    BEFORE HMAC verification and rejects unconditionally -- a hard
    override regardless of signature validity, per the doc's spec that a
    revoked device's messages are rejected 'regardless of HMAC validity'."""
    if device_id in DEVICE_REGISTRY:
        DEVICE_REGISTRY[device_id]["status"] = "revoked"


def reinstate_device(device_id: str) -> None:
    """Inverse of revoke_device() -- not in the original doc's spec, but a
    revocation with no way back isn't operationally realistic (a device
    pulled for suspected compromise that turns out clean needs a path back
    in without re-provisioning a brand new secret)."""
    if device_id in DEVICE_REGISTRY:
        DEVICE_REGISTRY[device_id]["status"] = "active"


def rotate_key(device_id: str, new_secret: str) -> None:
    """Moves the current secret to secret_previous (valid for
    KEY_ROTATION_GRACE_SECONDS, checked by verify_signature_with_rotation()
    below), installs new_secret as current, and increments key_version.
    Caller generates new_secret (e.g. secrets.token_hex(16), matching
    src/secrets_local.example.py's own generation pattern) -- this
    function only performs the swap, it does not generate key material
    itself, so the caller controls exactly where the new secret is
    distributed to the physical device out-of-band."""
    info = DEVICE_REGISTRY.get(device_id)
    if info is None:
        return
    info["secret_previous"] = info["secret"]
    info["secret"] = new_secret
    info["key_version"] = info.get("key_version", 1) + 1
    info["key_rotated_at"] = time.time()


def verify_signature_with_rotation(device_id: str, previous_check) -> bool:
    """Grace-period check: is `previous_check(secret_previous)` true, AND
    are we still within KEY_ROTATION_GRACE_SECONDS of the last rotation?
    Called by gateway.py ONLY after the current-key check has already
    failed -- this never widens acceptance beyond what the current key
    already covers, it only extends a temporary second chance for a
    device that hasn't yet picked up a just-rotated key. Once the grace
    window elapses, secret_previous is cleared so it can't be checked
    (and, incidentally, isn't leaked back out via config even if read)."""
    info = DEVICE_REGISTRY.get(device_id, {})
    previous = info.get("secret_previous")
    rotated_at = info.get("key_rotated_at")
    if previous is None or rotated_at is None:
        return False
    if time.time() - rotated_at > KEY_ROTATION_GRACE_SECONDS:
        info["secret_previous"] = None  # grace period elapsed -- stop honoring it
        return False
    return previous_check(previous)


def is_revoked(device_id: str) -> bool:
    return DEVICE_REGISTRY.get(device_id, {}).get("status") == "revoked"


def rule_range_score(device_id: str, reading) -> tuple[float, str]:
    """The plain rule-based check (Module 3 Section B.2) -- one of the four
    signals fusion_engine.py fuses into the Process Anomaly Score. `reading`
    is either a plain float (scalar devices) or a dict of Section-5.1
    features (feature_vector devices) -- shape decided by
    DEVICE_REGISTRY[device_id]['kind']. Unchanged by the two-score
    rearchitecture -- this was always a Process Anomaly signal, never a
    Security Trust one."""
    info = DEVICE_REGISTRY.get(device_id, {})
    kind = info.get("kind", "scalar")

    if kind == "feature_vector":
        ranges = info.get("expected_ranges", {})
        if not isinstance(reading, dict):
            return 0.15, "malformed feature payload (expected a dict of features)"
        for name, (lo, hi) in ranges.items():
            val = reading.get(name)
            if val is None:
                return 0.15, f"missing feature '{name}'"
            if not (lo <= val <= hi):
                return 0.15, f"{name}={val:.3f} outside expected range [{lo}, {hi}]"
        return 0.9, "all features within expected range"

    expected = info.get("expected_range")
    if expected is None:
        return 0.9, "no expected range configured"
    lo, hi = expected
    if not (lo <= reading <= hi):
        return 0.15, f"value {reading:.2f} outside expected range [{lo}, {hi}]"
    return 0.9, f"value {reading:.2f} within expected range"


# ---------------------------------------------------------------------------
# Module 2 Section 5: Identity Targeting Risk -- the attribution fix.
# ---------------------------------------------------------------------------

class IdentityTargetingRisk:
    """Tracks failed verification attempts per CLAIMED device_id (registered
    or not) -- completely separate storage from SecurityTrustState /
    AuthenticatedBehaviourState below. THIS IS THE FIX for the
    trust-poisoning vulnerability the old single-score design had: an
    attacker who does not know a device's real secret could previously
    lower THAT DEVICE'S OWN trust score just by sending garbage-HMAC
    messages claiming its device_id, because every rejected verification
    fed straight into that device's own score_message() call. A failed
    attempt claiming device_id X is evidence about whoever sent it, not
    about X -- it must never reach X's own Security Trust Score. See
    docs/03_module2_authentication.md Section 5 and gateway.py's _reject()."""

    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque] = {}
        self._cooldown_until: dict[str, float] = {}

    def _prune(self, dq: deque, now: float) -> None:
        while dq and now - dq[0] > self.window_seconds:
            dq.popleft()

    def record(self, claimed_device_id: str, reason: str) -> int:
        """Call for EVERY rejected verification attempt (unknown_device_id,
        hmac_mismatch, replay_or_stale_sequence,
        replay_of_superseded_boot_session, stale_timestamp). Returns the
        current 60s failure count for this claimed id."""
        now = time.time()
        dq = self._attempts.setdefault(claimed_device_id, deque())
        dq.append(now)
        self._prune(dq, now)
        if len(dq) >= IDENTITY_TARGETING_RISK_THRESHOLD_60S:
            self._cooldown_until[claimed_device_id] = now + IDENTITY_TARGETING_COOLDOWN_SECONDS
        return len(dq)

    def count_60s(self, claimed_device_id: str) -> int:
        dq = self._attempts.get(claimed_device_id)
        if not dq:
            return 0
        self._prune(dq, time.time())
        return len(dq)

    def is_throttled(self, claimed_device_id: str) -> bool:
        """Optional gateway-level protective response (Section 5.1): once a
        claimed id has crossed the threshold, further attempts against it
        are dropped before even reaching verification, for a cooldown
        window -- a defence against the traffic itself, never a judgement
        applied to a real device's own trust."""
        until = self._cooldown_until.get(claimed_device_id)
        return until is not None and time.time() < until


# ---------------------------------------------------------------------------
# Module 2 Section 4/4.1: boot_id + seq replay bookkeeping, and Section 7
# step-up challenge/response. Module 3 Section A: Security Trust Score.
# ---------------------------------------------------------------------------

@dataclass
class AuthenticatedBehaviourState:
    """Per REGISTERED device_id, updated ONLY by messages that pass full
    verification (HMAC + boot/seq + timestamp freshness) -- i.e. messages
    we actually know came from that device. This, and only this, feeds the
    Security Trust Score. See docs/03_module2_authentication.md Section 5."""
    last_seen_boot_id: int | None = None
    last_seen_seq: int = 0
    message_arrivals: deque = field(default_factory=deque)  # gateway wall-clock arrival times, last 60s
    step_up_failures_total: int = 0
    pending_step_up_nonce: str | None = None
    pending_step_up_issued_at: float | None = None


@dataclass
class SecurityTrustState:
    score: float = 0.8       # devices start "provisionally trusted," not blindly trusted
    last_updated_at: float = field(default_factory=time.time)


@dataclass
class ProcessAnomalyState:
    """Owned by Module 4, written to ONLY by Module 3 Section B (via
    update_process_anomaly() below) in response to an actual new reading.
    `score` is trust-style (high = normal/legitimate) and is RETAINED
    EXACTLY on silence -- never decayed, never capped toward "normal" --
    only `status` flips to STALE. This is the corrected silence-handling
    logic from docs/05_module4_continuous_verification.md Section 2.2: a
    device reporting severe anomaly and then going silent means the
    physical state is UNKNOWN, not "becoming normal," and quietly fading
    a high anomaly score back down purely because the device stopped
    reporting would be actively dangerous in any system driving a real
    operational response."""
    score: float = 0.8
    status: str = "FRESH"     # FRESH | STALE
    last_updated_at: float = field(default_factory=time.time)


class RuleBasedTrustEngine:
    """Owns: boot/seq replay checks, flood checks, step-up challenge state,
    the Security Trust Score, and the per-device Process Anomaly state
    store. Does NOT compute the Process Anomaly Score itself -- that's
    fusion_engine.py's job; this class only stores what it's told via
    update_process_anomaly()."""

    def __init__(self):
        self.auth_state: dict[str, AuthenticatedBehaviourState] = {}
        self.security_state: dict[str, SecurityTrustState] = {}
        self.process_state: dict[str, ProcessAnomalyState] = {}

    def _get_auth_state(self, device_id: str) -> AuthenticatedBehaviourState:
        if device_id not in self.auth_state:
            self.auth_state[device_id] = AuthenticatedBehaviourState()
        return self.auth_state[device_id]

    def _get_security_state(self, device_id: str) -> SecurityTrustState:
        if device_id not in self.security_state:
            self.security_state[device_id] = SecurityTrustState()
        return self.security_state[device_id]

    def _get_process_state(self, device_id: str) -> ProcessAnomalyState:
        if device_id not in self.process_state:
            self.process_state[device_id] = ProcessAnomalyState()
        return self.process_state[device_id]

    # -- Module 2 Section 4: boot-aware anti-replay ------------------------

    def check_boot_replay(self, device_id: str, boot_id: int, seq: int) -> tuple[bool, str]:
        """Returns (is_replay, reason). A strictly higher boot_id always
        starts a fresh, trusted seq baseline regardless of the incoming
        seq's value (a genuine reboot); a repeated boot_id must still have
        a strictly increasing seq; a LOWER boot_id is unconditionally
        rejected -- that session has already been superseded by a higher
        one, which is what closes the old ts-heuristic's blind spot: an
        attacker who captured a whole pre-reboot session cannot replay any
        message from it once a legitimate reboot has moved the device onto
        a new boot_id, even a message from very early in that old session."""
        st = self._get_auth_state(device_id)
        if st.last_seen_boot_id is None:
            st.last_seen_boot_id = boot_id
            st.last_seen_seq = seq
            return False, "first_message"
        if boot_id > st.last_seen_boot_id:
            st.last_seen_boot_id = boot_id
            st.last_seen_seq = seq
            return False, "new_boot_session"
        if boot_id == st.last_seen_boot_id:
            if seq <= st.last_seen_seq:
                return True, "replay_or_stale_sequence"
            st.last_seen_seq = seq
            return False, "ok"
        return True, "replay_of_superseded_boot_session"

    def check_timestamp_freshness(self, ts_ms: int) -> bool:
        """Secondary check (Module 2 Section 4 Check 5), independent of the
        boot/seq check above: is this message's self-reported timestamp
        within REPLAY_WINDOW_SECONDS of the gateway's own clock? Returns
        True if fresh."""
        now_ms = time.time() * 1000
        return abs(now_ms - ts_ms) <= REPLAY_WINDOW_SECONDS * 1000

    def check_flood(self, device_id: str) -> bool:
        """Returns True if this message arrived suspiciously soon after the
        last one, measured against the GATEWAY's own wall clock (not the
        payload's self-reported ts, which an attacker controls) -- IEC
        62443 FR7. Unlike the old design, a flood no longer blocks the
        message from reaching the Process Anomaly Engine (a flooding-but-
        genuinely-authenticated device is still reporting real sensor data)
        -- it only lowers the Security Trust Score, via score_security_trust()."""
        st = self._get_auth_state(device_id)
        now = time.time()
        was_flood = bool(st.message_arrivals) and (now - st.message_arrivals[-1]) < MIN_MESSAGE_INTERVAL_SECONDS
        st.message_arrivals.append(now)
        while st.message_arrivals and now - st.message_arrivals[0] > 60.0:
            st.message_arrivals.popleft()
        return was_flood

    # -- Module 2 Section 7: step-up challenge/response ---------------------

    def initiate_step_up(self, device_id: str) -> str:
        """Generates and stores a pending challenge nonce for this device,
        to be published to cps/challenge/{device_id} by gateway.py. Returns
        the nonce (hex string)."""
        import os
        nonce = os.urandom(16).hex()
        st = self._get_auth_state(device_id)
        st.pending_step_up_nonce = nonce
        st.pending_step_up_issued_at = time.time()
        return nonce

    def has_pending_step_up(self, device_id: str) -> bool:
        """gateway.py checks this before calling initiate_step_up() again --
        check_step_up_response() returns None for BOTH "no challenge was
        ever issued" and "a challenge is outstanding but this message
        didn't answer it yet" (see that method's docstring), so gateway.py
        needs this separate check to avoid re-issuing a fresh nonce (moving
        the target) on every message while genuinely still waiting for the
        first one's answer."""
        st = self.auth_state.get(device_id)
        return st is not None and st.pending_step_up_nonce is not None

    def check_step_up_response(self, device_id: str, echoed_nonce: str | None) -> str | None:
        """Call on every authenticated message. Returns None if no
        challenge is outstanding, "SUCCESS" / "MISMATCH" / "TIMEOUT"
        otherwise.

        `echoed_nonce is None` (the message carries no
        `step_up_nonce_echo` field at all) is treated as "hasn't answered
        yet", NOT a mismatch -- the challenge is published async over MQTT
        (Module 2 Section 7), so the device may not have received it before
        building its very next scheduled message, especially at this
        project's ~2s publish cadence. Only a message that actively echoes
        a WRONG nonce value counts as MISMATCH. Found live (not just
        theorized): the first version of this method treated "no echo yet"
        as an immediate, terminal MISMATCH and never cleared the pending
        challenge on that path -- every subsequent message from the device
        then re-compared against the same stale pending nonce and got
        MISMATCH again, escalating to BLOCK message after message until the
        10s timeout finally fired, instead of the intended single
        pass/fail evaluated once. Clears the pending challenge in every
        TERMINAL case (SUCCESS, MISMATCH, TIMEOUT) -- "still waiting" is
        the only non-terminal outcome, and is checked again on the next
        message."""
        st = self._get_auth_state(device_id)
        if st.pending_step_up_nonce is None:
            return None
        if time.time() - st.pending_step_up_issued_at > STEP_UP_CHALLENGE_TIMEOUT_SECONDS:
            st.pending_step_up_nonce = None
            st.pending_step_up_issued_at = None
            return "TIMEOUT"
        if echoed_nonce is None:
            return None  # hasn't answered yet -- not a failure, keep waiting until the timeout
        if echoed_nonce == st.pending_step_up_nonce:
            st.pending_step_up_nonce = None
            st.pending_step_up_issued_at = None
            return "SUCCESS"
        st.pending_step_up_nonce = None
        st.pending_step_up_issued_at = None
        return "MISMATCH"

    # -- Module 3 Section A: Security Trust Score ----------------------------

    def score_security_trust(self, device_id: str, is_flood: bool,
                              step_up_result: str | None = None) -> tuple[float, str]:
        """Recomputed on EVERY authenticated (accepted) message -- never on
        a rejected one (see gateway.py's _reject() path / IdentityTargetingRisk
        above). Inputs are cyber-behaviour evidence ONLY: rate/flood and
        step-up outcomes. Never physical sensor values, never auth-failure
        counts (those belong to IdentityTargetingRisk, tracked on the
        CLAIMED id, not this registered device's own state)."""
        st = self._get_security_state(device_id)
        auth_st = self._get_auth_state(device_id)
        now = time.time()

        elapsed = now - st.last_updated_at
        decay = min(0.3, TRUST_DECAY_PER_SECOND * elapsed)
        st.score = max(0.0, st.score - decay)

        reasons = []
        if step_up_result == "SUCCESS":
            # Bounded boost applied directly to the decayed score, not
            # blended in via the EWMA below (a single successful step-up
            # shouldn't be diluted by 65% of whatever the score was before) --
            # then treated as the observation too, so the EWMA blend just
            # confirms it rather than pulling it back down.
            st.score = min(1.0, st.score + STEP_UP_SUCCESS_SCORE_BOOST)
            observation = st.score
            reasons.append("step-up SUCCESS (bounded trust boost applied)")
        elif step_up_result in ("TIMEOUT", "MISMATCH"):
            auth_st.step_up_failures_total += 1
            observation = max(0.0, 0.5 - 0.15 * min(auth_st.step_up_failures_total, 3))
            reasons.append(f"step-up {step_up_result} ({auth_st.step_up_failures_total}x total)")
        elif is_flood:
            observation = 0.2
            reasons.append("FLOOD detected (messages arriving faster than the minimum interval)")
        else:
            observation = 0.95
            reasons.append("authenticated, normal rate")

        st.score = TRUST_EWMA_ALPHA * observation + (1 - TRUST_EWMA_ALPHA) * st.score
        st.score = round(max(0.0, min(1.0, st.score)), 3)
        st.last_updated_at = now
        return st.score, "; ".join(reasons)

    def get_security_trust(self, device_id: str) -> float:
        """Read-only peek (e.g. for a dashboard), applying decay-since-last-
        update without mutating state, matching the semantics
        score_security_trust() itself uses."""
        st = self.security_state.get(device_id)
        if st is None:
            return 0.8
        elapsed = time.time() - st.last_updated_at
        decay = min(0.3, TRUST_DECAY_PER_SECOND * elapsed)
        return round(max(0.0, st.score - decay), 3)

    # -- Module 4: Process Anomaly state store -------------------------------

    def update_process_anomaly(self, device_id: str, process_trust_value: float) -> None:
        """Called once per authenticated message with the fresh fusion
        output. Module 3 never caches this -- it's recomputed from scratch
        every message by fusion_engine.combine() -- this just stores the
        latest value + marks it FRESH."""
        st = self._get_process_state(device_id)
        st.score = process_trust_value
        st.status = "FRESH"
        st.last_updated_at = time.time()

    def get_process_anomaly(self, device_id: str) -> tuple[float, str]:
        """Lazily evaluates staleness at read-time (checked here, and again
        right before every policy decision) rather than a live-ticking
        background thread -- a deliberate simplification for this
        single-threaded gateway: the score is retained exactly either way,
        only the STATUS is time-dependent, and it only needs to be correct
        at the moments it's actually read (dashboard render, decide()
        call), not continuously between them."""
        st = self._get_process_state(device_id)
        if st.status == "FRESH" and time.time() - st.last_updated_at > PROCESS_STALE_AFTER_SECONDS:
            st.status = "STALE"
        return st.score, st.status

    def is_stale(self, device_id: str) -> bool:
        st = self.auth_state.get(device_id)
        if st is None:
            return False
        if not st.message_arrivals:
            return False
        return (time.time() - st.message_arrivals[-1]) > STALE_AFTER_SECONDS
