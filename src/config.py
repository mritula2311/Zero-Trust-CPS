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
# Gateway -> device step-up challenge nonce (Module 2 Section 7). Same
# per-device-suffix pattern as DECISION_TOPIC, for the same least-privilege
# reason -- each device only needs to read its own challenge topic.
CHALLENGE_TOPIC = "cps/challenge"

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

# --- Module 9 extension: dashboard HTTP server (Phase 9, merged into
# gateway.py itself -- see gateway.py's start_dashboard_server(), same
# background-thread pattern as coap_server.py's second transport) ---
DASHBOARD_PORT = 8600
COAP_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "certs", "coap_server.key")
COAP_ENABLED = os.path.exists(COAP_CERT_PATH) and os.path.exists(COAP_KEY_PATH)  # auto-on once certs exist

# --- Replay protection (Module 2/4, boot_id + seq scheme) ---
# SUPERSEDES the old REBOOT_TS_THRESHOLD_MS heuristic (a ts-size guess at
# "is this a reboot" that had a documented blind spot: a message captured
# from within a device's first few seconds of uptime could still be
# replayed later and be accepted, since it would look like a fresh boot).
#
# Every device now carries two extra fields: `boot_id` (a small counter,
# incremented exactly once per boot -- on real hardware this would be
# persisted to flash; here, firmware/main.py persists it to a local file as
# the flash-equivalent, and device_simulator.py just keeps it in memory)
# and `seq` (resets to 1 every boot, strictly increasing within a boot
# session). The gateway's rule (trust_engine.check_boot_replay()):
#   boot_id strictly higher than last seen  -> ACCEPT, new session, seq
#                                               baseline resets to this seq
#   boot_id equal to last seen              -> ACCEPT only if seq is
#                                               strictly higher than last seen
#   boot_id lower than last seen            -> REJECT unconditionally --
#                                               this session has already
#                                               been superseded by a higher
#                                               one, closing exactly the
#                                               blind spot above: an
#                                               attacker who captured a
#                                               whole pre-reboot session
#                                               cannot replay any message
#                                               from it after a legitimate
#                                               reboot has moved the device
#                                               onto a new boot_id.
# `ts` (still carried, still int ms) is now a SECONDARY freshness check --
# REPLAY_WINDOW_SECONDS below -- independent of the boot/seq check, per
# docs/03_module2_authentication.md Section 4 Check 5.
REPLAY_WINDOW_SECONDS = 600   # DEMO ACCOMMODATION (isolated hotspot, no NTP route): widened
                               # from 30s so a manually-set board RTC that's a few minutes off
                               # still passes the SECONDARY freshness check. boot_id/seq
                               # (check_boot_replay) remains the PRIMARY anti-replay mechanism and
                               # is unaffected. Revert to 30 once the board gets real NTP time
                               # (share the laptop's internet to the hotspot / enable ICS).

# --- Automatic quarantine on sustained BLOCK (Module 5 enforcement) ---
# The 2x2 policy table's BLOCK row is specified as "Block / quarantine"
# (docs/06 Section 2), but the decision itself is ADVISORY: it is computed,
# signed, delivered to the device, logged and displayed, and then nothing acts
# on it. Measured on this repository's own audit log: 1112 BLOCK decisions, and
# after the last one the same device sent 6264 more messages, all accepted and
# scored. Enforcement genuinely exists at Module 2 (a revoked device is rejected
# before HMAC, a throttled identity is dropped) but not at Module 5.
#
# This closes that gap using the enforcement primitive that already exists and
# is already validated -- trust_engine.revoke_device(), whose effect gateway.py
# checks before HMAC. Sustained BLOCK escalates to revocation, i.e. real
# quarantine.
#
# DEFAULT OFF, and that default is not timidity -- it is the measured lesson
# from this repository's own history. During the Isolation Forest calibration
# defect (RESULTS.md Section 0.1) the REAL, physically healthy ESP32 accumulated
# 953 BLOCK decisions, including 108 runs of >=3 consecutive BLOCKs, 20 runs of
# >=10, and one unbroken run of 50. Auto-quarantine armed at any threshold up to
# 50 would have revoked live hardware because of a scoring bug, and because
# is_revoked() is a hard override the board would have stayed dead until a human
# reinstated it. Arm this only once you trust the models' false-positive rate on
# YOUR data, and read RESULTS.md Section 0.6 for what that rate currently is.
AUTO_QUARANTINE_ENABLED = False

# Consecutive BLOCK decisions for ONE device before quarantine. Consecutive, not
# cumulative: a single ALLOW resets the counter, so this triggers on sustained
# conviction rather than on scattered BLOCKs across a long session. 20 is chosen
# against the history above -- it sits above the 108 short runs so ordinary
# noise never fires it, while the 20 genuinely sustained runs WOULD have fired
# it, which is the point: a device that looks blocked for 40 seconds straight is
# either compromised or the model is broken, and both deserve a human.
AUTO_QUARANTINE_CONSECUTIVE_BLOCKS = 20

# --- Step-up authentication (Module 2 Section 7 / Module 5) ---
# Real gateway-issued-nonce / device-echo challenge-response, closing the
# "not literal interactive challenge-response" gap
# docs/03_module2_authentication.md Section 1.2 names. See gateway.py's
# initiate_step_up() / check_step_up_response().
STEP_UP_CHALLENGE_TIMEOUT_SECONDS = 10
STEP_UP_SUCCESS_SCORE_BOOST = 0.1   # bounded -- does not fully reset a bad score

# --- Identity Targeting Risk (Module 2 Section 5 attribution fix) ---
# Tracked per CLAIMED device_id (registered or not) from REJECTED
# verification attempts only -- deliberately never allowed to touch a real
# device's own SecurityTrustState. See trust_engine.IdentityTargetingRisk
# and gateway.py's _reject() path. Crossing this threshold within 60s
# triggers a temporary gateway-level cooldown on further attempts against
# that specific claimed id, dropped before they even reach verification --
# a defence against the traffic, not a judgement about a real device.
IDENTITY_TARGETING_RISK_THRESHOLD_60S = 20
IDENTITY_TARGETING_COOLDOWN_SECONDS = 30

# --- Device Identity Registry (Module 1) ---
# In a real deployment each device would hold its own secret in a secure
# element (ATECC608A or similar). Here we keep a simple in-memory registry on
# the gateway so you can see the identity + authentication logic clearly.
#
# `kind: "feature_vector"` -- the real ESP32 (firmware/main.py), one MPU6050
# over I2C, no separate vibration sensor. Payload carries all 5 Section-5.1
# features (rms, peak, crest_factor, kurtosis, dominant_freq), computed
# on-device (see firmware/main.py's docstring for why the FFT etc. moved
# on-device rather than shipping a raw sample window over the signed
# channel). `expected_ranges` is a plausible
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
            # rms lower bound raised from 0.0 to 0.1 -- found live (RESULTS.md
            # Section 13.2) that a genuinely disconnected MPU6050 reads back
            # all-zero bytes over I2C rather than raising an error, producing
            # rms=peak=crest_factor=kurtosis=0.0 -- physically impossible for
            # a connected accelerometer (gravity alone contributes ~1g even
            # at rest), but rms=0.0 satisfied the old (0.0, 3.0) bound
            # trivially. 0.1 stays well below every real observed minimum
            # (0.33g across 5 real sessions, Section 13.2's table) while
            # catching this exact fault. peak/crest_factor/kurtosis are NOT
            # tightened the same way -- unlike rms, they can legitimately
            # approach 0 during genuinely still real readings (observed real
            # minimum peak was 0.0087g), so a similar floor there risks a
            # false positive on quiet-but-connected operation.
            "rms": (0.1, 3.0),              # g
            "peak": (0.0, 6.0),             # g (peak-to-peak)
            "crest_factor": (0.0, 10.0),    # dimensionless (peak-to-peak / rms, not textbook max/rms -- see feature_engineering.py)
            "kurtosis": (-3.0, 30.0),       # excess kurtosis
            # Upper bound is NYQUIST, derived rather than written down: a DFT cannot
            # report a frequency above half the sampling rate, so any fixed number here
            # silently becomes wrong the moment the rate changes. It did exactly that --
            # left at 50.0 after the rate moved to 500 Hz, it marked 35 of 114 genuine
            # resting readings "out of range" purely as an artefact of a stale constant.
            "dominant_freq": None,   # set below, once FEATURE_SAMPLE_RATE_HZ exists
        },
    },
    # SECOND REAL NODE. ESP32 + SW-420 digital vibration switch -- a comparator-
    # gated mechanical contact on one GPIO, NOT an accelerometer. It publishes
    # the four event-statistics features defined in
    # src/feature_engineering_sw420.py; rms/peak/crest_factor/kurtosis/
    # dominant_freq are physically undefined for a binary switch and are
    # deliberately absent rather than synthesised (see that module's docstring).
    #
    # This heterogeneity is the point: two physical nodes with different sensing
    # modalities test cross-device behaviour, NOT same-model MPU6050
    # sensor-to-sensor replication. Reported as such.
    #
    # expected_ranges are the Part A hard physical bounds only -- deliberately
    # wide, because the fine-grained judgement belongs to the ML scorers. They
    # are derived, not guessed:
    #   trigger_rate   [0, SW420_SAMPLE_RATE_HZ/2] -- an edge needs at least one
    #                  low sample between two highs, so the rate cannot exceed
    #                  half the sampling rate. Nyquist for an edge stream, set
    #                  below once SW420_SAMPLE_RATE_HZ exists, for the same
    #                  reason dominant_freq's bound is derived rather than typed.
    #   duty_cycle     [0, 1] by construction.
    #   burst_max_ms   [0, window duration] -- a closure cannot outlast the window.
    #   inter_event_cv [0, 5] -- unbounded above in principle; 5 is far past any
    #                  physically plausible gap-irregularity and exists only to
    #                  catch a corrupt payload.
    "esp32-vib-002": {
        "secret": DEVICE_SECRETS.get("esp32-vib-002", "CHANGE-ME-generate-your-own-secret"),
        "kind": "vibration_switch",
        "mqtt_username": "esp32-vib-002",
        "mqtt_password": MQTT_PASSWORDS.get("esp32-vib-002", "CHANGE-ME-generate-your-own-password"),
        "sensor_type": "SW-420",
        "expected_ranges": {
            "trigger_rate": None,     # set below, once SW420_SAMPLE_RATE_HZ exists
            "duty_cycle": (0.0, 1.0),
            "burst_max_ms": None,     # set below, once the window duration is known
            "inter_event_cv": (0.0, 5.0),
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

# --- Key rotation / device revocation (Module 1, docs/02_module1_device_
# identity.md Sections 2-3; RESULTS.md Section 14 item 1) ---
# Applied uniformly to every DEVICE_REGISTRY entry rather than repeated per
# entry above -- every device starts "active", version 1, no previous key.
# `secret` (unchanged key name, not renamed to avoid touching every
# existing `info["secret"]` call site) is always the CURRENT key;
# `secret_previous` is populated only during a rotation's grace window by
# trust_engine.rotate_key(), and cleared once KEY_ROTATION_GRACE_SECONDS
# has elapsed since `key_rotated_at` or on the next rotation, whichever
# comes first.
# --- The eight SIMULATED nodes of the 10-node hybrid network (03-10) ---
#
# Loaded from config/simulated_nodes.json rather than typed here, so the
# profile parameters, the seeds, and the registry entries cannot drift apart.
# JSON not YAML: docs/11 records dropping pyyaml, and it is not installed.
#
# These are NOT physical devices. Every record they produce carries
# source_type = "SIMULATED", and no result mixes them with real evidence
# without saying which is which. See docs/EXPERIMENTAL_PROTOCOL.md.
#
# Each gets its own HMAC secret and MQTT password derived deterministically from
# its seed. Real secrets for real devices live in the gitignored secrets_local.py;
# a simulated node has no physical secure element to hold a key, so deriving one
# reproducibly is honest about what it is rather than pretending otherwise.
import hashlib as _hashlib
import json as _json

SIMULATED_NODES_PATH = os.path.join(_SRC_DIR, "..", "config", "simulated_nodes.json")
GRAPH_TOPOLOGY_PATH = os.path.join(_SRC_DIR, "..", "config", "graph_topology.json")

with open(SIMULATED_NODES_PATH) as _f:
    SIMULATED_NODE_PROFILES = {n["device_id"]: n for n in _json.load(_f)["nodes"]}

for _did, _profile in SIMULATED_NODE_PROFILES.items():
    _derived = _hashlib.sha256(f"ztcps-sim-{_profile['seed']}".encode()).hexdigest()
    DEVICE_REGISTRY[_did] = {
        "secret": _derived[:32],
        "kind": _profile["kind"],
        "mqtt_username": _did,
        "mqtt_password": _derived[32:56],
        "source_type": "SIMULATED",
        "sensor_type": "MPU6050-like" if _profile["kind"] == "feature_vector" else "SW-420-like",
        "simulation_profile": _profile["variation"],
        "seed": _profile["seed"],
        # Same wide physical bounds as the corresponding real node's kind --
        # a simulated node is a stand-in for a device of that type, so it is
        # range-checked by the same rule, not given looser bounds that would
        # quietly make the rule signal unable to fire on it.
        "expected_ranges": (
            {"rms": (0.1, 3.0), "peak": (0.0, 6.0), "crest_factor": (0.0, 10.0),
             "kurtosis": (-3.0, 30.0), "dominant_freq": None}
            if _profile["kind"] == "feature_vector" else
            {"trigger_rate": None, "duty_cycle": (0.0, 1.0),
             "burst_max_ms": None, "inter_event_cv": (0.0, 5.0)}
        ),
    }
del _did, _profile, _derived, _f

with open(GRAPH_TOPOLOGY_PATH) as _f:
    GRAPH_TOPOLOGY = _json.load(_f)
del _f

# The ten nodes of the principal network experiment, in a fixed order.
# sensor-002 and actuator-001 remain in DEVICE_REGISTRY -- they are the original
# starter-kit demo devices and the live gateway/simulator still use them -- but
# they are NOT part of the 10-node network and are inactive throughout every
# network experiment, so they contribute only a self-loop and influence nothing.
# Reported network_size is therefore 10, which is what participates.
NETWORK_NODES = [n["device_id"] for n in GRAPH_TOPOLOGY["nodes"]]
REAL_NODES = [n["device_id"] for n in GRAPH_TOPOLOGY["nodes"] if n["source_type"] == "REAL"]
SIMULATED_NODES = [n["device_id"] for n in GRAPH_TOPOLOGY["nodes"] if n["source_type"] == "SIMULATED"]
assert len(NETWORK_NODES) == 10 and len(REAL_NODES) == 2 and len(SIMULATED_NODES) == 8, \
    "the hybrid network is 2 REAL + 8 SIMULATED = 10 by definition; graph_topology.json disagrees"


def network_edges() -> set:
    """Undirected edge set (frozensets of two device_ids) from the topology:
    complete within each process group, plus the declared inter-group backbone.
    One implementation, used by the GNN adjacency and by every baseline that
    needs the same neighbourhood, so a baseline can never be handed a different
    graph than the GNN and then lose to it."""
    edges = set()
    for members in (g["members"] for g in GRAPH_TOPOLOGY["groups"].values()):
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                edges.add(frozenset((a, b)))
    for a, b in GRAPH_TOPOLOGY["inter_group_edges"]:
        edges.add(frozenset((a, b)))
    return edges


for _device_id, _info in DEVICE_REGISTRY.items():
    _info.setdefault("status", "active")           # active | revoked
    _info.setdefault("key_version", 1)              # increments on every rotate_key() call
    _info.setdefault("secret_previous", None)       # populated only during a grace period
    _info.setdefault("key_rotated_at", None)        # time.time() of the last rotation, None if never rotated
del _device_id, _info


# Device kinds that publish a multi-feature vector and therefore carry their own
# per-device ML scorers, as opposed to `scalar` devices which have a single value
# and mirror rule_score into the ML slots.
#   feature_vector    -- MPU6050 accelerometer, 5 features (feature_engineering.py)
#   vibration_switch  -- SW-420 binary switch, 4 features (feature_engineering_sw420.py)
# The two feature sets are different LENGTHS and different QUANTITIES. That is
# fine and is the point: every model that consumes raw features is per-device
# (see the model-path helpers below), and everything shared downstream -- the
# GNN and the fusion meta-learner -- consumes already-normalised [0,1]
# sub-scores rather than raw features, so neither changes shape.
ML_FEATURE_KINDS = ("feature_vector", "vibration_switch")


def is_feature_vector(device_id: str) -> bool:
    """Single source of truth for 'does this device publish a multi-feature
    vector, and therefore run the per-device ML scorers (Isolation Forest /
    LSTM-AE / Transformer), rather than a single scalar?'.
    Every place that decides that -- the live gateway AND every offline
    train_*/evaluate_* script -- keys off THIS, not a hardcoded
    "esp32-vib-001" string, so the live and offline paths can never disagree
    about a device's shape and an additional feature-carrying device
    (simulated or real hardware) is handled identically everywhere without
    touching each call site.

    Widened from `kind == "feature_vector"` to cover the SW-420 second real
    node. The NAME is unchanged deliberately: it is called at ~20 sites and
    every one of them means "does this device have an ML feature vector",
    which is still exactly what this answers."""
    return DEVICE_REGISTRY.get(device_id, {}).get("kind") in ML_FEATURE_KINDS


def feature_names_for(device_id: str) -> list[str]:
    """The ordered feature names THIS device publishes. Callers that used the
    module-level FEATURE_NAMES global were implicitly assuming one sensor type;
    with a heterogeneous second node that assumption is no longer safe, so any
    site handling more than one device must ask here."""
    kind = DEVICE_REGISTRY.get(device_id, {}).get("kind")
    if kind == "vibration_switch":
        return list(SW420_FEATURE_NAMES)
    return list(FEATURE_NAMES)


def feature_vector_for(device_id: str, features: dict) -> list[float]:
    """Fixed-order feature list for `device_id`, dispatching on its kind. The
    one place that knows which reference implementation belongs to which
    device, so no scorer or training script has to."""
    return [features[name] for name in feature_names_for(device_id)]


# Every device that carries its OWN per-device Isolation Forest / LSTM-AE /
# Transformer model (see the per-device model-path helpers below). A device's
# raw vibration distribution is physics-specific, so these three scorers are
# trained per device rather than shared -- adding a second real board only
# means capturing its data and re-running the trainers, no code change. The
# GNN (a graph over ALL devices) and the fusion meta-learner (operates on the
# four already-normalised [0,1] sub-scores, not raw features) stay SHARED --
# they are device-agnostic by construction.
FEATURE_VECTOR_DEVICE_IDS = [d for d, i in DEVICE_REGISTRY.items() if i.get("kind") in ML_FEATURE_KINDS]

KEY_ROTATION_GRACE_SECONDS = 24 * 3600   # docs/02 Section 3's "24 hours in hardware-time-equivalent" default

# --- Real hardware onboarding (firmware/HARDWARE_SETUP.md) ---
# Once a real ESP32 is flashed and running firmware/main.py for a given
# device_id, add that id here so device_simulator.py stops also publishing
# under the same identity -- two publishers sharing one device_id would
# race on boot_id/seq (trust_engine.check_boot_replay()) and the real
# board's messages would intermittently get rejected as replays of the
# simulator's, or vice versa. Empty by default (pure simulation mode).
REAL_HARDWARE_DEVICE_IDS: set = {"esp32-vib-001", "esp32-vib-002"}

# --- Feature Engineering (Module 3, CLAUDE.md Section 5.1) ---
FEATURE_NAMES = ["rms", "peak", "crest_factor", "kurtosis", "dominant_freq"]
# NOMINAL sample rate, and it is NOT the achieved one -- see RESULTS.md 13.4c.
# The comment here used to claim it "matches firmware/main.py's dt_ms=10 sampling
# loop"; there is no such loop. sample_window() reads 32 samples back-to-back with
# no delay, measured at 26 ms on real hardware = ~1231 Hz, 12.3x this value.
# Both the simulator and the firmware use this same nominal constant and the same
# window size, so dominant_freq is a CONSISTENT bin index end to end and detection
# is unaffected -- but it is a bin index in nominal units, not a physical
# frequency. Do not read dominant_freq as Hz without applying the 12.3x
# correction, and do not change this constant without retraining: every
# dominant_freq value the models learned is scaled by it.
FEATURE_SAMPLE_RATE_HZ = 500.0
FEATURE_WINDOW_SIZE = 32         # samples per on-device window, matches firmware/main.py

# The dominant_freq bound is NYQUIST, derived here rather than written into the
# registry as a literal. A DFT cannot report a frequency above half the sampling
# rate, so any fixed number becomes wrong the moment the rate changes -- and it
# did: left at 50.0 after the rate moved to 500 Hz, it marked 35 of 114 genuine
# resting readings 'out of range' purely as an artefact of a stale constant.
# Deriving it means the bound can never drift from the acquisition chain again.
#
# Guarded on kind == "feature_vector". Without the guard this loop reaches the
# SW-420 node too, whose expected_ranges legitimately has no dominant_freq key,
# and `.get(...) is None` would be satisfied -- inventing a frequency bound for
# a device that publishes no frequency. rule_range_score would then check a
# feature that never arrives.
for _info in DEVICE_REGISTRY.values():
    if _info.get('kind') != 'feature_vector':
        continue
    if _info.get('expected_ranges', {}).get('dominant_freq') is None:
        _info.setdefault('expected_ranges', {})['dominant_freq'] = (0.0, FEATURE_SAMPLE_RATE_HZ / 2)
del _info

# --- SW-420 acquisition chain (esp32-vib-002, firmware/main_sw420.py) ---
# Same "the acquisition chain is one decision" rule as the MPU6050 node: rate
# and window size move together, both sides must agree exactly, and a change to
# either requires retraining that device's models. Enforced by
# tests/test_invariants.py::TestSW420SamplingContract.
#
# 1000 Hz / 256 samples = a 256 ms window. Chosen for the sensor, not copied
# from the MPU6050 node: an SW-420 fires as a sparse train of brief contact
# closures, so a 64 ms window (the MPU6050's) would frequently contain zero
# edges even during genuine shaking and every feature would read 0 -- the
# feature set would be mostly silence. 256 ms is long enough to hold several
# closures of a hand-shaken board while staying well inside the 1 s telemetry
# interval. 1 kHz sampling resolves a contact closure (order 1-30 ms) into tens
# of samples rather than one or two.
SW420_SAMPLE_RATE_HZ = 1000.0
SW420_WINDOW_SIZE = 256
SW420_WINDOW_MS = 1000.0 * SW420_WINDOW_SIZE / SW420_SAMPLE_RATE_HZ
SW420_FEATURE_NAMES = ["trigger_rate", "duty_cycle", "burst_max_ms", "inter_event_cv"]
SW420_GPIO_PIN = 4               # D0 -> GPIO4; documented in firmware/HARDWARE_SETUP_SW420.md

# Derived bounds, for the same reason dominant_freq's is derived: a literal here
# silently becomes wrong when the acquisition chain moves.
#   trigger_rate: a rising edge needs a low sample between two highs, so edges
#                 cannot exceed half the sample rate.
#   burst_max_ms: a closure cannot outlast the window that observed it.
for _info in DEVICE_REGISTRY.values():
    if _info.get('kind') != 'vibration_switch':
        continue
    _er = _info['expected_ranges']
    if _er.get('trigger_rate') is None:
        _er['trigger_rate'] = (0.0, SW420_SAMPLE_RATE_HZ / 2)
    if _er.get('burst_max_ms') is None:
        _er['burst_max_ms'] = (0.0, SW420_WINDOW_MS)
del _info, _er

# --- Trust Evaluation (Module 3, Section A: Security Behaviour Engine) ---
# Two-score rearchitecture: these now apply ONLY to the Security Trust
# Score (cyber-behaviour evidence -- rate/flood, silence). They are no
# longer touched by auth failures (see IdentityTargetingRisk above) or by
# physical sensor values (that's the Process Anomaly Score, Section B,
# entirely owned by fusion_engine.py's already-trained stack, unchanged).
TRUST_EWMA_ALPHA = 0.35          # weight given to the newest observation
TRUST_DECAY_PER_SECOND = 0.01    # security trust drifts down slowly if a device goes quiet
STALE_AFTER_SECONDS = 20         # a device not heard from in this long is "stale" (Security side)
PROCESS_STALE_AFTER_SECONDS = 20  # separate staleness clock for the Process Anomaly Score --
                                   # its VALUE is never touched on staleness, only this status
                                   # (docs/05_module4_continuous_verification.md Section 2.2)

# Found live (RESULTS.md Section 13): trust_engine.is_stale()/
# get_process_anomaly()'s staleness checks are lazily evaluated, but their
# only call site in gateway.py always runs immediately after
# update_process_anomaly() refreshes the very state being checked -- so in
# a live gateway, staleness was never actually reachable without a
# dedicated periodic check independent of message arrival. This is that
# check's interval -- how often gateway.py's silence watchdog (its own
# background thread, same pattern as the dashboard/HTTPS second
# transport) sweeps every registered device.
SILENCE_CHECK_INTERVAL_SECONDS = 5

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

# Per-device model artifacts (Isolation Forest / LSTM-AE / Transformer). One
# model file PER feature_vector device -- the filename carries the device_id
# so a second real board never silently reuses (or gets scored by) another
# device's model. A device with no trained file yet makes its scorer return
# the neutral "not trained" fallback (0.9), exactly as a missing single file
# did before, so an un-onboarded device fails SAFE rather than being scored
# by the wrong model.
def isolation_forest_path(device_id: str) -> str:
    return os.path.join(MODELS_DIR, f"isolation_forest_{device_id}.joblib")

def isolation_forest_meta_path(device_id: str) -> str:   # decision_function -> [0,1] calibration anchors
    return os.path.join(MODELS_DIR, f"isolation_forest_{device_id}_meta.json")

def lstm_ae_path(device_id: str) -> str:
    return os.path.join(MODELS_DIR, f"lstm_ae_{device_id}.pt")

def lstm_ae_meta_path(device_id: str) -> str:            # normalization + baseline-error stats
    return os.path.join(MODELS_DIR, f"lstm_ae_{device_id}_meta.json")

def transformer_path(device_id: str) -> str:
    return os.path.join(MODELS_DIR, f"transformer_ae_{device_id}.pt")

def transformer_meta_path(device_id: str) -> str:
    return os.path.join(MODELS_DIR, f"transformer_ae_{device_id}_meta.json")

# Shared, device-agnostic artifacts (see FEATURE_VECTOR_DEVICE_IDS' comment).
GNN_MODEL_PATH = os.path.join(MODELS_DIR, "gnn.pt")
FUSION_MODEL_PATH = os.path.join(MODELS_DIR, "fusion_meta_learner.joblib")
FUSION_BACKGROUND_PATH = os.path.join(MODELS_DIR, "fusion_background.npy")   # SHAP background sample
ADAPTIVE_PDP_MODEL_PATH = os.path.join(MODELS_DIR, "adaptive_pdp_qtable.json")

# --- Training seed ---
# Every training script pins its RNG so a rebuild is reproducible. That makes each
# number deterministic, which is NOT the same as it being stable: a single seed
# reports one draw from the distribution of models the pipeline can produce, with
# no indication of the spread. Overriding this (env ZTCPS_SEED) lets the same
# chain be retrained across seeds so headline metrics can carry a mean and a
# standard deviation instead of a point estimate (RESULTS.md 0.10.11).
# Default 0 -- the shipped models are the seed-0 draw.
TRAINING_SEED = int(os.environ.get("ZTCPS_SEED", "0"))

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

# --- Transformer sub-signal (ablation candidate, NOT wired into the live
# fusion meta-learner -- same keep/drop precedent as the GNN in Section
# B.5 of docs/04_module3_trust_evaluation.md: prove it earns its place in
# scripts/evaluate_ablation.py against the same held-out set before ever
# folding it into fusion_engine.py's inputs). Reuses LSTM_SEQ_LEN (not a
# separate constant) so the window length is held constant between the
# LSTM-AE and this signal -- the ablation comparison should isolate
# ARCHITECTURE as the only variable, not window size too.
#
# Denoising autoencoder, not plain reconstruction: self-attention gives
# every position direct access to every other position in the window, so
# a naive reconstruction transformer can partially "shortcut" -- attend to
# neighboring true values and copy, reconstructing anomalies too well and
# under-scoring them. Training against noise-corrupted input (this
# script) while scoring against the CLEAN window at inference time
# (transformer_scorer.py) removes the trivial-copy path without changing
# the task framing (still "reconstruct the window", directly comparable
# to the LSTM-AE's own framing).
TRANSFORMER_D_MODEL = 32          # kept small deliberately -- same "not a case that needs a
                                   # large model" reasoning documented for the GNN below;
                                   # 5 input features over an 8-step window has little room
                                   # for a bigger model to exploit before it starts overfitting.
TRANSFORMER_NHEAD = 4
TRANSFORMER_NUM_LAYERS = 2
TRANSFORMER_DIM_FEEDFORWARD = 64
TRANSFORMER_DROPOUT = 0.2          # higher than a typical NLP transformer -- regularization
                                    # matters more given the still-modest training set size.
TRANSFORMER_NOISE_STD = 0.15       # Gaussian noise std added to normalized input during
                                    # training only (denoising objective above).
TRANSFORMER_EPOCHS = 150
TRANSFORMER_LEARNING_RATE = 0.001  # lower than LSTM_LEARNING_RATE -- transformers are more
                                    # sensitive to a too-high LR than an LSTM at this scale.

# --- GNN (Module 3, Phase 6c) ---
# Sensor-channel graph vs. hybrid device-graph (CLAUDE.md Section 2 offers
# both as legitimate options): this build uses the HYBRID DEVICE-GRAPH --
# nodes = the entries in DEVICE_REGISTRY, edges = "communicated with the
# gateway in the same time window" -- because it reuses the existing
# per-device trust-state pattern cleanly and still satisfies the module's
# purpose (relational/coordinated anomaly detection across devices). State
# this choice explicitly in the paper (Section 2 asks you to).
GNN_EDGE_WINDOW_SECONDS = 5.0

# Weight of a node's OWN features relative to each neighbour's, inside the
# GCN's normalized adjacency (gnn_scorer.normalized_adjacency: A = wI + edges,
# then the usual D^-1/2 A D^-1/2). With the textbook w=1 and all 3 devices
# active, symmetric normalization gives a node's own evidence only 1/3 of its
# representation and its two neighbours the other 2/3 -- so a device's Process
# Anomaly score moved with whether UNRELATED devices happened to be publishing
# inside the edge window, measured at fused 0.02 (alone) vs 0.58 (3 active) for
# one identical ESP32 reading. It also made the isolated topology (a real board
# publishing with the simulator stopped -- the normal single-device deployment)
# a different activation scale than anything training emphasised. w=3 keeps the
# relational term that the GNN exists for (a neighbour still moves the score,
# which is what catches the 'coordinated' event type) while making a node's own
# physical evidence the majority of its own verdict, as it should be.
GNN_SELF_LOOP_WEIGHT = 3.0
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
# LR and epochs are env-overridable (ZTCPS_GNN_LR / ZTCPS_GNN_EPOCHS) so seed
# stability can be swept without editing source. The GNN is the most
# seed-sensitive signal (accuracy sd 0.011 across seeds, ~10x the fused model's),
# and lr is the first knob to check because a high Adam lr lands different
# initialisations in different minima. Deployed default kept unless a sweep shows
# a lower lr cuts variance WITHOUT hurting coordinated recall (the metric the GNN
# exists for) -- RESULTS.md 0.10.18.
GNN_EPOCHS = int(os.environ.get("ZTCPS_GNN_EPOCHS", "150"))
GNN_LEARNING_RATE = float(os.environ.get("ZTCPS_GNN_LR", "0.05"))
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

# --- Access Control / Policy Decision Point (Module 5) ---
# Two-score 2x2 table (docs/06_module5_access_control.md Section 2), NOT a
# single trust threshold anymore -- both scores are "trust-style" (high =
# good) internally, so "process high" means "process anomaly LOW":
#   security_high  and  process_high  -> ALLOW
#   security_high  and !process_high  -> ALERT    (pass through + flag ops --
#                                                    likely a REAL physical
#                                                    problem, not an attack)
#   !security_high and  process_high  -> STEP_UP
#   !security_high and !process_high  -> BLOCK
# Static thresholds remain available as the fallback/baseline -- set
# USE_RL_POLICY=True to switch the gateway to the offline-trained
# epsilon-greedy contextual bandit in adaptive_pdp.AdaptivePDP instead
# (state = (security_bucket, process_bucket), actions =
# {ALLOW, STEP_UP, ALERT, BLOCK}).
SECURITY_THRESHOLD = 0.6
PROCESS_THRESHOLD = 0.6

USE_RL_POLICY = True
# AdaptivePDP.greedy_action() (the live/eval path) is a pure, frozen Q-table
# lookup -- no exploration, no update() call -- so it needs no live reward
# signal at all; update() only ever runs offline in
# scripts/train_adaptive_pdp.py against known synthetic ground truth. This
# is what makes RL safe as the live default: see SESSION_LOG.md Section 7's
# epsilon-at-inference bug/fix for why choose_action() (WITH exploration) is
# the training-only method and greedy_action() is the only one the live
# gateway/evaluation scripts should ever call.
RL_SECURITY_BUCKET_SIZE = 0.1    # security trust score discretized into buckets of this width
RL_PROCESS_BUCKET_SIZE = 0.1     # process trust score discretized the same way -> second state dimension
RL_EPSILON = 0.1                 # exploration rate (training only)
# RL_ALPHA (a fixed 0.2 Q-value learning rate) was removed: AdaptivePDP.update()
# now uses an incremental SAMPLE AVERAGE (alpha = 1/N per (state, action) visit),
# which is the correct estimator for this stationary contextual bandit -- see that
# method's docstring for the measured failure the fixed rate caused.
RL_TRAINING_EPISODES = 20        # passes over the offline dataset during scripts/train_adaptive_pdp.py

# --- Monitoring / Audit Log (Module 7) ---
# Was a bare relative path ("data/audit_log.db") -- resolved differently
# depending on the CURRENT WORKING DIRECTORY a script happened to be
# launched from, not the repo layout. Silently masked as long as every
# script that touched it was launched from src/ (gateway.py,
# device_simulator.py, webapp_server.py always were, per every doc's
# instructions) -- surfaced as a real "no such table" error the first time
# scripts/evaluate_governance.py (run from the repo root, like the other
# scripts/*.py) tried to read it. Made absolute, anchored to src/, matching
# MODELS_DIR/DATA_COLLECTED_DIR's pattern above -- now correct regardless
# of which directory a script is launched from.
# THE SPLIT BETWEEN src/data/ AND data/ IS DELIBERATE, not an accident of history.
#
# The audit database lives under src/data/. The checkpoint store that ATTESTS it
# lives at the repository root, under data/. Co-locating them would put the
# evidence and its witness in the same directory, so a single `rm -rf` or a single
# mis-scoped backup restore takes out both -- and the checkpoint store exists
# precisely to detect tampering with the database. Separation is the property, and
# it survives here rather than in a comment nobody reads because these two
# constants are defined next to each other with this note between them.
#
# It was previously recorded as "partly deliberate, partly historical". It is now
# just deliberate. Consolidating would mean relocating a live hash-chained
# database for cosmetic tidiness, which trades a real integrity property for an
# aesthetic one. Do not do it.
AUDIT_DB_PATH = os.path.join(_SRC_DIR, "data", "audit_log.db")

# --- Decision-channel anti-replay (Module 2, RESULTS.md Section 14 item 3) ---
# Same boot_id/seq pattern telemetry replay already uses (trust_engine.
# check_boot_replay()), applied in the other direction: the GATEWAY is the
# one whose "boot" can restart here, so gateway.py persists its own
# incrementing boot id the same way firmware/main.py persists boot_id.txt
# on the device side.
GATEWAY_BOOT_ID_PATH = os.path.join(_SRC_DIR, "data", "gateway_boot_id.txt")

# --- Hash-chained audit log + checkpoints (Module 7, docs/08 Section 3) ---
# The in-DB hash chain alone only catches an attacker who edits an old row
# and does NOT also recompute every subsequent hash -- one who does both
# leaves the chain internally consistent. The checkpoint file below is
# stored SEPARATELY from audit_log.db (a different file, HMAC'd with a
# separate key never shared with any device's registry entry) specifically
# so that class of attacker still gets caught: their recomputed in-DB chain
# won't match the independently-stored checkpoint's hash for the same row.
CHECKPOINT_INTERVAL_ROWS = 100
# Deliberately NOT beside AUDIT_DB_PATH -- see the note there. This is the witness;
# the database is the evidence; they do not share a directory.
CHECKPOINT_STORE_PATH = os.path.join(_SRC_DIR, "..", "data", "checkpoint_log.jsonl")
AUDIT_KEY_PATH = os.path.join(_SRC_DIR, "..", "data", "audit_key.bin")

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
