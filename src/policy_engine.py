"""
Module 5: Access Control (Policy Decision Point) -- Phase 5, static thresholds.

The RL-adaptive Phase 8 upgrade lives in `adaptive_pdp.py` (renamed per
CLAUDE.md Section 11's file convention; imports `decide()` from here to
seed a fresh Q-table state, so there's one static-threshold
implementation, not two). Toggle which one the gateway uses via
config.USE_RL_POLICY -- both share the same `trust_score -> decision`
shape from the caller's perspective.
"""

from config import THRESHOLD_ALLOW, THRESHOLD_STEP_UP


def decide(trust_score: float) -> str:
    """Phase 5: static-threshold policy."""
    if trust_score >= THRESHOLD_ALLOW:
        return "ALLOW"
    elif trust_score >= THRESHOLD_STEP_UP:
        return "STEP_UP"   # e.g. require a fresh authentication challenge
    else:
        return "DENY"
