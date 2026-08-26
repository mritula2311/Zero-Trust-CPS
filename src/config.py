"""
Shared configuration for the Zero-Trust CPS starter kit.
Maps to Report Section 8 (System to Be Used) and CLAUDE.md.

Architecture note (CLAUDE.md v2): this is a HYBRID testbed -- one real
ESP32 device (`esp32-vib-001`, MicroPython firmware in `firmware/main.py`)
alongside two simulated devices (`sensor-002`, `actuator-001`) carried
over from the original starter kit design. The real device publishes a
5-feature vibration-analysis feature vector per message (Section 5.1);
the simulated devices publish a single scalar `value`, same as always.
`DEVICE_REGISTRY`'s `kind` field tells the rest of the pipeline which
shape to expect -- see gateway.py's `_extract_features()`.
"""

import os

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Secrets (never committed -- see src/secrets_local.example.py) ---
# Real values live in src/secrets_local.py, gitignored. Falls back to
# obviously-fake placeholders if that file doesn't exist (fresh clone) so
# the project still imports and runs for exploration -- auth against a
# real broker/device won't work until you copy secrets_local.example.py
# to secrets_local.py and fill in real values (or generate your own).
try:
    from secrets_local import DEVICE_SECRETS, MQTT_PASSWORDS, MQTT_GATEWAY_PASSWORD
except ImportError:
    print("[config] WARNING: src/secrets_local.py not found -- using placeholder "
          "secrets (see src/secrets_local.example.py). Copy it to secrets_local.py "
          "and fill in real values before relying on authentication.")
    DEVICE_SECRETS = {
        "esp32-vib-001": "CHANGE-ME-generate-your-own-secret",
        "sensor-002": "CHANGE-ME-generate-your-own-secret",
        "actuator-001": "CHANGE-ME-generate-your-own-secret",
    }
    MQTT_PASSWORDS = {
        "esp32-vib-001": "CHANGE-ME-generate-your-own-password",
        "sensor-002": "CHANGE-ME-generate-your-own-password",
        "actuator-001": "CHANGE-ME-generate-your-own-password",
    }
    MQTT_GATEWAY_PASSWORD = "CHANGE-ME-generate-your-own-password"

# --- MQTT broker (Module 6: Secure Communication) ---
# NOTE: This starter uses plain MQTT on localhost for simplicity so you can see
# the pipeline working immediately. Before you treat this as "done", follow
# docs/03_add_tls.md to switch this to MQTT-over-TLS (port 8883) -- that step
# is what actually satisfies Module 6 / references [23],[24] in the report.
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TLS_PORT = 8883
TELEMETRY_TOPIC = "cps/telemetry"      # devices publish sensor readings here
# Decision topic is a PREFIX, not a flat topic -- gateway.py publishes to
# f"{DECISION_TOPIC}/{device_id}" (e.g. "cps/decisions/esp32-vib-001"), not
# a single shared "cps/decisions" topic. This is what makes the MQTT_ACL_FILE
# below able to restrict each device to reading only ITS OWN decisions
# (least privilege / IEC 62443 FR5 "Restricted Data Flow") -- a flat shared
# topic couldn't be scoped per-device with topic-based ACLs at all.
DECISION_TOPIC = "cps/decisions"

_CERTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "certs")
MQTT_USE_TLS = os.path.exists(os.path.join(_CERTS_DIR, "ca.crt"))   # auto-on once certs exist -- see docs/03_add_tls.md
MQTT_TLS_CA_CERT = os.path.join(_CERTS_DIR, "ca.crt")

# --- MQTT broker authentication (IEC 62443 FR5 / NIST tenet 1, transport
# layer) ---
# Before this, the broker's `allow_anonymous true` meant ANY client could
# connect and publish/subscribe to ANY topic -- "no implicit trust" was
# only enforced at the APPLICATION layer (the HMAC signature in the
# payload), not the transport layer a client has to pass through to even
# reach that check. A client with no credentials at all could still
# forge a `cps/decisions` message or eavesdrop on another device's
# traffic; it just couldn't produce a message the GATEWAY would act on.
# certs/mosquitto_passwd (hashed, generated with mosquitto_passwd.exe) and
# certs/mosquitto_acl (least-privilege topic ACLs, see that file's
# comments) close this gap -- apply them to mosquitto.conf per
# docs/07_transport_zero_trust.md, then this auto-detects and both
# gateway.py and device_simulator.py start authenticating.
MQTT_PASSWORD_FILE = os.path.join(_CERTS_DIR, "mosquitto_passwd")
MQTT_ACL_FILE = os.path.join(_CERTS_DIR, "mosquitto_acl")
MQTT_USE_AUTH = os.path.exists(MQTT_PASSWORD_FILE)   # auto-on once the password file exists

MQTT_GATEWAY_USERNAME = "zt-gateway"
# MQTT_GATEWAY_PASSWORD comes from secrets_local.py (imported above) --
# matches certs/mosquitto_passwd -- regenerate both together if changed

# --- CoAP endpoint (Module 6: Secure Communication, synopsis Section 8.2) ---
# The synopsis requires MQTT/TLS *and* CoAP/DTLS as the two secured
# transports, "no plaintext fallback" on either. Classic CoAP-over-DTLS
# (RFC 7252) needs the `DTLSSocket` package, which needs a native autotools
# build (`autoreconf`) -- unavailable on this machine (no admin/sudo to
# install the toolchain, native Windows or WSL). coap_server.py uses CoAP
# over TLS instead (RFC 8323, "coaps+tcp") -- same encrypted+authenticated,
# no-plaintext-fallback transport, built on Python's standard `ssl` module,
# no native compilation required. Documented explicitly as a deliberate
# substitution, not a silent scope cut -- see coap_server.py's docstring.
COAP_TLS_PORT = 5684            # standard coaps+tcp port (RFC 8323)
COAP_TELEMETRY_PATH = "telemetry"
COAP_CERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "certs", "coap_server.crt")
COAP_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "certs", "coap_server.key")
COAP_ENABLED = os.path.exists(COAP_CERT_PATH) and os.path.exists(COAP_KEY_PATH)  # auto-on once certs exist

# --- Replay protection (Module 4 / synopsis Stage 6 adversarial testing) ---
# `ts` (ms) must strictly increase per device -- a captured-and-replayed
# message (identical value + identical signature) is now rejected the same
# way a bad signature is. Distinguishing a genuine device REBOOT (the real
# firmware's ts is millis()-since-boot, so it resets toward 0) from a REPLAY
# is done by looking at the incoming ts's absolute size, not the size of the
# backward jump: a backward jump could be small (attacker replays a message
# from seconds ago) or large (replays one from an hour ago) regardless of
# whether it's a reboot, so jump size alone can't disambiguate the two. A ts
# below REBOOT_TS_THRESHOLD_MS means the device itself claims to be within
# the first few seconds of its own uptime -- overwhelmingly more likely to
# be a real reboot than an attacker choosing to replay a message that
# happens to carry a near-zero timestamp. Anything else non-increasing is
# rejected as a replay.
#
# KNOWN LIMITATION (worth stating explicitly in the paper, not hiding): a
# message captured from within a device's first REBOOT_TS_THRESHOLD_MS of
# uptime is a blind spot -- replaying THAT specific message later would
# still fall under the reboot-grace window and be accepted. Closing this
# fully needs a monotonic hardware counter or a synced wall-clock + nonce,
# which is out of scope for this prototype; ts-only replay detection closes
# the general case (replaying any message from normal operation) but not
# this specific early-boot edge case.
REBOOT_TS_THRESHOLD_MS = 5000

# --- Device Identity Registry (Module 1) ---
# In a real deployment each device would hold its own secret in a secure
# element (ATECC608A or similar). Here we keep a simple in-memory registry on
# the gateway so you can see the identity + authentication logic clearly.
#
# `kind: "feature_vector"` -- the real ESP32 (firmware/main.py). Payload
# carries all 5 Section-5.1 features (rms, peak, crest_factor, kurtosis,
# dominant_freq) plus vibration_raw, computed on-device (see firmware/main.py's
# docstring for why the FFT etc. moved on-device rather than shipping a raw
# sample window over the signed channel). `expected_ranges` is a plausible
# per-feature PHYSICAL range for the Part A rule check -- deliberately wide
# (a hard override -- see trust_engine.py's "physically-out-of-range is
# absolute" comment -- so it should rarely trigger; the fine-grained "is
# this weird for normal operation" judgment belongs to the ML scorers, not
# this rule). Calibrated against device_simulator.py's actual normal vs.
# injected-shock distributions (normal crest_factor ~0.07-0.19,
# shock ~1.8-2.8; normal kurtosis ~-1.3 to 3.5, shock ~26-27; see
# scripts/generate_training_data.py's output for how these were checked) --
# replace with real numbers from a baseline data-collection session
# (Section 3, "Registering the real device") once the rig is running.
#
# `kind: "scalar"` -- the original starter-kit simulated devices, unchanged:
# a single `value` field, checked against one `expected_range`.
# `mqtt_password` is a SEPARATE credential from `secret` (the HMAC key) --
# deliberately not reused, even though both are prototype-simplification
# plaintext constants (CLAUDE.md Section 8 already accepts this for
# `secret`; same reasoning applies here). `secret` authenticates the
# MESSAGE CONTENT (application layer, Module 2); `mqtt_password`
# authenticates the CONNECTION to the broker itself (transport layer,
# Module 6 / FR5) -- two different trust boundaries, so a compromise of
# one shouldn't hand over the other. `mqtt_username` matches the device_id
# so certs/mosquitto_acl's `pattern read cps/decisions/%u` scopes each
# device to reading only its own decisions.
DEVICE_REGISTRY = {
    "esp32-vib-001": {
        "secret": DEVICE_SECRETS["esp32-vib-001"],
        "kind": "feature_vector",
        "mqtt_username": "esp32-vib-001",
        "mqtt_password": MQTT_PASSWORDS["esp32-vib-001"],
        "expected_ranges": {
            "rms": (0.0, 3.0),              # g
            "peak": (0.0, 6.0),             # g (peak-to-peak)
            "crest_factor": (0.0, 10.0),    # dimensionless (peak-to-peak / rms, not textbook max/rms -- see feature_engineering.py)
            "kurtosis": (-3.0, 30.0),       # excess kurtosis
            "dominant_freq": (0.0, 50.0),   # Hz, Nyquist-limited by the 100Hz on-device sample rate
        },
    },
    "sensor-002": {
        "secret": DEVICE_SECRETS["sensor-002"], "kind": "scalar", "expected_range": (20.0, 80.0),   # humidity sensor, %
        "mqtt_username": "sensor-002", "mqtt_password": MQTT_PASSWORDS["sensor-002"],
    },
    "actuator-001": {
        "secret": DEVICE_SECRETS["actuator-001"], "kind": "scalar", "expected_range": (0.0, 1.0),   # valve position, 0-1
        "mqtt_username": "actuator-001", "mqtt_password": MQTT_PASSWORDS["actuator-001"],
    },
}

# --- Feature Engineering (Module 3, CLAUDE.md Section 5.1) ---
FEATURE_NAMES = ["rms", "peak", "crest_factor", "kurtosis", "dominant_freq"]
FEATURE_SAMPLE_RATE_HZ = 100.0   # matches firmware/main.py's dt_ms=10 sampling loop
FEATURE_WINDOW_SIZE = 32         # samples per on-device window, matches firmware/main.py

# --- Trust Evaluation (Module 3) ---
TRUST_EWMA_ALPHA = 0.35          # weight given to the newest observation
TRUST_DECAY_PER_SECOND = 0.01    # trust drifts down slowly if a device goes quiet
STALE_AFTER_SECONDS = 20         # a device not heard from in this long is "stale"

# --- Flood / rate-limit detection (Module 4 extension, IEC 62443 FR7
# "Resource Availability") ---
# Every simulated/real device publishes on a ~2s cadence by design
# (device_simulator.py, firmware/main.py's main loop). A device suddenly
# publishing far faster than that is either malfunctioning or attempting
# to flood the gateway/broker -- this is the "message frequency" rule
# docs/01_getting_started.md already suggested as a hand-written exercise,
# now actually wired in. Measured against WALL-CLOCK arrival time at the
# gateway (time.time()), not the payload's self-reported `ts` -- an
# attacker flooding messages controls their own `ts` field, but not when
# the gateway's clock says the message actually arrived.
MIN_MESSAGE_INTERVAL_SECONDS = 0.5

# --- Model artifacts (CLAUDE.md Section 8: "train offline, infer at the
# gateway" -- every path below is a file scripts/train_*.py writes and the
# live gateway only ever reads. A missing file means "not trained yet";
# every scorer's inference-only class handles that by deferring to a
# neutral fallback, same principle as the old online-learning version's
# "not enough history yet" state, just decided at deploy time instead of
# runtime. ---
MODELS_DIR = os.path.join(_SRC_DIR, "..", "models")
ISOLATION_FOREST_MODEL_PATH = os.path.join(MODELS_DIR, "isolation_forest.joblib")
LSTM_AE_MODEL_PATH = os.path.join(MODELS_DIR, "lstm_ae.pt")
LSTM_AE_META_PATH = os.path.join(MODELS_DIR, "lstm_ae_meta.json")   # normalization stats, baseline error stats
GNN_MODEL_PATH = os.path.join(MODELS_DIR, "gnn.pt")
FUSION_MODEL_PATH = os.path.join(MODELS_DIR, "fusion_meta_learner.joblib")
FUSION_BACKGROUND_PATH = os.path.join(MODELS_DIR, "fusion_background.npy")   # SHAP background sample
ADAPTIVE_PDP_MODEL_PATH = os.path.join(MODELS_DIR, "adaptive_pdp_qtable.json")

# --- Isolation Forest (Module 3, Phase 6a) ---
ISOLATION_FOREST_CONTAMINATION = 0.1

# --- LSTM-Autoencoder (Module 3, Phase 6b) ---
LSTM_SEQ_LEN = 8                 # length of each training/scoring window (in messages, i.e. feature vectors)
                                  # -- a PHYSICAL-MEANING parameter (~16s of real device history at the
                                  # 2s telemetry cadence), not a capacity knob -- left unchanged by the
                                  # GPU-scale-up below, which only changes model CAPACITY.
# GPU-scale-up (SESSION_LOG.md): previously 8 (single LSTM layer), kept
# deliberately tiny because this ran on CPU with no GPU available. Now
# genuinely GPU-accelerated (RTX 5060) -- raised to 32 hidden units, 2
# stacked LSTM layers (LSTM_NUM_LAYERS), for real additional model
# capacity. Honest risk stated explicitly, not hidden: LSTM_SEQ_LEN=8
# windows over ~345 normal esp32-vib-001 training readings is a SMALL
# dataset for this much added capacity (roughly ~941 params before this
# change vs ~27k after) -- verified after training (not assumed) via
# scripts/evaluate_ablation.py that generalisation on HELD-OUT data didn't
# regress before keeping this change; see that script's output / this
# file's git history if it needs to be dialled back.
LSTM_HIDDEN_SIZE = 16
LSTM_NUM_LAYERS = 1              # dialled back from an initial 32-hidden/2-layer attempt (~27k params) --
                                  # verified via evaluate_ablation.py that it OVERFIT 345 training windows
                                  # (training loss dropped much lower, held-out accuracy/recall got WORSE:
                                  # 0.762->0.734, 0.775->0.737 -- textbook overfitting signature). 16
                                  # hidden units, 1 layer (~2.9k params) is a more defensible capacity
                                  # increase for this dataset size -- still real growth from the original
                                  # 8-unit model, verified NOT to regress held-out generalisation before
                                  # being kept (see SESSION_LOG.md).
LSTM_EPOCHS = 100
LSTM_LEARNING_RATE = 0.01

# --- GNN (Module 3, Phase 6c) ---
# Sensor-channel graph vs. hybrid device-graph (CLAUDE.md Section 2 offers
# both as legitimate options): this build uses the HYBRID DEVICE-GRAPH --
# nodes = the entries in DEVICE_REGISTRY, edges = "communicated with the
# gateway in the same time window" -- because it reuses the existing
# per-device trust-state pattern cleanly and still satisfies the module's
# purpose (relational/coordinated anomaly detection across devices). State
# this choice explicitly in the paper (Section 2 asks you to).
GNN_EDGE_WINDOW_SECONDS = 5.0
# GPU-scale-up (SESSION_LOG.md): previously 8 hidden units, 2-layer GCN,
# same "no GPU available" reasoning as LSTM_HIDDEN_SIZE above. Raised to
# 32 hidden units and a 3rd GCN layer (GNN_NUM_LAYERS) for real added
# depth/capacity, now that training genuinely runs on GPU (and, since the
# training loop is batched -- see SESSION_LOG.md's GPU timing entries --
# actually benefits from the extra parallel work). Same honesty check
# applied: verified via evaluate_ablation.py that 'coordinated' recall
# (the GNN's whole reason for existing) didn't regress before keeping
# this change.
GNN_HIDDEN_SIZE = 32
GNN_NUM_LAYERS = 3
GNN_EPOCHS = 150
GNN_LEARNING_RATE = 0.05
# Node feature vector: [rule_score, isolation_forest_score, lstm_ae_score]
GNN_NODE_FEATURE_DIM = 3

# --- Fusion Engine (Module 3, Phase 7) ---
# Placeholder if_score/lstm_score fed into the fusion/GNN feature vector for
# messages that FAILED authentication -- the real per-value scorers never
# run on unauthenticated data (see gateway.py), so without a fixed sentinel
# here, failed-auth messages (a primary source of label=0 examples) would
# be invisible to offline training entirely.
AUTH_FAIL_SENTINEL_SCORE = 0.1
FUSION_SHAP_BACKGROUND_SIZE = 50

# --- Access Control / Policy Decision Point (Module 5, Phase 8: RL) ---
# Static thresholds remain available as Phase 5's fallback/baseline -- set
# USE_RL_POLICY=True to switch the gateway to the offline-trained
# epsilon-greedy contextual bandit in adaptive_pdp.AdaptivePDP instead.
THRESHOLD_ALLOW = 0.70
THRESHOLD_STEP_UP = 0.40
# trust >= THRESHOLD_ALLOW      -> ALLOW
# THRESHOLD_STEP_UP <= trust <  THRESHOLD_ALLOW -> STEP_UP (re-authenticate)
# trust <  THRESHOLD_STEP_UP    -> DENY

USE_RL_POLICY = True
RL_TRUST_BUCKET_SIZE = 0.1       # trust score discretized into buckets of this width -> the bandit's "state"
RL_CONFIDENCE_BUCKET_SIZE = 0.5  # confidence discretized into 2 buckets (low/high) -> second state dimension
RL_EPSILON = 0.1                 # exploration rate
RL_ALPHA = 0.2                   # Q-value learning rate
RL_TRAINING_EPISODES = 20        # passes over the offline dataset during scripts/train_adaptive_pdp.py

# --- Monitoring / Audit Log (Module 7) ---
# Was a bare relative path ("data/audit_log.db") -- resolved differently
# depending on the CURRENT WORKING DIRECTORY a script happened to be
# launched from, not the repo layout. Silently masked as long as every
# script that touched it was launched from src/ (gateway.py,
# device_simulator.py, dashboard.py always were, per every doc's
# instructions) -- surfaced as a real "no such table" error the first time
# scripts/evaluate_governance.py (run from the repo root, like the other
# scripts/*.py) tried to read it. Made absolute, anchored to src/, matching
# MODELS_DIR/DATA_COLLECTED_DIR's pattern above -- now correct regardless
# of which directory a script is launched from.
AUDIT_DB_PATH = os.path.join(_SRC_DIR, "data", "audit_log.db")

# --- NIST SP 800-207 tenet mapping (Module 7, synopsis Sections 4.3/7.3/10.1) ---
# The synopsis calls this a PRIMARY deliverable, not a discussion point:
# "governance completeness -- proportion of tenets for which the system
# produces a traceable, logged artefact." Each audit_log row gets tagged
# with which tenet(s) it's evidence for -- see nist_mapping.py's
# tenets_for_decision(), called from gateway.py before every log_decision().
NIST_TENETS = {
    1: "All data sources and computing services are considered resources.",
    2: "All communication is secured regardless of network location.",
    3: "Access to individual resources is granted on a per-session basis.",
    4: "Access is determined by dynamic policy, including behavioural/trust state.",
    5: "The enterprise monitors and measures the security posture of all assets.",
    6: "Authentication and authorization are dynamic and strictly enforced before access.",
    7: "The enterprise collects state/telemetry and uses it to improve its posture.",
}

# --- Collected data (CLAUDE.md Section 11) ---
DATA_COLLECTED_DIR = os.path.join(_SRC_DIR, "..", "data", "collected")
