# 01 — Getting Started (Your First Session)

Goal for today: get the core loop running, watch it react to bad behaviour,
and make one small change yourself so you're confident you understand it —
not just that it "works."

## Step 1 — Run it as-is (5 minutes)

Follow the Setup + Run instructions in the main `README.md`. Confirm you see
lines like this in the gateway terminal:

```
esp32-vib-001  | rms=1.00 | auth=OK  | trust= 0.85 | conf=0.93 | ALLOW(RL) | [mqtt/secured] | authentication ok; all features within expected range; fusion: isolation_forest_score=0.56 most lowered trust (SHAP=-1.92)
```

(If `models/` isn't populated yet, you'll instead see `(fusion model not
trained yet)` — run the training scripts in `README.md`'s Setup step 4
first. Once trained, every scorer runs real inference from message one —
unlike the old online-learning version of this project, there's no
"needs 40 messages of history" warm-up anymore.)

## Step 2 — Watch it react to an attack (5 minutes)

Keep both terminals running for at least 30 seconds. You should see at least
one of these things happen (the simulator rotates through all four on a
fixed schedule):

- `esp32-vib-001` sends an in-range-but-unusual "shock" reading (a
  simulated developing mechanical fault) → trust dips → the ML scorers
  (not the plain range check, which can't see it at all) are what catch this.
- `actuator-001` sends a message with a forged signature → `auth=FAIL` →
  trust drops immediately.
- `sensor-002` sends an out-of-range value → the plain rule-based check
  catches this one directly.
- `esp32-vib-001` sends a REPLAYED message (a genuine earlier message,
  resent verbatim) → `auth=OK REPLAY` → caught by Module 4's freshness
  check even though the signature itself is perfectly valid.

If you don't see any of these within 30 seconds, wait a bit longer — timing
varies depending on when you started the simulator relative to its tick count.

**This is the core Zero-Trust behaviour your whole report is about**: no
device is ever permanently trusted, and misbehaviour is detected and acted on
automatically, without a human watching.

## Step 3 — Make one change yourself (10–15 minutes)

Pick ONE of these and do it. This is the fastest way to confirm you actually
understand the pipeline rather than just running someone else's code:

1. **Add a fourth device.** Add an entry to `DEVICE_REGISTRY` in `config.py`
   (pick a new `device_id`, secret, and `expected_range` — use `kind:
   "scalar"` like `sensor-002`/`actuator-001`, not `"feature_vector"`,
   unless you also want to teach `device_simulator.py` to generate a
   feature vector for it), then add it to the loop in `device_simulator.py`.
   Restart both processes and confirm it shows up in the gateway output.

2. **Compare the static and RL policies.** `config.USE_RL_POLICY = True` by
   default, so what you're already watching is Phase 8's offline-trained
   bandit (`adaptive_pdp.AdaptivePDP.greedy_action()` — no exploration at
   inference time, see that file's docstring for why) — `(RL)` in the
   console line is the tell. Set `USE_RL_POLICY` to `False`, restart, and
   compare: with RL on, decisions come from the trained Q-table; with RL
   off, decisions strictly follow `THRESHOLD_ALLOW`/`THRESHOLD_STEP_UP`
   every time. `scripts/evaluate_rl_policy.py` gives you the quantitative
   version of this comparison on held-out data.

3. **Add a new rule to the trust engine.** Open `trust_engine.py`'s
   `rule_range_score()` and add a check for message *frequency* — e.g., if a
   device sends more than one message per second (faster than the
   simulator's normal 2-second interval), treat that as suspicious. This is
   a real example of the kind of feature `isolation_forest_scorer.py`,
   `lstm_ae_scorer.py`, and `gnn_scorer.py` already learn automatically
   from data instead of a hand-written rule — worth doing by hand once so
   you feel the difference. Remember these three now train OFFLINE
   (`scripts/train_*.py`) — a rule change here takes effect immediately,
   but changing what THEY learn needs a re-run of the training scripts.

## Step 4 — Read the pipeline explanation

Once the above makes sense, read `docs/02_understand_the_pipeline.md` for a
line-by-line walkthrough of exactly what happens to one message from the
moment it's published to the moment it's logged.

## When you're ready to move on

- Everything through Phase 9 is implemented and offline-trained —
  `docs/05_phase_status.md` is the accurate, current status;
  `docs/04_next_phases.md` is the original planning doc it was implemented
  from (kept for reference, but read status first); `SESSION_LOG.md` (repo
  root) is the full narrative of how it got there, in order.
- Real hardware (ESP32 + MPU6050 + vibration sensor) → `docs/06_hardware_setup.md`
  — a complete beginner's guide (Thonny, wiring, flashing).
- Once you have real telemetry (simulated or real hardware), run
  `scripts/evaluate_*.py` for the report's evaluation numbers (ablation,
  latency, explainability, RL convergence, NIST governance completeness).
