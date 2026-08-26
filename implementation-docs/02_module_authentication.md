# Module 2 — Authentication

**Status:** Core implemented (`src/device_simulator.py::sign`, `src/gateway.py::verify_signature`)
**Report grounding:** Section 4.3 Module 2; literature refs [12], [14], [16]

## Purpose

Where Module 1 answers "who is claiming to be this device," Module 2
answers "can this device *prove* it's telling the truth?" An identity claim
without proof is worthless from a security standpoint — anyone could publish
a message claiming to be `sensor-001`. Module 2 closes that gap using a
per-message cryptographic proof that doesn't require the device to ever
transmit its secret.

**Honesty note on "mutual" (updated — now genuinely mutual, still not
interactive challenge-response):** `Zero_Trust_CPS_Project_Synopsis.docx`'s
Section 4.3 module table describes this as "Mutual challenge-response
authentication." Both directions are now cryptographically verified:
the device proves its identity to the gateway via HMAC-SHA256 over the
telemetry payload (as before), and the **gateway now signs its own
`cps/decisions/<device_id>` messages** with the same per-device secret
(`gateway.py::_sign_decision()`), which the device independently verifies
before trusting a decision (`device_simulator.py::verify_decision_signature()`;
mirrored on real hardware in `firmware/main.py::verify_decision_signature()`).
Reusing the existing per-device secret for both directions needed no new
key-provisioning step, since both sides already hold it from Module 1.
Verified live: a forged/tampered/wrong-secret decision message is rejected
(`!! REJECTED decision message`, device does NOT act on it) while a
genuine gateway decision passes (`<< verified gateway decision: ALLOW`) —
see SESSION_LOG.md.

What's still **not** implemented, so still worth naming explicitly in the
paper rather than importing the synopsis's "mutual challenge-response"
wording uncritically: this is not interactive challenge-response in the
strict protocol sense — there's no gateway-issued nonce the device must
echo back inside a session-establishment handshake; each message
(telemetry AND decision) is authenticated independently on its own
content, with replay resistance on the telemetry side coming from the
monotonic `ts` check (Module 4, `config.REBOOT_TS_THRESHOLD_MS`) rather
than a challenge/response round-trip, and the decision channel currently
has no equivalent replay check at all (a captured, validly-signed old
decision could in principle be replayed — lower-stakes than telemetry
replay since decisions are ephemeral access grants, not sensor readings
feeding trust scoring, but a real gap, not fixed here). A move to
mTLS (once client certs are added to `coap_server.py`) remains real,
buildable future work beyond this — see Extension Path item 2 below.

## Design Rationale

The literature on lightweight constrained-device authentication [12], [14]
converges on symmetric-key, hash-based schemes (HMAC, or hash+XOR
combinations) specifically because they avoid the computational cost of
asymmetric cryptography (RSA/ECC key operations) on devices that may not
have a hardware crypto accelerator. HMAC-SHA256 was chosen for this
implementation because:

- It requires only a hash function, which every modern microcontroller
  toolchain supports natively (no elliptic-curve library needed).
- It's provably secure as a MAC (message authentication code) given a
  secret the verifier and prover both know — exactly the trust model
  Module 1 establishes.
- It authenticates the **payload itself**, not just the connection —
  meaning even if the transport layer (Module 6) were somehow compromised
  or downgraded, a forged payload still fails this check.

This is worth pausing on: Module 2 provides **application-layer**
authentication, independent of whatever **transport-layer** security Module
6 provides. This is a deliberate defence-in-depth choice, not redundancy —
see `06_module_secure_communication.md` for why both layers matter.

## Implementation Walkthrough

### Device side — signing a message

```python
# src/device_simulator.py
def sign(secret: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
```

Two details matter here beyond "call HMAC":

1. **`sort_keys=True`** — JSON does not guarantee key ordering, so without
   this, the *same* logical payload could serialise to two *different*
   byte strings on different runs, producing two different (both
   "correct") signatures. Canonicalising the serialisation is what makes
   the signature reproducible and verifiable.
2. The signature covers the **entire payload**, including the `device_id`
   field inside it — so an attacker cannot take a validly-signed message
   from `sensor-002` and simply relabel it as coming from `sensor-001`;
   that would invalidate the signature.

### Gateway side — verifying a message

```python
# src/gateway.py
def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
    info = DEVICE_REGISTRY.get(device_id)
    if info is None:
        return False
    canonical = json.dumps(payload, sort_keys=True).encode()
    expected = hmac.new(info["secret"].encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

The gateway independently recomputes what the signature *should* be (using
the secret it holds for that `device_id`, from Module 1) and compares it to
what was actually sent. Two implementation details are security-critical,
not stylistic:

- **`hmac.compare_digest`, not `==`.** A plain string comparison in Python
  short-circuits on the first mismatched character, which means the
  comparison takes measurably less time for a signature that's wrong in the
  first byte than one that's wrong in the last byte. Over many requests, an
  attacker can exploit that timing difference to guess the correct
  signature one byte at a time (a timing side-channel attack).
  `compare_digest` runs in constant time regardless of where the mismatch
  is, closing that channel.
- **Recompute, don't trust a cached value.** The gateway never stores "the
  signature I expect from sensor-001" — it derives it fresh, from the
  current payload, every single time. This is what makes the check replay-
  resistant against payload tampering: change one digit in the temperature
  reading and the entire expected signature changes.

## Interface Contract

| Direction | What crosses the boundary | Consumed by |
|---|---|---|
| In | `device_id`, `payload` (dict), `signature` (hex string) — from the raw MQTT message | — |
| In | `info["secret"]` | From Module 1 |
| Out | `auth_ok` (boolean) | Module 3 (Trust Evaluation) — the single strongest input feature to the trust score |
| Out (indirect) | `consecutive_auth_failures` count | Maintained inside Module 3's `DeviceTrustState`, but conceptually belongs to this module's "how suspicious is this failure pattern" judgement |

## Failure Modes

| Scenario | Behaviour | Downstream effect |
|---|---|---|
| Wrong secret used (forged message) | `hmac.compare_digest` returns `False` | Module 3 applies a heavy trust penalty (see `03_module_trust_evaluation.md`), scaling with consecutive failures |
| Payload tampered in transit (e.g. MITM changes a value) | Signature no longer matches the recomputed one | Same as above — this is why signing the *whole* payload, not just an identity token, matters |
| Malformed message (missing fields) | Caught earlier, in `gateway.on_message`'s `try/except`, before reaching this function at all | Message dropped, no trust penalty applied (there's no device to penalise — see the integration doc for why this asymmetry is intentional) |
| Legitimate device, clock/counter desync (if a nonce/counter were added) | Would fail verification even though the device is genuine | Not currently modelled — flagged as a real limitation, see Extension Path |

## Extension Path (Beyond the Starter Kit)

1. **Add a nonce or monotonic counter to the signed payload.** The current
   scheme authenticates *content* but not *freshness* — a captured, validly
   signed message could in principle be replayed by an attacker. Including
   a strictly-increasing counter (rejected if not greater than the last seen
   value for that device) closes this gap and is a natural next step before
   claiming full replay-resistance in your report's evaluation section.
2. **Move to ECC-based challenge-response** for devices with a crypto
   accelerator, per references [21], [36] in the report — the interface
   contract above (`device_id, payload, signature -> auth_ok`) stays
   identical, so this is a drop-in replacement for `verify_signature()`,
   not a redesign.
3. **Rate-limit authentication attempts per device_id** at the gateway,
   independent of the trust-score mechanism, as a coarse defence against
   brute-force signature guessing.
