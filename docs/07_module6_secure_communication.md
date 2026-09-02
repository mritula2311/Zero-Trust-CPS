# 07 — Module 6: Secure Communication

> **AS-BUILT NOTE:** MQTT/TLS is implemented and live (auto-detected via
> `config.MQTT_USE_TLS` once `certs/` is populated); the CoAP/DTLS
> requirement is substituted with HTTPS (`src/coap_server.py` — see that
> file's docstring for the two real upstream blockers that motivated the
> substitution). One topic beyond Section 2's three: `cps/challenge/{device_id}`
> (gateway → device, step-up nonce, Module 2 Section 7) — added to
> `certs/mosquitto_acl` alongside `cps/decisions`'s existing per-device
> read restriction. The broker also enforces per-device MQTT-layer
> credentials (`certs/mosquitto_passwd`/`mosquitto_acl`, IEC 62443 FR5),
> which this file doesn't specify but which layers cleanly underneath it.
> **Known local-environment caveat, found this session**: adding new ACL
> rules to `certs/mosquitto_acl` requires restarting the Mosquitto service
> to take effect — same "needs admin PowerShell" pattern as any
> `mosquitto.conf` change.

## 1. Purpose

Carry every message between device and gateway over an encrypted channel, using a protocol chosen specifically because the literature review found it appropriate for constrained, frequent, small-message IoT traffic.

**Literature grounding:** [18] (measured TLS-secured MQTT overhead on constrained hardware, showing it is manageable), [19] (direct protocol comparison finding MQTT the best fit for this project's traffic pattern).

## 2. Topic Design

**AS-BUILT correction**: telemetry uses one shared topic, not a per-device
suffix — every device publishes to the same `cps/telemetry`, and the
gateway subscribes once (`gateway.py:322`). Only the two gateway-initiated
channels are per-device-suffixed:

```
cps/telemetry                 — device → gateway, every reading, ALL devices share this
                                  one topic (Module 1/2/3 subscribe here; device_id is
                                  read from the payload itself, not the topic string)
cps/challenge/{device_id}     — gateway → device, step-up nonce (Module 2 publishes here)
cps/decisions/{device_id}     — gateway → device/dashboard, the Module 5 outcome for
                                  monitoring/visualization (Module 7 subscribes here)
```

The two gateway→device channels use a per-device suffix specifically so
`certs/mosquitto_acl` can restrict each device to reading only its own
decisions/challenges (least privilege) — this is what makes the ACL
pattern rules (`pattern read cps/decisions/%u`, `pattern read
cps/challenge/%u`) work per Section 3's broker hardening. Telemetry is
deliberately kept flat (one shared topic, not `cps/telemetry/{device_id}`
per device) — every device publishing to the same topic is a simpler
topology, and `device_id` is read from the payload itself (Module 1), not
inferred from the topic string. For a larger device fleet, per-device
telemetry topics would let you additionally use MQTT's own topic-based
access control on the *publish* side (restrict each device to publishing
only its own topic) as a further defence-in-depth layer, but add real
operational complexity not currently justified at this scale.

### 2.1 Concurrency Note

`paho-mqtt`'s `on_message` callback runs on the client's network thread;
by default, successive messages are not guaranteed to run concurrently
with each other in a way that's safe if genuinely shared mutable state is
added beyond what exists today. The current implementation is safe because
each device's trust/anomaly state is only ever touched from within
`on_message`, one message at a time. If multi-threaded processing is ever
added (e.g. to parallelise GNN inference across devices), any state shared
*across* devices' processing — such as a shared graph structure for the
GNN, `docs/04_module3_trust_evaluation.md` Section B.5 — would need
explicit locking around it.

### 2.2 Why Both Module 2 AND Module 6 Authenticate — Threat Model

Worth being explicit about, since it can look redundant at first glance:
Module 2's HMAC operates at the **application layer** (signs the JSON
payload itself); TLS here operates at the **transport layer** (encrypts
the entire connection). They stop different threats:

| Threat | Stopped by Module 2 (HMAC) | Stopped by Module 6 (TLS) |
|---|---|---|
| Attacker reads telemetry values in transit | No — payload is plaintext without TLS | Yes |
| Attacker forges a message claiming to be a device | Yes | No — TLS alone doesn't prove *which device* sent a message, only that the *connection* is encrypted |
| Attacker on the broker itself (compromised MQTT server) reads/modifies messages | Modification is caught (HMAC breaks); reading is not stopped | No — TLS terminates at the broker, so a compromised broker sees plaintext regardless |
| Passive network eavesdropper | No | Yes |

The two layers are complementary, not redundant — worth stating explicitly
in a security-analysis writeup rather than leaving it implicit.

## 3. Broker Setup

- **Software:** Eclipse Mosquitto — free, well-documented, and light enough to run on the same machine as the gateway logic during development.
- **Plaintext port 1883:** used only during the very first Phase 1 connectivity test (`00_overview.md` build order step 1). Disabled immediately afterward.
- **TLS port 8883:** the only port used from Phase 3 onward.

```
Certificate generation (one-time setup, documented as shell commands — not
part of the application code):

  openssl req -x509 -newkey rsa:2048 -days 365 -nodes \
      -keyout ca.key -out ca.crt \
      -subj "/CN=ZeroTrustCPS-CA"

  openssl req -newkey rsa:2048 -nodes -keyout broker.key -out broker.csr \
      -subj "/CN=zt-gateway"
  openssl x509 -req -in broker.csr -CA ca.crt -CAkey ca.key \
      -CAcreateserial -out broker.crt -days 365

mosquitto.conf:
  listener 8883
  cafile   /path/to/ca.crt
  certfile /path/to/broker.crt
  keyfile  /path/to/broker.key
  require_certificate false   # devices authenticate via HMAC at the
                                # application layer (Module 2), not via
                                # per-device TLS client certificates —
                                # keeping certificate management off the
                                # constrained device entirely
```

### 3.1 Certificate Validation Must Actually Be Enforced on the Client Side

Enabling TLS on the broker is not sufficient by itself — if a client is configured to accept any certificate without checking it, the connection is still vulnerable to a man-in-the-middle attack that presents a fake certificate. Both client implementations must explicitly validate the broker's certificate against the CA generated above:

```
Simulation (paho-mqtt):
    client.tls_set(ca_certs="./certs/ca.crt", cert_reqs=ssl.CERT_REQUIRED,
                    tls_version=ssl.PROTOCOL_TLSv1_2)
    # cert_reqs=ssl.CERT_REQUIRED is what actually enforces verification
    # against ca_certs — never leave this at CERT_NONE, and never add a
    # verification bypass anywhere, even temporarily during development,
    # since a temporary bypass is easy to forget to remove later.

Hardware (MicroPython, for later, via umqtt.simple + ussl):
    ussl.wrap_socket(sock, cert_reqs=ssl.CERT_REQUIRED, ca_certs=ca_cert_bytes)
    # Equivalent requirement: the firmware validates the broker's certificate
    # against the same CA used to generate it, either by embedding the CA
    # certificate in flash, or by certificate/public-key pinning if flash
    # space is a concern. Never disable verification.
```

Add a specific test for this (Section 7) rather than assuming "TLS is on" is equivalent to "TLS is enforced correctly" — a broker presenting a self-signed, unrelated certificate should be rejected by the client, not silently accepted.

## 4. Client Behaviour

### 4.1 Simulation Mode

The simulated devices (from `01_simulation_and_hardware_abstraction.md`) and the gateway both connect using `paho-mqtt` (Python), pointed at `localhost:8883` with the CA certificate for verification.

### 4.2 Hardware Mode (for later)

The eventual ESP32 firmware connects using MicroPython's `umqtt.simple`, configured with the same CA certificate (stored in flash) and the same broker address/port. No topic names, message schema, or broker configuration changes between modes — only the client library differs, which is exactly the point of the abstraction in `01`.

## 5. Measuring the Security Overhead

As part of Phase 3's acceptance test, and again as part of the full evaluation (`10_testing_and_attack_simulation.md`), measure:

- Connection-establishment latency: plaintext vs. TLS.
- Per-message publish latency: unsigned/unencrypted vs. HMAC-signed + TLS-encrypted.
- These numbers are compared against what [18] and [19] report as a sanity check that the setup is behaving reasonably, not as a pass/fail gate.

## 5.1 Failure Modes

| Scenario | Behaviour | Note |
|---|---|---|
| Broker unreachable | Connection raises/retries per the MQTT client library's internal reconnect logic | No custom retry/backoff logic beyond that — acceptable for a prototype, worth hardening before any real deployment |
| Message published to the wrong topic (typo) | Silently never received by the intended subscriber | No built-in detection — a periodic per-device heartbeat message is one way to detect "device configured but not actually reaching the gateway" |
| Plain MQTT, no TLS | All traffic readable to anyone with network access to the broker | Not the default — TLS auto-enables once `certs/` is populated (`config.MQTT_USE_TLS`); plaintext only remains as a fallback for the very first connectivity check before certs exist |

## 5.2 AS-BUILT: the ACLs are enforced, and that was demonstrated rather than assumed

`certs/mosquitto_acl` gives each identity least privilege: a device may
**publish** its own telemetry and **read only** the decisions and challenges
addressed to itself (`pattern read cps/decisions/%u`), while the gateway may
**read** all telemetry and **write** all decisions and challenges. Note the
gateway is deliberately granted `topic write cps/decisions/#` and **not** read.

That asymmetry was confirmed accidentally, which makes it better evidence than a
deliberate test would have been. An attempt to verify the gateway→device
decision channel using **gateway** credentials returned zero messages. The
initial reading was a broken decision channel; the actual cause was the broker
correctly refusing a subscription the gateway has no right to make. Re-running
with a *device* credential — which `pattern read cps/decisions/%u` does permit —
returned the messages immediately.

Two results came out of that:

- **Mutual authentication verified.** 10/10 gateway→device decisions were
  HMAC-valid when recomputed with the device's own secret, exactly as
  `firmware/main.py`'s `verify_decision_signature()` does. Sample payload:
  `{device_id, decision, ts, gateway_boot_id, decision_seq}` — the last two
  giving the decision channel the same boot/seq anti-replay the telemetry
  channel uses, in the opposite direction.
- **No cross-device leakage.** Subscribing as `sensor-002` and attempting
  `cps/decisions/esp32-vib-001` yielded **0** messages.

A caveat on how that second result reads: Mosquitto **silently drops** delivery
for a topic the ACL denies rather than returning a subscribe failure code, so the
client sees success and simply never receives anything. The evidence is
therefore "zero messages delivered", not "subscription rejected". When testing
ACLs, absence of delivery is the signal — do not expect an error.

### 5.3 What FR5 "partial" actually means here

`iec62443_mapping.py` rates FR5 (Restricted Data Flow) **partial**, and that is a
deliberate, honest rating rather than an unfinished one. The transport-layer
conduit restriction genuinely exists — per-device broker credentials plus the
topic ACLs above, replacing what used to be `allow_anonymous=true` where the
application-layer HMAC was the *only* enforcement. What does not exist is
physical or VLAN segmentation between the three zones: all three still run as
processes on the same machine and network, so a compromised host would still see
all traffic regardless of the broker ACLs.

Both halves belong in the write-up: real conduit-level access control exists;
physical segmentation remains future work. The dashboard shows this gap inline
under the FR5 row rather than hiding it in a tooltip.

## 6. Configuration Parameters

```yaml
secure_communication:
  broker_host: "localhost"
  broker_port_tls: 8883
  broker_port_plaintext: 1883   # only used during Phase 1's initial connectivity check
  ca_cert_path: "./certs/ca.crt"
  qos: 1   # at-least-once delivery — appropriate for telemetry where an
            # occasional duplicate is harmless (sequence numbers in Module 2
            # already handle duplicate/replay detection) but a dropped
            # reading is undesirable
```

## 7. Acceptance Criteria

- The broker refuses any connection attempt on the plaintext port once Phase 3 disables it.
- A simulated device successfully publishes and the gateway successfully receives a message over TLS.
- **Certificate validation test:** point a test client at the broker but supply it with a different, unrelated self-signed certificate in place of the real CA certificate. Confirm the connection is rejected. This directly tests Section 3.1 and must not be skipped — a passing TLS connection test alone does not prove certificate validation is actually enforced.
- Measured TLS overhead is recorded and compared against [18]/[19]'s reported figures.
- Switching a device from simulation to hardware mode (once available) requires no topic or broker configuration change — confirmed by testing that the gateway subscriber code is completely unaware of which mode produced a given message.

Continue to `08_module7_monitoring_and_audit.md`.
