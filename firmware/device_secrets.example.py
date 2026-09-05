"""Copy this file to device_secrets.py before flashing; never commit that copy."""

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_HOST = "192.168.0.1"
DEVICE_ID = "esp32-vib-001"
DEVICE_SECRET = "REPLACE_WITH_DEVICE_SECRET"
MQTT_USERNAME = "REPLACE_WITH_MQTT_USERNAME"
MQTT_PASSWORD = "REPLACE_WITH_MQTT_PASSWORD"

# Optional. Uncomment and upload a DER-encoded CA certificate alongside this
# file to have firmware/main.py verify the broker's TLS certificate instead
# of accepting any certificate unchecked. See HARDWARE_SETUP.md Section 13.
# MQTT_CA_CERT_FILE = "ca.der"
