"""
Module 7 extension, Phase 9 (second view): local live web dashboard,
styled after the Claude Design mockup (`design/Main.dc.html`).

Why this exists alongside `dashboard.py` (Streamlit): the user asked for
the Design tool's aesthetic specifically, but that mockup was published as
a claude.ai Artifact -- a sandboxed page with a strict CSP that CANNOT
reach `localhost` or read a local file, so it generated its own fake data
client-side (Math.random()) rather than showing anything real. This file
is NOT that artifact republished -- it's a from-scratch rebuild of the
same visual design (`webapp/index.html`, plain HTML/CSS/vanilla JS, no
proprietary Design-tool runtime) served by a small stdlib-only local HTTP
server, so the page can freely `fetch()` real data from its own origin.
Run entirely on your machine, never published anywhere.

Every /api/* endpoint below reads from the exact same modules
`dashboard.py` and `scripts/evaluate_*.py` already use (`audit_log`,
`nist_mapping`, `iec62443_mapping`, `adaptive_pdp`) -- this is a second,
differently-styled VIEW onto the same real pipeline output, not a second
data source.

Run alongside gateway.py + a telemetry source, same as dashboard.py:
    python webapp_server.py
Then open http://localhost:8600 in a browser.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import DEVICE_REGISTRY, THRESHOLD_ALLOW, THRESHOLD_STEP_UP, NIST_TENETS, ADAPTIVE_PDP_MODEL_PATH, USE_RL_POLICY
import audit_log
import nist_mapping
import iec62443_mapping
from adaptive_pdp import ACTIONS, state_key

PORT = 8600
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
ROWS_TO_FETCH = 300


def _json(handler: BaseHTTPRequestHandler, payload) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _build_qtable_view() -> dict:
    """Reads the REAL trained Q-table (models/adaptive_pdp_qtable.json) --
    not mocked -- and reshapes it into trust-bucket rows for the frontend,
    same bucketing adaptive_pdp.state_key() uses live."""
    q = {}
    if os.path.exists(ADAPTIVE_PDP_MODEL_PATH):
        with open(ADAPTIVE_PDP_MODEL_PATH) as f:
            q = json.load(f)

    rows = []
    # confidence bucket 1 (>=0.5, the common case) at 10 trust buckets of width 0.1
    for trust_bucket in range(10):
        key = f"{trust_bucket},1"
        qvals = q.get(key)
        rows.append({
            "label": f"{trust_bucket / 10:.1f}–{(trust_bucket + 1) / 10:.1f}",
            "known": qvals is not None,
            "q": qvals or {a: 0.0 for a in ACTIONS},
        })
    return {"rows": rows, "actions": ACTIONS, "trained": os.path.exists(ADAPTIVE_PDP_MODEL_PATH)}


def _build_devices_view() -> list:
    return [
        {"device_id": d, "kind": info["kind"]}
        for d, info in DEVICE_REGISTRY.items()
    ]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep console quiet, same rationale as coap_server.py

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_static("index.html", "text/html")
        elif self.path.startswith("/api/decisions"):
            rows = audit_log.recent(ROWS_TO_FETCH)
            _json(self, {"rows": rows})
        elif self.path == "/api/devices":
            _json(self, {"devices": _build_devices_view()})
        elif self.path == "/api/governance":
            rows = audit_log.recent(ROWS_TO_FETCH)
            report = nist_mapping.completeness_report(rows)
            _json(self, {
                "tenets": NIST_TENETS,
                "coverage": report,
                "sample_size": len(rows),
            })
        elif self.path == "/api/iec62443":
            rows = audit_log.recent(ROWS_TO_FETCH)
            coverage = iec62443_mapping.fr_coverage_report(rows)
            frs = [
                {
                    "id": fr, "name": info["name"], "status": info["status"],
                    "coverage": coverage.get(fr) if info["status"] != "not_implemented" else None,
                    "detail": info.get("where") or info.get("note"),
                    "gap_note": info.get("note") if info["status"] == "partial" else None,
                }
                for fr, info in iec62443_mapping.FOUNDATIONAL_REQUIREMENTS.items()
            ]
            _json(self, {
                "zones": iec62443_mapping.ZONES,
                "conduits": iec62443_mapping.CONDUITS,
                "frs": frs,
                "sl_assessment": iec62443_mapping.SECURITY_LEVEL_ASSESSMENT,
                "sample_size": len(rows),
            })
        elif self.path == "/api/qtable":
            _json(self, _build_qtable_view())
        elif self.path == "/api/status":
            _json(self, {
                "use_rl_policy": USE_RL_POLICY,
                "threshold_allow": THRESHOLD_ALLOW,
                "threshold_step_up": THRESHOLD_STEP_UP,
            })
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = os.path.join(STATIC_DIR, filename)
        if not os.path.exists(path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"webapp/index.html not found")
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run():
    audit_log.init_db()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[webapp] serving http://localhost:{PORT} -- Ctrl+C to stop")
    print(f"[webapp] reading live data from the same audit_log.db / models/ the gateway writes to")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[webapp] stopped.")


if __name__ == "__main__":
    run()
