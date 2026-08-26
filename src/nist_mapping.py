"""
Module 7 extension: NIST SP 800-207 tenet mapping (synopsis Sections
4.3/7.3/10.1). The synopsis calls this a PRIMARY deliverable -- "proportion
of tenets for which the system produces a traceable, logged artefact" is
one of the report's named evaluation metrics (Section 10.1), not a
discussion point. This module decides, per message, which of the 7 tenets
(config.NIST_TENETS) that specific decision is evidence for, so
audit_log.log_decision() can store it and dashboard.py / a governance
report can compute real completeness numbers rather than assert them.
"""

from config import NIST_TENETS


def tenets_for_decision(auth_ok: bool, transport_secured: bool, fusion_trained: bool) -> str:
    """Returns a comma-separated string of tenet numbers (matching
    config.NIST_TENETS' keys) this specific decision is evidence for.

    - Tenet 1 (resources), 3 (per-session), 4 (dynamic policy), 5 (monitor),
      6 (auth enforced before access) apply to EVERY decision -- they
      describe the shape of the pipeline itself (Module 1 lookup -> Module
      2 auth -> Module 3/4 continuous trust -> Module 5 dynamic decision ->
      Module 7 logs it), which runs identically whether this particular
      message passed or failed.
    - Tenet 2 (secured communication) only applies if THIS message actually
      arrived over a secured transport -- claiming it unconditionally while
      plain MQTT is still the default would misrepresent the system's own
      current state (see docs/03_add_tls.md).
    - Tenet 7 (telemetry improves posture) only applies once the fusion
      engine is trained -- before that, decisions are the rule-based
      fallback and no learned signal was contributing.
    """
    tenets = {1, 3, 4, 5, 6}
    if transport_secured:
        tenets.add(2)
    if fusion_trained:
        tenets.add(7)
    return ",".join(str(t) for t in sorted(tenets))


def completeness_report(rows: list[dict]) -> dict:
    """Given a list of audit_log rows (each with a 'nist_tenets' string
    field), returns {tenet_number: coverage_fraction} -- the "governance
    completeness" metric the synopsis's Section 10.1 evaluation plan names
    explicitly. Used by dashboard.py's governance view."""
    if not rows:
        return {t: 0.0 for t in NIST_TENETS}
    counts = {t: 0 for t in NIST_TENETS}
    for row in rows:
        tenet_str = row.get("nist_tenets") or ""
        for part in tenet_str.split(","):
            part = part.strip()
            if part.isdigit():
                counts[int(part)] = counts.get(int(part), 0) + 1
    total = len(rows)
    return {t: counts.get(t, 0) / total for t in NIST_TENETS}
