"""
Template for src/secrets_local.py (gitignored, never committed).

Copy this file to secrets_local.py and fill in your own values:

    cp secrets_local.example.py secrets_local.py     # macOS/Linux
    Copy-Item secrets_local.example.py secrets_local.py   # Windows PowerShell

Generate real random values instead of typing your own, e.g.:

    python -c "import secrets; print(secrets.token_hex(16))"          # for DEVICE_SECRETS
    python -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"   # for MQTT_PASSWORDS

If you change MQTT_PASSWORDS or MQTT_GATEWAY_PASSWORD after
`certs/mosquitto_passwd` already exists, regenerate that file to match --
see docs/07_module6_secure_communication.md Section 3.
"""

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
