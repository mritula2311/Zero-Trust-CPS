# Module 3 — Trust Evaluation

**Status:** Core implemented (rule-based EWMA engine, `src/trust_engine.py`) + Full multi-model fusion design (extension, Report Section 4.4)
**Report grounding:** Section 4.3 Module 3, Section 4.4 (Figure 4.1); literature refs [17]–[21], [27]–[30], [33]–[37]

## Purpose

This is the module that actually decides, on an ongoing basis, *how much*
to trust a device — not as a one-time judgement, but as a continuously
updated number. Every other decision in the system (Module 5's access
decision, Module 7's audit record) is downstream of what this module
produces. Its output is a single float, `trust_score ∈ [0, 1]`, plus a
human- or machine-readable reason for that score.

## Part A — Core Implementation (Rule-Based, Shipped)

### Design Rationale

A rule-based engine is the correct **first** implementation for three
reasons that matter for both engineering and research purposes:

1. It requires zero training data, so it works from message one — there is
   no cold-start problem.
2. It's fully interpretable by construction — every score change traces to
   an explicit rule, which is valuable both for debugging and as a
   baseline to measure the ML-based extensions against (an ablation study,
   per Report Section 10.1, needs a non-ML baseline to compare against).
3. It de-risks the project timeline (Report Section 5.4) — a working trust
   engine exists before any model training is attempted.

### Data Structure

```python
@dataclass
class DeviceTrustState:
    trust_score: float = 0.8       # starts "provisionally trusted," not blindly trusted
    last_seen: float = field(default_factory=time.time)
    consecutive_auth_failures: int = 0
    message_count: int = 0
```

One `DeviceTrustState` instance is held per `device_id`, inside
`RuleBasedTrustEngine.state`, a dictionary keyed by device identity. Starting
`trust_score` at `0.8` rather than `1.0` is a deliberate choice: it reflects
that no device has yet demonstrated a track record, without treating every
new device as maximally suspicious either — this maps to Zero Trust's
"never fully trust, but don't need to fully distrust before evidence exists"
posture.

### Implementation Walkthrough

`score_message()` runs four steps, in order, for every incoming message:

**1. Time-decay.** Before looking at the current message at all, trust is
reduced based on how long it's been since the last message from this
device:

```python
elapsed = now - st.last_seen
decay = min(0.3, TRUST_DECAY_PER_SECOND * elapsed)
st.trust_score = max(0.0, st.trust_score - decay)
```

This is what makes verification *continuous* rather than event-triggered —
a device that's gone silent is drifting toward lower trust even without
sending anything, capturing the intuition that "I haven't heard from this
device in a while" is itself weak negative evidence, not a neutral fact.

**2. Authentication-driven observation.** The strongest signal available —
whether Module 2's signature check passed — sets the baseline observation
for this message:

```python
if not auth_ok:
    st.consecutive_auth_failures += 1
    penalty = 0.5 + 0.1 * min(st.consecutive_auth_failures, 3)
    observation = max(0.0, 1.0 - penalty)
else:
    st.consecutive_auth_failures = 0
    observation = 0.9
```

Note the penalty **escalates** with consecutive failures (capped at 3x) —
a single auth failure could plausibly be a transient network glitch; three
in a row looks like an active attack, and the scoring reflects that
distinction rather than treating every failure identically.

**3. Value-plausibility check** (only reached if auth passed):

```python
lo, hi = expected
if not (lo <= value <= hi):
    observation = 0.15
```

This uses `expected_range` from Module 1's registry — a concrete example
of Module 1 and Module 3 sharing data through the registry rather than
duplicating device metadata.

**4. EWMA blend.** The new observation is merged into the running score:

```python
st.trust_score = TRUST_EWMA_ALPHA * observation + (1 - TRUST_EWMA_ALPHA) * st.trust_score
```

With `TRUST_EWMA_ALPHA = 0.35`, roughly 35% of the new score comes from
this message and 65% carries forward from history. This is the mathematical
mechanism behind "sustained bad behaviour compounds, one bad message
doesn't tank you instantly" — solving for the steady-state, a device that
consistently produces `observation = 0.15` converges toward `0.15`, but it
takes several messages to get there, while a single bad message only pulls
the score part-way.

### Interface Contract

```python
def score_message(self, device_id: str, value: float, auth_ok: bool) -> tuple[float, str]:
```

| Direction | Data | From/To |
|---|---|---|
| In | `device_id`, `value`, `auth_ok` | From Module 1/2 (identity resolved, auth already checked) |
| In (implicit) | `expected_range` | From Module 1's registry |
| Out | `trust_score: float`, `reason: str` | To Module 5 (decision), Module 7 (logging) |

## Part B — Full Design: Multi-Model Fusion Engine (Extension Target)

This is the architecture from Report Figure 4.1, which is what earns the
project's novelty claim (Report Section 4.1). It does not replace the
rule-based engine above — it **adds three more scoring signals and a fusion
layer on top of it.**

### Architecture

```
Rule-Based Score ──┐
Isolation Forest ──┤
LSTM-Autoencoder ──┼──► Stacking Meta-Learner ──► Unified Trust Score ──► SHAP Layer ──► reason code
Graph Neural Net ──┘         (fusion)              + confidence
```

### The four signals and what each one catches

| Signal | Catches | Grounded in |
|---|---|---|
| Rule-based (Part A) | Known, explicit failure patterns (bad auth, out-of-range values) | Baseline |
| Isolation Forest | Point anomalies in feature space that don't match any hand-written rule | [17]–[20] |
| LSTM-Autoencoder | Temporal drift — a device slowly changing its behaviour pattern over many messages, which no single-message rule can see | [37] |
| Graph Neural Network | Relational/coordinated anomalies — multiple devices behaving unusually *together*, which no single-device model (rule, IF, or LSTM-AE) can see by construction | [27]–[30] |

### Code sketch — Isolation Forest signal

```python
from sklearn.ensemble import IsolationForest
import numpy as np

class IsolationForestScorer:
    def __init__(self):
        self.model = None
        self.history = []

    def observe(self, value: float):
        self.history.append([value])
        if len(self.history) >= 30 and len(self.history) % 10 == 0:
            self.model = IsolationForest(contamination=0.1).fit(self.history)

    def score(self, value: float) -> float:
        if self.model is None:
            return 0.9  # insufficient history -- defer to the rule-based score
        raw = self.model.decision_function([[value]])[0]
        return float(np.clip(raw + 0.5, 0.0, 1.0))
```

One instance per device, mirroring `DeviceTrustState`'s per-device pattern.
Note the explicit cold-start fallback (`return 0.9` before 30 observations)
— this is the same "don't over-penalise before there's evidence" principle
from Part A, applied to the ML signal.

### Code sketch — Fusion (stacking meta-learner)

```python
from sklearn.linear_model import LogisticRegression

class FusionEngine:
    def __init__(self):
        self.meta_model = LogisticRegression()
        self.is_trained = False

    def fit(self, X, y):
        # X: shape (n_samples, 4) -- [rule_score, if_score, lstm_ae_score, gnn_score]
        # y: 1 = legitimate, 0 = attack (from adversarial-testing labels, report Section 4.2 Stage 6)
        self.meta_model.fit(X, y)
        self.is_trained = True

    def fuse(self, rule_score, if_score, lstm_ae_score, gnn_score) -> tuple[float, float]:
        features = [[rule_score, if_score, lstm_ae_score, gnn_score]]
        if not self.is_trained:
            return float(np.mean(features)), 0.5   # unweighted average until trained
        proba = self.meta_model.predict_proba(features)[0]
        trust = float(proba[1])                     # P(legitimate)
        confidence = float(max(proba))               # how decisive the model is
        return trust, confidence
```

The meta-learner's job is specifically to **learn the relative reliability
of each signal**, rather than averaging them blindly — if, empirically, the
GNN signal turns out noisier than the LSTM-AE signal for your specific
testbed, logistic regression's learned coefficients reflect that
automatically, which a hand-tuned weighted average would not.

### Code sketch — SHAP explainability layer

```python
import shap

explainer = shap.Explainer(fusion_engine.meta_model, background_data)

def explain(features) -> str:
    shap_values = explainer([features])
    contributions = dict(zip(
        ["rule", "isolation_forest", "lstm_ae", "gnn"],
        shap_values.values[0]
    ))
    top_feature = max(contributions, key=lambda k: abs(contributions[k]))
    return f"driven primarily by {top_feature} signal (SHAP={contributions[top_feature]:.2f})"
```

This `explain()` function's output is what replaces the plain-English
`reason` string from Part A's rule-based engine — same interface contract
(`-> str`), richer content underneath.

### Interface Contract (Full Design)

| Direction | Data | From/To |
|---|---|---|
| In | `device_id`, `value`, `auth_ok`, plus device interaction graph edges | Modules 1/2, plus a graph-construction step observing which devices communicate through the gateway in the same time window |
| Out | `trust_score: float`, `confidence: float`, `reason: str` (SHAP-generated) | Module 5 (decision + confidence-aware policy), Module 7 (logging, now with a richer reason) |

The confidence value is new relative to Part A and is specifically what
lets Module 5's RL-adaptive policy (see `05_module_access_control.md`) make
better-calibrated step-up-vs-deny decisions — a low trust score with high
confidence is a very different situation from a low trust score the model
itself is unsure about.

## Failure Modes (Both Parts)

| Scenario | Part A behaviour | Part B (fusion) behaviour |
|---|---|---|
| New device, no history | Starts at 0.8, converges based on evidence | All four signals defer to their cold-start fallback; fusion output ≈ rule-based score alone until enough history accumulates |
| One signal unavailable (e.g. GNN model not yet trained) | N/A | Fusion should treat missing signals as neutral (0.5) inputs rather than crashing — implement this explicitly, it's a real edge case, not a hypothetical one |
| Conflicting signals (e.g. rule says fine, GNN says anomalous) | N/A | This is precisely what the meta-learner is trained to arbitrate — log cases where signals disagree by a large margin as a designated evaluation category (Report Section 10.1's ablation study) |

## Extension Path

See Report Section 9 (Phases 6–7) for the recommended build order: Isolation
Forest first (cheapest), then LSTM-Autoencoder, then GNN (most expensive),
then the fusion layer, then SHAP last. Each is independently testable
against the rule-based baseline before being wired into the fusion engine.
