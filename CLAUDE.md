# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. Project-Specific Invariants (Zero-Trust CPS)

The sections above are general. These are specific to this repository, and each
one has already been violated once and cost real debugging time. Read
`ZERO_TRUST_CPS_KB.md` for the full picture; this is the short list of things
not to "fix".

### Never blend the two scores
Security Trust and Process Anomaly are computed from disjoint evidence and meet
**only** in the 2×2 policy lookup. Averaging them makes "forged papers, normal
cargo" indistinguishable from "valid papers, machine shaking" — situations that
demand opposite responses. There is a measured check that the separation holds:
`high_rate` must move only the Security axis, `anomalous_shock`/`coordinated`
only the Process axis.

### Never train on the live path
`scripts/train_*.py` produce artifacts; `gateway.py` only ever runs inference.
No `.fit()`, no `update()`, on the live path. An online-learning PDP is an
attack surface — anyone who can generate traffic can move the model. The
training scripts have a strict dependency order (IF → LSTM-AE → GNN → fusion →
RL); each replays through the previous models, so the order is not optional.

### A rejected message must never touch the claimed device's state
Failed authentication updates `IdentityTargetingRisk` for the *claimed* ID only.
Penalising the claimed device is a trust-poisoning DoS that needs no secret.
This is load-bearing beyond attacks: during a clock misconfiguration the real
board was rejected hundreds of times and its trust score was correctly untouched.

### `feature_engineering.py` is a reference implementation, not a helper
The firmware computes the same five features on-device, and the models train
against *this* file. Changing a formula without re-verifying the firmware
against it creates a train/serve skew that **no offline evaluation can detect**
— it exists only on real telemetry. Verify by differential test over randomised
windows, not by reading the code.

### Evaluate at the deployed threshold
`PROCESS_THRESHOLD` is 0.6; `evaluate_ablation.py` thresholds at 0.5. A defect
that made a signal incapable of scoring above 0.621 moved that script's headline
accuracy by 0.003 while making the system reject a healthy physical board. If
the live system decides at 0.6, a metric computed at 0.5 is not evidence about
the live system. Prefer per-class score *distributions* over aggregate accuracy.

### A number going up is not the same as the model improving
When a fix moves a metric, re-run the case that motivated it **and** the
opposite case. A GNN fix that raised isolated-device scores from 0.020 to 0.929
also made the model saturate to 1.000 on a genuinely shaken board — masking a
real anomaly. The metric improved; the model got worse.

### Report what you measured, including when it fails
Where this system underperforms — `stealthy_forged_values` recall, Level-2
explainability at 39% against a 70% target — the number stays in the figures
with its explanation. Do not swap a metric for one the system happens to pass.
If a validation check cannot fail, it is not a check: state its falsifier and
inject it (`docs/10` §7.1).

### Secrets never enter a commit
`src/secrets_local.py` is gitignored. `firmware/main.py` **is** tracked and its
working copy holds real WiFi/HMAC/MQTT credentials — the committed version must
keep placeholders. It therefore shows as permanently modified locally, and that
is the intended steady state, not an uncommitted change. Check `git diff
--cached` for credentials before every push.

### Verify the surface a user actually touches
Endpoint checks verify an API, not the page consuming it. A dashboard fix was
confirmed correct by `curl` while the page rendered nothing, because the same
edit had introduced a JavaScript `SyntaxError`. Use `node --check` on the
extracted script, then load the real page.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.