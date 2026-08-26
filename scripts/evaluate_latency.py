"""
Synopsis Section 10.1: "Authentication and gateway-inference latency,
measured on the real ESP32 and the Pi-class (or laptop) gateway, compared
against [22],[23],[24]'s published baselines." This script measures the
GATEWAY side (the machine running gateway.py) -- HMAC verification alone,
and the full per-message pipeline (auth + all 4 scorers + fusion + EWMA +
policy decision).

The ESP32-side half of this metric (signing latency, feature-extraction
latency on the microcontroller itself) can't be measured from here --
that needs `time.ticks_ms()` calls added around the relevant sections of
firmware/main.py and reading them back over the serial console once the
board is flashed. Noted as a TODO, not silently omitted.
"""

import contextlib
import io
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, DEVICE_REGISTRY
import audit_log
import gateway
import device_simulator as ds

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")
N_WARMUP = 20
N_MEASURED = 200

# CLAUDE.md Section 8: "Use a separate test database during offline
# training/evaluation runs so you don't pollute the live audit log."
# gateway.process_telemetry() calls audit_log.log_decision() internally;
# audit_log.py's functions read the module-level AUDIT_DB_PATH on every
# call (not a value frozen at import time), so reassigning it here redirects
# every write this script triggers without touching config.py itself.
EVAL_DB_PATH = os.path.join(DATA_COLLECTED_DIR, "..", "eval_audit_log.db")
audit_log.AUDIT_DB_PATH = EVAL_DB_PATH


def build_envelopes(n):
    """Real, validly-signed envelopes for esp32-vib-001 -- exercises the
    full feature_vector code path, the one with the most work per message."""
    envelopes = []
    for i in range(n):
        reading = ds.make_reading("esp32-vib-001", anomalous=(i % 10 == 0))
        payload = {"device_id": "esp32-vib-001", "ts": 10_000_000 + i * 2000, **reading}
        sig = ds.sign(DEVICE_REGISTRY["esp32-vib-001"]["secret"], payload)
        envelopes.append({"payload": payload, "signature": sig})
    return envelopes


def main():
    audit_log.init_db()  # creates EVAL_DB_PATH's table -- separate from the live audit log
    envelopes = build_envelopes(N_WARMUP + N_MEASURED)

    # --- HMAC verification alone ---
    hmac_times = []
    for env in envelopes:
        t0 = time.perf_counter()
        gateway.verify_signature(env["payload"]["device_id"], env["payload"], env["signature"])
        hmac_times.append((time.perf_counter() - t0) * 1000)  # ms

    # --- Full pipeline (process_telemetry) ---
    # process_telemetry() prints one console line per message -- fine live,
    # 200+ lines of noise here. Suppressed with redirect_stdout so only this
    # script's own summary prints; timing itself is unaffected (perf_counter
    # calls sit outside the redirected block).
    with contextlib.redirect_stdout(io.StringIO()):
        for env in envelopes[:N_WARMUP]:  # warm up first (first-call overhead in torch/sklearn)
            gateway.process_telemetry(env, transport="mqtt", transport_secured=True)

        full_times = []
        for env in envelopes[N_WARMUP:]:
            t0 = time.perf_counter()
            gateway.process_telemetry(env, transport="mqtt", transport_secured=True)
            full_times.append((time.perf_counter() - t0) * 1000)

    def summarize(name, values):
        values.sort()
        n = len(values)
        p50 = values[n // 2]
        p95 = values[int(n * 0.95)]
        print(f"{name:<32} mean={statistics.mean(values):7.3f}ms  "
              f"median={p50:7.3f}ms  p95={p95:7.3f}ms  max={max(values):7.3f}ms  (n={n})")

    print(f"Gateway-side latency, measured on this machine, N={N_MEASURED} messages "
          f"(after {N_WARMUP}-message warmup):\n")
    summarize("HMAC verification only", hmac_times[N_WARMUP:])
    summarize("Full pipeline (auth+4 scorers+fusion+policy)", full_times)
    print(
        "\nCompare against [22] (device-to-device continuous auth), [23] (CoAP/MQTT/HTTP "
        "protocol overhead), [24] (TLS-tunnelled MQTT broker overhead) per synopsis Section 10.1 "
        "-- pull their reported figures from the literature review for the comparison table.\n"
        "ESP32-side signing/feature-extraction latency: not measured here -- needs "
        "time.ticks_ms() instrumentation in firmware/main.py on real hardware (TODO)."
    )

    if os.path.exists(EVAL_DB_PATH):
        os.remove(EVAL_DB_PATH)  # throwaway -- the numbers above are the deliverable, not this file


if __name__ == "__main__":
    main()
