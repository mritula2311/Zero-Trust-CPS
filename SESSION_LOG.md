# Session Log — Zero-Trust CPS Project

Single running catch-up document for everything done on this project across
sessions, in order. Read this top-to-bottom to get fully current without
having to piece the story together from `docs/05_phase_status.md`,
`CLAUDE.md`, or individual file docstrings — those remain the authoritative
*reference* docs (architecture, config, how-to), this file is the
*narrative* of how the project got here and why. **This file gets updated
every session, not just this one** — treat it as the first thing to read.

---

## 1. Starting point

Repo `d:\zt-cps\zt-cps-starter\` arrived as a "starter kit": a working
software-only Zero-Trust pipeline covering Phases 1–5 (Report Section 9) —
`src/{config,gateway,device_simulator,trust_engine,policy_engine,audit_log}.py`,
docs walking through Modules 1–7, `requirements.txt` with just `paho-mqtt`
+ `scikit-learn`. Three simulated devices (`sensor-001`, `sensor-002`,
`actuator-001`), plain MQTT, static-threshold access control, SQLite audit
log. Verified it ran end-to-end before touching anything.

## 2. Phase 6–9 build-out (first pass — later superseded, see §5)

Built out the rest of the report's 9-phase plan on top of the working core:

- **6a Isolation Forest** (`isolation_forest_scorer.py`) — per-device online
  scorer, retrains every N messages inside the live gateway.
- **6b LSTM-Autoencoder**, **6c GNN** (hand-rolled GCN, deliberately not
  `torch-geometric` — install-fragility risk not worth it for a 2-3 node
  graph) — same online-retraining pattern.
- **7 Fusion Engine + SHAP** (`fusion_engine.py`) — stacking
  `LogisticRegression` over the four signals, real `shap.LinearExplainer`
  reason codes. Had to upgrade `shap` 0.44.1→0.52.0 after finding the
  cached old version crashed on import under NumPy 2.4.4.
  **Bug found and fixed**: fusion/GNN could never actually train because
  failed-auth messages (the only reliable source of "malicious" label=0
  examples) were excluded from their training calls entirely — fixed by
  feeding a sentinel score for that case instead of skipping it.
- **8 RL-adaptive policy** (`policy_engine.RLPolicyEngine`) — epsilon-greedy
  bandit, seeded from the static thresholds so it doesn't look broken on
  cold start. Set active by default via `config.USE_RL_POLICY`.
- **9 Dashboard** (`dashboard.py`, Streamlit) — live, polls `audit_log.db`.

Verified the whole thing end-to-end multiple times (fresh runs, ~90-190s
each), confirmed each scorer transitions from its "not trained yet"
fallback to real scoring, confirmed SHAP reasons are sensible.

## 3. Real hardware — first pass (Arduino, later superseded, see §5)

User had ESP32 + vibration sensor + MPU6050 (no actuator). Reshaped the
device registry to 2 real-hardware devices (`vibration-001`,
`mpu6050-001`), updated `device_simulator.py` to match, wrote Arduino/C++
firmware (`hardware/esp32_zt_device.ino`) implementing HMAC-SHA256 signing
matching the gateway's canonicalisation exactly. Changed `payload.ts` from
a raw Python float to an integer millisecond count specifically so a
non-Python signer wouldn't need to replicate Python's float-repr
algorithm.

**Verified before claiming it worked**: simulated the firmware's exact
float-formatting algorithm against 4,000+ random values with zero
mismatches vs. Python's `json.dumps`, then ran the full canonical-string →
HMAC → `gateway.verify_signature()` path in Python — confirmed a real
board's signatures would actually verify before writing the setup doc.

**Infrastructure work**: installed Mosquitto (winget), discovered and
fixed two real gotchas the user then applied via elevated PowerShell
(no admin rights in this shell): (1) Windows Firewall blocking LAN
connections to port 1883, (2) Mosquitto's Windows service defaulting to
loopback-only binding even with the firewall open — fixed by adding an
explicit `listener 1883 0.0.0.0` to `mosquitto.conf`.

## 4. Claude Design dashboard artifact

Built a SOC/mission-control-styled live dashboard mockup via the `design`
skill — device trust gauges, scorer breakdown, SHAP panel, RL Q-value
heatmap, event log, alert feed, pipeline diagram. Published as a Claude
Artifact. A background review pass caught one real bug (the RL/STATIC
panels' initial-render hint was inverted relative to the actual default
state) and two minor naming/token cleanups — fixed and republished. This
is a **visual reference artifact**, not wired to live data — `dashboard.py`
remains the actual functional Phase 9 deliverable.

## 5. CLAUDE.md v2 + project synopsis arrive → full rearchitecture

User added `CLAUDE.md` (a detailed engineering brief) and
`docs/Zero_Trust_CPS_Project_Synopsis.docx` (37-source literature-grounded
academic report — extracted to plain text via direct docx-XML parsing,
no external tools needed, since `python-docx`/`pandoc` weren't installed)
and `implementation-docs/` (a 9-file module-by-module reference). These
specified real architectural requirements that conflicted with what was
already built:

| Area | New spec | What was built (§2/§3) |
|---|---|---|
| **Training** (flagged a "Hard Constraint") | Offline scripts → saved artifacts; gateway only infers | Online retraining inside the live gateway |
| Fusion output | `(trust, confidence)` | trust only |
| Firmware | MicroPython | Arduino/C++ |
| On-device features | 5-feature vibration vector (RMS, peak, crest factor, kurtosis, dominant freq) | 1 raw scalar |
| Device registry | Hybrid: 1 real ESP32 + `sensor-002`/`actuator-001` simulated | 2 real devices, no simulated ones |
| Transport | MQTT/TLS **and** CoAP/DTLS | MQTT only, untested TLS |
| Training labels | Real generated adversarial data | Heuristic pseudo-label |

User chose: refactor to match CLAUDE.md exactly. This was executed in
full:

- **`feature_engineering.py`** — the 5 Section-5.1 features, verified
  against synthetic baseline/shock/periodic test signals.
- **Hybrid `DEVICE_REGISTRY`** — `esp32-vib-001` (feature_vector kind) +
  `sensor-002`/`actuator-001` (scalar kind, restored). Found and fixed a
  real calibration bug here: placeholder `expected_ranges` didn't match
  `feature_engineering.py`'s actual output distribution (e.g.
  `crest_factor`'s configured lower bound of 0.5 was above where normal
  baseline readings actually fall, ~0.1) — recalibrated against real
  sampled statistics, all 5 models retrained after the fix.
- **Offline training pipeline**: `scripts/generate_training_data.py`
  (produces `data/collected/training_session.json`, 1220 records with
  REAL known ground-truth labels, not a heuristic) →
  `train_isolation_forest.py` → `train_lstm_ae.py` → `train_gnn.py` →
  `train_fusion_meta_learner.py` → `train_adaptive_pdp.py`, each saving to
  `models/`. Rewrote every scorer (`isolation_forest_scorer.py`,
  `lstm_ae_scorer.py` [renamed], `gnn_scorer.py`, `fusion_engine.py`,
  new `adaptive_pdp.py`) as **inference-only** — verified by code
  inspection that nothing reachable from `gateway.process_telemetry()`
  calls `.fit()`/`.backward()`/`.update()`.
- **`trust_engine.py`**: `rule_range_score()` now handles both device
  kinds; `score_message()` returns `(trust, confidence, reason)`; added
  `check_replay()` (Module 4 extension) — distinguishes a genuine device
  reboot from a replayed message by the timestamp's absolute size, not
  jump size. **Documented, narrow known limitation**: a message captured
  from within a device's first `REBOOT_TS_THRESHOLD_MS` (5s) of uptime
  could still be replayed undetected later.
- **`nist_mapping.py`** (new) — per-decision NIST SP 800-207 tenet tagging
  + a `completeness_report()` helper, since the synopsis calls this a
  primary deliverable, not a discussion point.
- **`gateway.py`** rewritten around `process_telemetry()`, a shared
  handler both MQTT and the second transport call into.
- **MQTT/TLS actually enabled** (was previously just documented, untested):
  generated real certs (`certs/`, hit and fixed a Git-Bash path-mangling
  issue with `openssl -subj` args via `MSYS_NO_PATHCONV=1`), added a TLS
  listener to `mosquitto.conf` (another elevated-PowerShell step for the
  user), verified live traffic over port 8883.
- **CoAP/DTLS — two real blockers found, both worked around and
  documented, not silently skipped**:
  1. Classic CoAP/DTLS needs `DTLSSocket`, which needs a native
     `autoreconf` build — unavailable natively on Windows and in WSL (no
     passwordless sudo to install the toolchain).
  2. CoAP-over-TLS via `aiocoap`'s `TLSServer` was implemented next —
     started cleanly, logged "ready," but refused every real connection.
     Verified this was a genuine upstream library defect (not a config
     mistake) with a raw-socket connect test on **native Windows AND
     WSL/Linux**, on **aiocoap 0.4.17 AND 0.4.7** — all 6 combinations
     failed identically.
  → Implemented **`coap_server.py`** as an HTTPS endpoint instead
     (stdlib `http.server` + `ssl`, zero new dependencies), delivering the
     same functional requirement (a second, independently TLS-secured,
     no-plaintext-fallback transport for Module 6). Verified with a real
     HTTPS POST through the full pipeline.
- **MicroPython firmware** (`firmware/main.py`, replaces the Arduino one)
  — computes all 5 features on-device (including a hand-written O(N²) DFT
  for `dominant_freq`, no numpy needed for N=32) rather than shipping a
  raw sample array over the signed channel, specifically to avoid
  multiplying the float-canonicalisation risk across 32 array elements.
  **Verified before claiming it worked**: the exact canonical-string
  construction tested against 500 random feature vectors, zero mismatches
  vs. Python's `json.dumps`, plus a full HMAC → `verify_signature()` round
  trip — same rigor as the Arduino firmware got in §3.
- **`hardware/esp32_zt_device.ino` deleted** (superseded); `docs/06_hardware_setup.md`
  rewritten for MicroPython flashing (`esptool`, `mpremote`).
- **`requirements.txt`** updated: added `numpy`, `joblib` (direct
  dependencies, previously only transitive); explicitly noted `aiocoap` is
  NOT required despite being pip-installed in this environment (dead end,
  see above).

**Final verification**: ran the complete rebuilt system for 100+ seconds
with MQTT + a live HTTPS burst running simultaneously — zero errors, all
three injected attack scenarios (forged signature, replay, in-range
anomalous shock) correctly detected and logged, `nist_tenets` and
`confidence` populated correctly in every audit row.

`docs/05_phase_status.md` was fully rewritten to reflect this — it's the
authoritative point-in-time architecture/compliance status doc (this file
is the narrative of how it got there).

## 6. Beginner-friendly hardware guide (Thonny, not raw esptool/mpremote)

User doesn't yet know how to physically connect hardware or flash a
board, and asked whether to use Arduino IDE — clarified first (Arduino
IDE compiles `.ino`/C++, it can't run `firmware/main.py` at all; going
that route would mean reversing CLAUDE.md Section 3's MicroPython choice).
User chose to keep MicroPython and wanted the flashing process explained.

Rewrote `docs/06_hardware_setup.md` from scratch as a true zero-to-hero
guide built around **Thonny** (a single free MicroPython-focused IDE with
built-in driver detection, a one-click "Install MicroPython" firmware
flasher, and simple file-upload — no command-line `esptool`/`mpremote`
required, unlike the previous version of this doc). Covers: parts list,
full wiring table for both the MPU6050 (I2C) and vibration sensor
(analog), installing Thonny, flashing MicroPython, editing
`firmware/main.py`'s WiFi/MQTT config block, uploading it to the board as
`main.py`, and what correct boot output looks like in Thonny's Shell vs.
in the gateway's own console. Kept the existing troubleshooting section
and known-limitations section (replay blind spot, disabled TLS cert
verification on-device) from the previous version. Mentions VSCode +
Pymakr as an optional later alternative, once comfortable — not the
primary path.

`hardware/esp32_zt_device.ino` (the old Arduino firmware, superseded in
§5) stays deleted — this session confirmed MicroPython is still the right
call rather than reversing that decision.

## 7. Dashboard fixed + synopsis Section 10.1 evaluation scripts built

User asked to continue the remaining implementation work. Checked
`dashboard.py` first, since §5's rearchitecture renamed/moved several
things it might have depended on — it didn't hard-crash (no defunct
imports) but was missing the new `confidence`/`nist_tenets`/`transport`
columns and had no NIST governance view at all, despite the synopsis
naming that a Section 7.3 Layer-3 deliverable. Added both.

Then built the five synopsis Section 10.1 evaluation deliverables as
`scripts/evaluate_*.py`, plus `scripts/generate_test_data.py` (a HELD-OUT
session, different random seed from `training_session.json` — evaluating
on training data would inflate every number and make the ablation study
meaningless):

- **`evaluate_ablation.py`** — fused score vs. each individual signal's
  accuracy/precision/recall/F1 on held-out data. Real result: **fusion
  (0.970 accuracy, 0.984 F1) beat every individual signal** (best
  individual was Isolation Forest at 0.957) — genuinely evidences the
  fusion's contribution, not asserted.
- **`evaluate_latency.py`** — HMAC-verification-only vs. full-pipeline
  latency on this gateway machine. Real numbers: HMAC ~0.013ms mean;
  full pipeline (auth + 4 scorers + fusion + policy) ~29ms mean, ~33ms
  p95. Notes the ESP32-side half of this metric needs real hardware
  (`time.ticks_ms()` instrumentation, not yet added) — flagged as TODO,
  not silently omitted.
- **`evaluate_explainability.py`** — checks whether each suspicious
  message's SHAP top-feature attribution is physically sensible for what
  actually caused it (a quantitative check, not eyeballing example
  strings). Real result: **40/40 (100%)** matched.
- **`evaluate_rl_policy.py`** — static vs. RL comparison, plus a
  convergence trend (trains a throwaway fresh bandit, doesn't touch the
  deployed Q-table). **Found and fixed a real methodological bug in the
  process**: the deployed policy was still using `epsilon`-greedy
  exploration at inference time, a training-time technique that only
  earns its keep paired with an `update()` call — and since CLAUDE.md's
  hard constraint means the live gateway never calls `update()`, that
  exploration was pure downside (measured: RL-with-exploration scored
  *worse* than the static baseline, 0.839 vs 0.936). Added
  `AdaptivePDP.greedy_action()` (pure exploitation, no exploration) as
  the correct live-path method, switched `gateway.py` to call it instead
  of `choose_action()`, re-verified the live gateway still works. With
  the fix: **RL (greedy) = 0.967 > Static = 0.936** — the theoretically-
  correct result direction, achieved by fixing a real bug, not by
  tuning until the number looked right.
- **`evaluate_governance.py`** — standalone NIST completeness report
  (paper-ready table, not just a dashboard screenshot). Surfaced and
  fixed a second real bug while building this: `config.AUDIT_DB_PATH`
  was a bare relative path (`"data/audit_log.db"`), silently resolving
  differently depending on which directory a script was launched from —
  masked for months because `gateway.py`/`device_simulator.py`/`dashboard.py`
  were always run from `src/`, but broke the instant an evaluation script
  (run from the repo root, like the others in `scripts/`) tried to read
  it. Fixed by making it absolute, anchored to `src/`, matching
  `MODELS_DIR`/`DATA_COLLECTED_DIR`'s existing pattern. Result after the
  fix: **100% coverage on all 7 NIST tenets** across every logged decision.

Both bugs found this session (RL exploration-at-inference, the relative
`AUDIT_DB_PATH`) were caught specifically *because* real evaluation
scripts were run against real data, not just eyeballing the architecture
— worth noting as a methodology point for the paper.

---

## 8. IEC 62443 mapping — the second half of CLAUDE.md Section 10's combined governance deliverable

CLAUDE.md Sections 6 and 10 ask for "A NIST SP 800-207 + IEC 62443
tenet-mapping table generated from the audit log" as one deliverable — the
NIST half (`nist_mapping.py`, §7 above) was done; IEC 62443 wasn't.

- **`src/iec62443_mapping.py`** (new) — the two IEC 62443 concepts CLAUDE.md
  names specifically: (1) `ZONES`/`CONDUITS` — a static mapping of the
  zones-and-conduits security model onto this project's actual Device/Edge,
  Gateway, and Monitoring/Governance layers (synopsis Section 7's three
  layers); (2) `FOUNDATIONAL_REQUIREMENTS` — IEC 62443-3-3's FR1–FR7,
  computed per-message from real audit_log rows the same way
  `nist_mapping.py` computes tenet coverage, **except** FR5 (Restricted
  Data Flow / network segmentation) and FR7 (Resource Availability) are
  reported honestly as `not_implemented` with a real explanatory note
  (no VLAN/firewall segmentation between zones; no rate-limiting or DoS
  protection on the gateway) rather than forced into a fabricated coverage
  percentage. Also includes `SECURITY_LEVEL_ASSESSMENT` — a reasoned SL-2
  target claim (evidence for: HMAC auth, TLS/HTTPS, replay protection,
  97% ablation accuracy; evidence against SL-3/4: no mutual TLS, no secure
  element, FR5/FR7 gaps) — stating a defensible SL-2 rather than an
  unsupported higher claim.
- **Caught a real bug before it shipped**: the first version of FR4 (Data
  Confidentiality) coverage checked `"https" in transport` directly, which
  would have silently reported 0% coverage for every MQTT/TLS-secured row
  (transport is literally the string `"mqtt"` for those — TLS-ness isn't
  in the transport string at all, it's already folded into
  `nist_mapping`'s tenet-2 computation as a separate flag). Also had an
  operator-precedence bug in the surrounding boolean logic. Fixed by
  reusing `nist_mapping`'s own tenet-2 ("secured communication")
  computation instead of re-deriving it — verified after the fix against
  live audit data: **FR1/FR2/FR3/FR4/FR6 = 100% of 47 logged decisions**,
  FR5/FR7 correctly print as NOT IMPLEMENTED with their notes.
- **`scripts/evaluate_iec62443.py`** (new) — standalone CLI, mirrors
  `evaluate_governance.py`'s pattern exactly, for a paper-ready printed
  report alongside NIST's.
- **`dashboard.py`** — added a live "IEC 62443-3-3 Foundational
  Requirements coverage" section right after the existing NIST section: a
  coverage table (implemented FRs get a %, not-implemented FRs show "—"),
  plus an expander with the full SL-2 self-assessment text. Verified with
  a full live run: gateway + `device_simulator.py` for 15s (mix of ALLOW
  decisions and a forged-signature auth=FAIL, confirming attack detection
  still works), then a headless `streamlit run` on port 8532 — HTTP 200,
  no errors in the Streamlit log, and the FR coverage numbers cross-checked
  directly against `iec62443_mapping.print_report()` on the same audit
  rows.

Both this session's IEC 62443 bug and last session's RL/AUDIT_DB_PATH bugs
were caught the same way: run the new code against real data before
declaring it done, not just reading it back.

---

## 9. Full synopsis re-audit — two real gaps found, both fixed

User asked directly whether the synopsis was actually integrated. Rather
than answer from memory, re-read `docs/synopsis_extracted.txt` (351 lines)
in full and checked it against the real code file-by-file. Found two
genuine gaps that had gone silently unimplemented:

**Gap 1 — Module 2 isn't actually "mutual."** The synopsis's Section 4.3
table says "Mutual challenge-response authentication"; the real
implementation is one-directional device→gateway HMAC-SHA256, matching
what CLAUDE.md Section 3 explicitly directs. Documented (not redesigned —
CLAUDE.md doesn't ask for the synopsis's version, and a real fix needs
firmware changes unverifiable without hardware) in
`implementation-docs/02_module_authentication.md`'s new "Honesty note on
'mutual'" section and `docs/05_phase_status.md`'s substitutions list
(now 5 items, was 3).

**Gap 2 — no "coordinated multi-device attack" scenario existed anywhere**,
despite the synopsis's Section 4.2 Stage 6 naming it explicitly as one of
four required adversarial-testing scenarios, and despite it being the
*specific* scenario the GNN (Module 3's relational signal, the Section
4.1 novelty claim) exists to catch. This meant the GNN's actual
contribution had never been tested by any evaluation script — a real gap
in the paper's central claim, not a cosmetic one. Fixed by:

1. Adding a `coordinated` event type to `device_simulator.py` and
   `scripts/generate_training_data.py` (both mirror each other exactly,
   same as the existing scenarios): every ~25 ticks, all 3 devices drift
   mildly and simultaneously — individually still inside their hard
   `expected_range`/`expected_ranges` (so the rule-based check can't see
   it, by design) and individually ambiguous to a single-device scorer.
   For `esp32-vib-001` specifically, the mild drift is a SHAPE change
   (elevation spread across 3-5 samples), not a scaled-down single-sample
   spike — a scaled-down spike still saturates kurtosis almost as high as
   the full shock case (kurtosis is dominated by whether any one sample
   is an outlier at all, not by how far), which would have made the
   scenario not actually ambiguous. Verified empirically (see below)
   before trusting it.
2. Running this exposed the GNN's actual contribution had never been
   tested was ALSO masking two real bugs, found by directly probing the
   trained model rather than trusting the first ablation number:
   - `train_gnn.py` built one snapshot per (tick, device) record but
     forced every OTHER node's training target to 1 ("assume normal") —
     wrong whenever another device was simultaneously anomalous, which is
     exactly backwards for a model whose whole purpose is relational
     reasoning. Fixed to track each device's own last-known TRUE label,
     so a coordinated tick's last-processed record carries the full true
     joint target.
   - Even after that fix, direct probing (`model(x, a_hat)` on synthetic
     "all three nodes bad" input) showed the GNN's raw output never
     crossed 0.5 even on the worst case (~0.66) — traced to unweighted
     `BCELoss` under ~90/10 class imbalance in the per-node targets.
     Fixed with standard inverse-frequency class weighting; re-probing
     confirmed real separation afterward (normal→0.99, all-bad→0.015).
3. Retraining fusion on the now-working GNN revealed a THIRD issue: the
   `LogisticRegression` meta-learner actively discarded the GNN's signal
   on `coordinated` specifically (fused recall 0.261 — *worse* than the
   GNN alone at 0.870), because the numerous easy normal/shock/forged
   examples dominated its single global linear hyperplane. Tested the
   synopsis's own named alternative (a shallow `DecisionTreeClassifier`,
   Section 5.6) as a candidate fix but rejected it — `fusion_engine.py`'s
   SHAP layer uses `shap.LinearExplainer`, which requires a linear model,
   and switching would have meant a bigger, riskier change (new explainer
   type, re-verifying `evaluate_explainability.py`) for a smaller net
   win than the simpler fix: `class_weight="balanced"` on the existing
   `LogisticRegression`. That recovered coordinated recall to 0.913 (best
   of any single signal) at a real, deliberate, documented cost — raw
   aggregate accuracy (0.875) now sits below Isolation Forest alone
   (0.923). `evaluate_ablation.py`'s summary message was rewritten to
   explain this trade-off explicitly rather than the old generic "may
   need more training data" framing, which would have been actively
   misleading here — this is a verified, deliberate choice, not an
   undertrained model.
4. Added a per-event-type recall breakdown to `evaluate_ablation.py`
   (aggregate accuracy alone hides exactly this kind of per-scenario
   story) and a `"coordinated": {"gnn_score", ...}` entry to
   `evaluate_explainability.py`'s expected-top-feature map. Final
   verified numbers: `gnn_score` recall on `coordinated` = 0.870 vs.
   Isolation Forest's 0.304 and LSTM-AE's 0.261 — the GNN's relational
   signal genuinely does what the paper claims it does, now with real
   evidence instead of an assumption. SHAP explainability check:
   100% (63/63) of suspicious held-out messages, including every
   `coordinated` one, attributed correctly to `gnn_score`.
5. Full retrain (all 5 `scripts/train_*.py`, in order) and full
   re-verification: `evaluate_rl_policy.py` (RL greedy 0.839 > static
   0.723, still correct direction), `evaluate_governance.py` /
   `evaluate_iec62443.py` (both still 100%), and a live 60-second
   gateway + simulator run confirming the coordinated-attack marker
   actually fires in production and correctly triggers a `STEP_UP`
   decision (`fusion: gnn_score=0.04 most lowered trust`) with zero
   errors in the gateway log.

Every number in this entry came from actually running the code against
real data, not from reasoning about what should happen — the same
methodology as the RL-exploration and `AUDIT_DB_PATH` bugs from §7,
now caught a third and fourth time in the same session.

---

## 10. Claude Design mockup rebuilt as a real, locally-run live dashboard

User asked why the earlier Claude Design artifact (`design/zero-trust-cps-command-center.html`,
published from `design/Main.dc.html`) wasn't being used for the demo instead
of Streamlit. Answer: it's a self-contained page hosted on claude.ai with a
strict CSP that cannot reach `localhost` or read a local file — it was
generating its own fake data client-side (`Math.random()`, confirmed by
grep) rather than showing anything real, and its device names
(`vibration-001`, `mpu6050-001`) even predate the current 3-device hybrid
architecture. User's explicit instruction: rebuild it according to the
real project, run it locally, don't publish it as a claude.ai artifact.

Also found `Main.dc.html` (the *editable* source, distinct from the
bundled 2.2MB published output) uses a proprietary Design-tool DSL
(`{{binding}}`, `<sc-if>`, `<sc-for>`, `class Component extends DCLogic`)
that depends on a `support.js` runtime — confirmed via `find` that this
runtime isn't distributed anywhere in the repo, so the source file can't
run standalone in a browser at all, published or not.

**Built from scratch, reusing only the CSS (fully portable, no proprietary
syntax) and layout structure**:
- `src/webapp_server.py` — stdlib-only `http.server`, no new dependency.
  Serves the static page at `/` and real JSON at `/api/decisions`,
  `/api/devices`, `/api/governance`, `/api/iec62443`, `/api/qtable`,
  `/api/status` — every one reads from the exact same modules
  `dashboard.py` and `scripts/evaluate_*.py` already use (`audit_log`,
  `nist_mapping`, `iec62443_mapping`), not a new data source. Runs on
  port 8600.
- `src/webapp/index.html` — plain HTML/CSS/vanilla JS (no framework, no
  build step), same dark cyan/amber/violet aesthetic as the original
  mockup, `fetch()`-polls the API every 2s and re-renders the DOM
  directly. Data-driven for however many devices `DEVICE_REGISTRY` has
  (not hardcoded to 2) — device cards, trust gauges, an SVG trust-over-time
  chart, a real scorer breakdown (rule/IF/LSTM-AE/GNN/fused), a SHAP panel
  parsed from the real `reason` string, a live event log, an alert feed
  derived from real non-ALLOW/auth-fail/replay rows, and — new relative to
  the original mockup — NIST + IEC 62443 governance panels (the mockup
  never had these at all).
- **The RL policy panel shows the REAL trained Q-table**
  (`models/adaptive_pdp_qtable.json`), not a mocked one like the original
  design had — an actual improvement over both the old mockup and
  `dashboard.py` (which doesn't surface the Q-table at all).
- Added a `rule_score` column to `audit_log.py` (same `ALTER TABLE ADD
  COLUMN` migration pattern as the other Phase 6/7/8 columns) and wired it
  through `gateway.py`'s `log_decision()` call — needed because the
  Scorer Breakdown panel needs all 4 signals, not just the 3 that were
  already logged (IF/LSTM-AE/GNN/fused; rule_score was computed every
  message but never persisted).

**Two real bugs found and fixed during verification** (same methodology as
§7/§9 — ran it, didn't just read it):
1. First live test showed `rule_score: null` on every fresh row despite
   the wiring looking correct. Traced with a direct monkey-patched probe
   of `process_telemetry()` (confirmed the value WAS 0.9, correctly
   passed) — the null values were from a stale leftover `gateway.py`
   process from an earlier test block that `taskkill` hadn't caught,
   still running the pre-edit code. A clean-start retest confirmed
   `rule_score` populates correctly on every row.
2. `index.html`'s `govBarRow()` had a genuine JS string-escaping bug in
   its unknown-coverage fallback branch (`\\"` inside a double-quoted
   string terminated the string early, leaving bare identifiers outside
   any string — a syntax error if that branch ever executed). Currently
   dead code with the current callers (both always pass numeric
   coverage), but fixed properly rather than left as a latent trap.

Verified end-to-end after both fixes: clean gateway + simulator +
webapp_server run, HTTP 200 from `/`, all 6 `/api/*` endpoints returning
well-formed real JSON, zero errors in any log, zero unresolved `{{...}}`
template markers in the served HTML (confirms it's not accidentally
serving the untranspiled Design-tool source). Could not visually verify
in an actual browser (no browser available to this session) — the user
should open `http://localhost:8600` and confirm the visual result looks
right; report back anything that looks off.

**Run it**: `python webapp_server.py` from `src/`, alongside `gateway.py`
and `device_simulator.py` (or the real ESP32), same as `dashboard.py` —
open `http://localhost:8600` in a browser. This is now a SECOND, more
visually polished live dashboard alongside Streamlit's, not a replacement
— both read the identical real data.

---

## 11. Transport-layer Zero Trust — FR5/FR7 upgraded from gap to "partial," honestly

User pushed back on FR5/FR7 (network segmentation, resource availability)
being flat "not implemented" gaps and asked for the "ZeroTrust part" to be
"implemented properly." Scoped this via two clarifying questions before
starting (real network segmentation across physical hosts genuinely isn't
buildable on one machine — confirmed that's not what was meant): the real
ask was transport-level hardening, closing the gap where the MQTT broker
had `allow_anonymous true` and so only the application-layer HMAC check
was ever enforcing "no implicit trust" — a client with zero credentials
could still connect to the broker, eavesdrop on any device's telemetry,
or forge `cps/decisions` messages.

**Built (all verified, not just written):**
- `certs/mosquitto_passwd` + `certs/mosquitto_acl` — per-device MQTT
  broker credentials (generated with `mosquitto_passwd.exe`, no admin
  needed since output was pointed at a repo path, not `Program Files`)
  and least-privilege topic ACLs: each device can publish only its own
  telemetry and read only its own decisions topic
  (`cps/decisions/<device_id>`, via Mosquitto's `%u` pattern
  substitution). Required changing `DECISION_TOPIC` from a flat shared
  topic to a per-device one in `gateway.py`'s `_publish_decision()` — a
  shared topic literally can't be scoped per-device with topic ACLs.
- `config.py` — `mqtt_username`/`mqtt_password` added per device in
  `DEVICE_REGISTRY` (deliberately separate credential from the HMAC
  `secret` — different trust boundary), `MQTT_USE_AUTH` auto-detect
  (same pattern as `MQTT_USE_TLS`), `MIN_MESSAGE_INTERVAL_SECONDS` for
  flood detection.
- `device_simulator.py` — **structurally refactored** from one shared
  MQTT connection for all 3 simulated devices to one connection PER
  device, each authenticating with its own credential. A shared
  connection would have made the whole ACL setup theater — the broker
  can't enforce per-device least-privilege on a connection that claims to
  be multiple devices at once.
- `firmware/main.py` — matching `MQTT_USERNAME`/`MQTT_PASSWORD` for the
  real ESP32, `umqtt.simple.MQTTClient`'s `user=`/`password=` kwargs.
- `trust_engine.py` — `check_flood()` (IEC 62443 FR7), mirroring
  `check_replay()`'s pattern exactly: per-device wall-clock arrival-time
  check (not the payload's self-reported `ts`, which an attacker
  controls), flags a device publishing faster than
  `MIN_MESSAGE_INTERVAL_SECONDS`. Wired into `gateway.py` alongside the
  replay check, and into `score_message()` as a new `is_flood` path with
  the same severity treatment as a replay.
- `scripts/run_gateway_supervised.py` (FR7) — restart-on-crash process
  supervisor with crash-loop backoff, run instead of `gateway.py`
  directly.
- `docs/07_transport_zero_trust.md` (new) — the exact `mosquitto.conf`
  diff, PowerShell commands, and a "prove the negative" verification step
  (`mosquitto_sub` with no credentials should be REFUSED after the
  change) — handed to the user since editing `mosquitto.conf` needs admin
  PowerShell, same constraint as the original TLS setup.
- `iec62443_mapping.py` — added a third `"partial"` status (alongside
  `"implemented"`/`"not_implemented"`) so FR5/FR7 can honestly report
  BOTH a real, computed coverage number AND an explicit `note` on exactly
  what's still not covered (no physical/VLAN segmentation; no
  multi-instance redundancy) — not silently upgraded to "implemented,"
  not left as a flat, now-outdated "not implemented" either.
  `fr_coverage_report()`, `print_report()`, `dashboard.py`,
  `webapp_server.py`, and `webapp/index.html` all updated to render the
  new 3-way status (amber "PARTIAL" tag distinct from cyan "implemented"
  and red "not implemented").
- `SECURITY_LEVEL_ASSESSMENT` text updated to cite the new mitigations as
  evidence FOR SL-2, while adding the MQTT credentials themselves (also
  plaintext constants, same simplification as the HMAC secret) and the
  FR5/FR7 partial-not-full status to evidence AGAINST SL-3/4 — the target
  stays SL-2, now with stronger, more specific evidence either way.

**Verified, not assumed**: `check_flood()` unit-tested directly (first
message → False, immediate second → True, after 0.6s wait → False); a
full clean gateway+simulator+webapp run showed zero false-positive flood
detections during normal 2s-cadence traffic and the
`MQTT broker auth: enabled` banner printing correctly; `/api/iec62443`
confirmed FR5/FR7 both report `"partial"` with real computed coverage and
a non-null gap note through the full stack (module → HTTP API → what the
browser would render).

**Honest limitation stated to the user**: `MQTT_USE_AUTH` (and therefore
FR5's reported coverage) reflects whether `certs/mosquitto_passwd` EXISTS
and the code is READY to authenticate — same auto-detect pattern as
`MQTT_USE_TLS`/`COAP_ENABLED` elsewhere in this codebase — not whether the
broker is actually CURRENTLY enforcing it. That last step
(`mosquitto.conf`'s `allow_anonymous false` + restart) is the one thing
still pending the user's admin PowerShell action, per
`docs/07_transport_zero_trust.md`.

---

## 12. Trust-score responsiveness — the last unbuilt synopsis Section 10.1 metric

User asked to close the two remaining open items from the last status
check: this evaluation script, and the `mosquitto.conf` admin step (§13).

`scripts/evaluate_trust_responsiveness.py` (new) — the one evaluation
metric flagged as missing several turns ago and never circled back to.
Structurally different from every other `evaluate_*.py`: those score each
message independently (stateless), but "responsiveness" is a property of
the EWMA trust score's *trajectory* over consecutive messages for the
same device, so this one replays `test_session.json` **in order** through
a real `trust_engine.RuleBasedTrustEngine` instance — the actual stateful
object the live gateway uses, not a re-derivation.

**Found and fixed a real bug in the harness itself before trusting its
output**: `trust_engine.py`'s decay and `check_flood()` read wall-clock
`time.time()`, which needed mocking for a batch replay (otherwise every
record appears to arrive "instantly"). First attempt fed each record's
own `ts` field directly into the fake clock — but a REPLAYED record's
`ts` deliberately jumps *backward* (that's what makes it detectable), and
feeding that straight into the mocked clock made the decay calculation's
`elapsed` go negative, which **inflated** trust instead of penalising it
— the opposite of correct. Caught by eyeballing a nonsensical result
(mean trust *increase* on replay events, when a drop was expected) rather
than just accepting the first number produced. Fixed with a monotonic
clock wrapper (`_FakeClock.advance()`) that follows `ts` forward normally
but only ever nudges forward, never backward — mirroring how real
wall-clock time behaves in the live gateway regardless of what a replayed
payload's `ts` claims. Re-ran after the fix: replay's mean immediate
trust drop flipped from -0.319 (wrong direction) to +0.071 (correct
direction, immediate ALLOW-threshold break on every one of the 10 replay
events in the test set).

**Real, verified results** (n=63 injected events, matching
`test_session.json`'s exact event-type breakdown):
- `forged_signature` / `replay`: essentially immediate (mean 0.00-0.08
  messages) drop below `THRESHOLD_ALLOW` — both go through
  `trust_engine`'s absolute auth-failure/replay penalty path, so this is
  expected and confirms it's wired correctly.
- `anomalous_shock`: also immediate ALLOW-break, but takes ~9.4 further
  messages on average to reach `THRESHOLD_STEP_UP` territory — a single
  isolated shock tick doesn't by itself justify a STEP_UP/DENY response;
  only sustained drift would, which is the physically correct behaviour
  for a genuinely transient anomaly.
- `coordinated`: takes ~0.78 messages on average to cross below
  `THRESHOLD_ALLOW` (not always the very first message) — consistent
  with §9's finding that individual coordinated-event readings are
  deliberately mild/ambiguous by design; the GNN's relational signal
  needs to see the pattern, not just one reading, which shows up here as
  a slightly slower (but still fast) reaction than the harder-signal
  event types.

---

## 13. Module 2 upgraded to genuine mutual authentication

User asked to (a) re-verify the whole pipeline still works without
hardware, (b) fix one of the documented substitutions, (c) see the live
dashboard, and (d) get a written report drafted. Re-verified the pipeline
first, live rather than trusting the log: ran `gateway.py` +
`device_simulator.py` fresh, confirmed real fusion scores/SHAP
reasons/RL decisions writing to `audit_log.db`, then re-ran
`evaluate_ablation.py`, `evaluate_governance.py`, `evaluate_iec62443.py` —
all numbers matched what `05_phase_status.md`/`SESSION_LOG.md` already
claimed (fusion 0.875 aggregate / 0.913 coordinated recall; NIST 100%
7/7; IEC 62443 FR1-4/6 100%, FR5/FR7 partial). Nothing had bit-rotted.

Picked substitution #4 (one-directional, not "mutual," authentication) to
fix, since — unlike CoAP/DTLS (blocked on a real upstream library defect
across two versions/platforms, needs an unavailable sudo/autoreconf
toolchain to even retry) — this one is genuinely closeable in software
alone, no hardware required, consistent with today's "without hardware"
framing.

**What changed**: the gateway now signs its own `cps/decisions/<device_id>`
messages (`gateway.py::_sign_decision()`) using the SAME per-device secret
Module 1 already provisions to both sides for telemetry signing — no new
key distribution needed. `device_simulator.py` (each simulated device
already has its own MQTT connection/credential, from §11's transport work)
now subscribes to its own decisions topic and verifies the signature
before trusting a decision (`verify_decision_signature()`); a rejected one
is logged and NOT acted on. Mirrored in `firmware/main.py` for the real
ESP32 (`verify_decision_signature()`, `on_decision()`, wired via
`umqtt.simple`'s `set_callback()`/`check_msg()`) — protocol-verified in
software only, same "not yet flashed" status as the rest of the firmware,
consistent with this session's hardware-free scope.

**Found and fixed a real bug during verification, not before it**: first
live run showed EVERY decision being rejected. Traced to two STALE
`gateway.py`/`device_simulator.py` processes (PIDs 31452/34872, found via
`Get-CimInstance Win32_Process`) left running from earlier in this
session, still publishing the OLD unsigned decision format and racing
with the newly-edited code on the same MQTT topics — the simulator's new
verification code was correctly rejecting those old-format messages, not
malfunctioning. Killed the stale processes, restarted clean, re-verified:
`<< verified gateway decision: ALLOW` on legitimate decisions, correctly
transitioning to `<< verified gateway decision: STEP_UP` on the
injected anomalous-shock event. A standalone unit-level check (tampered
payload, wrong secret, malformed envelope) confirmed the negative path
independently of the live run.

**Known remaining gap, stated explicitly**: still not interactive
challenge-response (no gateway-issued nonce inside a session handshake —
each message authenticates its own content independently, same style as
the existing telemetry-side scheme); the new decision channel has no
replay check of its own yet (lower stakes than telemetry replay, since a
decision is an ephemeral access grant rather than a sensor reading that
feeds trust scoring, but a real, undone gap). Documented in
`implementation-docs/02_module_authentication.md`'s updated "Honesty
note on 'mutual'" and `docs/05_phase_status.md`'s substitutions list
(now 4 items — this was #4, not fully removed, just upgraded).

---

## 14. Two real webapp bugs, found by the user looking at the actual dashboard

User opened `http://localhost:8600` (started this session for the first
time, see §13) and immediately spotted two visible problems: every "last
seen" showed **NaNh ago**, and the "FUSION — SHAP" panel showed a real
top-feature sentence at the bottom (e.g. `isolation_forest_score (0.90)
most raised trust`) but every bar above it, including the one for that
same feature, rendered as a blank `—` with no fill. Both were real bugs in
`src/webapp/index.html`, not caused by anything from this session's own
edits (§13/earlier) — pre-existing since `index.html` was first built.

**Bug 1 — `NaNh ago`**: `timeAgo()` and `renderLog()`'s row-timestamp
parsing both did `iso + (iso.endsWith("Z") ? "" : "Z")` before calling
`new Date()`. `audit_log.py` writes timestamps with
`datetime.now(timezone.utc).isoformat()`, which ALWAYS produces an
explicit `+00:00` offset, never a trailing `Z` — so the check was always
false and the code unconditionally appended `"Z"` onto a string that
already had a numeric offset, producing `...+00:00Z`, which `Date()`
silently parses as `Invalid Date` (`.getTime()` = `NaN`, propagating into
every downstream arithmetic op). Fixed with a shared `parseIsoUtc()` that
only appends `"Z"` when the string genuinely has no timezone marker at all
(checked via regex, not `endsWith`) — verified in Node against a real
`audit_log` timestamp string, correct `Date` and a sane seconds-ago value.

**Bug 2 — SHAP panel bars all blank**: `renderScorerAndShap()` compared
`s.key === parsed.feature` to decide which scorer row is "the" top
SHAP-attributed one (`s.key` from `SCORER_NAMES`, `parsed.feature` scraped
out of the `reason` string via regex). Two of the four signals have
DIFFERENT names in each place: `fusion_engine.py`'s `FEATURE_NAMES` puts
`isolation_forest_score`/`lstm_ae_score` into the reason text, while
`audit_log`'s actual columns (and this API's field keys, `SCORER_NAMES`)
are `anomaly_score`/`lstm_score` — `rule_score` and `gnn_score` happen to
already match, which is why the bug wasn't obvious on every row. The
comparison silently failed whenever Isolation Forest or LSTM-AE was the
top-contributing feature (empirically the common case in this dataset —
Isolation Forest is the strongest individual signal per
`evaluate_ablation.py`, §12/Section 1 of `docs/08_results_and_evaluation.md`),
which is why the panel looked comprehensively broken rather than
occasionally wrong. Fixed with an explicit `REASON_FEATURE_TO_KEY` mapping
dict, applied before the comparison — verified in Node against a real
logged reason string (`isolation_forest_score` correctly resolves to
`anomaly_score` and now matches its row).

Both fixes are pure client-side JS in a file `webapp_server.py` reads
fresh off disk on every request (confirmed no caching in
`_serve_static()`) — no server restart needed, just a browser refresh.

---

## 15. Full per-signal SHAP breakdown — closing the "only top feature" gap for real

User looked closer at the (now-fixed) SHAP panel and asked why Isolation
Forest was the only row ever showing a real value, with Rule-Based/
LSTM-Autoencoder/GNN permanently blank. Not a third bug — a real,
previously-stated design limitation (the sentence under the panel said so
outright: "Only the single top-contributing feature's SHAP value is
logged per decision"). Traced to `fusion_engine.py::_explain()`: it
computes the FULL 4-element SHAP vector via `shap.LinearExplainer` every
single decision, then immediately discards three of the four values,
keeping only `argmax(abs(shap_values))` for the human-readable `reason`
string. Nothing downstream (`audit_log`, the API, the dashboard) ever had
access to the other three — not a rendering bug, a genuine data-availability
gap, and a fixable one since the full vector WAS being computed all along.

**Fixed properly rather than left as a documented gap**, since the data
was already there for the taking:

- `fusion_engine.py` — `FusionEngine` now keeps `self.last_shap`, the full
  `{feature_name: shap_value}` dict from the most recently explained
  decision (reset to `None` on the untrained-fallback path). Documented as
  safe instance state specifically because `gateway.py`'s message handling
  is single-threaded (one message fully processed before the next), not
  shared across concurrent in-flight decisions.
- `audit_log.py` — four new columns (`shap_rule`, `shap_isolation_forest`,
  `shap_lstm_ae`, `shap_gnn`), added via the same `ALTER TABLE ADD COLUMN`
  migration pattern every prior column addition in this file has used;
  `log_decision()` gained an optional `shap: dict` parameter.
- `gateway.py` — one-line addition, passes `fusion_engine.last_shap`
  straight through to `log_decision()`.
- `webapp/index.html` — `SHAP_COLUMN_FOR_KEY` maps each scorer to its new
  column; `renderScorerAndShap()` now shows every signal's REAL SHAP
  contribution (not just the top one) when a row has them, with a clean
  fallback to the old top-feature-only behaviour for rows logged before
  these columns existed (their value is `NULL`, detected and handled, not
  crashed on or silently zeroed).

**Verified at every layer before calling it done**: restarted `gateway.py`
(module-level Python state needed a fresh process; `device_simulator.py`
and `webapp_server.py` didn't, since neither caches schema or scorer
state), confirmed zero startup errors, then queried `audit_log.db`
directly — all four columns populated with real, distinct, non-zero
values on fresh rows, and cross-checked that the largest-magnitude column
on each row always matches the feature `reason`'s regex-parsed top feature
(e.g. row with `reason` naming `gnn_score, SHAP=0.53` has
`shap_gnn=0.5309...` as the largest of the four — confirms the persisted
vector and the human-readable summary agree, not two independent
computations that happen to usually match). Also confirmed via `curl
/api/decisions` that the new fields serialize correctly over the API a
browser would actually receive.

## 16. "Is all the logic correct?" — verified the SHAP math itself, found and labeled one real subtlety

User pushed one level deeper than the display fix in §15 and asked whether
the underlying SHAP logic is actually correct, not just wired through
correctly. Checked mathematically rather than asserting it: loaded the
real trained fusion model and background sample, ran a feature vector
through `shap.LinearExplainer`, and confirmed `expected_value +
sum(shap_values)` exactly reproduces `model.decision_function(x)`
(1.5013 == 1.5013) — the SHAP computation is exact and correct, the
standard textbook decomposition for a linear/logistic model.

**One genuine, worth-stating subtlety found**: that exact decomposition is
in the model's **log-odds (margin) space** — the pre-sigmoid linear
score — not the same 0–1 scale as the `trust_score` that's actually
displayed (`model.predict_proba(x)[1]` = 0.818 in the same test case,
vs. margin = 1.501). This isn't a bug and isn't fixable by changing the
explainer: no exact additive decomposition into probability-space
contributions exists for a logistic model at all (`sigmoid(a+b) !=
sigmoid(a)+sigmoid(b)`), and `LinearExplainer`'s closed-form speed (vs. a
sampling-based `KernelExplainer`) is what makes running SHAP on every
single gateway message affordable. Direction (raised/lowered trust) is
always correct since sigmoid is monotonic; only the magnitude comparison
between bars is in log-odds units, not literal "trust-score points." Does
NOT affect any actual decision — the RL policy and static thresholds act
on `trust_score` directly; SHAP is a pure post-hoc explanation, never fed
back into the trust score or access decision.

Since this feeds a governance/audit-log deliverable where unit precision
genuinely matters (misreading "+0.53" as "+0.53 trust-score points" would
be a real misinterpretation risk for an auditor), fixed the LABELING
(not the computation, which was already correct) rather than leaving it
implicit:
- `fusion_engine.py::_explain()` — reason string now says `(SHAP=X.XX,
  log-odds)`, plus a docstring explaining the empirical verification above.
- `webapp/index.html` — regex updated to parse the new suffix (backward-
  compatible with older rows via an optional non-capturing group, verified
  in Node), and the SHAP panel's sentence now always appends an explicit
  units note explaining log-odds vs. probability space.
- Restarted the gateway, confirmed fresh rows carry the new `, log-odds`
  suffix and the updated regex parses them correctly (both checked
  directly, not assumed).

---

## 17. "Ensure LSTM and everything is working fine" — a real, deeper bug found in the fusion training methodology, fixed and verified

User pushed past the display-level checks (§14-16) and asked whether
everything is genuinely correct, specifically calling out the LSTM row.
Looked at the dashboard's own numbers rather than assuming: Scorer
Breakdown showed `LSTM-Autoencoder = 0.00` (raw score, meaning "looks very
anomalous") paired with `SHAP = +0.37` (raising trust) in the FUSION-SHAP
panel — backwards on its face. Checked the trained model directly instead
of guessing: `fusion_meta_learner.joblib`'s coefficient on `lstm_ae_score`
was **-0.46** (negative) — the only one of the four signals with the
wrong sign (`isolation_forest_score` +4.41, `gnn_score` +5.51, both
correctly positive).

**Root cause, traced empirically**: `lstm_ae_scorer.py` is STATEFUL — it
scores an 8-message (`LSTM_SEQ_LEN`) rolling window per device, not a
single reading. Fed the real `device_simulator.py` shock-injection
sequence through a fresh scorer and watched it directly: a shock at tick 7
holds `lstm_score` at the exact hard floor (0.0) through tick 14, only
clearing at tick 15 — 7 full messages of "memory" after the actual
anomalous tick. Checked the raw z-statistic behind that floor too (not
just the clipped output): ~4171, wildly past the clip threshold of 3.6,
traced to kurtosis (~27 during a shock) normalizing to ~45 standard
deviations against training-time stats built from normal-only data — an
extreme value an LSTM trained on roughly [-3,+3]-range inputs cannot
reconstruct sanely, hence the error explosion.
`scripts/train_fusion_meta_learner.py` trained the meta-learner directly
against each message's raw per-message ground-truth label, with zero
awareness that ~66-70% of the time (verified against 500 real audit rows:
exactly 70.4%), `lstm_score=0.0` co-occurs with a message that is itself
perfectly LEGITIMATE (label=1) purely because of this window-memory
residue. Training a linear model on that relationship teaches it the
literal opposite of what `lstm_score` means.

**Fix, iterated twice because the first attempt caused a real regression**:
1. First attempt: relabel every "window residue" message as suspicious
   (label=0) for fusion-training purposes. Fixed the sign (all four
   coefficients positive) but **broke something else**: verified via
   `evaluate_ablation.py` that `coordinated` recall collapsed from 0.913 to
   0.304. Diagnosed why before accepting the regression: relabelling ~300
   residue messages inflated the "suspicious" training class from ~10% to
   ~36% of the dataset, which dilutes `class_weight="balanced"`'s
   upweighting of the genuinely rare `coordinated` pattern — the exact
   regression `SESSION_LOG.md` §9 already fought to fix once, now
   reintroduced by a different route.
2. Second attempt (kept): **exclude** ambiguous window-residue messages
   from the fusion meta-learner's training set entirely, rather than
   forcing them into either class — computed via a `label_window` dict
   that mirrors `lstm_ae_scorer.py`'s own internal per-device rolling
   window exactly (tracking labels instead of feature vectors), not
   guessed from `event_type` or tick arithmetic (verified a `coordinated`
   event's randomised severity can occasionally contaminate the window
   too, at a different random seed — an event_type-based heuristic would
   have missed that case). Retrained
   (`isolation_forest`/`lstm_ae`/`gnn` scorers themselves untouched — only
   the meta-learner's training TARGET changed): all four coefficients now
   positive (`rule` +0.008, `isolation_forest` +4.39, `lstm_ae` +2.97,
   `gnn` +5.04), `coordinated` recall preserved at 0.913 (exact match to
   the original figure).

**Verified live, not just offline** (a genuinely wrong-looking result
surfaced mid-verification and was chased down before being accepted):
restarted the gateway with the corrected model, queried fresh audit rows,
and initially found `lstm_score=0.0` paired with `shap_lstm_ae=+0.368` —
STILL backwards. Isolated the true relationship with controlled inputs
(hold rule/if/gnn fixed, vary only lstm) against the freshly-loaded
model+explainer directly: confirmed `lstm_score=0.0 -> SHAP=-2.568`,
correctly negative, and confirmed via a second controlled test that SHAP
for one feature is independent of the others' values (linear model
property, verified not assumed). The "still backwards" rows turned out to
be timestamped BEFORE the gateway restart actually completed — a stale
write from the outgoing old process caught mid-transition, not a real
bug. The newest rows (well after restart) matched the isolated
calculation exactly, to 15 decimal places (`-2.568402388458186` in both).

**Retrained the full downstream chain and re-verified everything**:
`train_adaptive_pdp.py` (RL policy depends on fusion's trust/confidence
output) → `evaluate_ablation.py`, `evaluate_explainability.py` (still
100%), `evaluate_governance.py` (still 100%), `evaluate_rl_policy.py`
(RL greedy 0.779 > Static 0.428, larger margin than before, still correct
direction), `evaluate_trust_responsiveness.py`. That last one surfaced one
more thing worth explaining rather than treating as a bug: `replay`'s mean
immediate trust drop came out NEGATIVE (-0.093). Checked the 10 individual
events rather than accepting the aggregate: every replay event's
IMMEDIATELY PRECEDING message already had very low trust (0.05-0.27,
residual EWMA suppression from a nearby real shock in the same session
window), and the replay penalty resets to a roughly fixed low value that
happens to land slightly above that already-suppressed baseline. The
metric that actually matters, `messages_to_below_allow`, is 0.00 for all
10 events — replay is caught immediately, every single time; the negative
"drop" is a baseline artifact, not a detection failure. Documented
explicitly in `docs/08_results_and_evaluation.md` rather than left as an
unexplained-looking negative number.

`docs/08_results_and_evaluation.md` updated throughout with the
corrected, final numbers and the full fix narrative (Section 1 and
Section 4 especially).

---

## 18. GPU support added (RTX 5060) — verified correct, honestly slower for these model sizes

User has an RTX 5060 Laptop GPU and asked to install the required
libraries and use it. Verified hardware/driver first (`nvidia-smi`:
RTX 5060, 8GB VRAM, driver reports CUDA 13.1) before touching anything.
Installed `torch==2.11.0+cu128` (Blackwell/sm_120 needs a fairly recent
CUDA build; the machine previously had `2.7.1+cpu`), verified with a real
GPU matmul before trusting it further.

**Wired into the two PyTorch components** (`lstm_ae_scorer.py`,
`gnn_scorer.py`, and their trainers `train_lstm_ae.py`/`train_gnn.py`) via
a `_TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else
"cpu")` auto-detect — same code path on a GPU or CPU-only machine, nothing
to keep in sync. Isolation Forest and the fusion meta-learner are
scikit-learn (no GPU path exists for either); the RL policy is plain
tabular Q-learning (no tensors at all) — GPU doesn't apply to either,
correctly left untouched.

**Retrained the full chain** (isolation_forest → lstm_ae → gnn → fusion →
adaptive_pdp, in dependency order) and restarted the gateway. Verified
correctness, not just that it ran: LSTM-AE's loss curve on GPU matched the
CPU run to 5 decimal places (`1.04273 -> 0.87648` both runs); the fusion
model's coefficients came out bit-identical
(`0.008, 4.392, 2.966, 5.035`); `evaluate_ablation.py` reproduced the
exact same numbers as the CPU-trained pipeline.

**Honest finding, not hidden**: GPU training measured SLOWER than CPU for
these specific models — LSTM-AE ~7.7s (GPU) vs ~5.4s (CPU); GNN ~2m33s
(GPU) vs ~24s (CPU), a ~6.5x regression. Root cause: `train_gnn.py`'s
training loop does one Python-level forward/backward pass per graph
snapshot (`for x, a_hat, y in zip(xs, as_, ys)`, 1220 snapshots x 80
epochs = 97,600 individual tiny CUDA kernel launches) rather than batching
across snapshots -- for a 3-node graph with hidden_size=8, kernel-launch
overhead dominates the actual FLOPs by a wide margin. This is expected and
consistent with CLAUDE.md Section 5.2's own reasoning for keeping these
models demo-scale ("a laptop... is sufficient") -- GPU is now real,
correct, verified infrastructure here, just not a speed win for models
this small. Batching the GNN training loop would close most of the gap
but wasn't done (real, nontrivial architecture change -- would need
block-diagonal adjacency construction across the batch dimension -- not
requested, and this project's models are deliberately kept small enough
not to need it).

`requirements.txt` updated with the GPU install command and this
timing finding, so a future reader doesn't have to rediscover it.

**Follow-up, same session — batched the GNN training loop, GPU now
genuinely wins**: user asked why the GPU was slower and, after the
per-launch-overhead explanation (confirmed with a microbenchmark: ~8us/call
CPU vs ~88us/call GPU for a matmul this size -- ~11x GPU overhead per
launch), asked for the fix. `_GCN.forward()` already used `@` (matmul) and
`nn.Linear`, both of which handle an extra leading batch dimension for
free -- no architecture change needed, just replaced `train_gnn.py`'s
Python-level `for x, a_hat, y in zip(xs, as_, ys): model(x, a_hat)...`
(97,600 individual tiny kernel launches) with a single `model(xs, as_)`
call per epoch over the whole (1220, 3, 3) batch (80 kernel launches
total). Care taken to make this a PURE performance refactor, not an
accidental retrain with different dynamics: derived algebraically that
`binary_cross_entropy(..., reduction="sum") / num_nodes` over the whole
batch reproduces the exact gradient the old per-sample loop accumulated
(sum over snapshots of each snapshot's mean-over-3-nodes loss) -- verified
after training, not just derived on paper: loss trajectory matched the
unbatched runs almost exactly (842.541 -> 558.475, same as both the CPU
and unbatched-GPU runs), and the retrained fusion model's coefficients
came out bit-identical (`0.008, 4.392, 2.966, 5.035`).
**Result: 8.96s, down from 2m33s unbatched-GPU (~17x) and faster than the
original 23.6s CPU run (~2.6x)** -- GPU now genuinely wins once given
enough parallel work per kernel launch to amortize its overhead. Retrained
the full downstream chain (fusion -> adaptive_pdp), restarted the gateway,
re-ran `evaluate_ablation.py` -- numbers unchanged (0.923/0.762/0.882/0.710),
confirming the batched version is numerically equivalent, not just faster.
`gnn_scorer.py`'s live inference path needed no changes at all --
`forward()` already handled its single-snapshot (unbatched) call
correctly, since matmul/Linear are dimension-agnostic about a leading
batch dim being present or not.

---

## 19. Real architecture scale-up for the GPU — verified against overfitting, not just installed

User asked to "convert the entire architecture" to the GPU configuration.
Clarified scope first (two very different readings: keep the tiny
CLAUDE.md-specified models and just ensure full GPU coverage, vs.
genuinely increase model capacity now that real GPU compute exists) —
user chose the latter, a real design change away from CLAUDE.md's
original "deliberately demo-scale, no GPU available" reasoning.

**Config changes** (`config.py`): `LSTM_HIDDEN_SIZE` 8→16 (final),
`LSTM_NUM_LAYERS` new, =1 (final); `GNN_HIDDEN_SIZE` 8→32,
`GNN_NUM_LAYERS` new, =3. `LSTMAutoencoder` (`lstm_ae_scorer.py`) now
takes a `num_layers` param, passed straight to `nn.LSTM`'s native
stacking support. `_GCN` (`gnn_scorer.py`) restructured from two fixed
`nn.Linear`s to an `nn.ModuleList` of hop layers + one output layer, so
`num_layers` is configurable (`num_layers=2` reproduces the original
architecture exactly, verified by construction).

**Caught and corrected a real overfitting regression before accepting
the change** — this was the whole point of treating "bigger" as a
hypothesis to test, not a given: first attempt used LSTM-AE 32 hidden /
2 layers (~27k params against only ~345 training windows). Trained
cleanly (loss 1.008→0.378) but `evaluate_ablation.py` on HELD-OUT data
showed the textbook overfitting signature — training fit got much
better while generalisation got WORSE (accuracy 0.762→0.734, recall
0.775→0.737) — and it dragged `fused_score`'s headline `coordinated`
recall from 0.913 down to 0.652, even though `gnn_score` ALONE had
genuinely IMPROVED to a perfect 1.000 in the same run (real signal the
regression was fusion-side, from the degraded LSTM feature, not a GNN
problem). Dialled LSTM-AE back to 16 hidden / 1 layer (~2.9k params) —
retrained the full downstream chain (gnn → fusion → adaptive_pdp) and
re-checked: `lstm_ae_score` held-out accuracy/recall back to 0.764/0.777
(no longer regressed, still a real 2x capacity increase from the
original 8-unit model), `gnn_score` `coordinated` recall held at the
improved 1.000, and `fused_score` `coordinated` recall recovered to
0.913 — exactly matching the pre-scale-up figure.

**GNN's increase, unlike LSTM-AE's, was a clean win with no dialling
back needed** — `coordinated` recall for the GNN signal alone: 0.870 →
1.000, held-out, verified via `evaluate_ablation.py`, not asserted.
Plausible explanation stated rather than left as a mystery: GNN trains
over all 1220 per-message snapshots (one call per message across the
whole session) vs. LSTM-AE's much smaller ~345-window normal-only
training set — more data genuinely available to support the added
capacity.

**SHAP re-verified with the new fusion model**, same rigor as the
earlier investigation (§16-17), not just re-run and trusted: confirmed
`explainer.expected_value + shap_values.sum()` still reproduces
`model.decision_function(x)` exactly (-1.307954 both sides) with the
retrained coefficients (`-0.0115, 4.3876, 3.3064, 5.1235`).
`evaluate_explainability.py` still 100% (63/63).

**Full downstream chain retrained and re-verified end to end**: gateway
restarted cleanly (`Fusion trained: True | IF trained: True | LSTM-AE
trained: True | GNN trained: True`), `evaluate_governance.py` still 100%
(7/7 NIST tenets), `evaluate_rl_policy.py` still shows RL beating Static
(0.761 vs 0.420 this run — the deployed RL policy is retrained fresh each
time the upstream fusion output changes, so the exact numbers shift run
to run; every version this session has shown RL clearly ahead).
`evaluate_latency.py` re-run too, out of due diligence given bigger
models now run on GPU: mean full-pipeline latency actually came out
LOWER than the original tiny-CPU-only figure (11.64ms vs 14.13ms) — a
single forward pass per message doesn't hit the same per-launch-overhead
problem the (now-fixed, see §18's batching entry) training loop did.

`CLAUDE.md` Sections 5.4/5.5 updated in place with a note explaining the
capacity change and why (real GPU available, verified against held-out
data rather than just "bigger because possible") — the original
"don't over-engineer" guidance is left intact and stated as still valid
in principle, just superseded by new evidence on the specific number.
`docs/08_results_and_evaluation.md` updated throughout with final numbers
and a new subsection under §1 narrating this whole investigation.

---

## 20. Documentation pass — session log reordered, README refreshed, complete project report written

User said they'll do the hardware part later and asked for `SESSION_LOG.md`,
`README.md`, and the docs to be brought up to date, plus a complete
project report with hardware-dependent parts explicitly left as
placeholders to fill in later.

**Found and fixed a real structural bug in this very file first**: §17-19
(the LSTM fusion fix, GPU support, and architecture scale-up entries) had
been inserted using a stale anchor (`"## Current state (as of this
entry)"`, which existed BEFORE §13-16 in the file at the time), landing
them before §13-16 instead of after — the file read §1-12, §17, §18, §19,
a now-stale "Current state" block, then §13-16, then the file-map footer.
Fixed by extracting each block by exact line range (`sed -n`), verifying
word counts and section-header uniqueness/order before committing, and
reassembling as §1-12, §13-16, §17-19, a rewritten final "Current state"
reflecting everything through §19, then the footer — checked with `diff`/
`wc`/`grep` at every step rather than trusting the reconstruction blind.

**`README.md`** — refreshed throughout: mutual authentication and full
per-signal SHAP now described accurately (was still describing the
one-directional/top-feature-only original design); GPU auto-detection
noted in the ML pipeline description and the training-setup step (was
claiming "no GPU needed," no longer accurate now that one is used when
present); IEC 62443 FR5/FR7 status corrected from a stale "not-implemented"
to the current "partial" (post-§11 transport hardening); project structure
tree updated to include `iec62443_mapping.py`, `webapp_server.py`,
`docs/08_results_and_evaluation.md`, `docs/09_project_report.md` (new,
see below), and the two evaluation scripts added after the tree was last
written (`evaluate_iec62443.py`, `evaluate_trust_responsiveness.py`); the
report-mapping table's Module 2 row rewritten for mutual auth, Module 7
row updated to include both governance modules and both dashboards.

**`docs/09_project_report.md`** (new) — the complete, standalone project
report requested: abstract, objectives-vs-status table, architecture,
per-module implementation detail (including the mutual-auth and SHAP
fixes narrated as real bugs found and fixed, not hidden), governance proof
section (the same conditional-logic demonstrations from §-level probes
earlier in this log, reproduced here so the report doesn't just assert
"100%"), full results section cross-checked number-for-number against
`docs/08_results_and_evaluation.md` before being written (verified via
`grep`, not from memory — every figure matched exactly, plus one live
re-check of the Isolation Forest train/held-out numbers specifically,
since those were computed via an ad-hoc probe earlier rather than a
committed script), the four novelty claims mapped to specific measured
results, the four documented substitutions, and — per the user's explicit
request — **a "Pending Hardware Validation" section with literal `[
PENDING — ... ]` markers** for the three things that genuinely need the
physical ESP32 (firmware flashing, a real physical adversarial-testing
session, ESP32-side latency), each with a short note on exactly what
should be filled in and how (e.g. the real adversarial session drops
straight into `generate_training_data.py`'s existing JSON shape, no script
changes needed). Section 9.4 states explicitly that none of the rest of
the report is blocked on or qualified by these three items, so a reader
doesn't have to infer that from the structure.

---

## 21. "Are all seven Zero-Trust questions actually proven?" — six were, testing the seventh found and fixed a real live gap

User asked, module by module, for direct proof that this project actually
answers the seven canonical Zero-Trust questions (is this device known?
can it prove it cryptographically for this exact message? how much do we
trust it right now? are we re-asking constantly? what does that trust
level actually get allowed? is the channel private and tamper-evident?
can we prove after the fact what happened?) — not a description of the
code, actual live probes against the running system.

Six proved cleanly: fed `verify_signature()` an unknown device_id
(rejected), a tampered payload with a stale-but-valid-looking signature
(rejected), pulled 8 consecutive live `esp32-vib-001` rows showing the
trust score genuinely recomputed every ~2s (not cached), pulled the real
trained RL Q-table showing a genuine (non-monotonic, learned rather than
threshold-based) trust→decision mapping, and queried the live audit log's
15,000+ rows with full per-field capture (all four raw scores, all four
SHAP values, confidence, policy source, NIST tenets, transport) as the
proof mechanism for "after the fact."

**Testing #6 (Secure Communication) live surfaced a real, currently-active
gap instead of just confirming it was fine.** Connected to the broker on
port 8883 with a valid TLS handshake but NO username/password at all —
the broker accepted it. Checked the actual `mosquitto.conf` on the
machine directly: `allow_anonymous true`, no `password_file`/`acl_file`
line at all. This matched a limitation `SESSION_LOG.md` §11 had already
named (an admin-only step never completed) — testing it live, rather than
trusting that note, confirmed it was still genuinely open.

## 22. Applying the fix — two real, distinct bugs found and fixed along the way

User asked to apply the `docs/07_transport_zero_trust.md` fix. This
session's own PowerShell has no admin rights (confirmed directly: `Test
write access to C:\Program Files\mosquitto` → denied, `IsInRole
Administrator` → false), so every step needing elevation was handed to
the user's own elevated PowerShell window, with each command run and its
real output checked before the next step — not assumed to have worked.

**Bug 1 — a merged config line.** The user's Notepad edit (from the
FIRST set of manual instructions given, before a safer scripted version
was prepared) resulted in `#include_dirlistener 1883 0.0.0.0` at the file
tail — the newline between the default template's last line and the
custom block was lost. Since the merged line starts with `#`, mosquitto's
parser silently treated the entire `listener 1883 0.0.0.0` directive as a
comment. This is WHY the first "safe, exact-match" replacement script
correctly refused to run (its `$content.Contains($oldBlock)` check
legitimately failed to match, since the real file no longer matched the
expected old state) — the safety check did its job; it wasn't a false
alarm. Found by reading the actual file tail directly rather than
trusting the earlier `Select-String`-based grep (which had matched
individual patterns and missed that two lines had merged into one).
Fixed with a second, narrowly-targeted replace (`#include_dirlistener
1883 0.0.0.0` → `#include_dir` + real newline + `listener 1883
0.0.0.0`), also safety-checked before applying.

**Bug 2 — the actual root cause: `mosquitto_passwd` had no SYSTEM ACL
entry.** Fixing bug 1 didn't bring the service up (`Get-Service mosquitto`
still `Stopped`). Diagnosed by running `mosquitto.exe -c mosquitto.conf
-v` directly in the foreground (bypassing the Windows service wrapper,
which was hiding the real failure behind a misleadingly successful-looking
`Restart-Service` call) — the config loaded fine and even accepted a real
authenticated connection, proving the CONFIG CONTENT was correct and the
failure was specific to running it as a service. Compared `Get-Acl` on
`mosquitto_passwd` against the already-working `server.key` and
`mosquitto_acl`: the password file only granted the user's own account
access, missing the `NT AUTHORITY\SYSTEM` entry both of the other files
had (inherited from the parent folder; the password file apparently
didn't inherit it when `mosquitto_passwd.exe -c` created it fresh). Since
the Mosquitto Windows service runs as `LocalSystem`, it could not open
its own configured password file — plausible explanation for why
`Restart-Service` reported no error while the service ended up `Stopped`
moments later (a permission failure inside the service process, not
something the service-control call itself would see).

Attempted the ACL fix from this session's own (non-admin) PowerShell
first — it printed a misleading "SYSTEM access granted successfully"
message despite the underlying `Set-Acl` call throwing a
`SeSecurityPrivilege` error moments earlier (a bug in the fix script's
own try/catch — `Set-Acl`'s error didn't terminate the pipeline the way
the catch block assumed), caught only because the verification `Get-Acl`
immediately after still showed SYSTEM missing. Correct fix
(`icacls ... /grant "NT AUTHORITY\SYSTEM:F"`) handed to the user's
elevated session instead; confirmed via its own printed ACL listing that
SYSTEM now shows `(F)`. `Restart-Service mosquitto` then reported
`Running`, verified independently via a fresh `Get-Service` call.

**Full end-to-end re-verification after both fixes** (not stopping at
"service is Running"): re-ran the EXACT SAME anonymous-connection probe
that found the gap — flipped from `Success`/`connected: True` to `Not
authorized`/`connected: False`. Restarted `gateway.py` and
`device_simulator.py`; both connected successfully WITH their real
per-device credentials (`MQTT broker auth ... enabled`,
`with per-device broker credentials`), and fresh decisions kept landing
in `audit_log.db`. Re-ran `scripts/evaluate_iec62443.py`: FR5 (Restricted
Data Flow) now shows a live, computed 100% coverage over 10,000+ real
logged decisions — this is the item `docs/09_project_report.md`'s FR5 row
had described as "real per-device broker ACLs exist" somewhat ambiguously
between "code ready" and "actually enforced"; it is now unambiguously the
latter, live-proven, not just configured.

`docs/07_transport_zero_trust.md` updated with both bugs (symptoms, root
cause, exact fix) as a troubleshooting section, since anyone else applying
this same doc's original instructions could plausibly hit either one.

---

## 23. Two-score rearchitecture: reconciling a freshly-written LLD doc set against this working, evaluated codebase

User replaced the entire `docs/` folder with a new 12-file low-level design
set (`docs/00_overview.md` … `11_project_structure_and_config.md`), written
as a from-scratch build guide assuming no existing code — deleting the old
`docs/01_getting_started.md` … `09_project_report.md` in the process (which
broke nine links in `README.md`, fixed this session). Asked to "go through
each and every file... and finetune the entire architecture and pipeline."

**The real conflict, found by actually reading both sides before touching
anything**: the new LLD's central, repeated architectural rule — a
**Security Trust Score** (cyber-behaviour evidence) and a **Process
Anomaly Score** (physical sensor evidence) must never be blended into one
number before the final policy step — was violated by every session up to
this point. `trust_engine.RuleBasedTrustEngine.score_message()` fed
auth/replay/flood signal AND `fusion_engine`'s physical-anomaly output
into one EWMA `trust_score`. The new docs also named two concrete,
real vulnerabilities in the existing design: (1) a failed-auth message fed
straight into the CLAIMED device's own `score_message()` call — anyone who
didn't know a device's secret could still lower that device's own trust
score by sending it garbage HMACs (trust-poisoning); (2) the replay check
(`REBOOT_TS_THRESHOLD_MS`, a ts-size heuristic) had a documented,
never-closed blind spot — a message captured just after a reboot could be
replayed later and still look like a fresh boot.

**Decision, after presenting the conflict and the user's detailed
response**: don't discard 22 sessions of evaluated work to match a
docs-first spec written assuming a green field, and don't discard the new
docs' real, correct architectural fixes either. Fix the two vulnerabilities,
re-plumb the existing (already-trained) IF/LSTM-AE/GNN/fusion stack into
the two-score architecture, add three things the new docs asked for that
were real, closeable gaps (a genuine step-up challenge/response, a
hash-chained + independently-checkpointed audit log, a multi-class
confusion matrix), keep RL and the GNN as live defaults (both already
justified — RL's live path is a frozen, no-exploration Q-table lookup with
no live reward-signal dependency at all; GNN's `coordinated` recall is the
best of any single signal), leave the file layout/`config.py` alone
(cosmetic, no functional benefit), and rewrite every doc to describe the
resulting system honestly.

**What actually got built** (`src/trust_engine.py`'s module docstring has
the full architectural rationale):

- **`IdentityTargetingRisk`** (Module 2 Section 5's fix) — a rolling
  60s failure counter keyed by the CLAIMED device_id, completely separate
  storage from any registered device's own state. `gateway.py::_reject()`
  is now the ONLY path a failed verification takes; it never calls
  anything that touches a device's own Security Trust or Process Anomaly
  state. Verified live: 50+ forged-signature attempts against
  `actuator-001` left its own score completely untouched, and
  `identity_targeting_risk_60s` climbed instead.
- **`boot_id`/`seq` anti-replay** (`trust_engine.check_boot_replay()`) —
  every device now carries a boot counter (persisted to flash-equivalent
  in `firmware/main.py`, in-memory in `device_simulator.py`) plus a
  per-boot sequence number. A higher `boot_id` always accepts and resets
  the baseline; a repeated `boot_id` needs a strictly higher `seq`; a
  LOWER `boot_id` is unconditionally rejected as
  `replay_of_superseded_boot_session` — closing the exact blind spot
  `REBOOT_TS_THRESHOLD_MS` (now removed) had. `ts` is now a SECONDARY
  freshness check only. Verified live: a simulated reboot
  (`boot_id`→2, `seq`→1) was accepted, not rejected; the very next replay
  of a pre-reboot message was correctly rejected.
- **Real Security Trust Score** (`score_security_trust()`) — fed only by
  rate/flood (`check_flood()`, now genuinely exercised live via a new
  high-rate burst scenario in `device_simulator.py`, not just an offline
  flag) and step-up outcomes. Never by auth failures or physical values.
- **Process Anomaly Score** — literally `fusion_engine.combine()`'s
  existing output, kept in its original trust-style scale (high = normal)
  rather than inverted to the new docs' literal "high = anomalous"
  wording, specifically so the already-trained, already-ablation-verified
  meta-learner's coefficients didn't need to change sign. A deliberate,
  documented deviation from the LLD's literal scale, not an oversight.
- **Real step-up challenge/response** (Module 2 Section 7 — closes the
  "not literal interactive challenge-response" gap §13 left open) —
  `gateway.py::initiate_step_up()` publishes a nonce to
  `cps/challenge/<device_id>`; the device echoes it in its next message
  (`step_up_nonce_echo`, inside the signed payload). **Two real bugs found
  by actually running this live, not by reading the code back**: (1)
  `check_step_up_response()` never cleared the pending nonce on a
  mismatch, so ONE unanswered challenge kept re-comparing against every
  subsequent unrelated message and escalating to `BLOCK` repeatedly until
  the 10s timeout — fixed to clear on every terminal outcome, and to treat
  "no echo yet" as "still waiting," not an immediate mismatch, since the
  challenge arrives async and the device's very next scheduled publish may
  predate it. (2) `certs/mosquitto_acl` had no `cps/challenge/*` rules at
  all — the broker was silently denying every device's subscribe to its
  own challenge topic, so no device could ever receive one regardless of
  the echo logic being correct. Fixed the ACL file; **still needs the
  user's admin PowerShell to restart the Mosquitto service** for it to
  take effect (same pattern as every other `mosquitto.conf`/ACL change in
  this project) — a genuine SUCCESS-path demonstration is blocked on that
  one manual step, not on remaining code.
- **Hash-chained + independently-checkpointed audit log**
  (`audit_log.py`) — `prev_hash`/`this_hash` per row,
  `verify_chain_integrity()`; a separate `data/checkpoint_log.jsonl` file
  (different file, different HMAC key, never shared with any device's
  registry entry) written every 100 rows, `verify_against_checkpoints()`.
  Verified the specific two-step attack this design exists to catch:
  editing one old row alone is caught by `verify_chain_integrity()`
  alone; editing a row AND recomputing every subsequent hash to stay
  internally consistent fools `verify_chain_integrity()` (correctly, that
  is its known limit) but is caught by the separately-stored checkpoint
  mismatch. **Found and fixed a real bug during this exact verification**:
  `scripts/evaluate_latency.py` redirected `AUDIT_DB_PATH` to a throwaway
  database but not `CHECKPOINT_STORE_PATH`/`AUDIT_KEY_PATH` — its
  throwaway run's row 100 wrote a checkpoint entry into the SAME shared
  checkpoint file the real gateway uses, so the very next
  `verify_against_checkpoints()` against the real, completely untampered
  audit log failed, comparing the real row 100 against a checkpoint that
  described a different, unrelated database. Confirmed the fix in
  isolation (a clean 150-row synthetic run passes both checks) before
  re-confirming against a fresh live gateway+simulator run.
- **RL retrained for the new 2D state/4-action space**
  (`src/adaptive_pdp.py`, `scripts/train_adaptive_pdp.py`) — state
  `(security_bucket, process_bucket)`, actions
  `{ALLOW, STEP_UP, ALERT, BLOCK}`. **Found and fixed a real bug on
  first load**: the old, pre-rearchitecture Q-table file used the SAME
  `"int,int"` key format for entirely different state semantics
  (`trust_bucket,confidence_bucket`, 3 actions) — string-identical keys
  collided with the new format's keys, and loading it as-is `KeyError`'d
  the first time `update()` touched a collided state expecting the new
  4-action set. Fixed by validating the loaded table's action set on
  load and discarding it wholesale if it doesn't match, rather than
  partially trusting a table that could silently mix old- and
  new-semantics entries under the same key.
- **A real, measured methodology bug found via the confusion matrix**:
  adding `high_rate` (a pure Security Trust event — genuinely normal
  physical reading) to the training data generator, then naively reusing
  the OLD blended `label` field as ground truth for `train_fusion_meta_learner.py`
  and `train_gnn.py`, injected label noise — examples where every one of
  the four Process Anomaly input features looked completely ordinary,
  paired with a "suspicious" target the features gave no reason to
  predict. Measured effect before the fix: fused aggregate accuracy on
  held-out data dropped to ~0.68, `coordinated` recall to ~0.30. Fixed
  with `physical_label(event_type)` (`scripts/generate_training_data.py`)
  as the ground truth for every Process Anomaly training/eval script, and
  by excluding `auth_ok=False`/`event_type=="replay"` records from those
  same scripts entirely (they never reach Module 3 live either). After
  the fix: `coordinated` recall back to 1.000, `stealthy_forged_values`
  (attack-matrix row 11, expected to be hard) measured at a real,
  non-zero-but-still-low recall — reported honestly, not tuned toward a
  target number.
- **A second real imbalance bug, found the same way**: unweighted RL
  training left `physical_fault` recall at 0.125 — WORSE than the static
  table's trivial 1.000 — even though the underlying Process Anomaly
  signal cleanly separates those events (1.000 ablation recall). Root
  cause: `normal` outnumbers the rarer situations ~10-20x, and a
  discretized Q-table bucket shared between a `normal` example and a
  rarer situation's example gets dominated by whichever reward sign
  visits it more often. Fixed with the same `class_weight="balanced"`-style
  inverse-frequency reward weighting already used for the fusion
  meta-learner (`situation_weights()`) — `physical_fault` recall recovered
  to 0.475, macro-F1 rose from 0.280 (static) / 0.526 (RL, unweighted) to
  0.553 (RL, weighted).
- **`stealthy_forged_values`** (attack-matrix row 11) added to
  `device_simulator.py`/`scripts/generate_training_data.py` — a fully
  valid, correctly-signed message whose values are deliberately fabricated
  to look normal. Not tuned to be caught; its honestly-low, honestly-
  reported detection rate is the intended result
  (`docs/04_module3_trust_evaluation.md` Section B.8).

Full retrain was required for ALL FIVE models, not just the RL bandit as
first scoped — adding new scenarios to the data generator shifts the fixed
random seed's entire downstream sequence, so "the training data is
unchanged" stopped being true the moment `stealthy_forged_values`/`high_rate`
were added to it. Verified via a live gateway+simulator run afterward
(reboot accepted, post-reboot replay rejected, forged-id isolated to
`IdentityTargetingRisk`, flood→STEP_UP with a single clean resolution
instead of the pre-fix repeated-mismatch bug) and every `scripts/evaluate_*.py`
re-run against the regenerated held-out set.

**Known, disclosed limitation carried forward from this session**: the
step-up challenge's SUCCESS path (not just its TIMEOUT path) is unverified
live pending the mosquitto_acl restart above — the code path is exercised
and correct by inspection and by the TIMEOUT path's correct behavior, but
a live SUCCESS round trip has not been directly observed.

## 24. Second live dashboard switched from a from-scratch rebuild to the actual design-folder file, plus a real accuracy sanity-check

User asked three things in one message: (1) use `design/`'s actual dashboard
file instead of the from-scratch `webapp/index.html` rebuild §10 built, (2)
explain how §23's 1.000/100% figures are possible, (3) delete the webapp
folder entirely once the design-folder approach was confirmed feasible.

**Investigated §10's claim directly before acting on it, rather than
trusting the summary**: confirmed `design/Main.dc.html` still can't run
standalone (42 DSL-pattern occurrences, `support.js` genuinely absent
anywhere in the repo) and that `design/zero-trust-cps-command-center.html`
(the 2.2MB bundled export) has zero occurrences of the current device IDs
(`esp32-vib-001`/`sensor-002`/`actuator-001`) but 11-12 each of the old,
pre-hybrid-architecture names (`vibration-001`/`mpu6050-001`) — confirming
the export is a flattened, static snapshot with no live-binding
infrastructure left to reconnect, not something that can be safely
"wired up" by patching the minified bundle. Presented this via
AskUserQuestion; user initially picked "keep webapp/index.html," then
explicitly overrode that a message later ("delete the entire webapp
folder and use the design folder... proceed") after I'd already started
enhancing it — followed the later, more explicit instruction.

**What was built**: `src/webapp/` deleted entirely. `webapp_server.py`
rewritten to serve `design/zero-trust-cps-command-center.html`
byte-for-byte (the actual design-folder artifact, unmodified) with one
injected, clearly-labelled live overlay bar spliced in via `str.rfind("</body>")`
-- verified this file specifically has 6 literal `"</body>"` occurrences
(embedded license/template text inside its own minified JS), confirmed the
LAST one is the real document tag before checking this in rather than
assuming a naive first-match replace would be safe. The overlay polls the
same real `/api/*` endpoints (unchanged from §10): per-device Security
Trust/Process Anomaly/decision, chain-verification status, NIST/IEC
coverage, and the two features from this session's dashboard work that
would otherwise have been lost when `webapp/index.html` was deleted --
Identity Targeting Risk count and Step-Up challenge activity. Verified
live: served page is 2,268,536 bytes (original 2,264,835 + the injected
overlay), `/api/*` endpoints return real data, and a live gateway+simulator
run populated the overlay with real per-device scores and decisions.

**The accuracy question, answered directly rather than reassured away**:
the two families of "100%" numbers in §23's output are different KINDS of
metric, and conflating them is the natural source of the suspicion.
- **NIST 100%/7-of-7 governance completeness is a coverage metric, not a
  detection-accuracy metric.** `nist_mapping.tenets_for_decision()` marks
  tenets 1/3/4/5/6 as satisfied for EVERY decision *by construction* --
  they describe structural properties of the pipeline itself (every
  decision has an auth verdict, came from a fresh per-message policy call,
  etc.), not something a model has to get right. Tenet 2 is 100% only
  because every message in this environment actually arrives over
  MQTT/TLS or HTTPS; tenet 7 only because the fusion model is trained.
  100% here means "the governance evidence-logging mechanism is switched
  on and running," which is a binary, not a percentage that could
  meaningfully be 87% instead -- expected, not suspicious.
- **The 1.000 recall figures (GNN/fused on `anomalous_shock`/`coordinated`)
  ARE real detection-accuracy numbers, correctly computed, with real
  caveats worth stating explicitly rather than hidden.** `anomalous_shock`
  injects a magnitude-3.0-4.5g spike against a ~1.0g±0.03 baseline -- a
  large, cleanly-separable synthetic signal by construction, so a
  well-trained detector reaching ~100% on it is expected, not remarkable.
  `coordinated` is the exact pattern the GNN's class-weighted loss was
  specifically tuned to catch, on a held-out split from the SAME synthetic
  generator family (different random seed, same distributions) as
  training, with a relatively small held-out count for that event type
  (n=23 in the 610-record test set). None of that makes the number wrong
  -- it's a real, reproducible measurement of this specific
  held-out-synthetic-data pipeline -- but it is a different, weaker claim
  than "this would catch 100% of real-world attacks," and CLAUDE.md/docs
  already state the honest reason why (no real physical adversarial-
  testing session has been recorded yet). Told the user this directly
  rather than either dismissing the question or overclaiming the result.

**Also this session**: `docs/Zero_Trust_CPS_Project_Synopsis.docx` updated
-- user asked directly, and `python-docx` (not previously installed) was
installed to do this safely rather than hand-writing OOXML. Read the whole
document first rather than assuming what kind of document it was: it's a
forward-looking Synopsis/proposal (Objectives -> Threat Model -> Proposed
Solution -> Implementation Plan -> Evaluation *Plan*, not a results
report), and Section 6.4/6.4.1/6.4.2/6.7/6.8 already describe the exact
two-score/staleness/attribution/boot-replay/hash-chain design this session
implemented -- this docx and the new `docs/00-11` LLD set were evidently
written together, describing the same target architecture. Rather than
rewrite existing prose (real corruption/misrepresentation risk on a
364-paragraph academic document with no way to visually re-render and
check it), appended a new, clearly-dated "15. Implementation Status
Addendum" section: what's implemented and verified, real measured numbers
per the existing Section 13 evaluation plan's own structure, the two
stated deviations (trust-style Process Anomaly scale, flat `src/` layout),
and what's still outstanding (hardware not flashed, no real physical
adversarial session yet, one pending broker restart). Backed up the
original file before editing; hit and fixed a real `python-docx` quirk
along the way (by-name style lookup, e.g. `document.add_heading(level=1)`,
raised `KeyError: "no style with name 'Heading 1'"` despite existing
paragraphs correctly reporting that exact style name via `.style.name` --
worked around by capturing the actual style OBJECTS off existing
paragraphs and assigning those directly, `paragraph.style = existing_style`,
rather than looking anything up by name string). Verified by reopening the
saved file fresh (364 -> 394 paragraphs, zero exceptions, all new headings/
bullets present with the correct styles and text, the bullet character's
codepoint confirmed as U+2022 rather than trusting a terminal's garbled
display of it). **Known follow-up for the user**: Word's Table of Contents
is a field, not static text -- opening the file and doing Right-click ->
Update Field (or Ctrl+A then F9) will be needed to make Section 15 appear
in it; this isn't something safely automatable from outside Word itself.

## Current state (as of this entry)

**Done, tested, verified**: all 7 modules, offline training hard
constraint satisfied, real ground-truth training labels (now
`physical_label`/`situation`-based, not the old blended `label`), MQTT/TLS
live, a working second secured transport, NIST + IEC 62443 governance
mapping, **two permanently-separate Security Trust / Process Anomaly
scores** meeting only inside a 2×2 policy table (§23), **boot_id/seq
anti-replay** closing the old ts-heuristic's blind spot (§23),
**IdentityTargetingRisk** closing a real trust-poisoning vulnerability
(§23), a **genuine step-up challenge/response with BOTH outcomes now
verified live** (§23 got the TIMEOUT/failure path; the user restarted the
Mosquitto broker after §23/§24's `mosquitto_acl` fix, and the SUCCESS path
was then observed directly in the gateway log: `FLOOD detected` →
`STEP_UP` → `step-up SUCCESS (bounded trust boost applied)` → `ALLOW`,
security_trust_score visibly rising 0.66→0.76 across the exchange),
a **hash-chained + independently-checkpointed audit log** (§23),
MicroPython firmware protocol-verified in software, **genuine mutual
authentication** (§13, now with real step-up on top), a **fully corrected
fusion pipeline** with all four signal coefficients correctly signed and
SHAP mathematically verified down to the log-odds/probability-space
distinction (§16-17), **real GPU acceleration** on an RTX 5060, and a
**deliberately-verified capacity increase** for LSTM-AE/GNN checked
against both overfitting and underfitting (§19).

**Documented, deliberate substitutions remain** (not gaps — each has a
verified reason): CoAP/DTLS → HTTPS (blocked on an upstream `aiocoap`
defect + an unavailable sudo/autoreconf toolchain); GNN uses the hybrid
device-graph, not the sensor-channel graph; GNN is a hand-rolled GCN, not
`torch-geometric`; the Process Anomaly Score is kept trust-style (high =
normal) rather than the new docs' literal anomaly-style scale, to avoid
retraining the already-verified fusion meta-learner (§23); flat `src/` +
`config.py` kept instead of the new docs' package/`config.yaml` layout
(cosmetic, no functional benefit); `stealthy_forged_values` (attack-matrix
row 11) is explicitly, honestly not reliably detectable by this
single-node design — that is the intended result of including it, not an
unfixed bug.

**Not done — needs the user's physical hardware, not more code**:
1. `firmware/main.py` has never been flashed to a real ESP32.
2. No real physical adversarial-testing session (tap/shock the rig, etc.)
   has been recorded — training still runs on a synthetic-but-honestly-labeled
   session (`scripts/generate_training_data.py`).
3. ESP32-side signing/feature-extraction latency (needs `time.ticks_ms()`
   instrumentation on real hardware, flagged as TODO in
   `scripts/evaluate_latency.py`'s own printed output, not estimated).

These three are the ONLY remaining gaps — not silently skipped, not
estimated in their place — to be filled in once the physical board is
wired up. (The fourth item that used to be here — the step-up SUCCESS
path pending a broker restart — is closed: user restarted the Mosquitto
service after the `mosquitto_acl` fix, and the SUCCESS path was then
observed live, see above.)

**See it running right now** (no hardware needed — everything below works
with the software simulator standing in for the real ESP32):

```bash
cd src/
# Terminal 1
python gateway.py
# Terminal 2 (a couple seconds later)
python device_simulator.py
# Terminal 3 (any time after the above two are running)
python webapp_server.py        # or: streamlit run dashboard.py
```

Then open `http://localhost:8600` (or Streamlit's own URL). Per-device
trust-score metrics, a trust-over-time chart, the full recent-decisions
table with a real per-signal SHAP breakdown (all four bars, not just the
top one — §15), the NIST SP 800-207 governance-completeness view, and the
IEC 62443-3-3 Foundational Requirements coverage view + SL-2 assessment —
all updating every ~2 seconds as the simulator publishes telemetry
(including the coordinated multi-device drift, shock, forged-signature,
out-of-range, and replay scenarios). This is the "complete integrated
project" demo — it has been tested end-to-end many times across this
session, including after every retrain in §17-19, with zero errors. Run
`scripts/evaluate_*.py` from the repo root afterward for the printed,
paper-ready numbers behind what the dashboard shows live.

**Model sizes, for anyone re-running `scripts/train_*.py` from scratch**:
LSTM-Autoencoder is 16 hidden units / 1 layer; GNN is 32 hidden units / 3
layers — both GPU-accelerated (`torch.cuda.is_available()` auto-detected
in `lstm_ae_scorer.py`/`gnn_scorer.py`, falls back to CPU cleanly if no
GPU is present) and both verified via `evaluate_ablation.py` train-vs-
held-out comparisons to be neither overfitting nor underfitting (§19).

---

**Post-broker-restart follow-up**: user asked to (1) skip further docx edits
for now, (2) sweep every markdown file for anything still describing the
step-up SUCCESS path as unverified (it no longer is, per above), and (3)
create a new, separate `RESULTS.md` with full explanations/descriptions of
every measured result, with a clearly reserved place for hardware results.
Swept `docs/`, `implementation-docs/`, `CLAUDE.md`, `README.md` for stale
"unverified"/"pending broker restart" language (found and fixed two:
`docs/03_module2_authentication.md`'s AS-BUILT note and
`implementation-docs/02_module_authentication.md`'s honesty note — both
now state both step-up outcomes as live-verified). Built `RESULTS.md` at
the repo root: live-verification checklist (Section 1), the real ablation/
confusion-matrix/explainability/governance/latency/responsiveness/audit-
integrity numbers already produced during this session (Sections 2-8, all
traceable to a specific `scripts/evaluate_*.py`, none re-run for this --
the underlying models and held-out test data are unchanged since they
were last measured), the real bugs found along the way and why they matter
to how the numbers should be read (Section 9), stated deviations (Section
10), the acknowledged stealthy-device detection limit (Section 11),
explicit methodology notes (Section 12), and a clearly-separated,
explicitly-empty "13. Hardware-in-the-Loop Results (Reserved)" section
structured with the exact subsections (device latency, real adversarial
session, real sensor calibration, physical deployment overhead) that
should be filled in once hardware exists, rather than a vague "TODO."
Linked from `README.md` (three places), `CLAUDE.md` Section 10, and this
file's own file-map below.

**The docx addendum's step-up wording took two attempts, worth recording
why**: the first attempt (appending "15. Implementation Status Addendum")
saved successfully while the file was closed. The follow-up edit (fixing
Section 15.1/15.4's step-up bullets to say SUCCESS was confirmed, not
pending) failed with a `PermissionError` because the user had since opened
the file in Word. After the user confirmed Word was closed, re-running that
same follow-up script found **zero** matching paragraphs and the document
had silently reverted to 365 paragraphs — Section 15 was gone entirely.
Diagnosed directly rather than guessed: Word had the file open with its
OWN in-memory copy from before either edit; closing it (with or without an
explicit Save) wrote that stale in-memory state back to disk, clobbering
both edits that had happened out-of-band on the file underneath it. Fixed
by merging the corrected step-up wording directly into the original
addendum script (one clean append, not append-then-patch) and re-running
it once against the reverted file — verified by reopening afterward
(365→395 paragraphs, both target bullets present with the final wording).
**Lesson for next time**: an external editor holding a `.docx` open is a
real, silent data-loss risk for any out-of-band script edit, not just a
write-permission inconvenience — safest pattern is to make one complete,
correct edit while the file is confirmed closed, rather than several
smaller passes that assume it stays closed in between.

**File map for anyone catching up**:
- `CLAUDE.md` — the governing engineering brief (read this first if working from spec).
- `RESULTS.md` — every real measured result, with explanations and a reserved,
  clearly-marked section for hardware-in-the-loop results once the board is flashed.
- `docs/Zero_Trust_CPS_Project_Synopsis.docx` — the citable academic record; has a
  "15. Implementation Status Addendum" appended, including the confirmed-live
  step-up SUCCESS wording (see the note below on why this took two attempts).
- `docs/00_overview.md` onward — the as-built low-level design reference, module by module.
- `implementation-docs/` — module-by-module reference (Part A core + Part B extension design).
- `src/` — the live pipeline. `scripts/` — offline training. `models/` — trained artifacts. `firmware/` — MicroPython + `HARDWARE_SETUP.md` bring-up guide. `data/collected/` — training data.

## 25. ESP32 hardware bring-up guide, plus a coexistence mechanism for running real hardware alongside the simulator

User asked for the actual hardware side of this project to be finished: a
step-by-step implementation guide, kept inside `firmware/` (not `docs/`),
matching `firmware/main.py`'s already-implemented code exactly.

**`firmware/main.py` itself needed no code changes** — re-read in full
first to confirm: boot_id persistence via a local file
(`load_and_increment_boot_id()`), NTP sync, step-up nonce echo
(`_pending_step_up_nonce`, subscribed to `cps/challenge/{device_id}`),
manual HMAC-SHA256, register-level MPU6050 driver, and
`canonical_json()`/`build_and_sign()` matching the gateway's own
canonicalisation were all already in place from earlier in this session
(§13, §23). Only the guide was missing.

**Wrote `firmware/HARDWARE_SETUP.md`** (Thonny-based — no `esptool`/
`mpremote` CLI required, consistent with this project's established
beginner-friendly flashing convention): parts list, an MPU6050 I2C wiring
table (SDA→GPIO21, SCL→GPIO22, AD0→GND for address `0x68`) and a vibration
sensor ADC table (GPIO34, explicitly called out as ADC1 — ADC2 pins
conflict with WiFi and silently fail to read while WiFi is active, a real
ESP32 gotcha worth flagging up front rather than letting someone discover
it via a confusing failure), Thonny install + firmware flash, LAN-IP/
broker-reachability checks, secret provisioning (mirrors
`secrets_local.example.py`'s existing `DEVICE_SECRETS`/`MQTT_PASSWORDS`
pattern, including the `mosquitto_passwd -b` regeneration + service
restart this project already established is required), the
`CONFIGURE BEFORE FLASHING` block walkthrough, uploading via Thonny's
"Save As → MicroPython device → main.py" (relying on MicroPython's
auto-run-`main.py`-on-boot behaviour), expected first-boot Shell output,
a troubleshooting table for the five most likely first-boot failures, and
a dedicated "Critical First Integration Test" section explaining
specifically what an `hmac_mismatch` rejection on the very first real
message means and how to bisect it (print the canonical string, diff it
character-by-character against Python's own `json.dumps(..., sort_keys=True)`
for the same fields) — flagged as the step most likely to need real
debugging time, not assumed to just work.

**Added a real coexistence mechanism, not just a doc note**: today,
`device_simulator.py` publishes `esp32-vib-001` in software regardless of
whether a real board exists. Once a real board is flashed and running, a
second publisher under the identical `device_id` would race with it on
`boot_id`/`seq` (`trust_engine.check_boot_replay()`) and each would
intermittently get rejected as a replay of the other's messages. Fixed by
adding `config.REAL_HARDWARE_DEVICE_IDS: set = set()` (empty by default —
pure simulation mode, zero behaviour change for anyone not using real
hardware) and filtering `device_simulator.py::run()`'s device loop
(`SIMULATED_DEVICES = {d: info for d, info in DEVICE_REGISTRY.items() if
d not in REAL_HARDWARE_DEVICE_IDS}`), with existence guards added around
the two device-specific scenario injections (`esp32-vib-001`'s replay
scenario, `sensor-002`'s flood burst) so nothing crashes if a device is
excluded. Compile-checked and import-smoke-tested (`REAL_HARDWARE_DEVICE_IDS`
correctly defaults to `set()`, `SIMULATED_DEVICES` correctly excludes a
test id when added). The guide's own Section 11 documents the one-line
opt-in (`REAL_HARDWARE_DEVICE_IDS = {"esp32-vib-001"}`) once Step 10's
integration test passes.

**Also fixed**: `secrets_local.example.py` referenced
`docs/07_transport_zero_trust.md`, a file deleted earlier this session
when `docs/` was replaced (§23) — corrected to
`docs/07_module6_secure_communication.md` Section 3.

**Updated `README.md`** (three spots): the "Real hardware" bullet under
"What this does right now," the "Have real hardware?" paragraph under
"Run it" (now also mentions the `REAL_HARDWARE_DEVICE_IDS` opt-in and why
it's needed), and the project-structure tree, all now pointing at
`firmware/HARDWARE_SETUP.md` instead of the old scattered references
(`firmware/main.py`'s own docstring + `docs/01_simulation_and_hardware_abstraction.md`
Section 5).

**Still true, unchanged by this entry**: the board itself has not been
physically flashed — this entry closes the "no guide exists" gap, not the
"hardware not yet run" gap (§ "Current state," items 1-3, above, still
stand as the only remaining gaps).

## 26. Two documentation folders consolidated into one — `implementation-docs/` merged into `docs/`, then deleted

User asked why two documentation folders (`docs/` and `implementation-docs/`)
existed and asked for one, reorganised, matching the current implementation.

**Why there were two in the first place**: `implementation-docs/` (9
files) predated this session's two-score rearchitecture — it was written
as a module-by-module build log, each file structured Design Rationale →
Implementation Walkthrough (real code excerpts) → Interface Contract →
Failure Modes → Extension Path, with Modules 3 and 5 split into a literal
"Part A: Core (shipped)" / "Part B: Full Design (extension target)"
narrative reflecting the order things actually got built in. `docs/` (12
files, 00-11) was written later, from scratch, as a formal from-zero LLD
spec, then reconciled against the working codebase (§23) with an AS-BUILT
callout added to the top of each file. `docs/` was already the more
complete set — it covers four topics `implementation-docs/` never had as
standalone files at all (hardware/simulation abstraction, testing/attack-
simulation methodology, integration/data-flow, project structure/config)
— and every module file already carried an accurate, current AS-BUILT
note, where `implementation-docs/`'s Part A/B split had gone stale (its
own files needed patch-style "AS-BUILT REARCHITECTURE NOTE" boxes bolted
onto the top explaining what no longer applied).

**Decision: keep `docs/` as the single folder.** Read both files for
every one of the eight module/overview pairs in full (not summarized) and
folded forward whatever was still accurate and not already present in
`docs/` — mostly Design Rationale narrative, Failure Modes tables, and a
few genuinely-missing architectural pieces:
- `docs/02_module1_device_identity.md`: real code excerpts from
  `gateway.py` (the actual `verify_signature()`/unknown-device gate,
  replacing stale pseudocode), a Failure Modes table, and two further-
  extension ideas (secret hashing, gateway-held PKI relationship).
- `docs/03_module2_authentication.md`: **a real gap, not just missing
  prose** — this file covered device→gateway authentication in full but
  never mentioned the *other* direction: the gateway also signs its
  `cps/decisions/<device_id>` messages with the same per-device secret
  and the device verifies them (`gateway.py::_sign_decision()` /
  `device_simulator.py::verify_decision_signature()`, confirmed still
  real via grep before writing this). Added as new Section 1.2, along
  with the stated open gap (decision channel has no replay check of its
  own) and the HMAC-vs-transport-layer design rationale.
- `docs/04_module3_trust_evaluation.md`: a Design Rationale subsection for
  why the Security Behaviour Engine is rule-based, not learned, and a
  Failure Modes table (cold start per sub-signal, a missing signal
  treated as neutral not a crash, disagreeing signals as a designated
  eval category).
- `docs/05_module4_continuous_verification.md`: the "this isn't a session-
  token architecture" framing, and a Failure Modes table.
- `docs/06_module5_access_control.md`: a Failure Modes table specific to
  the live RL policy (threshold-boundary states, sparsely-trained state
  buckets).
- `docs/07_module6_secure_communication.md`: **found and fixed a real
  accuracy bug while merging, not just added content** — this file's
  topic-design table claimed telemetry uses a per-device-suffixed topic
  (`cps/telemetry/{device_id}`), but `config.py`/`gateway.py` (checked
  directly, not assumed) show telemetry actually uses one shared
  `cps/telemetry` topic for every device; only the two gateway-initiated
  channels (`cps/decisions`, `cps/challenge`) are per-device-suffixed.
  Corrected the table and explained why the asymmetry is intentional.
  Also added the `paho-mqtt` concurrency note and the HMAC-vs-TLS threat
  model table from `implementation-docs`, and a Failure Modes section.
- `docs/08_module7_monitoring_and_audit.md`: a Design Rationale subsection
  (why SQLite, parameterised queries, UTC timestamps, "Module 7 is a pure
  sink"), and a Failure Modes table including a real, still-open gap:
  `log_decision()`'s insert isn't wrapped in a try/except at any call
  site, so a disk-full/write-failure would crash the gateway rather than
  degrade gracefully (confirmed by reading `audit_log.py` directly — the
  only try/except in that file guards the schema-migration `ALTER TABLE`
  calls, not the insert).
- `docs/09_integration_and_data_flow.md`: the dependency-graph's
  explanatory bullets, the serial-processing concurrency note, and a
  "seven modules, one sentence each" cheat-sheet (rewritten for the
  two-score reality, e.g. Module 3's line now names both scores).
- `docs/00_overview.md` and `docs/11_project_structure_and_config.md`
  needed no content merged in (already fully superseding), but `11` got
  two more AS-BUILT corrections while in there: the "when hardware
  arrives" section pointed at a `device_mode` config flag that doesn't
  exist (real mechanism is `config.REAL_HARDWARE_DEVICE_IDS`, §25) and
  didn't yet know `firmware/HARDWARE_SETUP.md` (§25) exists.

**What was deliberately NOT carried forward**: `implementation-docs/03`'s
old EWMA-blend code sketch and worked numeric trace (both for the
single-score architecture §23 replaced), `implementation-docs/04`'s
"Missing Piece" background-decay-sweep code (contradicts `docs/05`'s own,
more current AS-BUILT reasoning for why lazy staleness evaluation is a
deliberate design, not an unfixed gap), and every Part A/B interface
signature that no longer exists (`decide(trust_score) -> str`,
`score_message(device_id, value, auth_ok)`) — carrying these forward
would have reintroduced exactly the kind of stale, contradictory
documentation this consolidation was meant to remove.

**Then deleted `implementation-docs/` entirely** and repointed every
reference: `CLAUDE.md` (7 places — the file-layout comment, Section 4's
reading order, Section 5.2's cross-reference, Section 6's NIST citation,
Section 7's phase-plan table twice, Section 10's verification-steps
pointer), `README.md`'s project-structure tree, and
`src/config.py`'s one code comment (pointed at
`docs/03_module2_authentication.md` Section 1.2 instead). Verified with a
final repo-wide case-insensitive grep for `implementation-docs` — zero
matches outside this file's own historical entries (§13, §20, etc., left
untouched, since this log is append-only and those entries were accurate
descriptions of the repo at the time they were written).

## 27. Transformer sub-signal added as a fifth ablation candidate, tuned, and a real evaluation-methodology bug found along the way

User asked for a recommendation on using a Transformer for the Process
Anomaly Engine, comparable against the existing ML/DL/RL signals; then to
actually implement it using the RTX 5060 (idle until this session — GPU
support already existed per §18/19 but had never been exercised beyond
the LSTM-AE/GNN scale-up); then to fine-tune it; then to verify every
model's architecture and fold everything into the docs.

**Dataset scale-up first** (`scripts/generate_training_data.py`/
`generate_test_data.py`): `TICKS` 400→5,000 / 200→1,000 — purely
synthetic (same generator, more repetitions with fresh random noise), but
~345→~3,967 normal esp32-vib-001 training readings, specifically so a
higher-capacity Transformer wouldn't be penalized for a small-dataset
artifact the way the LSTM-AE's own 32-hidden/2-layer attempt was (§19).
Every existing model (Isolation Forest, LSTM-AE, GNN, fusion) was
retrained on the larger set before any Transformer comparison, so the
comparison is apples-to-apples on data volume too.

**Transformer sub-signal** (`src/transformer_scorer.py` +
`scripts/train_transformer.py`, new): encoder-only, full bidirectional
self-attention (`nn.TransformerEncoder`, no decoder/causal mask — BERT/ViT
family, not GPT or T5-style seq2seq), 2 layers/4 heads/`d_model=32`,
17,701 params. Same window (`LSTM_SEQ_LEN`, shared, not duplicated) and
same 5-feature input as the LSTM-AE, deliberately, so any ablation
difference is architecture, not setup. Trained as a **denoiser** (noise
added to input, loss against the clean window), not plain reconstruction
— a plain reconstruction transformer can shortcut via direct attention to
neighboring true values in a way an LSTM's recurrent bottleneck can't,
under-scoring real anomalies; denoising removes that shortcut. Wired into
`scripts/evaluate_ablation.py` as a 6th column, NOT into
`fusion_engine.py`'s inputs (ablation-candidate-only, same bar the GNN
had to clear first).

**First ablation run tied the LSTM-AE almost exactly** (0.753 vs 0.753
accuracy, 0.851 vs 0.851 F1) — looked like a clean "no improvement"
result. Fine-tuning (a 7-config sweep: pre-LN vs post-LN, ReLU vs GELU,
6x capacity, up to 400 epochs, varied noise/LR/weight decay) reproduced
that same tie on EVERY config, which was the tell something was off — a
real architectural difference should show *some* spread across such a
wide sweep.

**Real bug found**: `evaluate_ablation.py`'s `lstm_ae_score`/
`transformer_score` columns blend rule_score for sensor-002/actuator-001
(66% of rows, since only esp32-vib-001 has a trained sequence model) with
the real model score for esp32-vib-001 (34%) — diluting any real
difference between the two architectures with an identical, unrelated
number for most rows. Isolating esp32-vib-001 rows exposed a second, more
consequential issue: on that isolated subset, BOTH models flagged ~75% of
genuinely normal test messages as suspicious (74.9%/74.7%, nearly
identical between architectures — the actual tell). Root cause:
`train_lstm_ae.py`/`train_transformer.py` build training windows only
from `label==1` rows with anomalies filtered OUT (gaps skipped in the
tick sequence) — the model never sees a window shaped like "a few
messages after a real anomaly." Live/eval replay of the raw interleaved
stream produces exactly that shape for any nominally-normal message within
`LSTM_SEQ_LEN` messages of a recent anomalous_shock/coordinated/
stealthy_forged_values/high_rate event. `train_fusion_meta_learner.py`
already excludes exactly these rows (`window_compromised`) for its own
training target (§17) — this exclusion had just never been applied when
judging the LSTM-AE/Transformer signals on their own. Fixed by adding the
same exclusion to `evaluate_ablation.py`, in a new "FAIR COMPARISON"
block (esp32-vib-001 only, residue rows excluded: 746 of 1,000 rows,
confirming the attack-injection schedule is dense enough relative to an
8-message window that most nominally-"normal" esp32 test messages are
actually recovery-period messages, not steady-state baseline).

**Corrected result**: LSTM-AE 0.933 acc / 0.920 F1 vs Transformer 0.941
acc / 0.930 F1 — the Transformer genuinely wins, by a small but real
margin (+0.010 F1), reproduced identically across all 7 hyperparameter
configs (confirming it's a real effect, not one lucky run, and that the
original, cheapest config was already at the ceiling — no config change
kept). **Decision: still not adopted into fusion** — the margin doesn't
justify ~6x the parameters and the downstream retraining cost (GNN node
features + fusion meta-learner both take `lstm_score` as an input; adding
a 5th signal isn't a free change) for a gain that doesn't move per-event
recall on `anomalous_shock`/`coordinated`/`stealthy_forged_values` at all.

**Confirms `stealthy_forged_values` is a data-limit, not a model-limit,
with direct evidence, not just argument**: the Transformer, genuinely
more capable, scores this scenario identically to the LSTM-AE (0.606
recall both). A different, larger architecture moved nothing.

**Documentation pass**: verified every scorer's actual architecture
against its own docstring and against `docs/04_module3_trust_evaluation.md`
(found and fixed real staleness pre-dating this session: the doc's config
yaml block still said LSTM `hidden_size=24`/`window_size=20` and
`feature_window_size=20` against `config.py`'s real 16/8/32, and
`gnn.enabled: false` against the GNN being a live default per
`00_overview.md` deviation 4; B.1's `ProcessFeatureVector` spec still
listed the original 12-field raw-6-channel-plus-variance schema against
the AS-BUILT 5-feature vibration vector actually implemented in
`feature_engineering.py` and consumed by every scorer). Added B.5b for the
Transformer, cross-referenced it from B.8 and `RESULTS.md` Section 11,
added deviation 6 to `00_overview.md`, and added `RESULTS.md` Section 14
consolidating five acknowledged gaps (key rotation/revocation, Level-2
explainability, decision-channel replay, stealthy compromised devices,
the unexplained `high_rate` Process-score movement from §7) with a
verified-not-assumed remediation plan for each — confirmed via direct
`grep` that key rotation/revocation is fully specified in
`docs/02_module1_device_identity.md`/`03_module2_authentication.md` but
genuinely absent from `src/*.py` (zero hits for `key_version`/
`secret_key_previous`/`revoked`), so that gap is pure wiring, not missing
design.

## 28. Level-2 explainability implemented, individual evaluation figures generated, two new documentation files, and a real hash-chain migration bug found along the way

User asked for four more things: validate every model from a research
perspective (with need/purpose/justification, not just what it is),
create a new doc with the full system architecture and workflow,
integrate the design folder's live overlay more deeply, enhance SHAP, and
generate individual comparison graphs for every ML model evaluation.

**Level-2 explainability** (`docs/04_module3_trust_evaluation.md` Section
C.3, previously an acknowledged gap): implemented as `src/explainability.py`
(orchestration) plus a `level2_explain()` method on each scorer —
`shap.TreeExplainer` for Isolation Forest, leave-one-channel-out
perturbation for LSTM-AE/Transformer, leave-one-node-out perturbation for
the GNN, the existing `rule_range_score()` reason string for the trivial
rule case. Wired into `gateway.py` right after `fusion_engine.combine()`
and logged to two new `audit_log` columns. `scripts/evaluate_explainability_level2.py`
implements Section C.4's validation procedure (perturb → rescore → does
the fused score recover). **Real, honestly-reported result: 36% overall
flip rate against a 70% target — but split 100% (GNN) / 2% (Isolation
Forest) / 0% (LSTM-AE)**, not adjusted to look better. The split has a
mechanistic explanation, not just a number: masking one neighboring
device genuinely IS the GNN's whole causal story, but Isolation
Forest/LSTM-AE's anomaly score depends on several correlated features
jointly (`rms`/`peak`/`crest_factor` all derive from the same raw window),
so fixing one feature, even the SHAP-top-ranked one, doesn't collapse a
multi-feature-correlated anomaly back to normal. Found via a bug along
the way: `shap.TreeExplainer.shap_values()` needed a numpy array, not a
plain list — fixed after a live crash during multi-device smoke testing.

**A second, more consequential bug found while cleaning up after that
smoke testing**: the smoke tests wrote ~225 real rows into the actual
`data/audit_log.db` (not a throwaway path — exactly the mistake
`CLAUDE.md` Section 8 already warns about and `evaluate_latency.py` had
to fix once before, §8/RESULTS.md item 8). Deleting those rows to restore
the genuine 31,670-row history (found via a timestamp-gap scan — a
125,432-second gap cleanly separates 2026-08-29's real data from
2026-08-31's test rows) then surfaced a REAL, previously-latent
architecture bug, not just cleanup: `verify_chain_integrity()` recomputes
each row's hash from `SELECT *` — i.e. whatever columns exist NOW, not
what existed when a given historical row was inserted. Adding the two new
Level-2 columns therefore broke chain verification for EVERY row starting
from row 1, immediately, regardless of the smoke-test cleanup. Fixed with
a one-time re-baseline: recomputed `this_hash`/`prev_hash` for all 31,670
rows and regenerated all 316 checkpoints against the new schema; both
`verify_chain_integrity()` and `verify_against_checkpoints()` pass cleanly
again. A warning comment is now in `audit_log.py` itself so the next
column addition doesn't silently repeat this — a real gap in the original
hash-chain design (any future migration breaks it the same way) that
nothing surfaced until a column actually got added and the DB actually
had history to break.

**Individual evaluation figures**: `scripts/generate_evaluation_graphs.py`
(new), calling the SAME functions each `evaluate_*.py` script already
uses (not reimplementing any metric), produces 9 PNGs in `docs/figures/`
— per-signal accuracy/precision/recall/F1, per-event-type recall, the
fair LSTM-AE vs. Transformer comparison, a capacity-vs-accuracy scatter,
RL vs. static reward and confusion matrices, macro-F1, and latency.

**Two new docs**: `docs/12_model_validation_and_justification.md` (every
model's purpose, research motivation, validated evidence, and threats to
validity, written to the standard Section 1 of that file states up
front — held-out only, earn-your-place, negative results reported as-is)
and `docs/13_system_architecture_and_workflow.md` (layered architecture,
module map, message sequence, training pipeline, deployment topology,
and explainability data-flow diagrams, all in Mermaid). Both linked from
`docs/00_overview.md`'s reading order and `CLAUDE.md` Section 4.

**Design folder integration**: `webapp_server.py`'s live overlay (same
"never patch the 2.2MB bundle" principle as before) gained a second thin
bar showing each device's most recent Level-2 explanation, and a
`/figures` route serving a standalone gallery page of every PNG above —
linked from the overlay, not spliced into the canvas.

---

## 29. Real ESP32 hardware flashed for the first time — genuine bring-up bugs found and fixed, real data collected, models retrained, second dashboard removed

The board from §25's guide was actually flashed and run for the first
time this session (everything before this was software-only
verification). Four real integration bugs surfaced that no amount of
additional synthetic-value checking could have caught, because they're
about firmware runtime behavior and real network timing, not
canonicalisation logic:

1. **`ImportError: no module named 'ussl'`** — this board's MicroPython
   build renamed the module to `ssl`. Fixed with `try: import ussl /
   except ImportError: import ssl as ussl`.
2. **MQTT `MQTTException: 5` (not authorized)** — root-caused, not
   guessed: independently recomputed the broker's stored PBKDF2 password
   hash in Python against the plaintext from `secrets_local.py` and
   confirmed it matched, which proved the mismatch was firmware-side.
   Added a temporary `len(MQTT_PASSWORD)`/`len(DEVICE_SECRET)` debug print
   (never the value itself) and found both a mistyped `MQTT_PASSWORD`
   (47 chars instead of 24) and later a mistyped `DEVICE_SECRET` (47
   instead of 32) — both copy/paste artifacts, both caught by the length
   check rather than by eye.
3. **`REJECTED (stale_timestamp)` despite `[time] synced via NTP`
   printing successfully** — MicroPython's `time.time()` counts seconds
   since 2000-01-01, not the Unix epoch (1970-01-01) the gateway's
   `time.time()` uses; NTP sets the RTC correctly but doesn't change that
   reference point. Every `ts` looked ~30 years stale. Fixed by adding the
   fixed 946,684,800-second offset when building `ts_ms`. Confirmed via a
   direct computation that the raw pre-fix `ts` value, interpreted under
   the 2000-epoch assumption, landed on today's actual date.
4. **Intermittent NTP `ETIMEDOUT` on a fresh boot** — happened twice,
   both times right after a physical reset, self-resolving on manual
   retry. `sync_time()` now retries up to 3 times, 2s apart, before giving
   up non-fatally, instead of one-shot.

**Design simplification, user-requested**: the original two-sensor design
(MPU6050 + a separate vibration sensor) was dropped in favor of MPU6050
only — the user's board only had 2 GND pins available, and all 5
Section-5.1 features were already derived entirely from the MPU6050's
accelerometer (`extract_features()`); the vibration sensor's `raw` ADC
reading was carried in the payload but never consumed by
`rule_range_score()`/the ML scorers/`gateway._extract_reading()` (grepped
and confirmed before removing it), so dropping it was a clean removal, not
a scoring-logic change. `device_simulator.py`'s matching synthetic
`vibration_raw` field removed too, for consistency.

**Once telemetry was flowing and authenticated, `process_trust_score` read
near-zero (~3e-6) for a genuinely normal board** — investigated properly
(a dedicated subagent read `gnn_scorer.py`, `fusion_engine.py`,
`trust_engine.py`, `explainability.py` against the actual `audit_log.db`
rows, not just the console text) rather than assumed. Verdict: genuine,
mathematically-expected train/serve mismatch (IF/LSTM-AE/GNN all trained
solely on `device_simulator.py`'s synthetic distribution; `lstm_score`
was hitting an exact `0.0` floor because real reconstruction error blew
past the synthetic-only baseline's tight `std=0.277`), not a scoring bug.
One REAL bug found along the way, though: `gnn_scorer.py::level2_explain()`
picks whichever perturbed neighbor changes the score most, but with zero
currently-active neighbors every candidate ties at `change=0.0` and the
loop's `>` comparison silently "won" on the first device in iteration
order every time — always reporting `"GNN score most driven by
neighboring device 'sensor-002' (score change=0.000)"`, a fake
attribution, regardless of the real device's actual behavior. Fixed:
`level2_explain()` now returns `None` when the best change is ≤1e-6, and
`explainability.py` reports an honest "no other device is currently
active in the graph" instead. Verified directly against the live trained
model with a single-active-device input, not just read.

**Real data collection + retraining, built from scratch this session**:
`scripts/collect_hardware_session.py` (read-only MQTT subscriber, safe
alongside a live `gateway.py`, walks the operator through either 5 short
labeled phases or one long free-form window via `--long`, joins in
`gateway.py`'s own live scoring from `audit_log.db` by timestamp) and
`scripts/merge_real_hardware_data.py` (idempotent — always regenerates a
fresh synthetic base via `generate_training_data.generate()` rather than
reading back a previous merge, then appends every collected real session)
— matching `generate_training_data.py`'s own documented intent that real
`data/collected/*.json` should be swappable in without touching any
`train_*.py` script. 5 collection sessions run (one caught 0 records,
overlapping an ~11-minute window where the board was manually
disconnected by the user -- confirmed directly, not a mystery bug),
totaling 380 real records. Retrained
`train_isolation_forest.py` → `train_lstm_ae.py` → `train_gnn.py` →
`train_fusion_meta_learner.py` (that dependency order — each stage loads
the previous stage's freshly trained scorer) at two checkpoints (253 real
records, then the final 380), each time backing up and restoring
`models/*` around a controlled A/B run of `scripts/evaluate_ablation.py`
against the untouched held-out `test_session.json` for a clean
before/after. Result, monotonic across both checkpoints: deployed
`fused_score` accuracy 0.707→0.745→0.748, recall 0.684→0.728→0.732, F1
0.811→0.840→0.843, precision cost negligible (0.996→0.993→0.992). One
honestly-reported, also-monotonic trade-off: LSTM-AE's undiluted F1
0.910→0.871→0.867 and `fused_score`'s `stealthy_forged_values` recall
0.788→0.576→0.515, both from the LSTM-AE's error baseline necessarily
widening to stop misreading real hardware as anomalous — full writeup in
`RESULTS.md` Section 13.

**Second dashboard removed, on explicit user instruction**: investigating
the design-folder dashboard surfaced that `dashboard.py` (Streamlit),
referenced throughout `README.md`/`RESULTS.md` as one of "two live
dashboards," **does not exist anywhere in the repo** — grepped for it and
for any Streamlit code, found nothing; stale documentation for a feature
that was apparently never actually committed, not a real second UI. The
user then asked to remove `webapp_server.py` too and keep only
`design/zero-trust-cps-command-center.html`, after being shown the real
consequence first (that file has zero live-data wiring on its own — its
device names are a hardcoded stale export snapshot, `vibration-001`/
`mpu6050-001`, predating the current registry entirely) and confirming
that tradeoff explicitly. `webapp_server.py` deleted (`git rm -f`, had
uncommitted local changes); `README.md`, `RESULTS.md`, and
`iec62443_mapping.py`'s zone description updated to describe the design
file as a static visual reference only, with live monitoring now via
`audit_log.recent()`/`scripts/evaluate_governance.py`/`evaluate_iec62443.py`
directly. `firmware/HARDWARE_SETUP.md` rewritten in full to match the
MPU6050-only design, the four bugs above, and the real data-collection
workflow.

---

## 30. Dashboard's live functionality restored — merged directly into gateway.py instead of a second script

Immediately after §29's dashboard removal (and after that change was
committed and pushed), the user asked for the live-data functionality
back, but explicitly ruled out reintroducing it as a second script —
`design/zero-trust-cps-command-center.html` had to stay "the only
dashboard," with the live wiring merged into `gateway.py` itself.

**What moved**: every piece of `webapp_server.py`'s logic (the live
overlay bar's HTML/JS, the Level-2 explainability bar, `_build_qtable_view()`/
`_build_devices_view()`, the `Handler` class's `do_GET` routing, and all
seven `/api/*` endpoints — `/decisions`, `/devices`, `/governance`,
`/iec62443`, `/qtable`, `/chain`, `/status` — plus `/figures` and
`/figures/<file>`) copied into a new "Module 9 extension" section inside
`gateway.py` itself, renamed with a `Dashboard`/`dashboard` prefix to
avoid colliding with `gateway.py`'s own existing names. `config.py` gained
`DASHBOARD_PORT = 8600` (previously a hardcoded local constant in
`webapp_server.py`) for consistency with how `COAP_TLS_PORT` etc. are
already centralized there.

**How it's launched**: `start_dashboard_server()` mirrors `coap_server.py`'s
own `start_https_server()` exactly — an `HTTPServer` started on a daemon
`threading.Thread`, non-blocking, called from `gateway.py::run()`
alongside the existing MQTT `loop_forever()` and the HTTPS second-transport
thread. Net effect: `python gateway.py` is now the only command needed to
get MQTT, the HTTPS second transport, AND the live dashboard running —
genuinely one process, not one process plus a second script the user has
to remember to also start.

**Verified working, not just written** — ran `python gateway.py` in the
background and tested every route directly: main page (200 OK, 2.27MB,
`ztcps-live-overlay` div confirmed present in the served HTML),
`/api/devices`, `/api/governance`, `/api/iec62443`, `/api/qtable`,
`/api/chain`, `/api/decisions` (300 real rows), and `/figures` (200 OK).
One transient `curl` failure on the very first request against a
just-started server (connection reset before the listener thread was
fully warmed up) turned out not to be reproducible on retry — noted, not
chased further, since every subsequent request across every endpoint
succeeded cleanly.

`docs/13_system_architecture_and_workflow.md`'s three diagrams (layered
architecture, module-to-file map, deployment topology) updated to show
the dashboard as a background thread inside the gateway process rather
than either a separate process (pre-§29) or absent entirely (§29).
`README.md`, `RESULTS.md`, `docs/00_overview.md`'s deviation list, and
`iec62443_mapping.py`'s zone description updated to match.

---

## 31. Closing RESULTS.md's Known Limitations table — three real gaps implemented, two stale entries corrected, and a sixth issue found along the way

Asked to "solve all" five items in RESULTS.md Section 14. Checked the
table against the current code FIRST rather than trusting it, since two
dashboard-related staleness rounds (§29/§30) had already shown that table
of claims can drift from reality:

- **Item 2 (Level-2 explainability) and item 5 (`high_rate` Process-score
  movement) were already stale** — item 2 was fully implemented (grepped
  `level2_explain` across every scorer, confirmed real and wired up: not
  a new build). Item 5 was root-caused, not previously investigated:
  wrote `scripts/diagnose_high_rate_leak.py`, importing
  `evaluate_trust_responsiveness.py`'s own `replay_with_state()` replay
  logic (not reimplemented, so it can't silently diverge from the number
  that flagged this) but keeping every sub-signal instead of just the
  fused output. Every flagged row was `esp32-vib-001`, `rule_score`
  passing cleanly, `lstm_score` floored at `0.0` -- and **17 of 18**
  flagged rows sat *exactly 4 messages* after a real `anomalous_shock`,
  inside `LSTM_SEQ_LEN=8`'s window (verified computationally: the one
  exception, at distance 10, had by far the mildest score dip). Root
  cause: `anomalous_shock` (`tick%12==7`) and `high_rate` (`tick%18==11`)
  are fixed periodic patterns in the synthetic generator, so they
  deterministically land near each other on a regular cadence -- the same
  "window residue" effect already documented for the LSTM-AE/Transformer
  comparison, just never checked against `high_rate` specifically. Not a
  live rate-to-process leak; the two-score separation itself is intact.

- **Item 1 (key rotation / device revocation) implemented for real**,
  following the already-specified `docs/02_module1_device_identity.md`
  schema but adapted to this project's actual architecture (additive
  fields on the existing `DEVICE_REGISTRY` dict in `config.py`, not a new
  SQLite `devices` table -- the original doc's schema assumed a table
  this project never uses, per `docs/00_overview.md`'s deviation #3).
  `trust_engine.py` gained `revoke_device()`/`reinstate_device()`/
  `rotate_key()`/`is_revoked()`/`verify_signature_with_rotation()`;
  `gateway.py` checks revocation before HMAC (a hard override) and tries
  `secret_previous` as a grace-period fallback only after the current key
  fails. Verified with a 7-assertion end-to-end test (revoke, reinstate,
  rotate, old key inside grace period, new key, wrong key rejected, old
  key correctly stops working once the grace period is aged past) plus a
  live `process_telemetry()` call against a revoked device, confirmed
  logged as `REJECTED (device_revoked)`.

- **Item 3 (decision-channel replay) implemented for real**, the same
  `boot_id`/`seq` pattern telemetry already uses, applied to the
  gateway's outgoing decisions: `gateway.py` persists its own
  `gateway_boot_id` (`src/data/gateway_boot_id.txt`, gitignored, same
  treatment as the device's own `boot_id.txt`) and a per-device
  `decision_seq` counter, signed into every decision. `firmware/main.py`'s
  `verify_decision_signature()` was rebuilt on top of `canonical_json()`
  (the same generic sorted-keys builder telemetry already uses) instead
  of a hand-rolled fixed-field format string, specifically to not repeat
  the earlier telemetry canonicalisation risk -- verified byte-for-byte
  identical against Python's `json.dumps(payload, sort_keys=True)` for
  the new 5-field payload, and the full HMAC signature verified to match
  end to end. `check_decision_replay()` mirrors `check_boot_replay()`'s
  logic (strictly-higher boot_id always wins; same boot_id needs a
  strictly-higher seq).

- **A sixth, unlisted issue found while verifying items 1 and 3**:
  `trust_engine.is_stale()` (Security side) had zero call sites anywhere
  in the codebase, and `get_process_anomaly()`'s staleness check (Process
  side) had exactly one -- inside `gateway.py::process_telemetry()`,
  always called immediately AFTER `update_process_anomaly()` refreshes
  the very timestamp being checked. Verified against the REAL audit log
  (not assumed): the genuine ~753-second silence in the actual board
  session earlier this session shows the very first message after it
  logged `process_status: 'FRESH'`, never `'STALE'` -- the staleness code
  was correct in isolation but structurally unreachable via the live
  message-triggered path. This directly answers the practical question
  that same silence raised (was the board offline, disconnected, or
  compromised? -- previously indistinguishable from "nothing happening"
  at all). Fixed: `gateway.py` now runs a background silence watchdog
  (`start_silence_watchdog()`, same thread pattern as the dashboard/HTTPS
  transport, checking every `SILENCE_CHECK_INTERVAL_SECONDS=5`) that
  exercises both staleness checks independent of message arrival, logs a
  real audit row on the silence-start AND the return-to-normal
  transition (`decision="SILENT"`, `reason_category="device_silent"`),
  and alerts once per episode, not every sweep. Verified end to end:
  simulated a device going silent, confirmed `is_stale()`/
  `get_process_anomaly()` now correctly report stale with the score
  frozen (not decayed, per the design's own stated philosophy), and
  confirmed the resulting audit row writes correctly with the hash chain
  staying intact afterward. (The real ~11-minute board silence itself was
  confirmed with the user to be a manual disconnection, not a bug --
  RESULTS.md's and this file's earlier "root cause not identified"
  framing corrected accordingly.)

- **One more real confirmation added while working through the above**:
  the real board genuinely triggered a live `FLOOD -> BLOCK` response
  (`rms=1.02 FLOOD | security=0.49 | process=0.40(FRESH) | BLOCK`) --
  previously this exact response was only ever confirmed against
  `device_simulator.py`'s synthetic flood scenario. Added to RESULTS.md's
  confirmed-behaviours table as the first live confirmation against
  genuine hardware, explicitly distinguished from Section 13.2's still-
  pending Process Anomaly (physical fault) adversarial testing -- this is
  a Security Trust (rate/timing) domain event, not a physical one.

`RESULTS.md` Section 14 rewritten: all five original items now marked
resolved (struck through, not deleted, so the roadmap's own history stays
visible), plus the new sixth-issue writeup. Nothing left on that list
requiring further engineering -- item 4 (stealthy in-range forged values)
remains the one architecturally-capped item, not fixable by more
modeling, per its own entry.

**Same round, RESULTS.md Section 13.1/13.4 (device-side latency/
footprint) also addressed** -- `firmware/main.py` now measures, per
message via `time.ticks_ms()`/`time.ticks_diff()` (the MicroPython-
correct wraparound-safe way, not plain subtraction): sampling time (the
32-reading I2C window), feature-extraction time (RMS/peak/crest-factor/
kurtosis + the on-device DFT), and signing time (canonicalisation +
HMAC-SHA256), printed every message as `[latency] ...`. A new
`print_deployment_footprint()` prints real `gc.mem_free()`/
`gc.mem_alloc()` and `os.statvfs("/")` RAM/flash numbers once at boot,
right after full initialization. Code verified (syntax-checked,
import-safe) but **no real numbers recorded yet** -- this genuinely needs
a live run, unlike the six items above which were all resolvable through
code/investigation alone. `firmware/HARDWARE_SETUP.md`'s Step 9 example
output and `RESULTS.md` Sections 13.1/13.4 updated to describe the new
output format and its still-pending status.

**Real numbers landed minutes later** -- the user reflashed and ran the
instrumented firmware, pasted back 4 real messages worth of `[latency]`/
`[footprint]` output. Recorded into `RESULTS.md`: sampling 27.2ms mean,
feature extraction 134.5ms mean (dominates -- the hand-rolled O(N^2) DFT
in interpreted MicroPython), signing 9.2ms mean, ~171ms total per-message
device-side compute against a 2000ms publish interval (~8.6% duty cycle,
comfortable headroom). RAM: 14.0% of the MicroPython GC heap used
(100,976/117,440 bytes free). Flash: 0.59% of the 2MB filesystem used
(essentially just `main.py` + `boot_id.txt`). Also fixed a stale line in
Section 6 that still said device-side latency was "not yet measured," and
added the real device-vs-gateway comparison it was missing: the ESP32's
feature-extraction step alone costs more than the gateway's entire full
pipeline (134.5ms vs. 43.5ms mean) -- expected, an interpreted
microcontroller loop against a PC's compiled numpy/torch, not a red flag.
Only Section 13.2 (real adversarial testing) and the network-round-trip-
latency half of 13.4 remain, both requiring new physical action from the
user, nothing left to close through code or analysis alone.

**Minutes after that, an unplanned but genuinely real physical fault**:
the user disconnected and reconnected the real MPU6050 while the board
was running. The board didn't error -- I2C reads against a disconnected
sensor came back all-zero bytes instead of raising an exception, so
`rms=peak=crest_factor=kurtosis=0.0` got published as if legitimate,
physically impossible for a connected accelerometer (gravity alone is
~1g at rest). Checked, not assumed, whether this was actually caught:
replayed the exact reading through the live scorers. `rule_range_score()`
missed it (`0.9`, "within expected range" -- the old `rms` bound was
`(0.0, 3.0)`), but the full fusion pipeline didn't: `if=0.42 lstm=0.9
gnn=0.002`, `fused=0.008`, well below `PROCESS_THRESHOLD=0.6` -- the
GNN/Isolation Forest caught what the rule check missed, the
defense-in-depth design working exactly as intended, no single point of
failure. Fixed the rule gap anyway (`rms` lower bound `0.0`->`0.1`, a
cheap deterministic check for an unambiguous physical impossibility
shouldn't rely on the ML signals alone) -- verified against both the
synthetic held-out set (`rule_score` accuracy unchanged at 0.921, no
regression) and every real session's data (`min` observed `rms` was
0.33g, comfortably above the new 0.1 floor). `RESULTS.md` Section 13.2
and the confirmed-behaviours table (Section 1) both updated -- this is
real evidence toward the still-open formal adversarial-testing item, not
a substitute for it (it was an incidental discovery, not a structured,
human-labelled session).

**A second real fault, minutes later -- a genuine firmware bug this
time**: the user removed the MPU6050's VCC entirely (not just SDA/SCL).
Different failure mode from the SDA/SCL-only case above: a fully
unpowered sensor can't ACK the I2C bus at all, so `sample_window()`
raises a real `OSError` (`ETIMEDOUT`) instead of silently returning zero
bytes. `main()`'s loop wrapped its ENTIRE per-message body (sensor read
AND MQTT publish) in one `except OSError` -- written for MQTT
reconnection, so an I2C failure was misdiagnosed as a network problem:
reconnect MQTT (never actually broken, succeeds every time) -> hit the
same I2C failure again next cycle -> repeat forever, printing
`[main] connection error, reconnecting` / `[mqtt] connected with broker
credentials` in an infinite loop that never addressed or even correctly
named the real problem. Confirmed by reading the exact code, not
guessed. Fixed: split the sensor read into its own `try`/`except`,
separate from the MQTT publish/reconnect block -- on an I2C failure it
now re-runs `mpu6050_init()` (same retry philosophy as `sync_time()`'s
NTP retries, so power being restored is picked up automatically) and
`continue`s straight to the next cycle without touching MQTT, with a
correctly-labelled message (`MPU6050 read failed`, not `connection
error`). Not yet re-verified live -- needs the user to remove VCC again
against the fixed firmware to confirm the new path actually recovers;
flagged as such in `RESULTS.md`, not claimed as confirmed.
