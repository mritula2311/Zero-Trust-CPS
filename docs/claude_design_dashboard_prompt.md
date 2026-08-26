# Claude Design Prompt — Zero-Trust CPS Command Center Dashboard

Copy everything in the box below into Claude Design.

---

Design a **security operations dashboard** called "Zero-Trust CPS Command Center" for monitoring a live industrial IoT Zero-Trust pipeline. This is a real, working backend (Python + MQTT + SQLite + PyTorch/scikit-learn ML models) — design the UI to visualize its actual data model below with realistic sample data, not a generic placeholder dashboard.

## System context (what this dashboard monitors)

Two physical CPS devices — `vibration-001` (vibration sensor) and `mpu6050-001` (accelerometer/gyro) — stream signed telemetry every ~2 seconds to a gateway. The gateway: verifies each device's HMAC signature, runs the reading through 3 independent ML anomaly scorers plus a rule-based check, fuses all 4 into one score via a stacking meta-learner explained with SHAP, blends that into a continuously-decaying trust score (EWMA), and an access-control engine (either fixed thresholds or a self-learning RL bandit) issues one of three decisions: **ALLOW / STEP_UP / DENY**. Every step is logged.

## Data model (design around these exact fields)

Each event row has: `timestamp`, `device_id`, `auth_ok` (bool), `trust_score` (0–1), `decision` (ALLOW/STEP_UP/DENY), `reason` (text, often a SHAP explanation like `"fusion: isolation_forest_score=0.60 most lowered trust (SHAP=-0.14)"`), `anomaly_score` (Isolation Forest, 0–1), `lstm_score` (LSTM-Autoencoder, 0–1), `gnn_score` (GNN, 0–1), `fused_score` (fusion engine output, 0–1), `policy_source` ("RL" or "STATIC").

Each scorer has a "not trained yet" state (returns a neutral ~0.9 default) before it accumulates ~40 messages of history, then transitions to real scoring — the UI should be able to represent both states.

## Required sections — every one of these must be present and clearly visible

1. **Top status bar**: system name/logo mark, live pulse indicator (gateway connected), MQTT broker status, a small badge showing "TLS: not yet enabled" as an honest known-limitation flag, and current policy engine mode (RL vs STATIC) as a toggle-styled indicator.

2. **Device status cards** (one per device, side by side): device ID, a large circular gauge/ring showing live trust score (0–1, color-graded green→amber→red), a decision badge (ALLOW=green / STEP_UP=amber / DENY=red, pill-shaped), an auth status icon (padlock, solid=OK, cracked/red=FAIL), last-seen timestamp, and a "stale" warning state for when a device goes quiet.

3. **Trust score over time** — a multi-line live time-series chart, one line per device, with horizontal reference lines at the ALLOW (0.70) and STEP_UP (0.40) thresholds, shaded background bands for the three decision zones, and small markers/annotations on the timeline where an auth failure or anomaly injection occurred.

4. **Scorer breakdown panel** (per selected device) — the 4 individual inputs feeding the fusion engine as a grouped bar chart or radar/spider chart: Rule-Based, Isolation Forest, LSTM-Autoencoder, GNN, plus the Fused output as a distinct highlighted bar. Show a "training..." state (e.g. dimmed/striped) for any scorer still under its history threshold.

5. **SHAP explainability panel** — the fusion engine's current top contributing feature for the selected device, as a horizontal diverging bar (feature name, SHAP value, color = raised trust vs lowered trust) plus a one-line plain-English sentence underneath.

6. **Policy engine panel** — a visual toggle between STATIC thresholds and the RL bandit. When RL is active, show a small heatmap/table of trust-score buckets (0.0–1.0 in steps of 0.1) × actions (ALLOW/STEP_UP/DENY) representing learned Q-values, so a viewer can see the bandit's current "policy" at a glance.

7. **Live event log** — a dense, scrollable, monospace-leaning table of recent decisions: time, device, auth, trust, decision, policy source, reason. Row background tinted by decision severity (subtle red tint for DENY/auth-fail rows, amber for STEP_UP, neutral for ALLOW).

8. **Alert feed** — a narrower side panel styled like a SOC/NOC alert stream: chronological cards for notable events only (auth failures, a device crossing into STEP_UP/DENY, a scorer transitioning from "training" to "trained"), each with a severity-colored left border and relative timestamp ("12s ago").

9. **Pipeline architecture strip** (small, bottom or collapsible) — a horizontal flow diagram: Device → Auth → [Rule + Isolation Forest + LSTM-AE + GNN] → Fusion Engine (SHAP) → EWMA Trust → Policy Engine (RL/Static) → Decision → Audit Log. Purely illustrative, but should visually echo which stage is "live."

## Visual style

Dark, high-contrast **mission-control / SOC aesthetic** — this is a security tool, not a consumer app. Deep charcoal/navy background (not pure black), restrained neon accent palette: cyan or teal for "normal/trusted," amber for caution, red for danger — used sparingly as signal, not decoration. Clean geometric sans-serif for UI chrome; a monospace font for data values, timestamps, and the event log to reinforce the "telemetry" feel. Subtle glow/soft-shadow on active/live elements (e.g. a gentle pulsing ring on the live status indicator) but nothing gratuitously animated. Generous spacing and clear visual hierarchy despite high information density — this should feel calm and legible at a glance, like a NOC wall display, not cluttered. Fully responsive grid layout.

## Notes

- Populate every chart/table with realistic sample data matching the field names and ranges above (trust scores clustering 0.7–0.95 for normal operation, occasional dips into STEP_UP/DENY territory, one or two visible "training..." scorer states).
- Both light and dark mode aren't required — commit fully to the dark SOC theme.
- This is a design/mockup pass; it does not need to be wired to a live backend.

---

