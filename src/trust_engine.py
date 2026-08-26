"""
Module 3: Trust Evaluation  +  Module 4: Continuous Verification.

This is the RULE-BASED v1 engine (Report Section 9, Phase 4) -- still
exactly the "Rule-Based Score" box in Figure 4.1 of the report, kept
deliberately simple and dependency-free. Its rule-based check
(`rule_range_score()`) is now ALSO used as one of four input features to
fusion_engine.FusionEngine, alongside isolation_forest_scorer (6a),
lstm_ae_scorer (6b), and gnn_scorer (6c) -- all four are now trained
OFFLINE (scripts/train_*.py) and only ever run inference here; see
CLAUDE.md Section 8's "train offline, infer at the gateway" hard
constraint. gateway.py computes all four scores, hands them to
FusionEngine.combine() for one fused (observation, confidence), then
passes both into this class's score_message() -- which still owns the
EWMA + time-decay logic that makes verification "continuous" (Module 4).

CLAUDE.md Section 8 / the integration doc's interface-contract table both
call out that extending Module 3 should add "at most one new field" to the
call site rather than restructuring it -- `confidence` is that one field.
score_message() now returns (trust_score, confidence, reason) instead of
(trust_score, reason); confidence defaults to 0.5 (maximally uncertain)
on any path that doesn't have a real fusion-engine confidence to report.

Replay protection (Module 4 extension, synopsis Stage 6 adversarial
testing): `check_replay()` tracks each device's last-seen `ts` and flags a
non-increasing one as a replay, distinguishing a genuine device reboot
(ts resets toward 0) from a captured-and-resent message -- see
config.REBOOT_TS_THRESHOLD_MS for the exact rule and reasoning.
"""

import time
from dataclasses import dataclass, field

from config import (
    TRUST_EWMA_ALPHA,
    TRUST_DECAY_PER_SECOND,
    STALE_AFTER_SECONDS,
    DEVICE_REGISTRY,
    REBOOT_TS_THRESHOLD_MS,
    MIN_MESSAGE_INTERVAL_SECONDS,
)


def rule_range_score(device_id: str, reading) -> tuple[float, str]:
    """The plain rule-based check alone (Module 3 v1). `reading` is either
    a plain float (scalar devices: sensor-002, actuator-001) or a dict of
    Section-5.1 features (feature_vector devices: esp32-vib-001) -- shape
    is decided by DEVICE_REGISTRY[device_id]['kind']. For a feature vector,
    ALL five features must be within their configured range for this to
    pass; the first one out of range is named in the reason string.
    Pulled out as a standalone function (no per-device state needed) so
    gateway.py can use it both as trust_engine's own default observation
    AND as one of FusionEngine's four input features -- one implementation,
    not two copies."""
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


@dataclass
class DeviceTrustState:
    trust_score: float = 0.8       # devices start "provisionally trusted", not blindly trusted
    last_seen: float = field(default_factory=time.time)
    consecutive_auth_failures: int = 0
    message_count: int = 0
    last_ts: int | None = None     # last accepted payload.ts (ms), for replay detection
    last_arrival_wallclock: float | None = None  # gateway's own clock, for flood detection


class RuleBasedTrustEngine:
    """
    Computes a per-message trust delta from simple, explainable rules, then
    blends it into a running per-device trust score with an EWMA -- this is
    what makes verification "continuous" rather than a one-time check.
    """

    def __init__(self):
        self.state: dict[str, DeviceTrustState] = {}

    def _get_state(self, device_id: str) -> DeviceTrustState:
        if device_id not in self.state:
            self.state[device_id] = DeviceTrustState()
        return self.state[device_id]

    def check_replay(self, device_id: str, ts: int) -> bool:
        """Returns True if `ts` looks like a replayed (previously-seen or
        older) message rather than fresh telemetry or a genuine reboot.
        Call this BEFORE score_message() -- a detected replay should be
        treated at least as seriously as a failed signature regardless of
        whether the signature itself is valid (a captured, replayed
        message has a perfectly valid signature by construction)."""
        st = self._get_state(device_id)
        if st.last_ts is None:
            st.last_ts = ts
            return False
        if ts > st.last_ts:
            st.last_ts = ts
            return False
        if ts < REBOOT_TS_THRESHOLD_MS:
            # Device's own clock claims to be within the first few seconds
            # of its own uptime -- treat as a genuine reboot, not a replay.
            st.last_ts = ts
            return False
        return True  # non-increasing ts, and not a plausible reboot -> replay

    def check_flood(self, device_id: str) -> bool:
        """Returns True if this message arrived suspiciously soon after the
        last one FROM THE GATEWAY'S OWN CLOCK (not the payload's
        self-reported ts, which an attacker controls) -- IEC 62443 FR7
        "Resource Availability". Call this alongside check_replay(), before
        score_message(); like a replay, a flood has a perfectly valid
        signature by construction, so auth_ok alone can't catch it."""
        st = self._get_state(device_id)
        now = time.time()
        was_flood = (
            st.last_arrival_wallclock is not None
            and (now - st.last_arrival_wallclock) < MIN_MESSAGE_INTERVAL_SECONDS
        )
        st.last_arrival_wallclock = now
        return was_flood

    def score_message(
        self,
        device_id: str,
        value,
        auth_ok: bool,
        observation_override: float | None = None,
        observation_reason: str | None = None,
        confidence_override: float | None = None,
        is_replay: bool = False,
        is_flood: bool = False,
    ) -> tuple[float, float, str]:
        """
        Returns (new_trust_score, confidence, human_readable_reason).

        `observation_override` / `observation_reason` / `confidence_override`
        (Phase 7): when the caller (gateway.py) has already computed a
        fused observation + confidence via fusion_engine.FusionEngine.combine()
        -- itself blending this class's own rule_range_score() with the
        Phase 6 ML scorers -- pass them here instead of letting this method
        derive its own plain rule-based observation. Only used on the
        authenticated + not-a-replay + not-a-flood + would-otherwise-pass-
        range-check path; a failed signature, a detected replay, or a
        detected flood always overrides it, since all three are absolute
        signals no ML fusion should be able to talk its way past.

        `is_replay`: set by the caller from check_replay(). Treated with
        the same severity as an auth failure -- a replayed message's
        signature is valid by construction, so auth_ok alone can't catch it.

        `is_flood`: set by the caller from check_flood() (IEC 62443 FR7).
        Same treatment as is_replay -- a flooding device's individual
        messages are each perfectly validly signed, so this has to be
        checked independently of auth_ok.
        """
        st = self._get_state(device_id)
        now = time.time()

        # 1. Apply time-decay since the last message (staleness -> lower trust)
        elapsed = now - st.last_seen
        decay = min(0.3, TRUST_DECAY_PER_SECOND * elapsed)
        st.trust_score = max(0.0, st.trust_score - decay)

        reasons = []
        confidence = 0.5  # default: no fusion-engine confidence to report on this path

        # 2. Authentication + freshness signal -- a failed signature or a
        #    detected replay are the strongest possible negative signals
        #    (this is Module 2 + the replay check feeding Module 3).
        if is_replay:
            st.consecutive_auth_failures += 1
            penalty = 0.5 + 0.1 * min(st.consecutive_auth_failures, 3)
            observation = max(0.0, 1.0 - penalty)
            confidence = 0.95  # a replay is an unambiguous signal, high confidence
            reasons.append("REPLAY detected (non-increasing ts on a previously-seen device)")
        elif is_flood:
            st.consecutive_auth_failures += 1
            penalty = 0.5 + 0.1 * min(st.consecutive_auth_failures, 3)
            observation = max(0.0, 1.0 - penalty)
            confidence = 0.9
            reasons.append("FLOOD detected (messages arriving faster than the minimum interval)")
        elif not auth_ok:
            st.consecutive_auth_failures += 1
            penalty = 0.5 + 0.1 * min(st.consecutive_auth_failures, 3)
            observation = max(0.0, 1.0 - penalty)
            confidence = 0.95
            reasons.append(f"authentication FAILED ({st.consecutive_auth_failures}x in a row)")
        else:
            st.consecutive_auth_failures = 0
            reasons.append("authentication ok")

            rule_score, rule_reason = rule_range_score(device_id, value)
            reasons.append(rule_reason)
            # A physically-out-of-range value is an absolute signal, same
            # spirit as auth failure -- no ML fusion result is allowed to
            # override it (this matters most before the fusion model has
            # trained, when its fallback is a naive average that could
            # otherwise get dragged up by scorers that haven't learned
            # anything yet). Fusion can only soften/sharpen the observation
            # on the path that already passed the physical plausibility check.
            if rule_score < 0.5:
                observation = rule_score
                confidence = 0.9
            elif observation_override is not None:
                observation = observation_override
                confidence = confidence_override if confidence_override is not None else 0.5
                reasons.append(observation_reason or f"fused observation {observation_override:.2f}")
            else:
                observation = rule_score

        # 4. Blend the new observation into the running score (EWMA) --
        #    this is the "continuous" part: no single message can instantly
        #    swing trust from 1.0 to 0.0, but sustained bad behaviour will.
        st.trust_score = (
            TRUST_EWMA_ALPHA * observation + (1 - TRUST_EWMA_ALPHA) * st.trust_score
        )
        st.trust_score = round(max(0.0, min(1.0, st.trust_score)), 3)
        st.last_seen = now
        st.message_count += 1

        return st.trust_score, round(confidence, 3), "; ".join(reasons)

    def is_stale(self, device_id: str) -> bool:
        st = self.state.get(device_id)
        if st is None:
            return False
        return (time.time() - st.last_seen) > STALE_AFTER_SECONDS
