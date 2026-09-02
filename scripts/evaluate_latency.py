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
board is flashed. It IS measured, on-device, by firmware/main.py's own
instrumentation -- see RESULTS.md 13.1/13.4b and the caveat printed below.
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
# audit_log.py's functions read the module-level AUDIT_DB_PATH/
# CHECKPOINT_STORE_PATH/AUDIT_KEY_PATH on every call (not values frozen at
# import time), so reassigning them here redirects every write this script
# triggers without touching config.py itself.
#
# ALL THREE must be redirected, not just AUDIT_DB_PATH -- found live, not
# theorized: an earlier version of this script only redirected
# AUDIT_DB_PATH, leaving log_decision()'s checkpoint writes
# (_maybe_write_checkpoint()) going to the SAME SHARED
# data/checkpoint_log.jsonl file the real gateway uses. This throwaway
# run's row 100 (in its own, unrelated EVAL_DB_PATH) got a checkpoint
# entry appended to that shared file claiming "row 100 has hash X" -- a
# hash that has nothing to do with the real audit_log.db's actual row 100.
# The next verify_against_checkpoints() call against the REAL audit log
# then failed on a completely untampered database, because it was
# comparing the real row 100 against a checkpoint written for a different
# database entirely.
EVAL_DB_PATH = os.path.join(DATA_COLLECTED_DIR, "..", "eval_audit_log.db")
EVAL_CHECKPOINT_PATH = os.path.join(DATA_COLLECTED_DIR, "..", "eval_checkpoint_log.jsonl")
EVAL_AUDIT_KEY_PATH = os.path.join(DATA_COLLECTED_DIR, "..", "eval_audit_key.bin")
audit_log.AUDIT_DB_PATH = EVAL_DB_PATH
audit_log.CHECKPOINT_STORE_PATH = EVAL_CHECKPOINT_PATH
audit_log.AUDIT_KEY_PATH = EVAL_AUDIT_KEY_PATH


def build_envelopes(n):
    """Real, validly-signed envelopes for esp32-vib-001 -- exercises the
    full feature_vector code path, the one with the most work per message.

    `ts` MUST be real wall-clock epoch ms now (Module 2's secondary
    freshness check compares against time.time()*1000 directly -- unlike
    the old ms-since-boot scheme, an arbitrary small constant here would
    make every single envelope fail as stale_timestamp). `boot_id`/`seq`
    are required fields too (Module 2 Check 4) -- one constant boot
    session, strictly increasing seq, so every envelope passes the
    boot-aware replay check and actually reaches the full pipeline this
    script means to measure."""
    envelopes = []
    now_ms = int(time.time() * 1000)
    for i in range(n):
        reading = ds.make_reading("esp32-vib-001", anomalous=(i % 10 == 0))
        payload = {"device_id": "esp32-vib-001", "ts": now_ms + i, "boot_id": 1, "seq": i + 1, **reading}
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
        "ESP32-side latency is NOT measured by this script -- it is measured on the "
        "device itself by firmware/main.py's own time.ticks_ms()/ticks_diff() "
        "instrumentation, which prints one [latency] line per message to the serial "
        "console. See RESULTS.md 13.1 and 13.4b. "
        "  CAVEAT, do not quote those tables without reading this: their sampling "
        "figure (26 ms) predates the 500 Hz pacing fix (ADR-16). 32 samples at the "
        "old unpaced ~1231 Hz is 26 ms; at the deployed 500 Hz it must be 64 ms. "
        "The totals derived from it are therefore understated, and the two sections "
        "also disagree with each other on feature extraction (134.5 ms vs 98-100 ms). "
        "Both need re-measuring on the current firmware."
    )

    for throwaway_path in (EVAL_DB_PATH, EVAL_CHECKPOINT_PATH, EVAL_AUDIT_KEY_PATH):
        if os.path.exists(throwaway_path):
            os.remove(throwaway_path)  # throwaway -- the numbers above are the deliverable, not these files


if __name__ == "__main__":
    main()
