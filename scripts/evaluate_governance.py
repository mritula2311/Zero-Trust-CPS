"""
Synopsis Section 10.1/10.2: "Governance completeness: proportion of NIST
SP 800-207 tenets for which the system produces a traceable, logged
artefact" / "A governance-ready audit report mapping implemented controls
... to NIST SP 800-207 tenets." This is the standalone, paper-ready
version of the same report dashboard.py's "NIST SP 800-207 governance
completeness" section shows live -- run this for a point-in-time snapshot
you can paste into the report, rather than a screenshot of the dashboard.

Reads the LIVE audit_log.db (not a held-out test set -- governance
completeness is about what the deployed system actually produced, not a
model's predictive accuracy).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import audit_log
import nist_mapping
from config import NIST_TENETS


def main():
    rows = audit_log.recent(10_000)
    if not rows:
        raise SystemExit("audit_log.db is empty -- run the gateway + a telemetry source first.")

    report = nist_mapping.completeness_report(rows)

    print(f"NIST SP 800-207 Governance Completeness Report")
    print(f"({len(rows)} audit log entries, data/audit_log.db)\n")
    print(f"{'#':<3} {'Tenet':<62} {'Coverage':>9}")
    print("-" * 76)
    for n in sorted(report):
        print(f"{n:<3} {NIST_TENETS[n]:<62} {report[n]:>8.0%}")

    overall = sum(report.values()) / len(report)
    print(f"\nOverall completeness: {overall:.0%} ({sum(1 for f in report.values() if f == 1.0)}/{len(report)} tenets at 100% coverage)")

    incomplete = {n: f for n, f in report.items() if f < 1.0}
    if incomplete:
        print("\nTenets not at 100% and why (see nist_mapping.tenets_for_decision()'s docstring):")
        if 2 in incomplete:
            print(f"  Tenet 2 (secured communication): {incomplete[2]:.0%} -- some logged messages "
                  f"arrived over an unsecured transport (plain MQTT before docs/03_add_tls.md's setup, "
                  f"if any such rows are still in the log).")
        if 7 in incomplete:
            print(f"  Tenet 7 (telemetry improves posture): {incomplete[7]:.0%} -- some logged decisions "
                  f"were made before the fusion engine finished training (scripts/train_fusion_meta_learner.py).")
        for n, f in incomplete.items():
            if n not in (2, 7):
                print(f"  Tenet {n}: {f:.0%} -- investigate; every OTHER tenet should always be 100% "
                      f"by construction (see nist_mapping.py).")
    else:
        print("\nAll 7 tenets at 100% coverage across every logged decision.")


if __name__ == "__main__":
    main()
