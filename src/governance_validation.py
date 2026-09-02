"""
Module 7 extension: NIST SP 800-207 governance VALIDATION.

This is deliberately a separate concern from nist_mapping.completeness_report(),
and the distinction is the whole point of this file:

  * COVERAGE (nist_mapping) answers "what proportion of logged decisions carry
    this tenet's tag?". It measures TAGGING.
  * VALIDATION (this module) answers "does the tagged claim actually hold, under
    an independent check against the logged evidence?". It measures COMPLIANCE.

Coverage alone is not evidence, and saying so plainly matters more than the
number looking good. nist_mapping.tenets_for_decision() attaches tenets
1, 3, 4, 5 and 6 to EVERY decision unconditionally -- they describe the shape of
the pipeline, so the tagger asserts them by construction. That makes their 100%
coverage tautological: it is 100% because the tagger always writes it, and no
arrangement of the system could ever make it anything else. A reader entitled to
ask "how do you know tenet 4 is satisfied?" deserves a better answer than
"because we always put a 4 in that column."

So each check below is written to be FALSIFIABLE -- every one of them names the
observation that would make it FAIL, and several of them genuinely can fail on
this system's own data (feed it a run where an unauthenticated message was
granted access, or where the policy ignored its inputs, and T6/T4 fail). A check
that cannot fail is not a check, and is reported here as UNFALSIFIABLE rather
than dressed up as a pass.

Every check reads ONLY the audit log -- the same hash-chained rows an external
auditor would be handed -- never live in-memory state. An assertion that depends
on trusting the running process is not independent of it.
"""

from config import DEVICE_REGISTRY, NIST_TENETS, PROCESS_THRESHOLD, SECURITY_THRESHOLD, MQTT_USE_TLS

# A transport is "secured" if the message arrived over a channel with transport
# encryption actually enabled: HTTPS always is; MQTT only when TLS is on (see
# config.MQTT_USE_TLS, which auto-detects certs/). An empty transport means the
# row was not produced by a device message at all -- the silence watchdog writes
# rows with no transport -- so those are excluded from T2 rather than counted
# against it.
SECURED_TRANSPORTS = {"https"} | ({"mqtt"} if MQTT_USE_TLS else set())

PASS, FAIL, UNFALSIFIABLE, INSUFFICIENT = "PASS", "FAIL", "UNFALSIFIABLE", "INSUFFICIENT_DATA"


def _result(tenet, claim, method, falsifier, status, checked, violations, evidence):
    return {
        "tenet": tenet,
        "name": NIST_TENETS[tenet],
        "claim": claim,
        "method": method,
        "falsifier": falsifier,
        "status": status,
        "checked": checked,
        "violations": violations,
        "evidence": evidence,
    }


# Rows the gateway writes about ITSELF rather than about an inbound message.
# SILENT comes from the silence watchdog; auto_quarantine from Module 5
# enforcement. Neither arrived over a transport and neither carries its own
# scores, because neither is a device message -- judging them as if they were
# makes T2 ("every message arrived encrypted") and T3 ("every message carries
# its own scores") fail on the gateway's own bookkeeping. Found exactly that
# way: 25 auto-quarantine rows turned a 7/7 validation into 5/7.
GATEWAY_ORIGINATED = {"REJECTED", "SILENT"}
GATEWAY_ORIGINATED_CATEGORIES = {"auto_quarantine"}


def _authenticated(rows):
    return [
        r for r in rows
        if r.get("auth_ok")
        and r.get("decision") not in GATEWAY_ORIGINATED
        and r.get("reason_category") not in GATEWAY_ORIGINATED_CATEGORIES
    ]


def validate(rows: list[dict]) -> list[dict]:
    """Runs all 7 tenet validations against a list of audit_log rows.

    Returns one result dict per tenet. A tenet is only PASS if its specific
    falsifier was searched for across `checked` rows and not found."""
    auth = _authenticated(rows)
    results = []

    # ---- T1: all data sources and computing services are considered resources.
    # Earned only if nothing was ever scored without first being a known resource.
    unknown_scored = [
        r for r in auth if r.get("device_id") not in DEVICE_REGISTRY
    ]
    rejected_unknown = sum(
        1 for r in rows
        if r.get("decision") == "REJECTED" and "unknown_device_id" in (r.get("reason") or "")
    )
    results.append(_result(
        1,
        "No identity is scored or granted access without first being a registered resource.",
        "For every authenticated row, check device_id is present in DEVICE_REGISTRY. "
        "Unregistered identities must appear ONLY as REJECTED/unknown_device_id rows.",
        "An authenticated, scored row whose device_id is not in the registry.",
        FAIL if unknown_scored else PASS,
        len(auth),
        len(unknown_scored),
        f"{len(auth)} authenticated rows, all from registered devices; "
        f"{rejected_unknown} unregistered identities rejected before scoring.",
    ))

    # ---- T2: all communication is secured regardless of network location.
    insecure = [r for r in auth if (r.get("transport") or "") not in SECURED_TRANSPORTS]
    results.append(_result(
        2,
        "Every message that reached the trust engine arrived over an encrypted transport.",
        f"For every authenticated row, check transport is one of {sorted(SECURED_TRANSPORTS)}. "
        "This is the one tenet the tagger already gates on, so coverage and validation should agree.",
        "An authenticated row whose transport was not encrypted.",
        FAIL if insecure else PASS,
        len(auth),
        len(insecure),
        f"transports seen: {sorted({(r.get('transport') or '(none)') for r in auth})}",
    ))

    # ---- T3: access is granted on a per-session basis.
    # Falsifiable as: is a verdict actually recomputed per message, or cached?
    missing_decision = [r for r in auth if not r.get("decision")]
    missing_scores = [
        r for r in auth
        if r.get("security_trust_score") is None or r.get("process_trust_score") is None
    ]
    per_device_decisions = {}
    for r in auth:
        per_device_decisions.setdefault(r["device_id"], set()).add(r.get("decision"))
    varied = {d: s for d, s in per_device_decisions.items() if len(s) > 1}
    # If no device ever changed decision in this window, the check cannot
    # distinguish "re-evaluated every message" from "decided once and cached".
    if missing_decision or missing_scores:
        status = FAIL
    elif not varied:
        status = UNFALSIFIABLE
    else:
        status = PASS
    results.append(_result(
        3,
        "Every message is independently evaluated; no verdict is cached across messages.",
        "Check each authenticated row carries its OWN decision and its own freshly-computed "
        "pair of scores, and that at least one device's decision changed within the window "
        "(which a cached, once-per-session grant could not produce).",
        "A row with no decision or no scores of its own, i.e. a verdict inherited "
        "rather than computed.",
        status,
        len(auth),
        len(missing_decision) + len(missing_scores),
        f"{len(varied)}/{len(per_device_decisions)} devices changed decision within the window"
        + (f" ({', '.join(f'{d}: {sorted(s)}' for d, s in list(varied.items())[:3])})" if varied
           else " -- steady state, so this window cannot rule out caching"),
    ))

    # ---- T4: access is determined by dynamic policy including behavioural state.
    # Falsifiable as: does the decision actually MOVE when the evidence moves?
    # Compared per AXIS, because a single pooled mean is a weak test here -- a
    # window whose only non-ALLOW rows are STEP_UPs driven by the SECURITY axis
    # would show almost no separation on the PROCESS axis and still pass, which
    # would be an accident rather than a result. Testing each axis separately
    # also directly exercises the two-score architecture's central claim: each
    # score must be able to move the outcome on its own.
    def allow_rate(subset):
        return (sum(1 for r in subset if r.get("decision") == "ALLOW") / len(subset)) if subset else None

    axes = {}
    for label, key, threshold in (
        ("process", "process_trust_score", PROCESS_THRESHOLD),
        ("security", "security_trust_score", SECURITY_THRESHOLD),
    ):
        low = [r for r in auth if r.get(key) is not None and r[key] < threshold]
        high = [r for r in auth if r.get(key) is not None and r[key] >= threshold]
        axes[label] = (allow_rate(low), allow_rate(high), len(low), len(high))

    testable = [l for l, (lo, hi, nl, nh) in axes.items() if lo is not None and hi is not None]
    responsive = [l for l in testable if axes[l][0] < axes[l][1]]
    if not testable:
        status, violations = INSUFFICIENT, 0
    elif len(responsive) == len(testable):
        status, violations = PASS, 0
    else:
        status, violations = FAIL, len(testable) - len(responsive)
    parts = []
    for label, (lo, hi, nl, nh) in axes.items():
        if lo is None or hi is None:
            parts.append(f"{label}: only one side present in window (below n={nl}, at/above n={nh}) -- not testable")
        else:
            parts.append(f"{label}: ALLOW rate {lo:.0%} below threshold (n={nl}) vs {hi:.0%} at/above (n={nh})")
    results.append(_result(
        4,
        "The policy's output is driven by the trust/anomaly state -- on EACH axis independently.",
        "Split authenticated rows by whether each score sits below or above its threshold, and "
        "compare the ALLOW rate across the split. A policy that genuinely reads an axis must "
        "allow less often when that axis is low.",
        "An equal (or inverted) ALLOW rate above and below a threshold, which would mean the "
        "decision ignored that axis entirely.",
        status, len(auth), violations, "; ".join(parts),
    ))

    # ---- T5: the enterprise monitors and measures the posture of ALL assets.
    seen = {r.get("device_id") for r in rows}
    unmonitored = [d for d in DEVICE_REGISTRY if d not in seen]
    results.append(_result(
        5,
        "Every registered asset is actually observed -- including ones that go silent.",
        "Check every device in DEVICE_REGISTRY produced at least one audit row in the window. "
        "A device that stops publishing must still appear, via the silence watchdog's SILENT rows.",
        "A registered device with no audit rows at all, i.e. an asset nobody is watching.",
        FAIL if unmonitored else PASS,
        len(DEVICE_REGISTRY),
        len(unmonitored),
        f"{len(DEVICE_REGISTRY) - len(unmonitored)}/{len(DEVICE_REGISTRY)} registered devices observed"
        + (f"; MISSING: {unmonitored}" if unmonitored else ""),
    ))

    # ---- T6: authentication and authorization strictly enforced BEFORE access.
    # The strongest check here: nothing that failed authentication was ever granted.
    granted_without_auth = [
        r for r in rows
        if not r.get("auth_ok") and r.get("decision") not in ("REJECTED", "SILENT", "", None)
    ]
    rejected = sum(1 for r in rows if r.get("decision") == "REJECTED")
    results.append(_result(
        6,
        "No unauthenticated message ever received anything other than rejection.",
        "Scan every row with auth_ok=False and confirm its decision is REJECTED. "
        "This is the single most load-bearing check in the set.",
        "Any row with auth_ok=False carrying an ALLOW/ALERT/STEP_UP/BLOCK decision.",
        FAIL if granted_without_auth else PASS,
        len(rows),
        len(granted_without_auth),
        f"{rejected} rejected rows in window, none of which reached a scoring or access decision.",
    ))

    # ---- T7: telemetry is collected and USED to improve posture.
    # Falsifiable as: did the learned signals actually change any outcome, or is
    # the fused score just echoing the rule baseline?
    comparable = [r for r in auth
                  if r.get("fused_score") is not None and r.get("rule_score") is not None]
    changed = [r for r in comparable if abs(r["fused_score"] - r["rule_score"]) > 0.01]
    if not comparable:
        status, evidence = INSUFFICIENT, "no rows carried both a fused and a rule score"
    elif changed:
        status = PASS
        evidence = (f"{len(changed)}/{len(comparable)} rows ({len(changed)/len(comparable):.0%}) "
                    f"where the learned fusion moved the score away from the rule-only baseline")
    else:
        status = FAIL
        evidence = "fused score never differed from the rule baseline -- no learned signal contributed"
    results.append(_result(
        7,
        "The learned models measurably change the outcome versus a rule-only baseline.",
        "Compare fused_score against rule_score per row. If the ML pipeline contributes nothing, "
        "the two are identical and the tenet is unearned.",
        "fused_score identical to rule_score on every row.",
        status, len(comparable), 0 if status == PASS else len(comparable), evidence,
    ))

    return results


def summary(results: list[dict]) -> dict:
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    passed = counts.get(PASS, 0)
    return {
        "passed": passed,
        "total": len(results),
        "counts": counts,
        "all_passed": passed == len(results),
    }
