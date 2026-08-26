"""
Module 5, Phase 8: RL-Adaptive Access Control / Policy Decision Point.

CLAUDE.md Section 8 / implementation-docs/05_module_access_control.md
Part B: training happens offline in scripts/train_adaptive_pdp.py, which
runs the epsilon-greedy Q-learning updates against the labelled training
session and saves the resulting Q-table to config.ADAPTIVE_PDP_MODEL_PATH.
This file's `AdaptivePDP.choose_action()` only ever READS that Q-table
(with epsilon-greedy action SELECTION, which is not the same as learning
-- no Q-VALUES are ever updated here); `update()` exists only for the
training script to call.

State = (bucketed trust_score, bucketed confidence) -- synopsis Section
5.8 / Figure 4.1: "a low trust score with high confidence is a very
different situation from a low trust score the model itself is unsure
about," which is exactly what the fusion engine's new `confidence` output
(fusion_engine.py) lets this module react to, unlike the Phase 5 static
thresholds which only ever see trust_score.
Action = {ALLOW, STEP_UP, DENY}.
"""

import json
import os
import random

from config import (
    RL_TRUST_BUCKET_SIZE,
    RL_CONFIDENCE_BUCKET_SIZE,
    RL_EPSILON,
    RL_ALPHA,
    ADAPTIVE_PDP_MODEL_PATH,
)
from policy_engine import decide  # Phase 5 static policy -- used only to seed a fresh Q-table state

ACTIONS = ["ALLOW", "STEP_UP", "DENY"]


def state_key(trust_score: float, confidence: float) -> str:
    trust_bucket = int(trust_score / RL_TRUST_BUCKET_SIZE)
    confidence_bucket = int(confidence / RL_CONFIDENCE_BUCKET_SIZE)
    return f"{trust_bucket},{confidence_bucket}"


class AdaptivePDP:
    def __init__(self):
        self.q: dict[str, dict[str, float]] = {}
        self._load()

    def _load(self):
        if os.path.exists(ADAPTIVE_PDP_MODEL_PATH):
            with open(ADAPTIVE_PDP_MODEL_PATH) as f:
                self.q = json.load(f)

    def _get_q(self, trust_score: float, confidence: float) -> dict[str, float]:
        key = state_key(trust_score, confidence)
        if key not in self.q:
            seeded_action = decide(trust_score)
            self.q[key] = {a: (1.0 if a == seeded_action else 0.0) for a in ACTIONS}
        return self.q[key]

    def choose_action(self, trust_score: float, confidence: float) -> str:
        """TRAINING-PATH call: epsilon-greedy SELECTION, paired with
        update() in scripts/train_adaptive_pdp.py's training loop --
        exploration only earns its keep when it feeds back into learning.
        Use greedy_action() instead for the live gateway / evaluation,
        where no update() ever follows (CLAUDE.md Section 8's hard
        constraint: no training in the live path) -- unlike the earlier
        online-learning version of this project, where the live gateway
        DID call update() and epsilon-exploration there was justified,
        that's no longer true, so epsilon-noise at inference time is pure
        downside with no corresponding benefit."""
        q = self._get_q(trust_score, confidence)
        if random.random() < RL_EPSILON:
            return random.choice(ACTIONS)
        return max(q, key=q.get)

    def greedy_action(self, trust_score: float, confidence: float) -> str:
        """LIVE-PATH / EVALUATION call: always the best known action for
        this state, no exploration. See choose_action()'s docstring for why
        this -- not choose_action() -- is the correct method once training
        is fully offline."""
        q = self._get_q(trust_score, confidence)
        return max(q, key=q.get)

    def update(self, trust_score: float, confidence: float, action: str, reward: float) -> None:
        """OFFLINE-TRAINING-ONLY. scripts/train_adaptive_pdp.py calls this;
        the live gateway never does (CLAUDE.md Section 8's hard constraint)."""
        q = self._get_q(trust_score, confidence)
        q[action] += RL_ALPHA * (reward - q[action])

    def save(self, path: str = ADAPTIVE_PDP_MODEL_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.q, f, indent=1)

    @staticmethod
    def reward_for(action: str, label: int) -> float:
        """label: 1 = ground-truth legitimate, 0 = ground-truth suspicious.
        ALLOW/DENY scored against it directly; STEP_UP is a neutral hedge."""
        if action == "ALLOW":
            return 1.0 if label == 1 else -1.0
        if action == "DENY":
            return 1.0 if label == 0 else -1.0
        return 0.0  # STEP_UP

    def is_trained(self) -> bool:
        return os.path.exists(ADAPTIVE_PDP_MODEL_PATH)
