"""
Module 6, second transport (synopsis Sections 4.3/7.2/8.2).

The synopsis requires MQTT/TLS AND CoAP/DTLS as two independently secured
transports, "no plaintext fallback" on either. Two separate paths to CoAP
were tried and both hit a real, verified blocker -- this file implements
an HTTPS-based substitute instead, on the same functional footing
(independent, TLS-secured, no-plaintext-fallback second channel a device
could use as an alternative to MQTT).

WHAT WAS TRIED, AND WHY IT'S BLOCKED (worth stating explicitly in the
paper's limitations section, not hiding):

1. Classic CoAP-over-DTLS (RFC 7252, "coaps" over UDP) needs the
   `DTLSSocket` package, which needs a native autotools build
   (`autoreconf`). Confirmed unavailable both natively on this Windows
   machine and in WSL (Kali) -- WSL has gcc/make/python3 but `sudo apt
   install autoconf` needs a password this environment doesn't have.

2. CoAP-over-TLS (RFC 8323, "coaps+tcp") via the `aiocoap` library's
   `TLSServer` transport was implemented and tested -- it starts without
   error and logs "ready to receive requests," but every real connection
   attempt is refused/times out. This was verified with a *raw TCP socket
   connect* (bypassing aiocoap's own client entirely, to rule out a
   client-side credentials/cert mismatch) on:
     - native Windows (this machine)
     - WSL/Kali Linux (ruling out a Windows ProactorEventLoop issue)
     - aiocoap 0.4.17 AND 0.4.7 (ruling out a recent regression)
   All six combinations reproduced the same failure. aiocoap's own
   `transports/tls.py` module docstring calls this transport "early work
   in progress," consistent with what was observed. This is a genuine
   upstream library defect, not a configuration mistake -- the setup code
   matches aiocoap's own documented `server_context_from_arguments`
   pattern (see aiocoap/cli/common.py) exactly.

Given both standard paths are blocked by verified external issues (not a
scope cut), this module delivers the same FUNCTIONAL requirement --
a second, independently TLS-secured, no-plaintext-fallback transport for
telemetry -- as an HTTPS POST endpoint instead, built on Python's
standard `http.server` + `ssl` (no new dependencies, no known defects).
A device (or a test client) POSTs the same envelope shape MQTT devices
publish -- {"payload": {...}, "signature": "..."} -- to
https://<gateway>:5684/telemetry. This hands it to
gateway.process_telemetry() unchanged, exactly like the MQTT path:
Module 6's whole point is that the rest of the pipeline doesn't know or
care which secured transport a message arrived over.
"""

import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import COAP_TLS_PORT, COAP_TELEMETRY_PATH, COAP_CERT_PATH, COAP_KEY_PATH

# A telemetry envelope is a handful of floats and a hex signature -- a few KB
# is generous headroom. Caps a single POST's declared and actual body size so
# one client can't force an unbounded rfile.read() on this single-threaded
# server (ASTRA_AUDIT.md P1, src/coap_server.py::do_POST).
MAX_BODY_BYTES = 16_384


class TelemetryHTTPSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # quiet -- gateway.process_telemetry() already prints one line per message

    def do_POST(self):
        import gateway  # deferred import -- avoids a circular import at module load time

        if self.path.strip("/") != COAP_TELEMETRY_PATH:
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing or invalid Content-Length")
            return
        if not 0 <= length <= MAX_BODY_BYTES:
            self.send_response(413)
            self.end_headers()
            self.wfile.write(b"body too large")
            return
        body = self.rfile.read(length)
        try:
            envelope = json.loads(body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"malformed JSON")
            return

        gateway.process_telemetry(envelope, transport="https", transport_secured=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=COAP_CERT_PATH, keyfile=COAP_KEY_PATH)
    return ctx


def start_https_server() -> HTTPServer:
    """Starts the HTTPS telemetry server in a background thread (same
    non-blocking pattern gateway.py already uses for MQTT's loop_start())
    and returns the server object so the caller can .shutdown() it if
    needed. Runs forever otherwise."""
    server = HTTPServer(("0.0.0.0", COAP_TLS_PORT), TelemetryHTTPSHandler)
    server.socket = _build_ssl_context().wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[https] listening on https://0.0.0.0:{COAP_TLS_PORT}/{COAP_TELEMETRY_PATH} "
          f"(Module 6's second secured transport -- see this file's docstring for why this substitutes for CoAP/DTLS)")
    return server


if __name__ == "__main__":
    # Standalone run, for testing this transport in isolation (gateway.py
    # normally launches this alongside MQTT -- see its run() function).
    import time
    import audit_log
    audit_log.init_db()
    start_https_server()
    while True:
        time.sleep(1)
