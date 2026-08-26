# Module 6 — Secure Communication

**Status:** Core implemented (plain MQTT, both `src/gateway.py` and `src/device_simulator.py`) + TLS design (extension, `docs/03_add_tls.md`)
**Report grounding:** Section 4.3 Module 6; literature refs [23], [24]

## Purpose

Module 6 is the transport that every other module's messages travel over.
Its job is narrower than it might first appear: it is **not** responsible
for proving who sent a message (that's Module 2) or deciding whether to act
on it (Module 5) — it is responsible for making sure messages travel between
components without being readable or alterable by anyone else on the
network path.

## Design Rationale

MQTT was chosen over CoAP for the starter kit specifically because its
publish/subscribe model maps cleanly onto this system's actual traffic
pattern: many devices publish telemetry to one topic, one gateway
subscribes and reacts, and decisions flow back out on a second topic to
however many devices care to subscribe. Reference [23] (a direct
CoAP/MQTT/HTTP benchmark) provides the quantitative baseline this project's
own overhead evaluation (Report Section 10.1) is designed to be compared
against — CoAP remains the better choice for extremely constrained,
request/response-style interactions (and is worth adding alongside MQTT if
your device fleet includes such nodes), but for the sensor/actuator
telemetry pattern this project centres on, MQTT is the better fit.

## Implementation Walkthrough

### Topic architecture

```python
TELEMETRY_TOPIC = "cps/telemetry"   # devices -> gateway
DECISION_TOPIC  = "cps/decisions"   # gateway -> devices
```

Two topics, one direction each. This is a deliberately simple starting
topology — every device publishes to the same telemetry topic and every
device could in principle subscribe to the same decisions topic, filtering
for messages addressed to its own `device_id`. For a larger device fleet,
per-device topics (`cps/telemetry/sensor-001`, etc.) would let you use
MQTT's built-in topic-based access control as an *additional* layer, but
add real operational complexity — the flat topology here is appropriate for
a prototype of this scale.

### Device side

```python
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="device-simulator")
client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
client.loop_start()
...
client.publish(TELEMETRY_TOPIC, json.dumps(message))
```

`loop_start()` runs the MQTT network loop on a background thread, so the
simulator's main thread is free to just call `publish()` on a timer without
manually pumping the network socket.

### Gateway side

```python
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="zt-gateway")
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
client.loop_forever()
```

The gateway instead uses `loop_forever()`, which blocks the main thread —
appropriate here because the gateway's entire job *is* reacting to MQTT
messages; there's no other work competing for the main thread the way there
is on the device side.

**Important concurrency note:** `paho-mqtt`'s `on_message` callback runs on
the client's network thread, and by default, callbacks for successive
messages are **not** guaranteed to run concurrently with each other in a way
that's safe if you add genuinely shared mutable state beyond what's already
here. The current implementation is safe because each device's
`DeviceTrustState` is only ever touched from within `on_message`, one
message at a time — but if you later add multi-threaded processing (e.g. to
parallelise the fusion engine's GNN inference), you will need explicit
locking around any state shared across devices' processing (like a shared
graph structure for the GNN — see Module 3, Part B).

## Interface Contract

| Direction | Data | From/To |
|---|---|---|
| Carries | `{"payload": {...}, "signature": "..."}` (Module 1/2's signed envelope) | Device → Gateway, via `TELEMETRY_TOPIC` |
| Carries | `{"device_id": ..., "decision": "..."}` (Module 5's output) | Gateway → Devices, via `DECISION_TOPIC` |

Module 6 is intentionally "dumb" about the content it carries — it does not
parse, validate, or interpret the JSON payload in any way; that's Module
2 and Module 3's job. This separation matters: it means Module 6 can be
upgraded (e.g. to TLS, or to a different broker entirely) without touching
any application-layer logic.

## Why Both Module 2 AND Module 6 Encrypt/Authenticate

This is worth being explicit about, since it can look redundant at first
glance: Module 2's HMAC operates at the **application layer** (it signs the
JSON payload itself), while TLS (the Module 6 extension) operates at the
**transport layer** (it encrypts the entire connection, MQTT protocol
framing included). These protect against different threats:

| Threat | Stopped by Module 2 (HMAC) | Stopped by Module 6 (TLS) |
|---|---|---|
| Attacker reads telemetry values in transit | No — payload is visible in plaintext without TLS | Yes |
| Attacker forges a message claiming to be a device | Yes | No — TLS alone doesn't prove *which device* sent a message, only that the *connection* is encrypted |
| Attacker on the broker itself (compromised MQTT server) reads/modifies messages | Modification is caught (signature breaks); reading is not stopped | No — TLS terminates at the broker, so a compromised broker can see plaintext regardless |
| Passive network eavesdropper | No | Yes |

The two layers are complementary, not redundant — this is the standard
"defence in depth" argument, and it's worth stating explicitly in your
report's security-analysis section rather than leaving it implicit.

## Failure Modes

| Scenario | Behaviour | Note |
|---|---|---|
| Broker unreachable | `client.connect()` raises/retries per paho-mqtt's internal reconnect logic | Not currently handled with custom retry/backoff logic — acceptable for a prototype, worth hardening before any real deployment |
| Message published to wrong topic (typo) | Silently never received by the intended subscriber | No built-in detection — consider a periodic heartbeat message per device as a way to detect "device configured but not actually reaching the gateway" |
| Plain MQTT, no TLS (current default) | All traffic readable to anyone with network access to the broker | This is the gap `docs/03_add_tls.md` closes — treat the starter kit's plain-MQTT mode as a development convenience, not a deployment-ready configuration |

## Extension Path

1. Follow `docs/03_add_tls.md` to add TLS on port 8883 — this is the single
   highest-priority upgrade for anyone treating this beyond a local demo.
2. For full mutual TLS, issue each device its own client certificate signed
   by the same CA, and set `require_certificate true` on the broker — this
   adds a *third* authentication layer (transport-level device identity) on
   top of Module 2's application-level HMAC, which is genuinely valuable
   defence-in-depth for a production CPS deployment, though likely beyond
   what's needed to satisfy your report's stated scope.
3. If your device fleet grows to include genuinely resource-constrained
   nodes that can't afford MQTT's persistent-connection overhead, add CoAP
   support alongside MQTT (per Report Section 8.2) rather than replacing
   it — the two protocols suit different device classes, and reference
   [23]'s benchmarks will tell you which threshold to use to decide which
   protocol a given device class should use.
