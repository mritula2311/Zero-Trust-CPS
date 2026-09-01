"""
Module 3 Section C — Two-Level Explainability, orchestration layer.

Level 1 (fusion_engine.py's SHAP over the 4 sub-scores) was already
implemented before this file existed. This implements Level 2 (Section
C.3): given which signal Level 1 named as dominant, drill into which raw
feature/node WITHIN that signal actually drove it. Lives here, not inside
fusion_engine.py, because Level 2 needs the individual scorer instances
(rule/Isolation Forest/LSTM-AE/GNN, and the Transformer ablation
candidate) that fusion_engine.py deliberately doesn't hold references to
-- FusionEngine only ever sees their 4 output SCORES, keeping its own job
(fusing scores) separate from explaining them. gateway.py already holds
every scorer instance, so it calls level2_explain() below right after
fusion_engine.combine() returns, using fusion_engine.last_shap to know
which signal was dominant.
"""


def level2_explain(
    dominant_signal: str,
    device_id: str,
    feature_vec: list | None,
    rule_reason: str,
    if_scorer,
    lstm_scorer,
    gnn_scorer,
    transformer_scorer=None,
) -> tuple[str, str]:
    """Returns (level2_dominant_feature, level2_summary) per Section C.4's
    TwoLevelExplanation. `dominant_signal` is one of
    fusion_engine.FEATURE_NAMES ("rule_score", "isolation_forest_score",
    "lstm_ae_score", "gnn_score") -- Level 1's argmax(abs(shap_value)).
    `transformer_score` is accepted too (not currently reachable from live
    fusion output, since the Transformer isn't one of fusion_engine.py's
    inputs -- see docs/04_module3_trust_evaluation.md Section B.5b -- but
    kept as a real branch, not a stub, so wiring it into live fusion later
    needs no change here)."""
    if dominant_signal == "rule_score":
        # Trivial per Section C.3 -- the rule score already IS a per-channel
        # violation report; rule_range_score()'s own reason string names it.
        return "rule_range_violation", rule_reason

    if dominant_signal == "isolation_forest_score" and feature_vec is not None:
        result = if_scorer.level2_explain(device_id, feature_vec)
        if result:
            name, shap_val = result
            return name, f"Isolation Forest flagged mainly due to '{name}' (SHAP={shap_val:.3f})"

    if dominant_signal == "lstm_ae_score":
        result = lstm_scorer.level2_explain(device_id)
        if result:
            name, drop, _cf_score = result
            return name, f"LSTM-Autoencoder reacting to abnormal '{name}' over the last window (error contribution={drop:.4f})"

    if dominant_signal == "transformer_score" and transformer_scorer is not None:
        result = transformer_scorer.level2_explain(device_id)
        if result:
            name, drop, _cf_score = result
            return name, f"Transformer reacting to abnormal '{name}' over the last window (error contribution={drop:.4f})"

    if dominant_signal == "gnn_score":
        result = gnn_scorer.level2_explain(device_id)
        if result:
            name, change, _cf_score = result
            return name, f"GNN score most driven by neighboring device '{name}' (score change={change:.3f})"
        return "no_active_neighbors", (
            "GNN score based on this device's own signals only -- no other "
            "device is currently active in the graph, so there is no "
            "relational neighbor to attribute it to"
        )

    return "unavailable", f"{dominant_signal} dominant, but Level-2 detail not available yet (cold start or missing window)"


def dominant_signal_name(shap_dict: dict | None) -> str | None:
    """argmax(abs(shap_value)) over fusion_engine.last_shap -- the same
    rule fusion_engine.py's own _explain() uses to pick Level 1's
    `reason`, exposed here so gateway.py doesn't need to reimplement it."""
    if not shap_dict:
        return None
    return max(shap_dict, key=lambda k: abs(shap_dict[k]))
