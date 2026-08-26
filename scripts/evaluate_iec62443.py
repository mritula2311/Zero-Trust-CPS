"""
CLAUDE.md Section 6/10: "its zones-and-conduits security model maps
naturally onto this project's Layer 1/2/3 architecture, and its
security-level concept (SL 1-4) gives you a vocabulary..." / "A NIST SP
800-207 + IEC 62443 tenet-mapping table generated from the audit log."

Standalone, paper-ready version of iec62443_mapping's report -- zones,
conduits, Foundational Requirements coverage (computed from the live
audit log where applicable, honestly marked not-implemented where FR5/FR7
genuinely aren't), and the SL-2 security-level self-assessment with its
reasoning. Run alongside scripts/evaluate_governance.py (NIST's half of
the same combined deliverable) for the full picture.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import audit_log
import iec62443_mapping


def main():
    rows = audit_log.recent(10_000)
    if not rows:
        raise SystemExit("audit_log.db is empty -- run the gateway + a telemetry source first.")
    iec62443_mapping.print_report(rows)


if __name__ == "__main__":
    main()
