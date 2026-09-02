# 08 — Module 7: Monitoring and Audit

> **AS-BUILT NOTE:** the hash chain and checkpoint design (Sections 2–3)
> are implemented exactly, including the two-step tamper test Section 3.2
> describes — verified live: editing one old row alone is caught by
> `verify_chain_integrity()`; editing a row AND recomputing every
> subsequent hash to stay internally consistent fools that check
> (expected) but is caught by `verify_against_checkpoints()` comparing
> against the separately-stored, separately-keyed checkpoint file
> (`data/checkpoint_log.jsonl`, `data/audit_key.bin`). **Found and fixed a
> real bug during this exact verification**: any evaluation/training
> script that redirects `audit_log.AUDIT_DB_PATH` to a throwaway database
> must also redirect `CHECKPOINT_STORE_PATH`/`AUDIT_KEY_PATH`, or its
> throwaway run's checkpoint writes silently pollute the real, shared
> checkpoint file with entries describing an unrelated database — this
> broke the live audit log's own tamper-detection on a completely
> untampered log the first time it was tested (see `SESSION_LOG.md`'s
> final entry). The audit schema carries `security_trust_score`,
> `process_trust_score`, `process_status`, `reason_category`, and
> `identity_targeting_count_60s` alongside the legacy `trust_score` column
> (kept as an alias of `security_trust_score` for backward compatibility).
> The live dashboard (`design/zero-trust-cps-command-center.html`, served
> live by `gateway.py` itself — see `gateway.py`'s Module 9
> extension section, `SESSION_LOG.md` §29/§30) shows the chain-verified
> indicator and the two independent score lines Section 4 below asks for.
> A Streamlit dashboard (`dashboard.py`) was found during real-hardware
> integration work to never have existed in the repo at all — Section 4
> below is stale with respect to that, kept only for its still-accurate
> panel-content requirements (Section 4.1), not as a description of what
> actually runs. `level2_dominant_feature`/`level2_summary` (this file's own
> Section 2 schema below already specified both) are now populated on
> every authenticated message, not placeholders — `src/explainability.py`,
> `docs/04_module3_trust_evaluation.md` Section C.
>
> **A second real bug found and fixed, this one architectural, not
> operational**: adding those two columns exposed that
> `verify_chain_integrity()` recomputes every row's hash from `SELECT *`
> — i.e. whatever columns exist NOW, not what existed when a given
> historical row was originally inserted. Adding a column (even one that
> backfills existing rows as NULL) therefore changes every pre-existing
> row's canonical JSON, and the chain check reports EVERY row broken,
> starting from row 1, immediately after the migration — not tampering,
> a schema-migration gap this design didn't originally account for.
> Fixed with a one-time re-baseline (recompute `this_hash`/`prev_hash` for
> every existing row and regenerate every checkpoint against the new
> schema, `RESULTS.md` Section 9 item 10) — required after ANY future
> column addition here, not just this one; a warning comment is now in
> `audit_log.py` itself so this doesn't silently repeat.

## 1. Purpose

Keep a tamper-evident, human-readable record of every decision the system makes, and provide both a live dashboard and a governance-alignment view mapped to NIST SP 800-207. SQLite by itself is just a database — nothing stops direct file access from silently editing old rows — so this module adds a hash chain on top specifically to make that kind of tampering detectable.

**Literature grounding:** [8] (blockchain-style tamper-evident logging with almost no added latency — the direct model for the hash chain here, scaled down appropriately for a single gateway), [24] (auditors need output organised around planning, verification, and reporting, not a raw log file).

### 1.1 Design Rationale — Why SQLite

SQLite requires zero setup (no separate database server process) while
still giving real SQL querying — the audit trail is genuinely inspectable
(`SELECT * FROM audit_log WHERE decision = 'BLOCK'`) rather than a flat
log file that needs parsing. The schema here is intentionally written to
be portable to PostgreSQL without changes, which is the natural upgrade
path for a scaled deployment (concurrent-write throughput is the main
reason to make that move — see Section 9's Failure Modes).

Two implementation details worth being explicit about wherever
`log_decision()`-equivalent code is written: use **parameterised queries**
(`?` placeholders), never string-formatted SQL — this isn't a style
preference, it's what prevents SQL injection via any field built from
device-influenced data (`reason`, `level2_summary`); and use **UTC
timestamps** in an unambiguous format — audit records that get compared
across systems or reviewed by someone in a different timezone need this,
and it matters most exactly when someone is trying to reconstruct an
incident timeline under pressure.

Module 7 is structurally the last step in the per-message pipeline (called
after every other module has produced its output) and is the one module
in the system that is purely a **sink** — nothing downstream of it feeds
back into the live per-message decision loop. Its outputs are consumed
asynchronously: by a human reviewing the dashboard, by an offline
governance-report generator, or as training data for Module 3's
meta-learner.

## 2. Audit Log Schema

```sql
CREATE TABLE audit_log (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             REAL NOT NULL,
    device_id             TEXT NOT NULL,
    seq                   INTEGER,
    security_trust_score   REAL NOT NULL,
    process_anomaly_score  REAL NOT NULL,
    decision               TEXT NOT NULL,       -- ALLOW | STEP_UP | ALERT | BLOCK
    level1_dominant_signal TEXT,                 -- from Module 3 Section C
    level1_contributions    TEXT,                 -- JSON-encoded dict
    level2_dominant_feature TEXT,
    level2_summary          TEXT,
    process_anomaly_status  TEXT NOT NULL,        -- FRESH | STALE (see Module 4, Section 2.2)
    reason                  TEXT,                 -- e.g. "silence_decay", "auth_failure", etc.
    prev_hash               TEXT NOT NULL,        -- hash of the previous row
    this_hash               TEXT NOT NULL         -- hash of this row (including prev_hash)
);

CREATE TABLE checkpoints (
    checkpoint_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                REAL NOT NULL,
    row_id_at_checkpoint      INTEGER NOT NULL,
    latest_chain_hash          TEXT NOT NULL,
    checkpoint_hmac              TEXT NOT NULL     -- signed with a separate audit key (Section 3.2)
);
-- NOTE: per Section 3.2, a copy of each checkpoint row should also be written
-- to a separate, more restrictively-permissioned store outside this database
-- file, not only to this table.
```

## 3. Hash Chain Computation

```
compute_row_hash(row_fields_excluding_this_hash: dict, prev_hash: str) -> str:
    canonical = json.dumps(row_fields_excluding_this_hash, sort_keys=True) + prev_hash
    return hashlib.sha256(canonical.encode()).hexdigest()

append_log_entry(fields: dict) -> None:
    prev_hash = get_last_row_hash() or "GENESIS"   # first row in the table chains to a fixed constant
    this_hash = compute_row_hash(fields, prev_hash)
    insert_row(fields, prev_hash=prev_hash, this_hash=this_hash)
```

### 3.1 Verification Procedure

```
verify_chain_integrity() -> (is_valid: bool, first_broken_row_id: int | None):
    rows = fetch_all_rows_in_order()
    expected_prev = "GENESIS"
    for row in rows:
        recomputed = compute_row_hash(row_fields_excluding_this_hash(row), expected_prev)
        if recomputed != row.this_hash:
            return (False, row.id)
        expected_prev = row.this_hash
    return (True, None)
```

Run this verification on a schedule (e.g., on dashboard load, and/or on a periodic background job) — its whole purpose is to make a silent edit to any past row detectable, so it needs to actually be run, not just be theoretically possible.

### 3.2 Why the Chain Alone Is Not Enough, and the Checkpoint Fix

The hash chain in Sections 2–3 detects tampering **as long as the attacker cannot also recompute every hash after the row they altered.** An attacker with full write access to the SQLite file can, in principle, edit an old row and then mechanically recompute every subsequent `this_hash`/`prev_hash` pair to make the chain internally consistent again — at which point `verify_chain_integrity()` would report `(True, None)` even though history has been rewritten. This is a real limitation of a pure in-database hash chain, and a full blockchain-style distributed ledger is well beyond what a project at this scale needs to solve it.

The practical fix is a periodic **checkpoint anchored outside the chain's own storage**:

```
CheckpointRecord (written every CHECKPOINT_INTERVAL_ROWS, default 100):
  checkpoint_id       : integer, increasing
  timestamp            : float
  row_id_at_checkpoint  : integer            # the audit_log.id this checkpoint covers up to
  latest_chain_hash      : string              # this_hash of that row
  checkpoint_hmac         : string (hex)        # HMAC-SHA256 over the three fields above,
                                                  # using a SEPARATE audit key — not any
                                                  # device's key, and not derived from the
                                                  # chain itself

create_checkpoint():
    if current_row_count % CHECKPOINT_INTERVAL_ROWS == 0:
        record = build_checkpoint_record(...)
        write_checkpoint(record, destination=CHECKPOINT_STORE)
        # CHECKPOINT_STORE must be a location an attacker who only compromises
        # the SQLite file cannot also silently rewrite — for a student project,
        # a separate append-only file on a different volume/permission set is
        # a reasonable, achievable target; periodically emailing/exporting the
        # checkpoint, or writing it to a separate small append-only log file
        # with stricter file permissions than the database, both work.
```

`verify_chain_integrity()` should be extended to also re-derive each stored checkpoint's HMAC using the separate audit key and confirm it matches both the stored value and the chain's actual state at `row_id_at_checkpoint`. If an attacker rewrites history *before* the most recent checkpoint and recomputes the in-database chain to stay internally consistent, the recomputed chain will no longer match the independently-stored checkpoint's `latest_chain_hash` — and that mismatch is what actually catches the attack this section exists to catch. This does not require a blockchain; it only requires that the checkpoint's storage and its audit key are kept separate from the database the checkpoint is protecting.

## 4. Dashboard (original design intent — see AS-BUILT note above for what actually runs)

### 4.1 Panels

```
1. Live Scores Panel
   - For each active device: current Security Trust Score and Process
     Anomaly Score, plotted as two separate time-series lines (never
     combined into one line — visually reinforcing the two-score design).

2. Audit Log Table
   - Scrollable, filterable (by device_id, by decision type, by time range).
   - A visible "chain verified ✓ / chain BROKEN at row N ✗" indicator,
     computed by calling verify_chain_integrity() on page load.

3. Governance Alignment View (Section 5)
   - The tenet-mapping table below, rendered directly from the audit log
     schema, not maintained as a separate hardcoded document.

4. Attack Matrix / Scenario Control Panel (simulation mode only)
   - Buttons or dropdowns to trigger each attack-matrix scenario from
     01_simulation_and_hardware_abstraction.md Section 4.3, for live
     demonstration purposes. This panel should not appear (or should be
     clearly disabled) once device_mode = hardware, since you cannot
     command a real ESP32 to fake an attack on itself.
```

## 5. NIST SP 800-207 Alignment Mapping

Stated explicitly, again, per the project synopsis: this is **alignment and traceability**, not certified compliance.

| NIST SP 800-207 Tenet (paraphrased) | Audit Log Field(s) That Provide Traceability |
|---|---|
| All data sources and computing services are considered resources | `device_id` (every resource is explicitly registered, Module 1) |
| All communication is secured regardless of network location | Module 6's TLS enforcement; implicitly evidenced by every log row existing at all (unencrypted traffic is never processed) |
| Access to individual resources is granted per-session/per-request | `decision` computed fresh per message (Module 5), never cached |
| Access is determined by dynamic policy, including behavioural attributes | `security_trust_score`, `process_anomaly_score`, `level1_dominant_signal` |
| The system monitors and measures the integrity/security posture of assets | `process_anomaly_score` and its sub-scores (Module 3) |
| All resource authentication/authorization is dynamic and strictly enforced before access | `decision` = BLOCK/STEP_UP rows, tied to specific `reason` values from Module 2 |
| The system collects information about assets, network traffic, and requests to improve security posture | The audit log itself, plus the hash chain proving it has not been silently altered |

## 6. Interface Contract

| Producer | What It Writes to the Log |
|----------|----------------------------|
| Module 5 | Every decision, with both scores and both explanation levels |
| Module 4 | Silence-decay events that cross a threshold |
| Module 2 | Step-up challenge issued / succeeded / failed events |

## 7. Configuration Parameters

```yaml
monitoring:
  db_path: "./data/audit.db"
  chain_verification_schedule_seconds: 300
  dashboard_refresh_seconds: 2
  checkpoint_interval_rows: 100
  checkpoint_store_path: "./data/checkpoints.log"   # deliberately separate from db_path;
                                                       # see Section 3.2 — this file should
                                                       # have stricter write permissions than
                                                       # the audit database itself
  audit_hmac_key_path: "./certs/audit_key.bin"        # generated once, never shared with any
                                                        # device's registry entry (Module 1)
```

## 8. Failure Modes

| Scenario | Behaviour | Note |
|---|---|---|
| Database file locked (concurrent write) | SQLite serialises writes; under heavy concurrent load this can introduce latency | Acceptable at this project's scale — would need PostgreSQL's proper concurrency control at production scale (Section 1.1) |
| Disk full / write failure | `log_decision()`'s insert raises, currently uncaught by that function itself | Should be wrapped in a try/except at the call site so a logging failure doesn't crash the whole gateway — "the audit system going down silently disables the audit system" is exactly the kind of failure a governance reviewer would flag; a real, open gap, not yet fixed |
| Table grows unbounded | No retention/archival policy exists | Worth stating explicitly as a limitation in any write-up rather than silently ignoring — a real deployment needs an archival/rotation strategy this starter kit does not implement |

## 9. Acceptance Criteria

- `verify_chain_integrity()` returns `(True, None)` on an untouched log.
- Manually editing one historical row's `decision` field directly in the SQLite file, then re-running verification, returns `(False, <that row's id>)`.
- **Sophisticated-tampering regression test (directly targeting the gap in Section 3.2):** manually edit an old row, then also manually recompute and rewrite every subsequent `prev_hash`/`this_hash` pair so the in-database chain is internally consistent again. Confirm that `verify_chain_integrity()` alone would now incorrectly report `(True, None)` — this is expected and is exactly why Section 3.2 exists — and then confirm that comparing the most recent stored `CheckpointRecord`'s `latest_chain_hash` (from the separate checkpoint store) against the recomputed chain correctly reveals the mismatch.
- The dashboard's two score lines are visibly independent (a physical-anomaly test scenario should show Process Anomaly Score spiking while Security Trust Score stays flat, and vice versa for a cyberattack scenario).
- The governance table maps at least five distinct NIST SP 800-207 tenets to specific, named audit-log fields.

Continue to `09_integration_and_data_flow.md`.
