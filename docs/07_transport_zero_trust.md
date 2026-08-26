# 07 — Transport-Layer Zero Trust (MQTT broker hardening)

**Why this exists:** every other Zero-Trust check in this project (HMAC
signature, trust scoring, continuous verification) happens at the
**application layer** — inside `gateway.py`, after a message has already
reached it. Until now, the **transport layer** underneath that — the
Mosquitto broker itself — had `allow_anonymous true`, meaning *any* client
on the network could connect with no credentials at all and:

- publish a message to `cps/telemetry` claiming to be any device (the
  gateway would still reject it via HMAC, but the broker itself never
  checked),
- eavesdrop on every device's telemetry by subscribing to `cps/telemetry`,
- publish a forged message to `cps/decisions` that a real actuator would
  have acted on, with nothing at the broker level stopping it.

That's "no implicit trust" (NIST tenet 1) being violated at exactly the
layer a real attacker would hit first — the network connection, before a
single application-layer check ever runs. This doc closes that gap.

## What changed in the code (already done, nothing to do here)

- `certs/mosquitto_passwd` — hashed per-identity broker credentials
  (`esp32-vib-001`, `sensor-002`, `actuator-001`, `zt-gateway`), generated
  with `mosquitto_passwd.exe`.
- `certs/mosquitto_acl` — least-privilege topic ACLs: each device can
  publish only its own telemetry and read only its own decisions
  (`cps/decisions/<device_id>`, via Mosquitto's `%u` username
  substitution); only the gateway can read telemetry / write decisions.
- `src/config.py` — `DEVICE_REGISTRY` now carries `mqtt_username`/
  `mqtt_password` per device (deliberately separate from the HMAC
  `secret` — different trust boundary), plus `MQTT_GATEWAY_USERNAME`/
  `MQTT_GATEWAY_PASSWORD` and `MQTT_USE_AUTH` (auto-detects once
  `certs/mosquitto_passwd` exists, same pattern as `MQTT_USE_TLS`).
- `src/gateway.py` — connects with `MQTT_GATEWAY_USERNAME`/`PASSWORD`
  when `MQTT_USE_AUTH` is on; publishes decisions to
  `cps/decisions/<device_id>` instead of a flat shared topic (this is
  what makes the ACL's per-device read restriction possible at all —
  a shared topic can't be scoped by device with topic-based ACLs).
- `src/device_simulator.py` — now opens **one MQTT connection per
  simulated device**, each authenticating with that device's own
  credential, instead of one shared connection for all three. This
  matters: if all 3 simulated devices shared one broker login, the ACL
  couldn't actually distinguish them, and least-privilege would be
  theater rather than real.
- `firmware/main.py` — `MQTT_USERNAME`/`MQTT_PASSWORD` added for the real
  ESP32, matching `esp32-vib-001`'s credential in `certs/mosquitto_passwd`.
- `src/trust_engine.py` / `src/gateway.py` — `check_flood()` (IEC 62443
  FR7): per-device message-rate check using the gateway's own wall-clock
  arrival time (not the payload's self-reported `ts`, which an attacker
  controls), flags a device publishing faster than
  `config.MIN_MESSAGE_INTERVAL_SECONDS`.
- `scripts/run_gateway_supervised.py` (FR7): restart-on-crash process
  supervisor — run this *instead of* `python gateway.py` directly if you
  want the gateway to recover automatically from a crash.

**None of this takes effect until `mosquitto.conf` itself is updated** —
the code above just makes the gateway/simulator/firmware *capable* of
authenticating; the broker still needs to be told to *require* it.

## What you need to do (needs your admin PowerShell)

### 1. Back up the current config

```powershell
Copy-Item "C:\Program Files\mosquitto\mosquitto.conf" "C:\Program Files\mosquitto\mosquitto.conf.bak"
```

### 2. Edit `C:\Program Files\mosquitto\mosquitto.conf`

Open it as Administrator (Notepad is fine: right-click Notepad → Run as
administrator → File → Open). Find the block at the very end of the file
that currently looks like this:

```
listener 1883 0.0.0.0
allow_anonymous true


listener 8883
cafile D:/zt-cps/zt-cps-starter/certs/ca.crt
certfile D:/zt-cps/zt-cps-starter/certs/server.crt
keyfile D:/zt-cps/zt-cps-starter/certs/server.key
require_certificate false
```

Replace it with this:

```
listener 1883 0.0.0.0
max_connections 100
message_size_limit 65536

listener 8883
cafile D:/zt-cps/zt-cps-starter/certs/ca.crt
certfile D:/zt-cps/zt-cps-starter/certs/server.crt
keyfile D:/zt-cps/zt-cps-starter/certs/server.key
require_certificate false
max_connections 100
message_size_limit 65536

allow_anonymous false
password_file D:/zt-cps/zt-cps-starter/certs/mosquitto_passwd
acl_file D:/zt-cps/zt-cps-starter/certs/mosquitto_acl
```

What each new line does:
- `max_connections 100` / `message_size_limit 65536` (per listener, IEC
  62443 FR7) — basic connection-count and message-size DoS mitigation at
  the broker itself; 100 connections and 64KB is generous headroom for
  this project's 3-4 clients while still bounding worst-case resource use.
- `allow_anonymous false` — the actual fix; no client connects without a
  valid username/password from here on.
- `password_file` / `acl_file` — point at the files already generated in
  `certs/`.

Save the file.

### 3. Restart the Mosquitto service

```powershell
Restart-Service mosquitto
```

If that errors with "service not found," check the actual name first:

```powershell
Get-Service *mosquitto*
```

and use whatever name that shows instead.

### 4. Verify it worked

Run the gateway and simulator as usual (`python gateway.py`, then
`python device_simulator.py`, from `src/`). You should see:

```
[gateway] MQTT broker auth (IEC 62443 FR5, per-device credentials + topic ACLs): enabled
[simulator] connecting each of ['esp32-vib-001', 'sensor-002', 'actuator-001'] over ..., with per-device broker credentials
```

If instead you see connection failures (`rc=5` / "not authorised"), the
most likely cause is `certs/mosquitto_passwd`'s absolute path not
matching what's in `mosquitto.conf`, or the service not having actually
restarted — check `Get-Service mosquitto` shows `Running`, and re-check
step 2's paths use forward slashes exactly as shown (Mosquitto on
Windows accepts `/` even on an otherwise-Windows path).

**Two real bugs hit applying this on this machine, both worth checking
first if the service won't come up** (full trail: `SESSION_LOG.md`,
"Applied and verified"):

1. **A merged config line.** If step 2 was done by editing in Notepad
   (rather than the exact block replacement), check the file's tail for
   something like `#include_dirlistener 1883 0.0.0.0` — a missing newline
   between the default template's last line and the custom block. Since it
   starts with `#`, mosquitto silently treats the whole line as a comment,
   meaning your `listener` directive is never actually parsed. Symptom in
   the log: `Creating default listener due to 'max_connections' option...
   It is best practice to define a 'listener' first`. Fix: put a real
   newline between `#include_dir` and `listener 1883 0.0.0.0`.
2. **`mosquitto_passwd` missing a SYSTEM ACL entry.** The Mosquitto
   Windows service runs as `NT AUTHORITY\SYSTEM`, but a freshly-generated
   `mosquitto_passwd` file (via `mosquitto_passwd.exe -c`) can end up with
   an ACL that only grants your own user account access, unlike
   `mosquitto_acl`/`server.key`/etc., which correctly inherit SYSTEM
   access from the parent folder. The service fails to start with no
   obvious error in `Restart-Service`'s output (it reports success, then
   the service is `Stopped` moments later) — check with `Get-Acl
   certs\mosquitto_passwd` and compare against `Get-Acl certs\server.key`;
   if SYSTEM is missing from the former, fix it with:

   ```powershell
   icacls "D:\zt-cps\zt-cps-starter\certs\mosquitto_passwd" /grant "NT AUTHORITY\SYSTEM:F"
   ```

   **This was the actual root cause the one time this was hit** — the
   config content itself was fine (confirmed by running
   `mosquitto.exe -c mosquitto.conf -v` directly in a foreground shell,
   which loaded and accepted connections with no fatal error, unlike the
   service).

**Verified working, live, on this machine** (not just "should work"): the
anonymous-connection probe below returned `Success`/`connected: True`
before this fix and `Not authorized`/`connected: False` after it, and
`scripts/evaluate_iec62443.py`'s FR5 coverage moved from unverified/
code-ready to a live, computed 100% over real logged decisions.

**Prove the negative too** — this is what actually demonstrates the fix,
not just that nothing broke. From a terminal, try connecting with no
credentials at all:

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -p 1883 -t "cps/telemetry" -C 1
```

Before this change, that would silently work and print the next
telemetry message. After it, it should fail to connect (`Connection
Refused: not authorised`) — that failure is the actual evidence FR5 is
enforced, not just configured.

### 5. Dashboards need no changes

Neither `dashboard.py` (Streamlit) nor `webapp_server.py`/`webapp/index.html`
talk to MQTT at all — both read `data/audit_log.db` directly. Nothing to
update there.

## If you ever rotate credentials

Regenerate all of these together, or they'll silently disagree:

```powershell
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b "D:\zt-cps\zt-cps-starter\certs\mosquitto_passwd" <username> <new-password>
```

then update the matching entry in `src/config.py`'s `DEVICE_REGISTRY` /
`MQTT_GATEWAY_USERNAME`/`PASSWORD`, and `firmware/main.py`'s
`MQTT_USERNAME`/`MQTT_PASSWORD` if it's `esp32-vib-001`'s credential that
changed. `certs/mosquitto_acl` doesn't need touching unless you're adding
or removing a device entirely.
