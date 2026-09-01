"""
Module 5, RL-Adaptive Access Control / Policy Decision Point.

Training happens offline in scripts/train_adaptive_pdp.py, which runs the
epsilon-greedy Q-learning updates against the labelled training session and
saves the resulting Q-table to config.ADAPTIVE_PDP_MODEL_PATH. This file's
AdaptivePDP.choose_action() only ever READS that Q-table (with
epsilon-greedy action SELECTION, which is not the same as learning -- no
Q-VALUES are ever updated here); update() exists only for the training
script to call. greedy_action() (pure exploitation, no exploration at all)
is the correct method for the live gateway and every evaluate_*.py script,
since neither ever calls update() -- a policy that never updates itself
live has no live-reward-signal problem to solve in the first place; see
SESSION_LOG.md Section 7 for the bug this distinction fixed.

TWO-SCORE REARCHITECTURE: state is now
(security_trust_bucket, process_trust_bucket) instead of
(trust_bucket, confidence_bucket), and the action space grows from
{ALLOW, STEP_UP, DENY} to {ALLOW, STEP_UP, ALERT, BLOCK} to match
policy_engine.decide()'s 2x2 table.
"""

import json
import os
import random

from config import (
    RL_SECURITY_BUCKET_SIZE,
    RL_PROCESS_BUCKET_SIZE,
    RL_EPSILON,
    ADAPTIVE_PDP_MODEL_PATH,
)
from policy_engine import decide  # static 2x2 policy -- used only to seed a fresh Q-table state

ACTIONS = ["ALLOW", "STEP_UP", "ALERT", "BLOCK"]

# The four ground-truth situation classes from
# docs/10_testing_and_attack_simulation.md Section 4.1's confusion matrix,
# and which action is "correct" for each -- shared between reward_for()
# below and scripts/evaluate_rl_policy.py's confusion-matrix table, so the
# two never silently drift apart.
CORRECT_ACTION_FOR_SITUATION = {
    "normal": "ALLOW",
    "physical_fault": "ALERT",
    "security_concern": "STEP_UP",
    "combined": "BLOCK",
}


def state_key(security_trust_score: float, process_trust_score: float) -> str:
    # A score of exactly 1.0 (reachable: score_security_trust() clamps to
    # min(1.0, ...) after a step-up SUCCESS boost) would otherwise produce
    # int(1.0 / 0.1) == 10 -- one past the last valid bucket [0..9], a state
    # the trained Q-table never contains and _build_qtable_view()'s range(10)
    # never renders, silently dropping that message back to the seeded static
    # action. Clamp into range so the top bucket owns the 1.0 endpoint.
    n_security = int(round(1.0 / RL_SECURITY_BUCKET_SIZE))
    n_process = int(round(1.0 / RL_PROCESS_BUCKET_SIZE))
    security_bucket = min(int(security_trust_score / RL_SECURITY_BUCKET_SIZE), n_security - 1)
    process_bucket = min(int(process_trust_score / RL_PROCESS_BUCKET_SIZE), n_process - 1)
    return f"{security_bucket},{process_bucket}"


class AdaptivePDP:
    def __init__(self):
        self.q: dict[str, dict[str, float]] = {}
        self._visit_counts: dict[tuple[str, str], int] = {}  # (state_key, action) -> visits; training-only, not saved
        self._load()

    def _load(self):
        if not os.path.exists(ADAPTIVE_PDP_MODEL_PATH):
            return
        with open(ADAPTIVE_PDP_MODEL_PATH) as f:
            loaded = json.load(f)
        # A pre-two-score-rearchitecture Q-table used the SAME "int,int"
        # key format (trust_bucket,confidence_bucket) this file now uses
        # for (security_bucket,process_bucket) -- string-identical keys can
        # exist for entirely different states, and the old action set
        # {ALLOW, STEP_UP, DENY} is missing ALERT/BLOCK entirely. Loading
        # it as-is would silently reuse stale, wrong-shaped entries (and
        # KeyError the first time update()/greedy_action() touched a
        # collided key expecting the new 4-action set). Any state dict that
        # doesn't have exactly the current ACTIONS is treated as
        # incompatible -- discard the WHOLE table rather than partially
        # trust it, since a table mixing old- and new-semantics entries
        # under colliding keys would be silently wrong, not just incomplete.
        if loaded and any(set(qvals.keys()) != set(ACTIONS) for qvals in loaded.values()):
            print(f"[adaptive_pdp] {ADAPTIVE_PDP_MODEL_PATH} is in the pre-two-score action format "
                  f"-- discarding and starting fresh (run scripts/train_adaptive_pdp.py to rebuild it).")
            return
        self.q = loaded

    def _get_q(self, security_trust_score: float, process_trust_score: float) -> dict[str, float]:
        key = state_key(security_trust_score, process_trust_score)
        if key not in self.q:
            seeded_action = decide(security_trust_score, process_trust_score)
            self.q[key] = {a: (1.0 if a == seeded_action else 0.0) for a in ACTIONS}
        return self.q[key]

    def choose_action(self, security_trust_score: float, process_trust_score: float) -> str:
        """TRAINING-PATH call: epsilon-greedy SELECTION, paired with
        update() in scripts/train_adaptive_pdp.py's training loop --
        exploration only earns its keep when it feeds back into learning.
        Use greedy_action() for the live gateway / evaluation."""
        q = self._get_q(security_trust_score, process_trust_score)
        if random.random() < RL_EPSILON:
            return random.choice(ACTIONS)
        return max(q, key=q.get)

    def greedy_action(self, security_trust_score: float, process_trust_score: float) -> str:
        """LIVE-PATH / EVALUATION call: always the best known action for
        this state, no exploration, no update() -- see choose_action()'s
        docstring and this module's docstring for why this is the correct
        method once training is fully offline."""
        q = self._get_q(security_trust_score, process_trust_score)
        return max(q, key=q.get)

    def update(self, security_trust_score: float, process_trust_score: float,
               action: str, reward: float) -> None:
        """OFFLINE-TRAINING-ONLY. scripts/train_adaptive_pdp.py calls this;
        the live gateway never does.

        Incremental SAMPLE AVERAGE (alpha = 1/N for the N-th visit to this
        exact (state, action) pair), not the previous fixed-alpha
        exponential moving average. One state bucket holds a MIXTURE of
        ground-truth situations -- the same (security, process) bucket is
        reached by genuinely normal messages and by attack messages alike --
        so Q(s,a) is estimating an EXPECTATION over that mixture, and the
        target is stationary. A fixed alpha=0.2 EMA tracks only the last
        ~5 visits, leaving the stored value dominated by visit ORDER rather
        than by the mixture's mean: measured on the trained table, every
        action in the high-security/high-process states sat within 0.4 of
        every other (e.g. state 9,8: BLOCK -0.3 vs ALLOW -0.7), so argmax
        picked essentially at random and the live policy answered BLOCK for
        a device with security=0.91 and process=0.87 -- which the static 2x2
        table correctly answers ALLOW. A sample average converges to the
        true expected reward instead, which is what the greedy argmax needs
        to be meaningful."""
        q = self._get_q(security_trust_score, process_trust_score)
        key = (state_key(security_trust_score, process_trust_score), action)
        self._visit_counts[key] = self._visit_counts.get(key, 0) + 1
        q[action] += (reward - q[action]) / self._visit_counts[key]

    def save(self, path: str = ADAPTIVE_PDP_MODEL_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.q, f, indent=1)

    @staticmethod
    def reward_for(action: str, situation: str) -> float:
        """`situation` is one of the four ground-truth classes from
        docs/10_testing_and_attack_simulation.md Section 4.1's confusion
        matrix, derived from the training data's event_type
        (see scripts/train_adaptive_pdp.py::situation_for_event_type()):
          "normal"            -> correct action is ALLOW
          "physical_fault"    -> correct action is ALERT   (event_type: anomalous_shock,
                                                              coordinated, out_of_range --
                                                              all Process Anomaly evidence,
                                                              no security concern)
          "security_concern"  -> correct action is STEP_UP (event_type: forged_signature, replay --
                                                              pure Security Trust evidence, physical
                                                              reading itself is unaffected)
          "combined"          -> correct action is BLOCK   (event_type: stealthy_forged_values --
                                                              attack matrix row 11: a compromised
                                                              device deliberately hiding an abnormal
                                                              reading behind valid credentials)
        Exact match: +1. Anything else: -1. No partial credit, matching
        this project's existing reward_for() simplicity."""
        return 1.0 if action == CORRECT_ACTION_FOR_SITUATION[situation] else -1.0

    def is_trained(self) -> bool:
        return os.path.exists(ADAPTIVE_PDP_MODEL_PATH)
