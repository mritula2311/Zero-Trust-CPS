# Module 1 — CPS Device Identity

**Status:** Core implemented (starter kit `src/config.py`, consumed by `src/gateway.py`)
**Report grounding:** Section 4.3 Module 1; literature refs [12], [13], [16]

## Purpose

Every other module in this system depends on being able to answer one
question first: *which specific device sent this message?* Zero Trust's
foundational rule — "no implicit trust based on network location" — only
means something if identity is established independently of the network
path a message travelled. Module 1's job is to give every device a stable,
checkable identity **before** any behavioural judgement (Module 3) or access
decision (Module 5) is made about it.

## Design Rationale

Full X.509/PKI certificate chains are the conventional way to establish
device identity, but they impose real cost on constrained hardware: chain
validation, certificate storage, and revocation checking all consume memory
and CPU that an ESP32-class device may not comfortably spare. The
open-access literature on constrained-device identity [12] (nano-scale IoT,
hash/XOR-based schemes) and [16] (systematic review of IoT auth/authz design
space) both point to the same resolution: push the heavy identity-management
logic to the gateway, and let the constrained device hold only a lightweight,
symmetric secret.

This project follows that resolution directly: **the device holds a shared
secret; the gateway holds the registry.** The device never needs to parse a
certificate or verify a chain — it only needs to compute an HMAC, which is
cheap enough to run on essentially any microcontroller.

## Data Structure

```python
# src/config.py
DEVICE_REGISTRY = {
    "sensor-001": {"secret": "s3cr3t-key-001", "expected_range": (15.0, 35.0)},
    "sensor-002": {"secret": "s3cr3t-key-002", "expected_range": (20.0, 80.0)},
    "actuator-001": {"secret": "s3cr3t-key-003", "expected_range": (0.0, 1.0)},
}
```

Each entry is keyed by `device_id` (the identity claim a message makes) and
holds:
- `secret` — the shared key used by Module 2 to verify the identity claim
  cryptographically. This field is what turns "a string called sensor-001"
  into "a verifiable identity."
- `expected_range` — a device-type-specific physical plausibility bound,
  used by Module 3. It's stored here, alongside identity, because it's
  properties *of* the identity (a temperature sensor's valid range is a fact
  about what that device is, not about its current behaviour).

In production, this dictionary would be backed by a real datastore (SQLite,
or a small key-value store), and the `secret` field would be replaced by a
reference to a hardware secure element (e.g. ATECC608A) rather than a
plaintext value sitting in configuration — the plaintext form here is a
deliberate simplification for a learning/prototype context, not a
recommendation for deployment.

## Implementation Walkthrough

Identity resolution happens as the first step of `gateway.verify_signature()`:

```python
def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
    info = DEVICE_REGISTRY.get(device_id)
    if info is None:
        return False  # unknown device -> automatic fail, never implicitly trusted
    ...
```

Notice what happens when `device_id` is not in the registry: the function
returns `False` **immediately**, before any cryptographic work is even
attempted. This is a deliberate Zero-Trust design choice, not just an
optimisation — an unrecognised identity claim gets no benefit of the doubt
and no partial credit. There is no code path in this system where a message
from an unregistered device can reach Module 3 with a positive trust
observation.

## Interface Contract

| Direction | What crosses the boundary | Consumed by |
|---|---|---|
| In | `device_id` (string, from the incoming message payload) | — |
| Out | `info["secret"]` | Module 2 (Authentication) — used to recompute the expected HMAC |
| Out | `info["expected_range"]` | Module 3 (Trust Evaluation) — used for the value-plausibility rule |
| Out | Boolean existence check (device known / unknown) | Module 2, and indirectly Module 7 (an unknown-device event is itself an audit-worthy fact) |

Module 1 has **no outbound network calls and no state that changes at
runtime** in the starter-kit version — it is a static lookup. This is
intentional: identity should be one of the most stable, least dynamic parts
of the system. (Trust, by contrast, in Module 3, is designed to be highly
dynamic — that asymmetry is itself a Zero-Trust principle: *who you are*
should not fluctuate message-to-message, but *how much you're trusted*
should.)

## Failure Modes

| Scenario | Behaviour | Why |
|---|---|---|
| `device_id` not in registry | `verify_signature()` returns `False` immediately | No implicit trust for unknown identities |
| Two devices configured with the same secret | Both can forge each other's messages | Secrets must be unique per device — this is a configuration invariant the system does not currently validate; worth adding an assertion in `config.py` for production use |
| Secret compromised (leaked) | Attacker can pass Module 1+2 indefinitely until the secret is rotated | Motivates the secret-rotation extension below |

## Extension Path (Beyond the Starter Kit)

1. **Move the registry to a real datastore.** Swap the dictionary for a
   SQLite table (`devices(device_id, secret_hash, expected_range_lo,
   expected_range_hi, created_at, revoked_at)`), so devices can be
   provisioned and revoked without editing source code.
2. **Store secret hashes, not plaintext secrets**, on the gateway side where
   possible, verifying via a keyed comparison rather than storing the raw
   key — reduces blast radius if the gateway's storage is compromised.
2. **Add secret rotation.** Give each registry entry a `secret_version` and
   accept either the current or previous version's HMAC for a defined grace
   window, so you can rotate a device's key without a hard cutover.
3. **Gateway-held PKI relationship.** For deployments that need
   interoperability with other Zero-Trust tooling, have the gateway issue
   and hold an X.509 certificate on each constrained device's behalf (the
   device itself still only ever handles its lightweight symmetric secret)
   — this is the design referenced in the report's literature grounding
   [12] and gives you a PKI-compatible identity at the network boundary
   without pushing PKI cost onto the endpoint.
