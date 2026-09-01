"""
Module 5: Access Control (Policy Decision Point) -- static 2x2 table.

TWO-SCORE REARCHITECTURE: decide() now reads the Security Trust Score and
Process Anomaly Score TOGETHER, but combines them only through this lookup
table -- never blended into one number. This is the only place in the
system the two scores meet before a decision is made
(docs/06_module5_access_control.md Section 1). Both scores are trust-style
(high = good) -- see trust_engine.py's module docstring for why -- so
"process high" below means "process anomaly LOW".

The RL-adaptive Phase 8 upgrade lives in adaptive_pdp.py; imports decide()
from here to seed a fresh Q-table state, so there's one static-policy
implementation, not two. Toggle which one the gateway uses via
config.USE_RL_POLICY -- both share this same
(security_trust, process_trust, process_status) -> decision shape.
"""

from config import SECURITY_THRESHOLD, PROCESS_THRESHOLD


def decide(security_trust_score: float, process_trust_score: float,
           process_status: str = "FRESH") -> str:
    """Returns one of ALLOW / STEP_UP / ALERT / BLOCK.

    process_status is a required input, not an afterthought: because
    ProcessAnomalyState.score is RETAINED EXACTLY on silence (never faded
    toward "normal" -- see trust_engine.ProcessAnomalyState), a STALE
    status with a low (= anomalous) score already carries the same
    "unresolved concern" information a fresh low score would -- no special
    branch is needed to keep treating it seriously, since the value itself
    was never allowed to drift toward looking safe. `process_status` is
    still threaded through so callers can log/flag
    STALE_HIGH_ANOMALY_UNRESOLVED distinctly (docs/06 Section 2.1), which
    gateway.py does.
    """
    security_high = security_trust_score >= SECURITY_THRESHOLD
    process_high = process_trust_score >= PROCESS_THRESHOLD

    if security_high and process_high:
        return "ALLOW"
    if security_high and not process_high:
        # Likely a REAL physical/process problem, not an attack -- pass the
        # data through and flag operations, don't silently block it. This
        # is exactly the case a single blended score would have gotten
        # wrong (a real bearing fault would have looked identical to a
        # compromised device).
        return "ALERT"
    if not security_high and process_high:
        return "STEP_UP"
    return "BLOCK"  # highest-risk combination: possibly compromised device ALSO reporting abnormal data
