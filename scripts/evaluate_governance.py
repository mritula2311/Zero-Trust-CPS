"""
Synopsis Section 10.1/10.2: "Governance completeness: proportion of NIST
SP 800-207 tenets for which the system produces a traceable, logged
artefact" / "A governance-ready audit report mapping implemented controls
... to NIST SP 800-207 tenets." Run this for a point-in-time,
paper-ready snapshot of the same completeness metric `nist_mapping.py`
computes.

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
import governance_validation


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
        print("")
        print("NOTE: coverage measures TAGGING, and nist_mapping.tenets_for_decision()")
        print("writes tenets 1/3/4/5/6 on every decision unconditionally -- so 100% there")
        print("is true by construction, not a finding. The validation report below is the")
        print("part that can actually fail.")

    validation_report(rows)
    falsifiability_self_test()


# ---------------------------------------------------------------------------
# Part 2: VALIDATION (not coverage). See src/governance_validation.py's module
# docstring for why this exists as a separate report -- in short, coverage
# measures whether a tenet was TAGGED, and for five of the seven tenets the
# tagger writes them unconditionally, so 100% coverage there is tautological.
# ---------------------------------------------------------------------------

FALSIFIABILITY_CASES = {
    1: ("an authenticated row from an unregistered device",
        [{"device_id": "ghost-999", "auth_ok": 1, "decision": "ALLOW", "transport": "mqtt",
          "security_trust_score": 0.9, "process_trust_score": 0.9, "rule_score": 0.9,
          "fused_score": 0.5, "reason": ""}]),
    2: ("an authenticated row that arrived over an unencrypted transport",
        [{"device_id": "sensor-002", "auth_ok": 1, "decision": "ALLOW", "transport": "plain-tcp",
          "security_trust_score": 0.9, "process_trust_score": 0.9, "rule_score": 0.9,
          "fused_score": 0.5, "reason": ""}]),
    3: ("a row granted access with no scores of its own (a cached verdict)",
        [{"device_id": "sensor-002", "auth_ok": 1, "decision": "ALLOW", "transport": "mqtt",
          "security_trust_score": None, "process_trust_score": None, "rule_score": 0.9,
          "fused_score": 0.5, "reason": ""}]),
    4: ("a policy that ALLOWs at exactly the same rate above and below both thresholds",
        [{"device_id": "sensor-002", "auth_ok": 1, "decision": "ALLOW", "transport": "mqtt",
          "security_trust_score": s, "process_trust_score": p, "rule_score": 0.9,
          "fused_score": 0.5, "reason": ""}
         for s, p in ((0.1, 0.1), (0.9, 0.9), (0.1, 0.9), (0.9, 0.1))]),
    6: ("an UNauthenticated row that was granted ALLOW",
        [{"device_id": "sensor-002", "auth_ok": 0, "decision": "ALLOW", "transport": "mqtt",
          "security_trust_score": 0.9, "process_trust_score": 0.9, "rule_score": 0.9,
          "fused_score": 0.5, "reason": ""}]),
    7: ("a pipeline whose fused score never differs from the rule baseline",
        [{"device_id": "sensor-002", "auth_ok": 1, "decision": "ALLOW", "transport": "mqtt",
          "security_trust_score": 0.9, "process_trust_score": 0.9, "rule_score": 0.9,
          "fused_score": 0.9, "reason": ""}]),
}


def falsifiability_self_test():
    """Proves each check can actually FAIL. A validation that passes on every
    possible input is not a validation, so each tenet's own stated falsifier is
    injected here as a synthetic row set and the check must reject it.

    Tenet 5 is excluded: its falsifier is a registered device with NO rows,
    which is the absence of data rather than a row that can be constructed."""
    print("\n" + "=" * 78)
    print("Falsifiability self-test -- can these checks actually fail?")
    print("=" * 78)
    print("Each tenet's own stated falsifier is injected as synthetic rows; the check")
    print("must return FAIL. A check that still passes here would be vacuous.\n")

    proved = 0
    for tenet, (description, bad_rows) in sorted(FALSIFIABILITY_CASES.items()):
        result = next(r for r in governance_validation.validate(bad_rows) if r["tenet"] == tenet)
        detected = result["status"] == governance_validation.FAIL
        proved += detected
        print(f"  T{tenet} inject {description}")
        print(f"       -> {result['status']:10s} {'(correctly rejected)' if detected else '(NOT DETECTED -- check is vacuous)'}")
    print(f"\n{proved}/{len(FALSIFIABILITY_CASES)} checks demonstrably reject their own falsifier.")
    print("Tenet 5 is not injectable (its falsifier is missing data, not a bad row) and is")
    print("excluded from this count rather than assumed.")
    return proved, len(FALSIFIABILITY_CASES)


def validation_report(rows):
    results = governance_validation.validate(rows)
    summary = governance_validation.summary(results)

    print("\n" + "=" * 78)
    print(f"NIST SP 800-207 Governance VALIDATION  ({len(rows)} audit rows)")
    print("=" * 78)
    print("Coverage above answers 'was this tenet TAGGED?'. This answers 'does the")
    print("claim HOLD?' -- each check below reads only the hash-chained audit log,")
    print("never live process state, and names the observation that would fail it.\n")

    for r in results:
        print(f"T{r['tenet']}  {r['status']:16s} {r['name']}")
        print(f"     claim     : {r['claim']}")
        print(f"     method    : {r['method']}")
        print(f"     fails if  : {r['falsifier']}")
        print(f"     evidence  : {r['evidence']}")
        print(f"     checked   : {r['checked']} rows, {r['violations']} violation(s)\n")

    print(f"VALIDATION RESULT: {summary['passed']}/{summary['total']} tenets validated "
          f"{summary['counts']}")
    if not summary["all_passed"]:
        print("A tenet that is not PASS is reported as-is rather than softened -- see its")
        print("evidence line for whether it FAILED or simply could not be tested by this window.")
    return summary


if __name__ == "__main__":
    main()
