# Module 5 — Access Control (Policy Decision Point)

**Status:** Core implemented (static threshold, `src/policy_engine.py`) + RL-adaptive design (extension, Report Section 4.3/4.4)
**Report grounding:** Section 4.3 Module 5; literature refs [2], [3], [9], [31], [32]

## Purpose

This is the module where trust becomes *consequence*. Every upstream module
— identity, authentication, trust scoring, continuous verification — exists
to feed this one decision: should this device's message/command actually be
acted on right now? Module 5 converts a continuous number (trust score)
into a discrete, enforceable action.

## Part A — Core Implementation (Static Threshold, Shipped)

### Design Rationale

A static-threshold policy is the correct starting point for the same reason
the rule-based trust engine is: it's immediately testable, fully
explainable ("trust was 0.35, threshold is 0.40, hence DENY" requires no
further justification), and gives you a working baseline to measure any
adaptive policy against later.

### Implementation

```python
# src/policy_engine.py
def decide(trust_score: float) -> str:
    if trust_score >= THRESHOLD_ALLOW:
        return "ALLOW"
    elif trust_score >= THRESHOLD_STEP_UP:
        return "STEP_UP"
    else:
        return "DENY"
```

With `THRESHOLD_ALLOW = 0.70` and `THRESHOLD_STEP_UP = 0.40`, the score
range is partitioned into three enforcement zones. `STEP_UP` is
deliberately a distinct outcome from `DENY` — a device in the "uncertain"
middle zone isn't necessarily malicious, it may just not have enough
positive history yet (a new device, per Module 3, starts at 0.8 and can
dip into this band from a single early anomaly). `STEP_UP` represents
asking for stronger proof (e.g. a fresh authentication challenge) rather
than outright rejection — this graduated response is itself a design
choice grounded in the Zero Trust literature's emphasis on proportionate,
not binary, enforcement [2], [3].

### Interface Contract

```python
def decide(trust_score: float) -> str:   # returns "ALLOW" | "STEP_UP" | "DENY"
```

| Direction | Data | From/To |
|---|---|---|
| In | `trust_score: float` | From Module 3 |
| Out | `decision: str` | To Module 6 (published on the decisions topic), Module 7 (logged) |

Note this function's signature is deliberately minimal — it is the single
narrowest interface in the whole system. This is intentional: it means the
static-threshold implementation can be swapped for the RL-adaptive version
below by changing this one function's internals, without touching
`gateway.py`, `trust_engine.py`, or `audit_log.py` at all.

## Part B — Full Design: RL-Adaptive Policy Decision Point (Extension Target)

### Design Rationale

Static thresholds have one real weakness: they're a guess, hand-tuned once,
that never adapts to how the tuning actually performs in practice. If
`THRESHOLD_STEP_UP = 0.40` turns out to generate far more false step-ups
than necessary (annoying legitimate devices) or lets through attacks that a
slightly higher threshold would catch, a static policy has no mechanism to
notice or correct that. References [31] (SecureChain-ZT) and [32]
(ZT-IoTrust) both demonstrate that formulating this as a reinforcement
learning problem — where the system observes the *outcome* of its past
decisions and adjusts — closes that gap.

### MDP Formulation

| RL element | Definition in this system |
|---|---|
| **State** | `(trust_score_bucket, confidence, device_type, recent_decision_history)` — a discretised representation of the current situation |
| **Action** | One of `{ALLOW, STEP_UP, DENY}` |
| **Reward** | `+1` if the action matched ground truth (the device's actual legitimacy, known during adversarial testing per Report Section 4.2 Stage 6); `-1` if it didn't; a smaller penalty (e.g. `-0.2`) for unnecessary `STEP_UP` on a legitimate device, reflecting that friction has a cost even when not strictly wrong |

### Code Sketch — Epsilon-Greedy Contextual Bandit

A full Markov Decision Process with state transitions is more than this
problem needs — access decisions here don't meaningfully depend on a
sequence of prior *states* in a way that requires modelling transitions,
only on the current trust signal and a short recent-history context. A
contextual bandit is the right-sized tool, and is considerably easier to
explain and defend in a viva than a deep RL setup:

```python
import random
from collections import defaultdict

class AdaptivePDP:
    def __init__(self, epsilon=0.1, learning_rate=0.1):
        self.epsilon = epsilon
        self.lr = learning_rate
        self.actions = ["ALLOW", "STEP_UP", "DENY"]
        # Q-table: state (bucketed trust score) -> action -> estimated value
        self.q_table = defaultdict(lambda: {a: 0.0 for a in self.actions})

    def _bucket(self, trust_score: float) -> str:
        if trust_score >= 0.7: return "high"
        if trust_score >= 0.4: return "mid"
        return "low"

    def decide(self, trust_score: float) -> str:
        state = self._bucket(trust_score)
        if random.random() < self.epsilon:
            return random.choice(self.actions)          # explore
        return max(self.q_table[state], key=self.q_table[state].get)  # exploit

    def update(self, trust_score: float, action: str, reward: float):
        state = self._bucket(trust_score)
        old_value = self.q_table[state][action]
        self.q_table[state][action] = old_value + self.lr * (reward - old_value)
```

Note the `decide()` method's signature — `trust_score: float -> str` — is
**identical** to Part A's `decide()` function. This is the payoff of
keeping Part A's interface narrow: swapping to this class is a one-line
change at the call site in `gateway.py`.

### How the Reward Signal Reaches the Policy

During Report Section 4.2 Stage 6 (adversarial evaluation), you know ground
truth — which messages were legitimate and which were injected attacks.
After each decision, compute and apply the reward:

```python
decision = adaptive_pdp.decide(trust_score)
# ... later, once ground truth for this message is known (offline, during
# labelled adversarial testing) ...
correct = (decision == "ALLOW" and was_legitimate) or (decision in ("DENY", "STEP_UP") and not was_legitimate)
reward = 1.0 if correct else -1.0
adaptive_pdp.update(trust_score, decision, reward)
```

In a live deployment without ground-truth labels, the reward signal instead
typically comes from *downstream* evidence — e.g., a device that was
`STEP_UP`'d and then passed re-authentication is retroactively evidence the
original decision was reasonably cautious rather than wrong; one that never
completes step-up look more like it deserved `DENY`. Designing this
feedback loop precisely is one of the genuinely open questions your
research can contribute an answer to — don't treat it as a solved detail.

### Interface Contract (Full Design)

| Direction | Data | From/To |
|---|---|---|
| In | `trust_score`, `confidence` (from Module 3's fusion engine, Part B) | Module 3 |
| Out | `decision: str` | Module 6, Module 7 (unchanged from Part A) |
| Internal (training-time only) | `reward` signal | From adversarial-testing ground truth or downstream outcome evidence |

## Failure Modes

| Scenario | Part A behaviour | Part B (RL) behaviour |
|---|---|---|
| Trust score exactly at a threshold boundary | Deterministic, always the same decision | Depends on the learned Q-values for that bucket — may vary, which is a feature (adapting) but should be logged distinctly for evaluation |
| Early in training, before the Q-table has meaningful values | N/A | All-zero Q-values mean actions are effectively random within the `epsilon` exploration rate — expect noisy behaviour until enough (state, action, reward) triples have been observed; don't evaluate the RL policy's accuracy until it's had a genuine training period |
| Reward signal is noisy or delayed | N/A | Q-values converge more slowly; this is a real risk worth explicitly measuring (Report Section 10.1, "RL policy convergence" metric) rather than assuming it works |

## Extension Path

1. Ship Part A first, collect a labelled adversarial-testing dataset (you
   need this regardless, for the fusion engine's meta-learner — see Module
   3, Part B).
2. Implement Part B's bandit, train it offline against that same labelled
   dataset (consistent with the "train offline, infer at runtime" split
   described in Report Section 5.2).
3. Compare Part B's accuracy against Part A's static thresholds on a held-
   out test split — this comparison *is* your evidence for whether the RL
   upgrade earned its added complexity, and should be reported explicitly
   rather than assumed.
