"""
Module 7: Monitoring & Audit Logging.

Every trust score and access decision is written here. This table is the
artefact Report Section 7.3 calls "governance evidence" -- `nist_tenets`
(comma-separated tenet numbers, see nist_mapping.py) is what turns that
from a claim into a computable metric.

TWO-SCORE REARCHITECTURE: `security_trust_score` and `process_trust_score`
(+ `process_status`) are the new primary fields. The legacy `trust_score`
column (kept, still NOT NULL, for any older tooling that reads it) is
populated with `security_trust_score` on every new row -- not a real third
score, just a backward-compatible alias.

HASH CHAIN + CHECKPOINTS (docs/08_module7_monitoring_and_audit.md Section
3): SQLite by itself is just a database -- nothing stops direct file access
from silently editing an old row. `prev_hash`/`this_hash` make that
detectable via verify_chain_integrity(). That alone only catches an
attacker who does NOT also recompute every subsequent hash after the row
they edited -- one who does both leaves the in-DB chain internally
consistent. The checkpoint file (CHECKPOINT_STORE_PATH, deliberately a
SEPARATE file from this database, HMAC'd with a separate key that is never
shared with any device's registry entry) is what catches that more
sophisticated case: comparing the most recent checkpoint's stored hash
against the current chain state at that row reveals the mismatch even when
the in-DB chain alone would report clean. See verify_against_checkpoints().
"""

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

from config import AUDIT_DB_PATH, CHECKPOINT_INTERVAL_ROWS, CHECKPOINT_STORE_PATH, AUDIT_KEY_PATH

GENESIS_HASH = "GENESIS"

# The hash chain's read-then-insert (get last row's this_hash -> compute this
# row's hash against it -> INSERT) must be atomic: log_decision() is called
# from several threads at once in a live gateway (the MQTT loop, the HTTPS
# second transport in coap_server.py, and the silence watchdog -- see
# gateway.py's run()). Without this lock two concurrent callers can read the
# SAME prev_hash before either inserts, forking the chain into two rows that
# both point at the same predecessor -- verify_chain_integrity() then reports
# a false BROKEN even though nothing was tampered with. SQLite's file lock
# serializes the INSERTs themselves but NOT the preceding read, so it cannot
# prevent this on its own.
_chain_lock = threading.Lock()


def init_db():
    os.makedirs(os.path.dirname(AUDIT_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            device_id TEXT NOT NULL,
            auth_ok INTEGER NOT NULL,
            trust_score REAL NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT
        )
    """)
    # Columns added after the initial release -- migrate older DBs in place
    # rather than requiring users to delete data/audit_log.db.
    #
    # REAL GOTCHA, found and fixed live (not hypothetical -- see
    # SESSION_LOG.md's Level-2 explainability entry): _row_hash_fields()
    # builds its hash input from `SELECT *`, i.e. WHATEVER COLUMNS EXIST
    # NOW, not the columns that existed when a given historical row was
    # originally inserted and hashed. Adding a column here via ALTER TABLE
    # (even though it backfills existing rows with NULL) therefore changes
    # every pre-existing row's canonical JSON -- verify_chain_integrity()
    # will report EVERY historical row as broken, starting from row 1,
    # immediately after any such migration, purely from the new NULL
    # column being included in the recomputed hash. This is not tampering
    # and not a real integrity failure -- but a one-time re-baseline
    # (recompute this_hash/prev_hash for every existing row against the
    # NEW schema, then regenerate every checkpoint the same way) is
    # required after adding a column here, or verify_chain_integrity()/
    # verify_against_checkpoints() will both report false positives against
    # every row from before the migration. Do this once, immediately after
    # adding a column, before any real tampering-detection reliance on the
    # chain resumes.
    for column, coltype in [
        ("anomaly_score", "REAL"),
        ("lstm_score", "REAL"),
        ("gnn_score", "REAL"),
        ("fused_score", "REAL"),
        ("policy_source", "TEXT"),
        ("confidence", "REAL"),
        ("nist_tenets", "TEXT"),
        ("transport", "TEXT"),
        ("rule_score", "REAL"),
        ("shap_rule", "REAL"),
        ("shap_isolation_forest", "REAL"),
        ("shap_lstm_ae", "REAL"),
        ("shap_gnn", "REAL"),
        # Two-score rearchitecture (see module docstring).
        ("security_trust_score", "REAL"),
        ("process_trust_score", "REAL"),
        ("process_status", "TEXT"),
        ("reason_category", "TEXT"),           # "" for normal decisions; "identity_targeting",
                                                 # "silence_decay", "step_up" etc. otherwise
        ("identity_targeting_count_60s", "INTEGER"),
        # Two-Level Explainability, Level 2 (Module 3 Section C.3/C.4) --
        # which raw feature/node within the Level-1-dominant signal
        # actually drove it, per src/explainability.py.
        ("level2_dominant_feature", "TEXT"),
        ("level2_summary", "TEXT"),
        # Hash chain (Module 7 Section 3).
        ("prev_hash", "TEXT"),
        ("this_hash", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE audit_log ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            row_id_at_checkpoint INTEGER NOT NULL,
            latest_chain_hash TEXT NOT NULL,
            checkpoint_hmac TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _get_audit_key() -> bytes:
    """Separate key from any device's HMAC secret (config.DEVICE_REGISTRY)
    -- generated once, locally, gitignored, never transmitted anywhere."""
    if os.path.exists(AUDIT_KEY_PATH):
        with open(AUDIT_KEY_PATH, "rb") as f:
            return f.read()
    os.makedirs(os.path.dirname(AUDIT_KEY_PATH), exist_ok=True)
    key = os.urandom(32)
    with open(AUDIT_KEY_PATH, "wb") as f:
        f.write(key)
    return key


def _row_hash_fields(row: dict) -> dict:
    """The exact set of fields the hash covers -- everything except the
    hash columns themselves and the autoincrement id (id is positional/
    implied by chain order, not signed content)."""
    return {k: v for k, v in row.items() if k not in ("id", "prev_hash", "this_hash")}


def compute_row_hash(row_fields_excluding_hash: dict, prev_hash: str) -> str:
    canonical = json.dumps(row_fields_excluding_hash, sort_keys=True, default=str) + prev_hash
    return hashlib.sha256(canonical.encode()).hexdigest()


def _get_last_row_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row and row[0] else GENESIS_HASH


def _maybe_write_checkpoint(conn: sqlite3.Connection, row_id: int, this_hash: str) -> None:
    if row_id % CHECKPOINT_INTERVAL_ROWS != 0:
        return
    key = _get_audit_key()
    ts = datetime.now(timezone.utc).timestamp()
    payload = json.dumps({"row_id_at_checkpoint": row_id, "latest_chain_hash": this_hash}, sort_keys=True)
    checkpoint_hmac = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    conn.execute(
        "INSERT INTO checkpoints (timestamp, row_id_at_checkpoint, latest_chain_hash, checkpoint_hmac) "
        "VALUES (?, ?, ?, ?)",
        (ts, row_id, this_hash, checkpoint_hmac),
    )
    # Written to a genuinely SEPARATE file, not just a separate table in the
    # same database -- an attacker with write access to audit_log.db's file
    # does not necessarily also have write access here. Append-only (never
    # rewritten), one JSON line per checkpoint.
    os.makedirs(os.path.dirname(CHECKPOINT_STORE_PATH), exist_ok=True)
    with open(CHECKPOINT_STORE_PATH, "a") as f:
        f.write(json.dumps({
            "timestamp": ts, "row_id_at_checkpoint": row_id,
            "latest_chain_hash": this_hash, "checkpoint_hmac": checkpoint_hmac,
        }) + "\n")


def log_decision(
    device_id: str,
    auth_ok: bool,
    decision: str,
    reason: str = "",
    security_trust_score: float | None = None,
    process_trust_score: float | None = None,
    process_status: str = "",
    if_score: float | None = None,
    lstm_score: float | None = None,
    gnn_score: float | None = None,
    fused_score: float | None = None,
    policy_source: str = "",
    confidence: float | None = None,
    nist_tenets: str = "",
    transport: str = "",
    rule_score: float | None = None,
    shap: dict[str, float] | None = None,
    reason_category: str = "",
    identity_targeting_count_60s: int | None = None,
    level2_dominant_feature: str = "",
    level2_summary: str = "",
):
    shap = shap or {}
    # trust_score (legacy, NOT NULL) is populated as an alias of
    # security_trust_score -- see module docstring. Rejected-attempt rows
    # (reason_category="identity_targeting") still pass the claimed
    # device's LAST KNOWN security trust here (untouched by the rejection
    # itself, per the attribution fix) rather than leaving it null.
    trust_score_alias = security_trust_score if security_trust_score is not None else 0.0

    conn = sqlite3.connect(AUDIT_DB_PATH)
    fields = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_id": device_id,
        "auth_ok": int(auth_ok),
        "trust_score": trust_score_alias,
        "decision": decision,
        "reason": reason,
        "anomaly_score": if_score,
        "lstm_score": lstm_score,
        "gnn_score": gnn_score,
        "fused_score": fused_score,
        "policy_source": policy_source,
        "confidence": confidence,
        "nist_tenets": nist_tenets,
        "transport": transport,
        "rule_score": rule_score,
        "shap_rule": shap.get("rule_score"),
        "shap_isolation_forest": shap.get("isolation_forest_score"),
        "shap_lstm_ae": shap.get("lstm_ae_score"),
        "shap_gnn": shap.get("gnn_score"),
        "security_trust_score": security_trust_score,
        "process_trust_score": process_trust_score,
        "process_status": process_status,
        "reason_category": reason_category,
        "identity_targeting_count_60s": identity_targeting_count_60s,
        "level2_dominant_feature": level2_dominant_feature,
        "level2_summary": level2_summary,
    }
    columns = list(fields.keys()) + ["prev_hash", "this_hash"]
    placeholders = ",".join("?" for _ in columns)

    # Read the predecessor's hash, chain onto it, and INSERT as one atomic
    # unit -- see _chain_lock's definition above for why the read cannot be
    # left outside the lock.
    with _chain_lock:
        prev_hash = _get_last_row_hash(conn)
        this_hash = compute_row_hash(fields, prev_hash)
        cur = conn.execute(
            f"INSERT INTO audit_log ({','.join(columns)}) VALUES ({placeholders})",
            [*fields.values(), prev_hash, this_hash],
        )
        row_id = cur.lastrowid
        _maybe_write_checkpoint(conn, row_id, this_hash)
        conn.commit()
    conn.close()


def recent(limit: int = 20):
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def verify_chain_integrity(after_row_id: int = 0, anchor_hash: str = GENESIS_HASH) -> tuple[bool, int | None]:
    """Recomputes every row's hash from its stored fields and compares
    against this_hash. Detects a naive edit (a row changed but the chain
    NOT recomputed afterward) -- see verify_against_checkpoints() for the
    sophisticated-tampering case this alone cannot catch.

    Called with no arguments this is a full scan from the genesis hash, which
    is O(total rows) and therefore grows without bound. `after_row_id` /
    `anchor_hash` let a caller verify only the tail of the chain, starting from
    a hash it already trusts -- see verify_chain_incremental(), which is the
    safe way to use this and explains why the anchor must be a CHECKPOINT
    rather than any arbitrary previously-seen row."""
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE id > ? ORDER BY id ASC", (after_row_id,)
    ).fetchall()
    conn.close()
    expected_prev = anchor_hash
    for row in rows:
        row_dict = dict(row)
        recomputed = compute_row_hash(_row_hash_fields(row_dict), expected_prev)
        if recomputed != row_dict.get("this_hash"):
            return False, row_dict["id"]
        expected_prev = row_dict["this_hash"]
    return True, None


def latest_checkpoint() -> dict | None:
    """The newest checkpoint record, or None if none has been written yet."""
    if not os.path.exists(CHECKPOINT_STORE_PATH):
        return None
    newest = None
    with open(CHECKPOINT_STORE_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cp = json.loads(line)
            if newest is None or cp["row_id_at_checkpoint"] > newest["row_id_at_checkpoint"]:
                newest = cp
    return newest


def verify_chain_incremental() -> tuple[bool, int | None, int]:
    """Fast TAIL check: re-verifies only the rows written since the newest
    checkpoint, in O(rows since that checkpoint) instead of O(all rows).
    Returns (ok, first_broken_row_id, rows_scanned).

    READ THIS BEFORE USING IT AS A SUBSTITUTE FOR verify_chain_integrity().
    It is not one. Measured against two concrete attacks on a copy of a real
    39k-row log:

      | attack                                   | full scan | checkpoints | this |
      |------------------------------------------|-----------|-------------|------|
      | naive edit of an old row, hashes untouched | DETECTED  | missed      | missed |
      | old row edited AND all hashes recomputed   | missed    | DETECTED    | missed |

    The reason it misses the naive edit is structural, not a bug here: editing
    a row's fields without recomputing its this_hash leaves every STORED hash
    after it mutually consistent, so nothing downstream of the edit looks
    wrong. Only recomputing that row's own hash from its fields exposes it --
    which is what the full scan does and what any tail check, by definition,
    skips.

    Checkpoints do not cover it either, and it is worth being precise about
    why, because it is easy to assume they do: a checkpoint attests the chain
    hash VALUE at a row boundary, comparing stored against stored. It catches
    a consistent rewrite (every hash recomputed, so the values move) but not a
    naive edit (no hash moved at all).

    So the correct usage is all three together, with different periods:
      * this, on every poll -- continuous coverage of the newest rows;
      * verify_chain_integrity(), periodically -- the only thing that catches a
        naive edit anywhere in history, and the detection latency for that
        attack is exactly the interval you choose;
      * verify_against_checkpoints(), periodically -- the only thing that
        catches a fully consistent rewrite.
    gateway.py wires exactly that, and reports when the last full scan ran so
    the bound is visible rather than implied."""
    cp = latest_checkpoint()
    if cp is None:
        ok, broken = verify_chain_integrity()
        return ok, broken, _row_count()
    ok, broken = verify_chain_integrity(
        after_row_id=cp["row_id_at_checkpoint"], anchor_hash=cp["latest_chain_hash"]
    )
    return ok, broken, max(0, _row_count() - cp["row_id_at_checkpoint"])


def _row_count() -> int:
    conn = sqlite3.connect(AUDIT_DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    return n


def verify_against_checkpoints() -> tuple[bool, str | None]:
    """The check that actually catches an attacker who edited an old row
    AND recomputed every subsequent prev_hash/this_hash to stay internally
    consistent -- verify_chain_integrity() alone would report clean in that
    case. Re-derives each stored checkpoint's HMAC with the separate audit
    key and confirms it matches both the checkpoint file's own record and
    the CURRENT chain's actual hash at that row_id; a mismatch means
    history was rewritten before that checkpoint."""
    if not os.path.exists(CHECKPOINT_STORE_PATH):
        return True, None
    key = _get_audit_key()
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row

    with open(CHECKPOINT_STORE_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cp = json.loads(line)
            payload = json.dumps(
                {"row_id_at_checkpoint": cp["row_id_at_checkpoint"], "latest_chain_hash": cp["latest_chain_hash"]},
                sort_keys=True,
            )
            expected_hmac = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hmac, cp["checkpoint_hmac"]):
                conn.close()
                return False, f"checkpoint at row {cp['row_id_at_checkpoint']} has an invalid HMAC (checkpoint file itself tampered)"

            row = conn.execute("SELECT this_hash FROM audit_log WHERE id = ?", (cp["row_id_at_checkpoint"],)).fetchone()
            if row is None:
                conn.close()
                return False, f"row {cp['row_id_at_checkpoint']} referenced by a checkpoint no longer exists"
            if row["this_hash"] != cp["latest_chain_hash"]:
                conn.close()
                return False, (
                    f"row {cp['row_id_at_checkpoint']}'s current chain hash does not match the "
                    f"independently-stored checkpoint -- history was rewritten before this checkpoint"
                )
    conn.close()
    return True, None
