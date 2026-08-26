"""
Module 7: Monitoring & Audit Logging.

Every trust score and access decision is written here. This table is the
artefact Report Section 7.3 calls "governance evidence" -- `nist_tenets`
(comma-separated tenet numbers, see nist_mapping.py) is what turns that
from a claim into a computable metric: the synopsis's Section 10.1
"governance completeness" evaluation metric is a query over this column.
"""

import sqlite3
import os
from datetime import datetime, timezone

from config import AUDIT_DB_PATH


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
    # rather than requiring users to delete data/audit_log.db. anomaly_score
    # is Phase 6a's Isolation Forest score (kept under its original name for
    # backward compatibility); lstm_score/gnn_score/fused_score/policy_source
    # are Phase 6b/6c/7/8.
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
        # Full per-signal SHAP breakdown (fusion_engine.py's FusionEngine.last_shap)
        # -- previously only the single top-contributing feature's SHAP value
        # was kept anywhere (embedded in `reason`'s text); these four columns
        # persist all of them, so the dashboard can show every signal's real
        # SHAP contribution instead of "--" for the three non-top ones. NULL
        # on rows logged before this column existed, or on any row where the
        # fusion model wasn't trained yet (see FusionEngine.combine()).
        ("shap_rule", "REAL"),
        ("shap_isolation_forest", "REAL"),
        ("shap_lstm_ae", "REAL"),
        ("shap_gnn", "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE audit_log ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


def log_decision(
    device_id: str,
    auth_ok: bool,
    trust_score: float,
    decision: str,
    reason: str = "",
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
):
    shap = shap or {}
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.execute(
        "INSERT INTO audit_log "
        "(timestamp, device_id, auth_ok, trust_score, decision, reason, anomaly_score, lstm_score, gnn_score, fused_score, policy_source, confidence, nist_tenets, transport, rule_score, "
        "shap_rule, shap_isolation_forest, shap_lstm_ae, shap_gnn) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            device_id,
            int(auth_ok),
            trust_score,
            decision,
            reason,
            if_score,
            lstm_score,
            gnn_score,
            fused_score,
            policy_source,
            confidence,
            nist_tenets,
            transport,
            rule_score,
            shap.get("rule_score"),
            shap.get("isolation_forest_score"),
            shap.get("lstm_ae_score"),
            shap.get("gnn_score"),
        ),
    )
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
