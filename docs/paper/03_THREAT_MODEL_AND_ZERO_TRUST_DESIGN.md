# Threat model and Zero-Trust design

[VERIFIED: implementation] Trust anchors are configured device HMAC keys, gateway/broker trust configuration and an independently provisioned audit-checkpoint key. The attacker may submit arbitrary JSON, claim a legitimate identity, replay signed traffic, alter features, send rapid traffic, or possess a compromised device key. Sensor failure and physical disturbance are process events, not automatically cyberattacks.

| Threat | Gate / response | Residual limitation |
|---|---|---|
| Unknown identity / revocation | Registry membership; unconditional revocation check | Registry and revocation are local software state |
| Forged payload | HMAC-SHA256 over canonical JSON; constant-time comparison | Extracted legitimate key authenticates false telemetry |
| Replay / old boot | Boot/sequence predicate; commit only after full acceptance | Replay history is memory-resident; restart weakens continuity |
| Stale signed traffic | Timestamp within ±600 seconds | Wide demonstration setting; not tight freshness |
| Nonfinite/malformed value | Type/finite checks before state mutation | Plausible finite forged values require process evidence |
| Claimed-ID trust poisoning | Separate IdentityTargetingRisk, no rejected trust update | Rejection audit/log volume still consumes resources |
| Authenticated flooding | Security Trust rate observation 0.2 | Accepted physical telemetry still processed |
| Step-up failure | TIMEOUT/MISMATCH forces BLOCK | Assumes challenge/key channel remains trustworthy |
| Database tampering | Hash chain plus HMAC checkpoints | Does not protect a fully compromised host/key store |

Implementation evidence: [gateway](../../src/gateway.py), [trust engine](../../src/trust_engine.py), [audit](../../src/audit_log.py), [gateway tests](../../tests/test_gateway_input_validation.py), [invariants](../../tests/test_invariants.py). The rejection invariant concerns accepted-message baselines, trust, process histories and cooldown enforcement; targeting telemetry and rejection records intentionally change. A failed current-key check can also lazily clear an already-expired previous key. This does not advance replay/trust state or shorten its grace period, but means “no registry field ever changes on rejection” would be too broad.

## Transport and deployment verdict

`gateway.run` raises unless TLS, broker authentication and a non-template gateway password are configured. The plain MQTT branch is unreachable through normal guarded startup. Paho `tls_set(ca_certs=...)` is used without a `tls_insecure_set(True)` override. Broker ACL enforcement is deployment configuration, not independently reverified by these unit tests. The second endpoint in `coap_server.py` is **HTTPS**, despite its historical filename/port naming; it does not implement CoAP/DTLS wire semantics.

MPU firmware has an opt-in CA-verification path; without configuration, encrypted-but-unverified TLS remains possible. SW-420 firmware supplies `server_hostname` but does not configure a required CA-validation path equivalent to the MPU option. Physical firmware peer verification remains [PENDING VALIDATION]. Do not describe end-to-end mutually authenticated or production-hardened transport on this evidence. See [firmware](../../firmware/main.py), [SW firmware](../../firmware/main_sw420.py), and [TLS regression tests](../../tests/test_firmware_tls_verification.py).

The secret scan compares configured local credential values with reachable Git blobs without emitting values, and checks private-key material. Its exact scope and result are in [credential_scan.json](../../results/final_verification/credential_scan.json). No configured-secret match was found in the inspected history. Unknown/rotated historical credentials cannot be excluded by this scan. Local secret files and the external backup are retained; no credential deletion or rotation was performed. If any real historical credential is subsequently identified, **CREDENTIAL ROTATION REQUIRED**; removing the current file alone is insufficient.

No compliance certification, physical tamper resistance, device-key secure enclave, compromised-host protection, availability guarantee or denial-of-service immunity is established. NIST/IEC mapping code is traceability documentation, not standards certification.
