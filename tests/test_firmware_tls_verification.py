"""firmware/main.py must support opting into broker certificate verification.

String-level checks only, matching tests/test_invariants.py's firmware tests:
firmware/main.py imports MicroPython-only modules and cannot be executed here.
"""

import os
import unittest


class TestFirmwareTLSVerification(unittest.TestCase):
    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "firmware", "main.py")
        with open(path, encoding="utf-8") as f:
            self.src = f.read()

    def test_ca_cert_file_is_optional_and_defaults_unset(self):
        self.assertIn("MQTT_CA_CERT_FILE = None", self.src,
                      "MQTT_CA_CERT_FILE must default unset -- unconfigured firmware "
                      "must not silently require a CA cert it was never given")

    def test_configured_ca_cert_switches_to_verified_tls(self):
        self.assertIn("ussl.CERT_REQUIRED", self.src)
        self.assertIn('"ca_certs": ca_cert', self.src)

    def test_unconfigured_path_still_warns_instead_of_connecting_silently(self):
        self.assertIn("ussl.CERT_NONE", self.src)
        idx = self.src.index('"cert_reqs": ussl.CERT_NONE')
        nearby = self.src[max(0, idx - 400):idx + 400]
        self.assertIn("WARNING", nearby,
                      "unverified-TLS fallback must print an explicit warning at boot")


if __name__ == "__main__":
    unittest.main()
