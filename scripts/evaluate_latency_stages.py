"""
Per-stage latency with percentiles (reviewer concern P).

The existing evaluate_latency.py reports aggregate timings. A mean hides the
tail, and for a gateway the tail is the number that matters: a p99 that exceeds
the telemetry interval means a queue that grows without bound, which a mean of
a few milliseconds will never reveal.

Measures each host-side stage independently, with a HIGH-RESOLUTION MONOTONIC
timer (time.perf_counter_ns -- monotonic, so an NTP correction mid-run cannot
produce a negative interval, and nanosecond-resolution, because several of
these stages are faster than time.time()'s tick on Windows).

WARM inference only. Model loading is measured separately and reported as
cold-start, never folded into the per-message figures -- a one-off 2-second
torch load averaged across 3000 messages would silently add 0.7 ms to every
stage and make the pipeline look slower than it is, or, worse, be quietly
excluded and make a cold start look impossible.
"""

import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import DATA_COLLECTED_DIR, is_feature_vector, NETWORK_NODES, REAL_NODES
import feature_engineering as fe
from trust_engine import RuleBasedTrustEngine, rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from policy_engine import decide
from adaptive_pdp import AdaptivePDP
import datasets

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "latency")
TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")

STAGES = ["authentication", "security_trust", "rule_detector", "isolation_forest",
          "lstm_ae", "gnn", "fusion", "policy", "explainability", "audit_logging",
          "total_pipeline"]


def summarise(samples_ms):
    """count / mean / sd / p50 / p95 / p99 / max. Percentiles by
    numpy.percentile with linear interpolation, stated so the number is
    reproducible -- p99 of 3000 samples is sensitive to the estimator."""
    if not samples_ms:
        return None
    a = np.array(samples_ms)
    return {"count": int(a.size),
            "mean_ms": round(float(a.mean()), 4),
            "sd_ms": round(float(a.std(ddof=1)) if a.size > 1 else 0.0, 4),
            "p50_ms": round(float(np.percentile(a, 50)), 4),
            "p95_ms": round(float(np.percentile(a, 95)), 4),
            "p99_ms": round(float(np.percentile(a, 99)), 4),
            "max_ms": round(float(a.max()), 4)}


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=" * 78)
    print("PER-STAGE LATENCY -- warm inference, monotonic ns timer")
    print("=" * 78)

    # --- cold start, measured and reported separately -------------------
    t0 = time.perf_counter_ns()
    if_s = IsolationForestScorer()
    lstm_s = LSTMAEScorer()
    gnn_s = GNNScorer()
    fusion = FusionEngine()
    pdp = AdaptivePDP()
    cold_start_ms = (time.perf_counter_ns() - t0) / 1e6
    print(f"cold start (loading every model artifact): {cold_start_ms:.1f} ms  "
          f"-- reported separately, NOT amortised into the warm figures\n")

    with open(TEST_PATH) as f:
        records = [r for r in json.load(f) if r["auth_ok"] and r["event_type"] != "replay"]
    engine = RuleBasedTrustEngine()

    import hashlib, hmac as hmac_mod
    secret = b"latency-benchmark-key"
    timings = {s: [] for s in STAGES}

    for r in records:
        device_id = r["device_id"]
        t_msg = time.perf_counter_ns()

        # authentication: canonicalise + HMAC-SHA256 + compare, the real work
        # gateway.verify_signature() does per message.
        t = time.perf_counter_ns()
        canonical = json.dumps({"device_id": device_id, "reading": r["reading"],
                                "ts": r.get("ts", 0)}, sort_keys=True).encode()
        sig = hmac_mod.new(secret, canonical, hashlib.sha256).hexdigest()
        hmac_mod.compare_digest(sig, sig)
        timings["authentication"].append((time.perf_counter_ns() - t) / 1e6)

        t = time.perf_counter_ns()
        sec, _ = engine.score_security_trust(device_id, is_flood=False)
        timings["security_trust"].append((time.perf_counter_ns() - t) / 1e6)

        t = time.perf_counter_ns()
        rule, reason = rule_range_score(device_id, r["reading"])
        timings["rule_detector"].append((time.perf_counter_ns() - t) / 1e6)

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            t = time.perf_counter_ns()
            iso = if_s.score(device_id, fv)
            timings["isolation_forest"].append((time.perf_counter_ns() - t) / 1e6)
            t = time.perf_counter_ns()
            lstm = lstm_s.score(device_id, fv)
            timings["lstm_ae"].append((time.perf_counter_ns() - t) / 1e6)
        else:
            iso = lstm = rule

        t = time.perf_counter_ns()
        gnn = gnn_s.score(device_id, rule, iso, lstm)
        timings["gnn"].append((time.perf_counter_ns() - t) / 1e6)

        t = time.perf_counter_ns()
        fused, _, explanation = fusion.combine(rule, iso, lstm, gnn)
        timings["fusion"].append((time.perf_counter_ns() - t) / 1e6)

        t = time.perf_counter_ns()
        decide(sec, fused, "FRESH")
        pdp.greedy_action(sec, fused)
        timings["policy"].append((time.perf_counter_ns() - t) / 1e6)

        # explainability: the per-message contribution decomposition the
        # dashboard renders. Measured because it runs on the live path.
        t = time.perf_counter_ns()
        _ = fusion._explain(np.array([rule, iso, lstm, gnn]))
        timings["explainability"].append((time.perf_counter_ns() - t) / 1e6)

        # audit logging: the hash-chain link computation, WITHOUT the sqlite
        # write. The write is I/O-bound and would measure the disk, not the
        # gateway; it is called out here rather than silently omitted.
        t = time.perf_counter_ns()
        hashlib.sha256(json.dumps({"device_id": device_id, "decision": "ALLOW",
                                   "s_sec": sec, "s_proc": fused},
                                  sort_keys=True).encode()).hexdigest()
        timings["audit_logging"].append((time.perf_counter_ns() - t) / 1e6)

        timings["total_pipeline"].append((time.perf_counter_ns() - t_msg) / 1e6)

    print(f"{'stage':20s} {'n':>6s} {'mean':>8s} {'sd':>8s} {'p50':>8s} "
          f"{'p95':>8s} {'p99':>8s} {'max':>8s}")
    print("-" * 78)
    summary = {}
    for s in STAGES:
        m = summarise(timings[s])
        if m is None:
            continue
        summary[s] = m
        print(f"{s:20s} {m['count']:>6d} {m['mean_ms']:>8.4f} {m['sd_ms']:>8.4f} "
              f"{m['p50_ms']:>8.4f} {m['p95_ms']:>8.4f} {m['p99_ms']:>8.4f} {m['max_ms']:>8.4f}")

    # --- 10-node hybrid network throughput, distinguished from single-message --
    print()
    print("10-NODE HYBRID NETWORK -- one graph inference over all ten nodes.")
    print("Reported separately from single-message latency: they answer different")
    print("questions, and conflating them would overstate per-message cost.")
    net_times = []
    for scenario in datasets.scenarios():
        rows = datasets.network_records(scenario, "test")
        by_tick = {}
        for r in rows:
            by_tick.setdefault(r["tick"], []).append(r)
        for tick in sorted(by_tick)[:150]:
            t = time.perf_counter_ns()
            for r in by_tick[tick]:
                if r.get("reading") is None:
                    continue
                did = r["device_id"]
                rule, _ = rule_range_score(did, r["reading"])
                if is_feature_vector(did):
                    fv = fe.feature_vector(r["reading"])
                    iso, lstm = if_s.score(did, fv), lstm_s.score(did, fv)
                else:
                    iso = lstm = rule
                gnn_s.score(did, rule, iso, lstm)
            net_times.append((time.perf_counter_ns() - t) / 1e6)
    net = summarise(net_times)
    summary["network_10_node_tick"] = net
    print(f"{'10-node tick':20s} {net['count']:>6d} {net['mean_ms']:>8.4f} {net['sd_ms']:>8.4f} "
          f"{net['p50_ms']:>8.4f} {net['p95_ms']:>8.4f} {net['p99_ms']:>8.4f} {net['max_ms']:>8.4f}")
    print(f"  -> {1000.0 / net['mean_ms']:.1f} network ticks/s = "
          f"{1000.0 * len(NETWORK_NODES) / net['mean_ms']:.0f} messages/s sustained")
    print("  Ten nodes is not evidence of industrial scalability, and is not "
          "presented as such.")

    out = {"environment_note": "see docs/ENVIRONMENT.md for host CPU/RAM/GPU and versions",
           "timer": "time.perf_counter_ns (monotonic, nanosecond resolution)",
           "warm": True,
           "cold_start_ms": round(cold_start_ms, 1),
           "audit_logging_note": "hash-chain link computation only; the sqlite write is "
                                 "I/O-bound and excluded, stated rather than omitted",
           "stages": summary}
    with open(os.path.join(RESULTS_DIR, "latency.json"), "w") as f:
        json.dump(out, f, indent=2)

    import csv
    with open(os.path.join(RESULTS_DIR, "latency.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stage", "count", "mean_ms", "sd_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"])
        for s, m in summary.items():
            w.writerow([s, m["count"], m["mean_ms"], m["sd_ms"], m["p50_ms"],
                        m["p95_ms"], m["p99_ms"], m["max_ms"]])
    print(f"\nwritten to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
