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

## Current state (as of this entry)

**Done, tested, verified**: all 7 modules, all 9 phases, offline training
hard constraint satisfied, real ground-truth training labels, MQTT/TLS
live, a working second secured transport, NIST + IEC 62443 governance
mapping (both live in the dashboard and as standalone `evaluate_*.py`
scripts, with the underlying conditional logic directly proven — not just
its printed output — in §-level probes throughout this log), replay
protection, MicroPython firmware protocol-verified in software, **genuine
mutual authentication** (§13), a **fully corrected fusion pipeline** with
all four signal coefficients correctly signed and SHAP mathematically
verified down to the log-odds/probability-space distinction (§16-17),
**real GPU acceleration** on an RTX 5060 with a verified ~17x training
speedup from batching (§18), and a **deliberately-verified capacity
increase** for LSTM-AE/GNN that was checked against both overfitting and
underfitting rather than assumed safe (§19 and this entry's own
train-vs-held-out proof).

**Four documented, deliberate substitutions remain** (not gaps — each has
a verified reason, full list in `docs/05_phase_status.md`): CoAP/DTLS →
HTTPS (blocked on an upstream `aiocoap` defect + an unavailable sudo/
autoreconf toolchain); GNN uses the hybrid device-graph, not the
sensor-channel graph; GNN is a hand-rolled GCN, not `torch-geometric`;
Module 2 authentication is mutual (§13 closed the one-directional gap)
but still not literal interactive challenge-response (no gateway-issued
nonce inside a session handshake).

**Not done — needs the user's physical hardware, not more code**:
1. `firmware/main.py` has never been flashed to a real ESP32.
2. No real physical adversarial-testing session (tap/shock the rig, etc.)
   has been recorded — training still runs on a synthetic-but-honestly-labeled
   session (`scripts/generate_training_data.py`).
3. ESP32-side signing/feature-extraction latency (needs `time.ticks_ms()`
   instrumentation on real hardware, flagged as TODO in
   `docs/08_results_and_evaluation.md`, not estimated).

These three are the ONLY remaining gaps, and they're explicitly carried
forward as placeholders in `docs/09_project_report.md`'s "Pending Hardware
Validation" section, to be filled in once the physical board is wired up
— not silently skipped, not estimated in their place.

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
paper-ready numbers behind what the dashboard shows live —
`docs/09_project_report.md` is the polished write-up of all of them.

**Model sizes, for anyone re-running `scripts/train_*.py` from scratch**:
LSTM-Autoencoder is 16 hidden units / 1 layer; GNN is 32 hidden units / 3
layers — both GPU-accelerated (`torch.cuda.is_available()` auto-detected
in `lstm_ae_scorer.py`/`gnn_scorer.py`, falls back to CPU cleanly if no
GPU is present) and both verified via `evaluate_ablation.py` train-vs-
held-out comparisons to be neither overfitting nor underfitting (§19).

---

**File map for anyone catching up**:
- `CLAUDE.md` — the governing engineering brief (read this first if working from spec).
- `docs/Zero_Trust_CPS_Project_Synopsis.docx` — the citable academic record.
- `docs/05_phase_status.md` — current architecture/compliance status, module by module.
- `docs/06_hardware_setup.md` — MicroPython flashing instructions.
- `implementation-docs/` — module-by-module reference (Part A core + Part B extension design).
- `src/` — the live pipeline. `scripts/` — offline training. `models/` — trained artifacts. `firmware/` — MicroPython. `data/collected/` — training data.
