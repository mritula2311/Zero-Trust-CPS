"""
Module 7 extension: IEC 62443 alignment (CLAUDE.md Section 6 / 10, synopsis
Section 7). CLAUDE.md names IEC 62443 explicitly, alongside NIST SP
800-207 (nist_mapping.py): "its zones-and-conduits security model maps
naturally onto this project's Layer 1/2/3 architecture, and its
security-level concept (SL 1-4) gives you a vocabulary for stating what
level of attacker sophistication your prototype is designed to resist."
Section 10 asks for "A NIST SP 800-207 + IEC 62443 tenet-mapping table
generated from the audit log" as one combined evaluation deliverable --
this file is IEC 62443's half of that.

Two things this module provides, matching the two IEC 62443 concepts
CLAUDE.md names:

1. Zones and conduits (static architecture mapping, synopsis Section 7's
   three layers) -- ZONES and CONDUITS below.
2. Foundational Requirements (IEC 62443-3-3's FR1-FR7) coverage, computed
   from real audit_log rows the same way nist_mapping.py computes tenet
   coverage -- HONESTLY: FR5 and FR7 are "partial", a third status
   alongside "implemented"/"not_implemented", because real, achievable
   sub-controls now exist (MQTT broker per-device credentials + topic
   ACLs for FR5; flood detection + Mosquitto connection/size limits +
   process supervision for FR7) but the FULL requirement genuinely
   doesn't hold on a single machine (no physical network segmentation for
   FR5; no multi-instance redundancy/failover for FR7). Real IEC 62443
   assessments distinguish exactly this kind of partial coverage from
   both "not applicable" and "fully implemented" -- this module does the
   same rather than forcing every FR into a binary box that doesn't fit.
"""

from config import NIST_TENETS, MQTT_USE_AUTH  # NIST_TENETS kept for symmetry/reference with nist_mapping.py

ZONES = {
    "Device/Edge Zone": "ESP32 (firmware/main.py) + simulated devices (device_simulator.py) -- Modules 1, 2, 3-feature-extraction, 6 (client side). Deliberately minimal: identity, auth handshake, TLS/HTTPS termination only -- no model inference here (synopsis Section 7.1).",
    "Gateway Zone": "gateway.py + every src/*.py it imports -- Modules 1 (registry), 2 (verification), 3 (all 4 trust signals + fusion), 4, 5, 6 (server side). All computational cost of Zero Trust is absorbed here (synopsis Section 7.2).",
    "Monitoring/Governance Zone": "audit_log.py, nist_mapping.py, iec62443_mapping.py (this file) -- Module 7 (synopsis Section 7.3). The dashboard (design/zero-trust-cps-command-center.html, served with a live overlay by gateway.py itself -- see gateway.py's Module 9 extension section) reads from this zone via the same /api/* endpoints.",
}

CONDUITS = {
    "Device/Edge -> Gateway (telemetry)": "MQTT/TLS (port 8883) or HTTPS (port 5684, coap_server.py -- see its docstring for why HTTPS substitutes for CoAP/DTLS). Both encrypted, both no-plaintext-fallback once certs/ is populated. Since certs/mosquitto_passwd exists, each device authenticates to the broker with its own credential (config.DEVICE_REGISTRY's mqtt_username/mqtt_password) and certs/mosquitto_acl restricts it to write-only on this topic -- FR5.",
    "Gateway -> Device/Edge (decisions)": "MQTT, per-device topic cps/decisions/<device_id> (not a flat shared topic) -- a real actuator would subscribe to its OWN topic and refuse to act unless its own device_id's latest decision is ALLOW. certs/mosquitto_acl restricts each device to read-only on its own decisions topic specifically, not every device's -- FR5.",
    "Gateway -> Monitoring/Governance (audit)": "In-process function call (audit_log.log_decision()) -- not a network conduit in this single-process prototype; would become one (e.g. a message queue) in a distributed deployment.",
}

# IEC 62443-3-3 Foundational Requirements. `status` is one of:
#   "implemented"     -- fully covered, computed per-message from audit_log, like NIST tenets
#   "partial"         -- a real, achievable sub-control is implemented and its
#                         coverage IS computed, but the full requirement isn't
#                         (see `note` for the exact boundary)
#   "not_implemented" -- a real, honest gap in this prototype (see notes)
FOUNDATIONAL_REQUIREMENTS = {
    "FR1": {
        "name": "Identification and Authentication Control",
        "status": "implemented",
        "where": "Modules 1/2 -- DEVICE_REGISTRY + HMAC-SHA256 verify_signature()",
    },
    "FR2": {
        "name": "Use Control",
        "status": "implemented",
        "where": "Module 5 -- policy_engine.decide() / adaptive_pdp.AdaptivePDP.greedy_action()",
    },
    "FR3": {
        "name": "System Integrity",
        "status": "implemented",
        "where": "Modules 3/4 -- the 4-signal Process Anomaly fusion + boot_id/seq anti-replay "
                 "(trust_engine.check_boot_replay()) + secondary timestamp-freshness check "
                 "(trust_engine.check_timestamp_freshness())",
    },
    "FR4": {
        "name": "Data Confidentiality",
        "status": "implemented",
        "where": "Module 6 -- MQTT/TLS + HTTPS (both encrypted transports)",
    },
    "FR5": {
        "name": "Restricted Data Flow",
        "status": "partial",
        "where": "Module 6 -- certs/mosquitto_passwd + certs/mosquitto_acl (per-device MQTT broker credentials + topic ACLs: each device can publish only its own telemetry and read only its own decisions, via config.DEVICE_REGISTRY's mqtt_username/mqtt_password and the per-device cps/decisions/<device_id> topic)",
        "note": "This closes the TRANSPORT-layer conduit-restriction gap IEC 62443's zones/conduits model calls for (previously the broker's allow_anonymous=true meant application-layer HMAC checking was the ONLY enforcement -- see docs/07_transport_zero_trust.md for the before/after). What's still genuinely NOT done: physical/VLAN network segmentation between the three zones -- all three still run as processes on the same machine/network, so a compromised host itself would still see all traffic regardless of the broker ACLs. State both halves explicitly in the paper: real conduit-level access control exists now; physical segmentation is still future work.",
    },
    "FR6": {
        "name": "Timely Response to Events",
        "status": "implemented",
        "where": "Module 7 -- audit_log.py (every decision logged with a reason) + dashboard.py (live view, ~2s refresh)",
    },
    "FR7": {
        "name": "Resource Availability",
        "status": "partial",
        "where": "Module 4 -- trust_engine.check_flood() (per-device message-rate anomaly detection, config.MIN_MESSAGE_INTERVAL_SECONDS) + trust_engine.IdentityTargetingRisk's gateway-level cooldown (drops further attempts against a claimed device_id once IDENTITY_TARGETING_RISK_THRESHOLD_60S is crossed, before they even reach verification) + Mosquitto max_connections/message_size_limit (docs/07_transport_zero_trust.md) + scripts/run_gateway_supervised.py (restart-on-crash process supervision)",
        "note": "What's still genuinely NOT done: true redundancy/failover in the multi-instance sense -- this is still ONE gateway process (now automatically restarted if it crashes, but not load-balanced across multiple instances) and the rate-limiting is connection/message-count based, not a sophisticated per-client token-bucket. A production deployment would need multiple gateway instances behind a broker that can route around a dead one. State this boundary explicitly: crash-resilience and basic flood/connection limits are real; horizontal redundancy is not.",
    },
}

# Security Level self-assessment (IEC 62443-3-3's SL 1-4 scale). This is a
# DESIGN-TIME claim, not something computed from audit_log data -- state
# the reasoning explicitly rather than just asserting a number.
SECURITY_LEVEL_ASSESSMENT = """
Target: SL-2 ("protection against intentional violation using simple
means with low resources, generic skills, low motivation").

Evidence FOR SL-2: HMAC-SHA256 authentication (FR1) defeats a naive
device-impersonation attempt; TLS/HTTPS (FR4) defeats passive network
sniffing; the boot_id/seq anti-replay check (FR3) defeats a
captured-message replay attack, including a replay of an entire pre-reboot
session (closing the earlier ts-heuristic's documented blind spot -- see
SESSION_LOG.md); IdentityTargetingRisk (FR3/FR7) closes a real
trust-poisoning vulnerability the earlier single-score design had -- a
device's own Security Trust Score can no longer be lowered by anyone who
merely CLAIMS its device_id without knowing its secret; per-device MQTT
broker credentials + topic ACLs (FR5, certs/mosquitto_acl) defeat a naive
attacker who has network access but no device credentials; the
flood/rate-limit check plus the Identity Targeting Risk cooldown (FR7)
defeat a naive message-flood or credential-guessing attempt. All of this
is exactly the "simple means, low resources" attack profile SL-2 is
scoped to. scripts/evaluate_ablation.py's real result (fusion detects
process anomalies at 97% accuracy on held-out data) is additional
evidence the system detects low-sophistication behavioural attacks it
wasn't explicitly told to look for.

Evidence AGAINST SL-3/4 ("sophisticated means, moderate-to-extended
resources, IACS-specific skills"): no mutual TLS / device-side certificate
verification (firmware/main.py's cert_reqs=CERT_NONE, see
docs/06_hardware_setup.md) -- an attacker who already has valid MQTT
credentials (e.g. extracted from a captured device) can still connect
without the broker verifying ITS identity back; no hardware secure
element for key storage (shared secrets, including the MQTT passwords,
are plaintext constants in firmware/main.py and config.py -- CLAUDE.md
Section 8 explicitly names this an accepted prototype simplification for
the HMAC secret, and the same reasoning applies to the MQTT credentials);
FR5/FR7 are "partial" not "implemented" -- no physical network
segmentation, no multi-instance redundancy (see those FRs' `note` fields
for the exact boundary); a compromised device that still holds valid
credentials and deliberately reports plausible, in-range fabricated
sensor values (the `stealthy_forged_values` scenario) is explicitly
acknowledged as not reliably detectable by this single-node design (see
docs/04_module3_trust_evaluation.md Section B.8) -- this is a stated,
measured limitation, not a fixed gap. A moderately-resourced attacker with
IACS-specific skills, or one with physical access to a device's flash
memory, could plausibly defeat one or more of these.

State this SL-2 target explicitly in the paper rather than claiming a
higher level the evidence doesn't support -- an honest, evidenced SL-2
claim, now with real transport-layer access control behind it, is more
defensible in a viva than an unsupported SL-3/4 claim.
"""


def fr_coverage_report(rows: list[dict]) -> dict:
    """Mirrors nist_mapping.completeness_report()'s shape for every FR that
    has a computable coverage number -- that's "implemented" AND "partial"
    FRs now (see FOUNDATIONAL_REQUIREMENTS' status docstring); only
    "not_implemented" FRs are excluded, since there's genuinely nothing to
    compute a percentage of for those."""
    computable = {fr: info for fr, info in FOUNDATIONAL_REQUIREMENTS.items() if info["status"] != "not_implemented"}
    if not rows:
        return {fr: 0.0 for fr in computable}

    total = len(rows)
    coverage = {}
    for fr, info in computable.items():
        if fr == "FR1":
            coverage[fr] = 1.0  # every row has an auth_ok verdict, by construction
        elif fr == "FR2":
            coverage[fr] = 1.0  # every row has a decision, by construction
        elif fr == "FR3":
            coverage[fr] = 1.0  # trust_score + fused_score present on every row, by construction
        elif fr == "FR4":
            # Reuse nist_mapping's own tenet-2 ("secured communication")
            # determination rather than re-deriving it from the transport
            # string here -- avoids the two ever disagreeing, and a naive
            # `"https" in transport` check would have missed MQTT/TLS-secured
            # rows entirely (transport is literally "mqtt" for those, TLS-ness
            # is a separate flag folded into nist_tenets already).
            secured = sum(1 for r in rows if "2" in str(r.get("nist_tenets", "")).split(","))
            coverage[fr] = secured / total
        elif fr == "FR5":
            # The MQTT broker ACLs only protect messages that actually went
            # over MQTT (not the HTTPS second transport, which has no
            # equivalent client-cert restriction yet) -- and only if the
            # broker's auth is actually turned on right now. Honest 0% if
            # MQTT_USE_AUTH is off, rather than crediting a control that
            # isn't active.
            if not MQTT_USE_AUTH:
                coverage[fr] = 0.0
            else:
                mqtt_rows = sum(1 for r in rows if r.get("transport") == "mqtt")
                coverage[fr] = mqtt_rows / total
        elif fr == "FR6":
            coverage[fr] = 1.0  # every row is a logged, reasoned event, by construction
        elif fr == "FR7":
            coverage[fr] = 1.0  # check_flood() runs unconditionally on every message, by construction
    return coverage


def print_report(rows: list[dict]) -> None:
    print("IEC 62443 Zones and Conduits\n")
    for zone, desc in ZONES.items():
        print(f"  ZONE: {zone}\n    {desc}\n")
    for conduit, desc in CONDUITS.items():
        print(f"  CONDUIT: {conduit}\n    {desc}\n")

    print("IEC 62443-3-3 Foundational Requirements Coverage\n")
    coverage = fr_coverage_report(rows)
    status_label = {"implemented": "IMPLEMENTED", "partial": "PARTIAL     ", "not_implemented": "NOT IMPLEMENTED"}
    for fr, info in FOUNDATIONAL_REQUIREMENTS.items():
        label = status_label[info["status"]]
        if info["status"] == "not_implemented":
            print(f"  {fr} {info['name']:<38} {label}")
            print(f"       -> {info['note']}")
        else:
            pct = coverage.get(fr, 0.0)
            print(f"  {fr} {info['name']:<38} {label} ({pct:.0%} of {len(rows)} logged decisions)")
            print(f"       -> {info['where']}")
            if info["status"] == "partial":
                print(f"       -> gap: {info['note']}")
        print()

    print("Security Level Self-Assessment")
    print(SECURITY_LEVEL_ASSESSMENT)
