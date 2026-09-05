"""One client's declared/actual body size must not force an unbounded read.

Run: python -m unittest discover -s tests -p test_coap_server_hardening.py -v
"""

import io
import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import coap_server
from config import COAP_TELEMETRY_PATH


def make_handler(headers, body=b""):
    handler = coap_server.TelemetryHTTPSHandler.__new__(coap_server.TelemetryHTTPSHandler)
    handler.path = "/" + COAP_TELEMETRY_PATH
    handler.headers = headers
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.end_headers = Mock()
    return handler


class TestCoapServerHardening(unittest.TestCase):
    def test_oversized_content_length_rejected_without_reading_body(self):
        handler = make_handler({"Content-Length": str(coap_server.MAX_BODY_BYTES + 1)})
        handler.do_POST()
        handler.send_response.assert_called_once_with(413)
        self.assertEqual(handler.rfile.tell(), 0, "body was read despite failing the size cap")

    def test_malformed_content_length_rejected(self):
        handler = make_handler({"Content-Length": "not-a-number"})
        handler.do_POST()
        handler.send_response.assert_called_once_with(400)

    def test_missing_content_length_rejected(self):
        handler = make_handler({})
        handler.do_POST()
        handler.send_response.assert_called_once_with(400)

    def test_within_cap_reaches_the_normal_json_path(self):
        handler = make_handler({"Content-Length": "1"}, body=b"{")
        handler.do_POST()
        handler.send_response.assert_called_once_with(400)
        handler.wfile.seek(0)
        self.assertEqual(handler.wfile.read(), b"malformed JSON")


if __name__ == "__main__":
    unittest.main()
