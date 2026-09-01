# 02 — Module 1: Device Identity

> **AS-BUILT NOTE:** implemented as `src/config.py`'s `DEVICE_REGISTRY`
> (a Python dict, not a SQLite table — this project keeps registry state
> in code/config rather than a database row per device; `src/audit_log.py`
> owns the only SQLite tables). Each entry carries `secret` (HMAC key,
> Module 2), `mqtt_username`/`mqtt_password` (a deliberately separate
> transport-layer credential, Module 6), and either `expected_range`
> (scalar devices) or `expected_ranges` (the 5-feature vibration vector).
> Key rotation and `secret_key_previous` grace-period handling described
> below are **not implemented** — every device has exactly one active
> secret; this is a real, smaller-scope gap relative to this file's design,
> not yet built. `revoke_device()` is likewise not implemented (no
> `status` field). See `00_overview.md`'s AS-BUILT callout for the full
> deviation list, and `RESULTS.md` Section 14 for the concrete remediation
> plan for this specific gap — the schema below is already fully specified,
> so closing it is pure wiring, not new design.

## 1. Purpose

Give every device a unique, checkable ID and its own individually-generated secret key, held in a gateway-side registry. This is the foundation every other module checks against — Module 2 cannot verify a message from a device it does not recognise, and Module 3's Security Behaviour Engine cannot track "this device's recent auth failures" without a stable identity to key its state on.

**Literature grounding:** [9] (systematic review showing full certificate-based identity is too costly for constrained devices, hence the lightweight registry approach) and [12] (lightweight identity authentication for small IoT devices).

### 1.1 Design Rationale — Why a Shared Secret, Not a Certificate

Full X.509/PKI certificate chains are the conventional way to establish device
identity, but they impose real cost on constrained hardware: chain
validation, certificate storage, and revocation checking all consume memory
and CPU an ESP32-class device may not comfortably spare. The open-access
literature on constrained-device identity ([12], and [16]'s systematic
review of the IoT auth/authz design space) both point to the same
resolution: push the heavy identity-management logic to the gateway, and let
the constrained device hold only a lightweight, symmetric secret. This
project follows that resolution directly — **the device holds a shared
secret; the gateway holds the registry.** The device never needs to parse a
certificate or verify a chain, only compute an HMAC (Module 2), which is
cheap enough to run on essentially any microcontroller.

### 1.2 Implementation Walkthrough (Real Code)

Identity resolution happens as the first gate in `gateway.py`:

```python
# src/gateway.py:172 (process_telemetry) — the unknown-device_id gate
if device_id not in DEVICE_REGISTRY:
    ...  # rejected immediately, routed to IdentityTargetingRisk (Section 5,
         # docs/03_module2_authentication.md) -- never reaches this device's
         # own trust state, since no such registered device exists

# src/gateway.py:101 (verify_signature) — only called once identity is confirmed known
def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
    info = DEVICE_REGISTRY[device_id]
    canonical = json.dumps(payload, sort_keys=True).encode()
    expected = hmac.new(info["secret"].encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

Notice the unknown-`device_id` check happens **before** any cryptographic
work is attempted, and lives in the caller (`process_telemetry()`), not
inside `verify_signature()` itself — `verify_signature()` is only ever
called once identity is already confirmed known, which is why it can safely
index `DEVICE_REGISTRY[device_id]` directly rather than using `.get()`. This
is a deliberate Zero-Trust design choice: an unrecognised identity claim
gets no benefit of the doubt and no partial credit, and there is no code
path where a message from an unregistered device reaches Module 3 with a
positive trust observation.

## 2. Data Structure: The Device Registry

```
DeviceRegistryEntry:
  device_id           : string           # unique, human-readable, e.g. "esp32-node-01"
  secret_key_current   : bytes (32 bytes) # randomly generated at provisioning time
  secret_key_previous  : bytes | null     # populated only during a rotation grace period
  key_version_current  : integer          # increments on every rotation
  status               : enum(active, revoked)
  expected_range       : dict              # per-channel {min, max} used by Module 3's rule-based check
  registered_at        : timestamp
  last_seen_seq        : integer          # last accepted sequence number (owned jointly with Module 2)
  last_seen_at         : timestamp | null
```

Storage: a SQLite table `devices`, one row per device. This is the same SQLite database Module 7 (Monitoring) uses for the audit log, but a separate table — the registry is operational state, the audit log is historical record, and they should not be conflated even though they share a database file for simplicity.

```sql
CREATE TABLE devices (
    device_id TEXT PRIMARY KEY,
    secret_key_current BLOB NOT NULL,
    secret_key_previous BLOB,
    key_version_current INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    expected_range TEXT NOT NULL,   -- JSON-encoded dict
    registered_at REAL NOT NULL,
    last_seen_seq INTEGER NOT NULL DEFAULT 0,
    last_seen_at REAL
);
```

## 3. Operations

```
register_device(device_id, expected_range) -> DeviceRegistryEntry
    # Generates a new random 32-byte secret (os.urandom or equivalent CSPRNG).
    # Sets key_version_current = 1, status = active, last_seen_seq = 0.
    # This is the ONLY place a secret is ever generated — never derive one device's
    # key from another's, and never reuse a secret across two device_ids.

get_device(device_id) -> DeviceRegistryEntry | None
    # Returns None for unknown device_id — Module 2 treats this as an immediate reject.

revoke_device(device_id) -> None
    # Sets status = revoked. Module 2 must reject every subsequent message from a
    # revoked device_id regardless of HMAC validity — revocation is a hard override.

rotate_key(device_id) -> new_secret
    # Moves secret_key_current -> secret_key_previous, generates a fresh
    # secret_key_current, increments key_version_current.
    # secret_key_previous remains valid for a configurable grace period
    # (default: 24 hours in hardware-time-equivalent, or a configurable number
    # of messages in simulation) so an in-flight device isn't locked out mid-rotation.

update_last_seen(device_id, seq, timestamp) -> None
    # Called by Module 2 after successful verification. This is the field
    # Module 2's anti-replay check reads on the next message.
```

## 4. Provisioning Workflow

### 4.1 Simulation Mode

A setup script (run once, or on demand) calls `register_device()` for each simulated device the `01_simulation_and_hardware_abstraction.md` simulator will run, and hands the generated secret directly to the simulator's in-memory device state (they are in the same process, so this is a direct function call — no out-of-band transfer needed).

### 4.2 Hardware Mode (for when hardware arrives)

`register_device()` generates the secret as normal. The secret and `key_version_current` must then be transferred to the physical ESP32 out-of-band (e.g., flashed into the firmware's config at build time, or entered once over a serial/USB connection during setup) — **never transmitted over the same MQTT channel the device will use for telemetry**, since that channel is exactly what this whole framework treats as untrusted until proven otherwise. This document flags this as a manual, one-time step per physical device; it is not automated, and should not be, for a project at this scale.

## 5. Interface Contract With Other Modules

| Consumer | What It Reads | What It Writes |
|----------|---------------|-----------------|
| Module 2 (Authentication) | `secret_key_current`, `secret_key_previous`, `key_version_current`, `status`, `last_seen_seq` | `last_seen_seq`, `last_seen_at` (via `update_last_seen`) |
| Module 3 (Trust Evaluation) | `expected_range` (for the rule-based Process Anomaly check) | — (read-only) |
| Module 5 (Access Control) | `status` (a revoked device is an automatic Block regardless of scores) | — (read-only) |

## 6. Edge Cases

- **Unknown `device_id`:** `get_device()` returns `None`. Module 2 rejects immediately, and this event itself should be counted as a Security Behaviour Engine feature (Module 3) — a burst of unknown-ID messages is itself suspicious, per the attack matrix row "Unknown device ID."
- **Revoked device sends a perfectly valid HMAC:** still rejected. Revocation must be checked *before* HMAC verification is even attempted, both for correctness and so a revoked device cannot be used to probe whether its old key still works.
- **Duplicate registration attempt for an existing `device_id`:** reject with an explicit error; provisioning must not silently overwrite an existing device's secret (that would be indistinguishable from a takeover).

## 7. Failure Modes

| Scenario | Behaviour | Why |
|---|---|---|
| `device_id` not in registry | Rejected immediately (`src/gateway.py:172`), routed to `IdentityTargetingRisk`, never to a device's own trust state | No implicit trust for unknown identities |
| Two devices configured with the same secret | Both can forge each other's messages | Secrets must be unique per device — a configuration invariant this project does not currently validate; worth an assertion in `config.py` for production use |
| Secret compromised (leaked) | Attacker passes Module 1+2 indefinitely until the secret is rotated | Motivates the secret-rotation design in Section 3/4 above — not yet implemented, per this file's AS-BUILT note |

## 8. Further Extensions (Beyond This Spec)

Beyond the rotation/revocation design already specified in Sections 3-4
above (not yet implemented — see the AS-BUILT note at the top of this
file), two further hardening steps a production deployment would add:

1. **Store secret hashes, not plaintext secrets, on the gateway side**
   where possible, verifying via a keyed comparison rather than keeping the
   raw key at rest — reduces blast radius if the gateway's storage is
   compromised.
2. **Gateway-held PKI relationship.** For deployments needing
   interoperability with other Zero-Trust tooling, have the gateway issue
   and hold an X.509 certificate on each constrained device's behalf (the
   device itself still only ever handles its lightweight symmetric secret)
   — gives a PKI-compatible identity at the network boundary without
   pushing PKI cost onto the endpoint. Grounded in [12].

## 9. Acceptance Criteria

- Registering two devices produces two different secrets (verify by direct comparison in a test — this sounds trivial but is worth asserting explicitly, since a copy-paste provisioning bug is a realistic mistake).
- `get_device()` on an unregistered ID returns `None`, not an exception.
- After `revoke_device()`, a subsequent valid-HMAC message from that device is rejected by Module 2's integration test.
- After `rotate_key()`, a message signed with the previous key is still accepted until the grace period ends, and a message signed with the new key is accepted immediately.

Continue to `03_module2_authentication.md`.
