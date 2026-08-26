# 04 — Next Phases (6 through 9)

> **Status: implemented, then rearchitected.** This was the original plan
> and the code sketches below (online `.fit()` calls inside the scorer,
> `RLPolicyEngine`) reflect that original, since-superseded design — the
> current code is `isolation_forest_scorer.py` (6a), `lstm_ae_scorer.py`
> (6b, renamed), `gnn_scorer.py` (6c), `fusion_engine.py` (7),
> `adaptive_pdp.AdaptivePDP` (8, replaced `policy_engine.RLPolicyEngine`),
> `dashboard.py` (9, now also renders the NIST + IEC 62443 governance
> views). CLAUDE.md Section 8's hard constraint moved all training
> offline into `scripts/train_*.py` — none of the scorers below still
> call `.fit()`/`.update()` from the live path the way this file's
> original sketches do. **Read `docs/05_phase_status.md` first** for
> what's actually running today. This file is kept purely as the
> original design reference — useful for the "why" behind each phase's
> approach, not an accurate description of current code.

Once the core loop (docs 01–03) is solid, this is the path to the full
system described in Report Sections 4.3–4.4. Each phase below is scoped to
plug into the existing code without rewriting what already works.

## Phase 6 — Add Isolation Forest, then LSTM-AE, then GNN

Start with Isolation Forest — it's the cheapest to add and needs no new
libraries (`scikit-learn` is already in `requirements.txt`).

**6a. Isolation Forest** (`src/isolation_forest_scorer.py`):
```python
from sklearn.ensemble import IsolationForest
import numpy as np

class IsolationForestScorer:
    def __init__(self):
        self.model = None
        self.history = []   # collect [value] feature vectors per device

    def observe(self, value: float):
        self.history.append([value])
        if len(self.history) >= 30 and len(self.history) % 10 == 0:
            self.model = IsolationForest(contamination=0.1).fit(self.history)

    def score(self, value: float) -> float:
        if self.model is None:
            return 0.9  # not enough history yet -- defer to the rule-based score
        raw = self.model.decision_function([[value]])[0]   # higher = more normal
        return float(np.clip((raw + 0.5), 0.0, 1.0))        # rescale to ~[0,1]
```
Keep one `IsolationForestScorer` instance per device (same pattern as
`DeviceTrustState` in `trust_engine.py`).

**6b. LSTM-Autoencoder** — needs a *sequence* of readings, not one value, so
buffer the last N values per device first (e.g. `collections.deque(maxlen=20)`)
and feed the window in. Use `torch` or `tensorflow` per `requirements.txt`
guidance in the report (Section 8.2, grounded in reference [37]).

**6c. Graph Neural Network** — this is the biggest lift. Model devices as
nodes and "communicated with the gateway in the same time window" as edges.
Start with `PyTorch Geometric`'s tutorial GCN on a toy graph before wiring it
to real telemetry — this is legitimately the hardest component, budget extra
time for it (see report Section 9, Phase 6 spans 3 weeks for this reason).

## Phase 7 — Fusion engine + SHAP (Figure 4.1 in your report)

Once you have 2+ scorers producing values in `[0,1]` per device, train a
small `LogisticRegression` or shallow `DecisionTreeClassifier` on their
outputs as features, with your adversarial-testing labels (Section 4.2 Stage
6) as the target. That's the "stacking meta-learner."

Then wrap its `.predict_proba()` call with `shap.Explainer(...)` — the `shap`
library works directly on scikit-learn models with almost no extra code.
Store the top contributing feature name as your `reason` string in
`audit_log.py`, replacing the plain-English rule-based reason.

## Phase 8 — RL-adaptive Access Control

Replace `policy_engine.decide()`. The simplest version that's still genuinely
RL (not just a lookup table) is a contextual bandit: state = trust score
bucket, action = {ALLOW, STEP_UP, DENY}, reward = +1 if the decision matched
the eventual ground truth (was this device actually malicious or not, from
your adversarial test labels), -1 otherwise. `Stable-Baselines3` is overkill
for this simple a state space — a hand-rolled epsilon-greedy bandit in ~30
lines is a perfectly legitimate, easier-to-explain-in-a-viva implementation.

## Phase 9 — Dashboard

Swap the console `print()` in `gateway.py` for a `Streamlit` app that polls
`audit_log.recent()` every second or two and renders it as a live table plus
a line chart of trust score over time per device. This is a few dozen lines
in Streamlit and is the fastest-to-build, most visually impressive part of
the whole project for a demo — save it for last, since by then you'll have
real data flowing through it.

## A note on pacing

Don't try to do Phases 6–9 in one sitting. The report's own 16-week plan
gives Phases 6–9 eight weeks combined for a reason — each phase is
independently demoable, so you always have a working system to show, even if
you stop partway through the advanced components.
