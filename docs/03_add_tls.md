# 03 — Upgrading to MQTT-over-TLS (Module 6, properly)

The starter kit uses plain MQTT on port 1883 so you can get running in five
minutes. Report Section 4.3 (Module 6) and references [23],[24] specifically
require TLS — do this before you consider Module 6 "done" for your report.

## 1. Generate a self-signed Certificate Authority and server certificate

Run these on the machine that will run the broker (your laptop or the
Raspberry Pi gateway):

```bash
mkdir certs && cd certs

# Certificate Authority (CA)
openssl req -x509 -newkey rsa:2048 -days 365 -nodes \
  -keyout ca.key -out ca.crt \
  -subj "/CN=ZT-CPS-Demo-CA"

# Server (broker) key + certificate signing request
openssl req -newkey rsa:2048 -nodes \
  -keyout server.key -out server.csr \
  -subj "/CN=localhost"

# Sign the server certificate with your CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 365
```

## 2. Configure Mosquitto to require TLS

Create `mosquitto_tls.conf`:

```conf
listener 8883
cafile /full/path/to/certs/ca.crt
certfile /full/path/to/certs/server.crt
keyfile /full/path/to/certs/server.key
require_certificate false
```

Run the broker with this config: `mosquitto -c mosquitto_tls.conf`

## 3. Update `config.py`

```python
MQTT_PORT = 8883
MQTT_TLS_CA_CERT = "certs/ca.crt"
```

## 4. Update the `mqtt.Client(...)` calls in both `gateway.py` and
   `device_simulator.py`

Add this line right after creating the client, before `.connect(...)`:

```python
client.tls_set(ca_certs=MQTT_TLS_CA_CERT)
```

## 5. Re-run and confirm

Run the gateway and simulator exactly as before. If the connection succeeds,
you're now encrypting every message on the wire. If you want to go further
(and this is worth mentioning in your report's evaluation section as a
stretch item), issue each *device* its own client certificate signed by the
same CA and set `require_certificate true` — that gives you mutual TLS, where
the broker also verifies the device's identity at the transport layer, on top
of the HMAC check already happening at the application layer in `gateway.py`.
