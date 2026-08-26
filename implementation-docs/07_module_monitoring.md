# Module 7 — Monitoring & Audit Logging

**Status:** Core implemented (SQLite, `src/audit_log.py`) + Dashboard/governance-mapping design (extension)
**Report grounding:** Section 4.3 Module 7, Section 7.3; literature refs [25], [26]

## Purpose

Module 7 is where this system's IT-governance claim either becomes real or
stays a slogan. Every decision every other module makes is ephemeral unless
it's recorded somewhere that can be queried, reviewed, and mapped back to a
governance standard after the fact. Reference [25] makes the underlying
problem explicit: resource-constrained devices structurally cannot maintain
their own audit trails — which is exactly why this system generates the
audit record at the **gateway**, not on the devices themselves.

## Design Rationale

SQLite was chosen for the starter kit specifically because it requires zero
setup (no separate database server process), while still giving you real
SQL querying — meaning the audit trail is genuinely inspectable (`SELECT *
FROM audit_log WHERE decision = 'DENY'`) rather than just a flat log file
you'd need to parse. For a scaled deployment, Report Section 8.2 specifies
PostgreSQL as the natural upgrade path — the schema below is intentionally
written to be portable to that without changes.

## Data Structure

```python
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    device_id TEXT NOT NULL,
    auth_ok INTEGER NOT NULL,
    trust_score REAL NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT
)
```

Every column corresponds directly to an output of an earlier module:

| Column | Source module | Why it's here |
|---|---|---|
| `timestamp` | — | Every audit record needs a "when," non-negotiably, for any compliance review |
| `device_id` | Module 1 | Which identity this record concerns |
| `auth_ok` | Module 2 | Was the identity claim actually verified |
| `trust_score` | Module 3 | The behavioural judgement at this point in time |
| `decision` | Module 5 | What was actually enforced |
| `reason` | Module 3 | Why — this is the field that becomes a SHAP reason code once Module 3's fusion engine (Part B) is in place |

## Implementation Walkthrough

```python
# src/audit_log.py
def log_decision(device_id, auth_ok, trust_score, decision, reason=""):
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.execute(
        "INSERT INTO audit_log (timestamp, device_id, auth_ok, trust_score, decision, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), device_id, int(auth_ok), trust_score, decision, reason),
    )
    conn.commit()
    conn.close()
```

Two details worth calling out:

- **Parameterised query (`?` placeholders), not string formatting.** This
  isn't a style preference — it's what prevents SQL injection if any of
  these values were ever attacker-influenced (and `reason`, built from
  device data, plausibly could be, once you're constructing it from
  message content rather than fixed strings).
- **UTC timestamps, ISO 8601 format.** Audit records that will ever be
  compared across systems, correlated with other logs, or reviewed by
  someone in a different timezone need an unambiguous timestamp format —
  this is a small detail that matters a great deal the first time you
  actually need to reconstruct an incident timeline.

`log_decision()` is called exactly once per message, from
`gateway.on_message()`, **after** every other module has produced its
output for that message — Module 7 is structurally the last step in the
per-message pipeline, which is why it has visibility into every other
module's result.

## Interface Contract

| Direction | Data | From |
|---|---|---|
| In | `device_id`, `auth_ok`, `trust_score`, `decision`, `reason` | Modules 1 (via device_id), 2, 3, 5 |
| Out (query) | Rows via `recent(limit)` | Consumed by: a human reviewing the console/database directly now; a dashboard (extension); a governance-mapping report generator (extension) |

Module 7 is the one module in this system that is purely a **sink** in the
real-time pipeline — nothing downstream of it feeds back into the live
per-message decision loop. Its outputs are consumed asynchronously, by
humans or by offline processes (training data for Module 3's meta-learner,
governance reports), not by another module's real-time logic.

## Extension Path

### 1. Governance / NIST SP 800-207 tenet mapping

Add a mapping table and a query that expresses the same audit data in
compliance terms:

```python
NIST_TENET_MAP = {
    "auth_ok":     "Tenet 3 -- All resource authentication is dynamic and strictly enforced",
    "trust_score": "Tenet 2 -- Trust is never granted implicitly; access is per-session, evaluated continuously",
    "decision":    "Tenet 5 -- Access control is enforced consistently, resource-by-resource",
}

def governance_report(limit=100):
    rows = recent(limit)
    return [
        {**row, "tenets_evidenced": [v for k, v in NIST_TENET_MAP.items() if k in row]}
        for row in rows
    ]
```

This turns the raw audit table into a document you can literally hand to a
compliance reviewer, with every row explicitly labelled against the
standard your report is built around (Report Section 7.3).

### 2. Live dashboard

```python
import streamlit as st
import pandas as pd
import time
import audit_log

st.title("Zero-Trust CPS — Live Monitoring")
placeholder = st.empty()

while True:
    rows = audit_log.recent(50)
    df = pd.DataFrame(rows)
    with placeholder.container():
        st.dataframe(df)
        if not df.empty:
            st.line_chart(df.pivot_table(index="timestamp", columns="device_id", values="trust_score"))
    time.sleep(2)
```

Run with `streamlit run dashboard.py`. This is a genuinely small amount of
code for a large improvement in how demoable the system is — save it for
last (Report Section 9, Phase 9) once there's real, varied data flowing
through the audit log to visualise.

### 3. Retention and integrity

For a real deployment, two things this starter kit does not address are
worth flagging explicitly in your report's limitations section rather than
silently ignoring:

- **Retention policy** — the table grows unbounded; a real system needs an
  archival/rotation strategy.
- **Tamper-evidence** — nothing currently stops someone with direct
  database access from editing past audit rows. A hash-chained log (each
  row includes a hash of the previous row) is the standard mitigation, and
  is a legitimate, scoped addition if your report's governance angle needs
  to address audit-log integrity, not just audit-log existence.

## Failure Modes

| Scenario | Behaviour | Note |
|---|---|---|
| Database file locked (concurrent write) | SQLite serialises writes; under heavy concurrent load this can introduce latency | Acceptable at this project's scale; would need PostgreSQL's proper concurrency control at production scale |
| Disk full / write failure | `log_decision()` will raise an exception, currently uncaught | Should be wrapped in a try/except in `gateway.on_message()` so a logging failure doesn't crash the entire gateway — a real gap worth fixing, since "the audit system going down silently disables the audit system" is exactly the kind of failure a governance reviewer would flag |
