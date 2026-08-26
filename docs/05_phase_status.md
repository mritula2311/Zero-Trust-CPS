# 05 — Phase Status: What's Built vs. What's Left

Authoritative status doc — kept current as the project evolves. Supersedes
any status claims in `docs/04_next_phases.md` (original planning doc,
pre-CLAUDE.md-v2) and earlier versions of this file. Cross-reference:
`CLAUDE.md` (engineering brief) and `docs/Zero_Trust_CPS_Project_Synopsis.docx`
(citable academic record) are the two governing specs this file tracks
compliance against.

## Summary table

| Module / Phase | What it is | Status |
|---|---|---|
| 1 — Device Identity | `DEVICE_REGISTRY`, hybrid (1 real + 2 simulated devices) | **Done** |
| 2 — Authentication | HMAC-SHA256, mutual (device→gateway telemetry + gateway→device signed decisions), both simulator and real ESP32/MicroPython firmware | **Done**, protocol-verified |
| 3 — Trust Evaluation (rule-based) | `trust_engine.rule_range_score()`, handles both scalar and feature-vector devices | **Done** |
| 4 — Continuous Verification | EWMA + time-decay + **replay/freshness check** (new) | **Done** |
| 5 — Access Control | Static (`policy_engine.decide()`) + RL-adaptive (`adaptive_pdp.py`, offline-trained) | **Done**, both |
| 6 — Secure Communication | MQTT/TLS (working) + a second secured transport (HTTPS, substituting for CoAP/DTLS — see below) | **Done**, with one documented substitution |
| 7 — Monitoring | `audit_log.py` (13 columns incl. confidence, NIST tenets, transport) + `dashboard.py` | **Done** |
| 6a — Isolation Forest | Offline-trained (`scripts/train_isolation_forest.py`), inference-only at runtime | **Done** |
| 6b — LSTM-Autoencoder | Offline-trained, 5-feature vibration vector input | **Done** |
| 6c — GNN | Offline-trained, hybrid device-graph (not sensor-channel graph — see below) | **Done**, one documented design choice |
| 7 — Fusion Engine + SHAP | Offline-trained `LogisticRegression` + `confidence` output + real SHAP explanations | **Done** |
| 8 — RL-Adaptive Access Control | `AdaptivePDP`, offline Q-learning against real labels, state = (trust, confidence) | **Done** |
| 9 — Dashboard | `dashboard.py` (Streamlit, live) | **Done** |
| Feature engineering (5.1) | `feature_engineering.py`: rms, peak, crest_factor, kurtosis, dominant_freq (DFT) | **Done** |
| NIST SP 800-207 mapping | `nist_mapping.py`, per-decision tenet tagging, `completeness_report()` | **Done** |
| Real hardware | `firmware/main.py`, MicroPython (not the earlier Arduino firmware) | **Written, protocol-verified in software — not yet flashed to real hardware** |

**Every module now has a genuine, tested implementation matching CLAUDE.md's
architecture** — this is a substantial rebuild from the previous online-
learning version (see "What changed" below). Three things are documented,
deliberate substitutions, not gaps — read them before citing results.

## The Hard Constraint, actually satisfied now

CLAUDE.md Section 8: *"Train offline, infer at the gateway... `gateway.py`
only ever loads and runs inference, never trains, in the live path."*

This was **violated** in the previous version of this project (all four ML
scorers retrained online, inside the live gateway). It is now genuinely
satisfied:

- `scripts/train_isolation_forest.py`, `train_lstm_ae.py`, `train_gnn.py`,
  `train_fusion_meta_learner.py`, `train_adaptive_pdp.py` — five scripts,
  run in that dependency order (each replays `scripts/generate_training_data.py`'s
  output through the previously-trained scorers to build its own training
  set), each saving an artifact under `models/`.
- `isolation_forest_scorer.py`, `lstm_ae_scorer.py`, `gnn_scorer.py`,
  `fusion_engine.py`, `adaptive_pdp.py` — five inference-only classes.
  Verified by direct code inspection: none of them calls `.fit()`,
  `.backward()`, or `AdaptivePDP.update()` from any function reachable from
  `gateway.process_telemetry()`.
- Verified live: ran the gateway for 90+ seconds against both MQTT and
  HTTPS telemetry simultaneously, confirmed `Fusion trained: True | IF
  trained: True | LSTM-AE trained: True | GNN trained: True` in the
  startup banner (meaning the artifacts loaded), zero errors.

## Real labels, not a pseudo-label heuristic

The previous version's biggest caveat was that fusion/GNN/RL all trained
on a heuristic pseudo-label (`auth_ok AND in-range`) computed at scoring
time — a weak proxy that could never label the "sneaky" in-range anomalies
the ML scorers exist to catch.

`scripts/generate_training_data.py` now generates a session where the
label is **ground truth the script itself knows**, because it's the one
injecting the anomalies (forged signatures, out-of-range values, in-range
shock events, replays) — a categorically stronger claim, and consistent
with synopsis Section 5.3's requirement that only the meta-learner needs
labelled data, constructed from the project's own adversarial-testing
scenarios.

**Still worth stating explicitly**: this is a *synthetic* adversarial
session, not the *real physical* one synopsis Section 9 Stage 6 describes
(tap/shock the rig, loosen a mount, disconnect a sensor, on real
hardware). Swapping in a real recorded session is a contained change —
`scripts/generate_training_data.py`'s output shape
(`{tick, device_id, reading, auth_ok, ts, label, event_type}`) is exactly
the input format every `train_*.py` script consumes; a
`data/collected/adversarial_*.json` recorded from real hardware could
replace or augment `training_session.json` without touching the training
scripts themselves.

## Three documented substitutions (read before citing results)

**1. CoAP/DTLS → HTTPS.** The synopsis requires MQTT/TLS *and* CoAP/DTLS.
Classic CoAP/DTLS needs the `DTLSSocket` package, which needs a native
`autoreconf` build unavailable in this environment (no admin/sudo to
install the toolchain, tried both native Windows and WSL). CoAP-over-TLS
via `aiocoap` was then implemented and found to have a reproducible
defect — verified with a raw socket connect on native Windows AND
WSL/Linux, on two aiocoap versions (0.4.17, 0.4.7), all six combinations
failing the same way. `coap_server.py` now serves the same functional
role (a second, independently TLS-secured, no-plaintext-fallback
transport) as an HTTPS endpoint over Python's standard `http.server` +
`ssl`. See `coap_server.py`'s docstring for the full trail. **If your
report specifically needs to say "CoAP," name this substitution
explicitly** — the security property (encrypted, authenticated, no
plaintext) holds; the specific protocol does not.

**2. GNN uses the hybrid device-graph, not the sensor-channel graph.**
CLAUDE.md Section 2 offers both as legitimate options. The hybrid graph
(nodes = `DEVICE_REGISTRY` entries) was chosen because it reuses the
existing per-device trust-state pattern with far less new code than a
7-channel correlation graph would need, while still satisfying the
module's purpose (relational/coordinated anomaly detection). State this
choice explicitly in the paper — Section 2 asks you to.

**3. GNN implementation is a hand-rolled GCN, not `torch-geometric`.**
Unchanged from the previous version — `torch-geometric`'s compiled
extensions are a common source of broken installs; not worth the risk for
a 3-node graph. Same math, different library.

**4. Module 2 authentication — UPGRADED: now genuinely mutual, still not
interactive challenge-response.** Originally one-directional (device→gateway
only). Fixed: the gateway now signs its `cps/decisions/<device_id>`
messages with the same per-device secret (`gateway.py::_sign_decision()`),
and the device independently verifies that signature before trusting a
decision (`device_simulator.py::verify_decision_signature()`, mirrored in
`firmware/main.py`) — reusing the existing Module 1 secret, no new
provisioning needed. Verified live: forged/tampered/wrong-secret decisions
are rejected (`!! REJECTED decision message`), genuine ones pass (`<<
verified gateway decision: ALLOW`); a standalone negative-case check
(tampered payload, wrong secret, malformed envelope) also confirmed. Still
not literal interactive challenge-response (no gateway-issued nonce inside
a session handshake — each message is authenticated independently on its
own content) and the decision channel has no replay check of its own yet
(lower-stakes than telemetry replay, but a real remaining gap). See
`implementation-docs/02_module_authentication.md`'s updated "Honesty note
on 'mutual'" for the full detail.

**5. "Coordinated multi-device attack" (synopsis Section 4.2 Stage 6) now
has a real scenario, and it revealed (and then fixed) two genuine bugs.**
Until this pass, no such scenario existed anywhere in
`device_simulator.py` or `scripts/generate_training_data.py` — meaning the
GNN's entire reason for existing (relational/coordinated-anomaly
detection, the Section 4.1 novelty claim) had never actually been tested.
Adding it (all 3 devices drift mildly, individually in-range, in the same
tick) surfaced:

- `scripts/train_gnn.py`'s per-(tick,device) snapshot labelling forced
  every node OTHER than the current record's device to a target of 1
  ("assume normal") — actively wrong whenever another device was
  simultaneously anomalous, which defeats the entire point of a
  relational model. Fixed to track each device's own last-known TRUE
  label instead.
- Even after that fix, an unweighted `BCELoss` left the GNN's raw output
  never crossing the 0.5 decision boundary even on the worst input
  (~90/10 class imbalance in the per-node targets). Fixed with standard
  inverse-frequency class weighting.
- The fusion meta-learner (`LogisticRegression`) then discarded the
  now-working GNN signal on "coordinated" specifically (recall 0.261,
  worse than the GNN alone at 0.870) because the numerous easy examples
  dominated one global linear hyperplane. Fixed with `class_weight=
  "balanced"` — recovers coordinated recall to 0.913 at a deliberate,
  documented cost to raw aggregate accuracy (0.875 vs isolation forest's
  0.923 alone) — see `scripts/evaluate_ablation.py`'s per-event-type
  breakdown and its printed rationale for why aggregate accuracy alone is
  the wrong number to optimise for a security system.

## Known limitations (not fixed, honestly bounded)

- **Replay protection has a narrow blind spot**: a message captured from
  within a device's first `REBOOT_TS_THRESHOLD_MS` (5s) of uptime could
  still be replayed later undetected. Documented in `config.py`'s
  `REBOOT_TS_THRESHOLD_MS` comment — closing it fully needs a monotonic
  hardware counter or synced clock+nonce.
- **Firmware TLS skips CA verification** (`cert_reqs=CERT_NONE`) — a
  stated simplification for a prototype on a private test network, not
  silently ignored. See `docs/06_hardware_setup.md`'s limitations section.
- **Firmware not yet flashed to real hardware.** The protocol (HMAC
  canonicalisation, float formatting) was verified thoroughly in
  software — 6000+ random values with zero mismatches, plus a full
  canonical-string → HMAC → `gateway.verify_signature()` round trip — but
  nobody has run `firmware/main.py` on an actual ESP32 yet. Budget real
  debugging time for this integration point per CLAUDE.md Section 3's own
  advice, even though the math is verified.

## What changed this session (for the record)

This was a full rearchitecture from the previous online-learning version,
triggered by a new `CLAUDE.md` (v2) and the project synopsis being added
to the repo, which specified an architecture that conflicted with what was
already built in several real ways (not cosmetic): online vs. offline
training (the big one), device registry shape (2 pure-real devices vs. a
hybrid 1-real+2-simulated testbed), firmware language (Arduino/C++ vs.
MicroPython), feature engineering (raw scalar vs. a proper 5-feature
vibration-analysis vector), and file/directory naming conventions. All of
it was rebuilt to match the new specs rather than layered on top — see
git history / this file's prior version for what the online-learning
architecture looked like, if useful for a "design evolution" discussion
in the paper.

## What's next, in order

**Updated — item 5 below is now DONE** (was outstanding when this list
was first written; see `docs/08_results_and_evaluation.md` and
`SESSION_LOG.md` §12/§17-19 for the full evaluation suite, the LSTM
fusion-sign fix, the GPU architecture scale-up, and the overfit/underfit
verification). Everything achievable without physical hardware is now
complete — both remaining items genuinely need the real ESP32:

1. **Flash `firmware/main.py` to real hardware** and work through
   `docs/06_hardware_setup.md`'s troubleshooting section for the first
   real-device integration bugs.
2. **Run a real physical adversarial-testing session** (synopsis Stage 6)
   and feed it into `scripts/generate_training_data.py`'s output format,
   replacing the synthetic session for at least the esp32-vib-001 portion,
   then **re-run all five `scripts/train_*.py` in order** (everything
   downstream depends on IF/LSTM-AE training first) and re-run
   `scripts/evaluate_*.py` against the real data.
3. Optional: pursue genuine CoAP/DTLS if you want the literal protocol
   for the paper — the one-line WSL fix (`sudo apt install build-essential
   autoconf automake libtool`, needs a password this environment doesn't
   have) would unblock `DTLSSocket`. `coap_server.py`'s HTTPS substitute
   already satisfies the functional requirement (Module 6, second secured
   transport); this would only matter if the exact protocol name is
   required.
4. ~~Produce the synopsis Section 10.1 evaluation artefacts~~ — **DONE**,
   see `docs/08_results_and_evaluation.md`.

## Environment status (this machine)

- Python 3.12.10, all of `requirements.txt` installed and verified.
- Mosquitto: TLS listener on 8883 (bound `0.0.0.0`, confirmed reachable),
  plain listener still on 1883.
- `certs/` populated: self-signed CA + server cert, shared by MQTT/TLS and
  the HTTPS second transport.
- `models/` populated: all 5 offline-trained artifacts present and loading
  correctly (`isolation_forest.joblib`, `lstm_ae.pt` + `lstm_ae_meta.json`,
  `gnn.pt`, `fusion_meta_learner.joblib` + `fusion_background.npy`,
  `adaptive_pdp_qtable.json`).
- `data/collected/training_session.json`: 1220 synthetic labeled records.
