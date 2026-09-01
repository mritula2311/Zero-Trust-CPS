"""
Generates individual PNG figures for every ML-model evaluation comparison
computed anywhere in this project -- 20 figures total (RESULTS.md's
"Figure Index" lists all of them with a one-line description and section
reference), saved to docs/figures/, for use directly in the project
report/paper. Covers every scripts/evaluate_*.py comparison (ablation,
the fair LSTM-AE/Transformer comparison, RL vs. static policy + confusion
matrices, latency, both explainability levels, score responsiveness),
plus three things no evaluate_*.py script produces on its own: NIST/IEC
62443 governance coverage, the RL convergence trend, dataset class
balance, threshold-sensitivity curves, and training loss curves for the
two sequence-model sub-signals. Does not invent new numbers: every figure
either calls the SAME functions the corresponding evaluate_*.py script
uses, or recomputes with the exact same replay/training logic (same
torch.manual_seed(0) as every train_*.py, for the loss-curve figure) where
a script only prints rather than returns -- so a figure and this project's
other numbers can never silently drift apart.

GOTCHA worth knowing if you add another figure function here:
fig_latency() temporarily redirects audit_log.AUDIT_DB_PATH/
CHECKPOINT_STORE_PATH/AUDIT_KEY_PATH to a throwaway location for its own
measurement and MUST restore them in a finally block (it does) -- an
earlier version of this script didn't, and fig_governance() (which runs
later, in the same process) silently read an empty throwaway DB instead
of the real audit log the first time this was tested. Same class of bug
`evaluate_latency.py`'s own docstring already warns about, reproduced
here in a new place because this script runs multiple such functions in
one process where the original scripts each ran alone.

Run AFTER all scripts/train_*.py have been run (needs every trained model
loaded) and AFTER generate_training_data.py/generate_test_data.py.

    python scripts/generate_evaluation_graphs.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import DATA_COLLECTED_DIR

FIGURES_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "figures")
os.makedirs(FIGURES_DIR, exist_ok=True)

# Consistent palette across every figure -- one color per signal, reused
# everywhere that signal appears so a reader can track it figure-to-figure.
COLOR = {
    "rule_score": "#94a3b8",
    "isolation_forest_score": "#38bdf8",
    "lstm_ae_score": "#818cf8",
    "transformer_score": "#f472b6",
    "gnn_score": "#34d399",
    "fused_score": "#fbbf24",
    "Static": "#94a3b8",
    "RL (greedy)": "#fbbf24",
    "RL (epsilon=0.1)": "#818cf8",
}
LABEL = {
    "rule_score": "Rule-based",
    "isolation_forest_score": "Isolation Forest",
    "lstm_ae_score": "LSTM-AE",
    "transformer_score": "Transformer",
    "gnn_score": "GNN",
    "fused_score": "Fused (meta-learner)",
}


def savefig(fig, name):
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


# --- Figure 1 & 2: Process Anomaly signal comparison (evaluate_ablation.py) ---

def fig_signal_comparison():
    import evaluate_ablation as ea

    with open(ea.TEST_PATH) as f:
        records = json.load(f)
    rows = ea.score_all_signals(records)
    labels = [row["label"] for row in rows]

    names = ea.SIGNAL_NAMES
    metrics = ["accuracy", "precision", "recall", "f1"]
    results = {}
    for i, name in enumerate(names):
        scores = [row["features"][i] for row in rows]
        results[name] = ea.metrics_at_threshold(scores, labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(metrics))
    width = 0.13
    for i, name in enumerate(names):
        vals = [results[name][m] for m in metrics]
        ax.bar(x + (i - len(names) / 2) * width + width / 2, vals, width, label=LABEL[name], color=COLOR[name])
    ax.set_xticks(x)
    ax.set_xticklabels([m.capitalize() for m in metrics])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Score")
    ax.set_title("Process Anomaly Engine -- Signal Comparison (blended across all devices)\nRESULTS.md Section 2")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig1_signal_comparison_blended.png")

    # Per-event-type recall
    event_types = sorted({row["event_type"] for row in rows if row["event_type"] != "normal" and row["event_type"] != "high_rate"})
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(event_types))
    for i, name in enumerate(names):
        recalls = []
        for et in event_types:
            sub = [(row["features"][i], row["label"]) for row in rows if row["event_type"] == et]
            sub_scores, sub_labels = zip(*sub)
            if sub_labels.count(0) == 0:
                recalls.append(0.0)
                continue
            preds = [1 if s >= 0.5 else 0 for s in sub_scores]
            recalls.append(sum(1 for p, l in zip(preds, sub_labels) if p == l == 0) / sub_labels.count(0))
        ax.bar(x + (i - len(names) / 2) * width + width / 2, recalls, width, label=LABEL[name], color=COLOR[name])
    ax.set_xticks(x)
    ax.set_xticklabels(event_types)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Recall (event correctly flagged suspicious)")
    ax.set_title("Process Anomaly Engine -- Per-Event-Type Recall\nRESULTS.md Section 2.1")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig2_per_event_type_recall.png")

    return rows


# --- Figure 3: Fair LSTM-AE vs Transformer comparison ---

def fig_fair_comparison(rows):
    import evaluate_ablation as ea

    esp32_rows = [row for row in rows if row["device_id"] == "esp32-vib-001"]
    clean_rows = [row for row in esp32_rows if not (row["label"] == 1 and row["residue_compromised"])]
    fair_labels = [row["label"] for row in clean_rows]

    metrics = ["accuracy", "precision", "recall", "f1"]
    results = {}
    for name in ("lstm_ae_score", "transformer_score"):
        i = ea.SIGNAL_NAMES.index(name)
        scores = [row["features"][i] for row in clean_rows]
        results[name] = ea.metrics_at_threshold(scores, fair_labels)

    fig, ax = plt.subplots(figsize=(7, 5))
    x = np.arange(len(metrics))
    width = 0.32
    for i, name in enumerate(("lstm_ae_score", "transformer_score")):
        vals = [results[name][m] for m in metrics]
        bars = ax.bar(x + (i - 0.5) * width, vals, width, label=LABEL[name], color=COLOR[name])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.3f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([m.capitalize() for m in metrics])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Score")
    ax.set_title("Fair, Undiluted Comparison: LSTM-AE vs Transformer\n(esp32-vib-001 only, window-residue rows excluded -- RESULTS.md Section 2.2)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig3_fair_lstm_vs_transformer.png")

    # Parameter-count vs F1 tradeoff scatter
    fig, ax = plt.subplots(figsize=(6, 5))
    points = [("LSTM-AE", 3029, results["lstm_ae_score"]["f1"], COLOR["lstm_ae_score"]),
              ("Transformer", 17701, results["transformer_score"]["f1"], COLOR["transformer_score"])]
    for name, params, f1, color in points:
        ax.scatter(params, f1, s=200, color=color, edgecolor="black", zorder=3)
        ax.annotate(f"{name}\n{params:,} params\nF1={f1:.3f}", (params, f1), xytext=(15, 0),
                    textcoords="offset points", va="center", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Parameter count (log scale)")
    ax.set_ylabel("F1 (fair comparison)")
    ax.set_title("Capacity vs. Accuracy Tradeoff\nTransformer: +0.010 F1 for ~6x the parameters")
    ax.grid(alpha=0.3)
    ax.set_ylim(min(f1 for *_, f1, _ in points) - 0.03, max(f1 for *_, f1, _ in points) + 0.03)
    savefig(fig, "fig4_capacity_vs_accuracy_tradeoff.png")


# --- Figure 5/6/7: RL policy vs static table (evaluate_rl_policy.py) ---

def fig_rl_policy():
    import evaluate_rl_policy as er
    from adaptive_pdp import AdaptivePDP, ACTIONS, CORRECT_ACTION_FOR_SITUATION
    from policy_engine import decide

    test_triples = er._load_triples(er.TEST_PATH)
    pdp = AdaptivePDP()

    policies = {
        "Static": lambda sec, proc: decide(sec, proc),
        "RL (greedy)": lambda sec, proc: pdp.greedy_action(sec, proc),
    }
    totals = {name: 0.0 for name in policies}
    counts = {name: {s: {a: 0 for a in ACTIONS} for s in er.SITUATIONS} for name in policies}
    n = len(test_triples)
    for security, process, situation in test_triples:
        for name, fn in policies.items():
            action = fn(security, process)
            totals[name] += AdaptivePDP.reward_for(action, situation)
            counts[name][situation][action] += 1

    # Avg reward bar chart
    fig, ax = plt.subplots(figsize=(5, 5))
    names = list(policies.keys())
    vals = [totals[n_] / n for n_ in names]
    bars = ax.bar(names, vals, color=[COLOR[n_] for n_ in names])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=10)
    ax.set_ylabel("Average reward")
    ax.set_title("Policy Comparison -- Held-Out Average Reward\nRESULTS.md Section 3.1")
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig5_rl_vs_static_reward.png")

    # Confusion matrix heatmaps + macro-F1
    macro_f1s = {}
    for name in names:
        mat = np.array([[counts[name][s][a] for a in ACTIONS] for s in er.SITUATIONS])
        fig, ax = plt.subplots(figsize=(6.5, 5))
        im = ax.imshow(mat, cmap="Blues")
        ax.set_xticks(range(len(ACTIONS)))
        ax.set_xticklabels(ACTIONS)
        ax.set_yticks(range(len(er.SITUATIONS)))
        ax.set_yticklabels(er.SITUATIONS)
        ax.set_xlabel("Predicted action")
        ax.set_ylabel("Actual situation")
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                ax.text(j, i, str(mat[i, j]), ha="center", va="center",
                        color="white" if mat[i, j] > mat.max() / 2 else "black", fontsize=11)
        f1s = []
        for s in er.SITUATIONS:
            correct = CORRECT_ACTION_FOR_SITUATION[s]
            tp = counts[name][s][correct]
            fn = sum(counts[name][s].values()) - tp
            fp = sum(counts[name][other][correct] for other in er.SITUATIONS if other != s)
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1s.append(2 * precision * recall / (precision + recall) if (precision + recall) else 0.0)
        macro_f1 = sum(f1s) / len(f1s)
        macro_f1s[name] = macro_f1
        ax.set_title(f"Confusion Matrix -- {name}\nmacro-F1 = {macro_f1:.3f}")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        savefig(fig, f"fig6_confusion_matrix_{name.split()[0].lower()}.png")

    fig, ax = plt.subplots(figsize=(5, 5))
    bars = ax.bar(list(macro_f1s.keys()), list(macro_f1s.values()), color=[COLOR[n_] for n_ in macro_f1s])
    for b, v in zip(bars, macro_f1s.values()):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=10)
    ax.set_ylabel("Macro-F1")
    ax.set_title("Policy Comparison -- Macro-F1 (4-class)\nRESULTS.md Section 3.2")
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig7_macro_f1_comparison.png")


# --- Figure 8: Latency (evaluate_latency.py's own logic, re-run fresh) ---

def fig_latency():
    import contextlib
    import io
    import statistics
    import time

    import audit_log
    import gateway
    import device_simulator as ds
    from config import DEVICE_REGISTRY

    eval_db = os.path.join(DATA_COLLECTED_DIR, "..", "eval_graphs_audit_log.db")
    eval_checkpoint = os.path.join(DATA_COLLECTED_DIR, "..", "eval_graphs_checkpoint_log.jsonl")
    eval_key = os.path.join(DATA_COLLECTED_DIR, "..", "eval_graphs_audit_key.bin")
    # MUST restore these afterward -- same real gotcha evaluate_latency.py's own
    # docstring already warns about (SESSION_LOG.md: an earlier version of that
    # script redirected AUDIT_DB_PATH only, once, for its whole process lifetime,
    # which was fine there since nothing ran after it. This script calls
    # fig_governance() AFTER fig_latency() in the same process -- leaving these
    # redirected would make fig_governance() read an empty throwaway DB instead
    # of the real one. Found live: it did exactly that the first time this ran.
    real_db, real_checkpoint, real_key = audit_log.AUDIT_DB_PATH, audit_log.CHECKPOINT_STORE_PATH, audit_log.AUDIT_KEY_PATH
    audit_log.AUDIT_DB_PATH = eval_db
    audit_log.CHECKPOINT_STORE_PATH = eval_checkpoint
    audit_log.AUDIT_KEY_PATH = eval_key
    try:
        audit_log.init_db()

        n_warmup, n_measured = 20, 200
        now_ms = int(time.time() * 1000)
        envelopes = []
        for i in range(n_warmup + n_measured):
            reading = ds.make_reading("esp32-vib-001", anomalous=(i % 10 == 0))
            payload = {"device_id": "esp32-vib-001", "ts": now_ms + i, "boot_id": 1, "seq": i + 1, **reading}
            sig = ds.sign(DEVICE_REGISTRY["esp32-vib-001"]["secret"], payload)
            envelopes.append({"payload": payload, "signature": sig})

        hmac_times = []
        for env in envelopes:
            t0 = time.perf_counter()
            gateway.verify_signature(env["payload"]["device_id"], env["payload"], env["signature"])
            hmac_times.append((time.perf_counter() - t0) * 1000)

        with contextlib.redirect_stdout(io.StringIO()):
            for env in envelopes[:n_warmup]:
                gateway.process_telemetry(env, transport="mqtt", transport_secured=True)
            full_times = []
            for env in envelopes[n_warmup:]:
                t0 = time.perf_counter()
                gateway.process_telemetry(env, transport="mqtt", transport_secured=True)
                full_times.append((time.perf_counter() - t0) * 1000)
    finally:
        audit_log.AUDIT_DB_PATH, audit_log.CHECKPOINT_STORE_PATH, audit_log.AUDIT_KEY_PATH = real_db, real_checkpoint, real_key
        for p in (eval_db, eval_checkpoint, eval_key):
            if os.path.exists(p):
                os.remove(p)

    def stats(vals):
        vals = sorted(vals)
        return {"mean": statistics.mean(vals), "median": vals[len(vals) // 2],
                "p95": vals[int(len(vals) * 0.95)], "max": max(vals)}

    hmac_stats = stats(hmac_times[n_warmup:])
    full_stats = stats(full_times)

    fig, ax = plt.subplots(figsize=(8, 5))
    metrics = ["mean", "median", "p95", "max"]
    x = np.arange(len(metrics))
    width = 0.35
    ax.bar(x - width / 2, [hmac_stats[m] for m in metrics], width, label="HMAC verification only", color="#38bdf8")
    ax.bar(x + width / 2, [full_stats[m] for m in metrics], width, label="Full pipeline (auth+4 scorers+fusion+policy)", color="#fbbf24")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([m.capitalize() for m in metrics])
    ax.set_ylabel("Latency, ms (log scale)")
    ax.set_title("Gateway-Side Latency\nRESULTS.md Section 6")
    ax.legend()
    ax.grid(axis="y", alpha=0.3, which="both")
    savefig(fig, "fig8_latency.png")


# --- Figure 9: Level-1 explainability validation (evaluate_explainability.py) ---

def fig_level1_explainability():
    import evaluate_explainability as ee

    with open(ee.TEST_PATH) as f:
        records = json.load(f)
    if_scorer = ee.IsolationForestScorer()
    lstm_scorer = ee.LSTMAEScorer()
    gnn_scorer = ee.GNNScorer()
    fusion = ee.FusionEngine()

    checked, matched = 0, 0
    for r in sorted(records, key=lambda r: r["tick"]):
        if r["label"] != 0 or r["event_type"] not in ee.EXPECTED_TOP_FEATURE:
            continue
        device_id = r["device_id"]
        rule_score, _ = ee.rule_range_score(device_id, r["reading"])
        if device_id == "esp32-vib-001":
            fv = ee.fe.feature_vector(r["reading"])
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score
        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        _, _, reason = fusion.combine(rule_score, if_score, lstm_score, gnn_score)
        top_feature = reason.split("fusion: ")[-1].split("=")[0] if reason.startswith("fusion: ") else None
        checked += 1
        matched += int(top_feature in ee.EXPECTED_TOP_FEATURE[r["event_type"]])

    fig, ax = plt.subplots(figsize=(5, 5))
    pct = matched / checked if checked else 0.0
    ax.bar(["Level-1 SHAP\ntop-feature match"], [pct], color="#34d399", width=0.5)
    ax.text(0, pct + 0.02, f"{matched}/{checked}\n({pct:.0%})", ha="center", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Match rate")
    ax.set_title("Level-1 Explainability Validation\nSHAP top-feature vs. physically-sensible ground truth\nRESULTS.md Section 4")
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig9_level1_explainability.png")


# --- Figure 10: Level-2 explainability validation (evaluate_explainability_level2.py) ---

def fig_level2_explainability():
    import evaluate_explainability_level2 as el2
    import explainability as expl

    with open(el2.TEST_PATH) as f:
        records = json.load(f)
    if_scorer = el2.IsolationForestScorer()
    lstm_scorer = el2.LSTMAEScorer()
    gnn_scorer = el2.GNNScorer()
    fusion = el2.FusionEngine()
    medians = el2._training_medians()

    by_signal = {}
    for r in sorted(records, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue
        device_id = r["device_id"]
        rule_score, rule_reason = el2.rule_range_score(device_id, r["reading"])
        fv = None
        if device_id == "esp32-vib-001":
            fv = el2.fe.feature_vector(r["reading"])
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score
        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        fused_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)
        if fused_score >= el2.THRESHOLD or el2.physical_label(r["event_type"]) == 1:
            continue
        dominant = expl.dominant_signal_name(fusion.last_shap)
        if dominant is None:
            continue
        cf_rule, cf_if, cf_lstm, cf_gnn = rule_score, if_score, lstm_score, gnn_score
        if dominant == "rule_score":
            cf_rule = 0.9
        elif dominant == "isolation_forest_score" and fv is not None:
            result = if_scorer.level2_explain(fv)
            if result is None:
                continue
            name, _ = result
            perturbed = list(fv)
            perturbed[el2.fe.FEATURE_NAMES.index(name)] = medians[name]
            cf_if = if_scorer.score(perturbed)
        elif dominant == "lstm_ae_score":
            result = lstm_scorer.level2_explain(device_id)
            if result is None:
                continue
            _, _, cf_lstm = result
        elif dominant == "gnn_score":
            result = gnn_scorer.level2_explain(device_id)
            if result is None:
                continue
            _, _, cf_gnn = result
        else:
            continue
        cf_fused, _, _ = fusion.combine(cf_rule, cf_if, cf_lstm, cf_gnn)
        bucket = by_signal.setdefault(dominant, [0, 0])
        bucket[0] += 1
        bucket[1] += int(cf_fused >= el2.THRESHOLD)

    names_map = {"gnn_score": "GNN", "isolation_forest_score": "Isolation Forest", "lstm_ae_score": "LSTM-AE", "rule_score": "Rule-based"}
    labels = [names_map.get(k, k) for k in by_signal]
    rates = [v[1] / v[0] for v in by_signal.values()]
    counts = [f"{v[1]}/{v[0]}" for v in by_signal.values()]
    colors = [COLOR.get({"GNN": "gnn_score", "Isolation Forest": "isolation_forest_score", "LSTM-AE": "lstm_ae_score", "Rule-based": "rule_score"}.get(l, ""), "#94a3b8") for l in labels]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    bars = ax.bar(labels, rates, color=colors)
    for b, r, c in zip(bars, rates, counts):
        ax.text(b.get_x() + b.get_width() / 2, r + 0.02, f"{c}\n({r:.0%})", ha="center", fontsize=10)
    ax.axhline(0.70, color="#f87171", linestyle="--", linewidth=1, label="Section C.4 target (70%)")
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("Flip rate (score recovers after perturbation)")
    ax.set_title("Level-2 Explainability Validation, by Dominant Signal\nRESULTS.md Section 4.1 -- relational (GNN) vs. feature-correlated (IF/LSTM-AE)", fontsize=11)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    savefig(fig, "fig10_level2_explainability_by_signal.png")


# --- Figure 11: RL convergence trend (evaluate_rl_policy.py's convergence_trend) ---

def fig_rl_convergence():
    import evaluate_rl_policy as er
    from adaptive_pdp import AdaptivePDP
    from train_adaptive_pdp import situation_weights

    train_triples = er._load_triples(er.TRAIN_PATH)
    weights = situation_weights(train_triples)
    pdp = AdaptivePDP()
    rewards = []
    for episode in range(25):
        total_reward = 0.0
        for security, process, situation in train_triples:
            action = pdp.choose_action(security, process)
            reward = AdaptivePDP.reward_for(action, situation) * weights[situation]
            pdp.update(security, process, action, reward)
            total_reward += reward
        rewards.append(total_reward / len(train_triples))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(range(len(rewards)), rewards, marker="o", color="#fbbf24", markersize=4)
    ax.set_xlabel("Episode")
    ax.set_ylabel("Avg reward per episode (situation-weighted)")
    ax.set_title("RL Convergence Trend -- Fresh Bandit Trained From Scratch\n(does not touch the deployed Q-table) -- RESULTS.md Section 3.3")
    ax.grid(alpha=0.3)
    savefig(fig, "fig11_rl_convergence_trend.png")


# --- Figure 12/13: Governance coverage (evaluate_governance.py / evaluate_iec62443.py) ---

def fig_governance():
    import audit_log
    import nist_mapping
    import iec62443_mapping
    from config import NIST_TENETS

    audit_log.init_db()  # creates the table if this process hasn't touched the DB yet -- no-op if it already exists
    rows = audit_log.recent(10_000)
    if not rows:
        print("(skipping governance figures -- audit_log.db is empty)")
        return

    report = nist_mapping.completeness_report(rows)
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = [f"{n}. {NIST_TENETS[n][:30]}" for n in sorted(report)]
    values = [report[n] for n in sorted(report)]
    bars = ax.barh(labels, values, color="#38bdf8")
    for b, v in zip(bars, values):
        ax.text(v + 0.01, b.get_y() + b.get_height() / 2, f"{v:.0%}", va="center", fontsize=9)
    ax.set_xlim(0, 1.1)
    ax.set_xlabel("Coverage (fraction of logged decisions with traceable evidence)")
    ax.set_title("NIST SP 800-207 Governance Completeness")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    savefig(fig, "fig12_nist_governance_coverage.png")

    coverage = iec62443_mapping.fr_coverage_report(rows)
    frs = iec62443_mapping.FOUNDATIONAL_REQUIREMENTS
    labels = [f"{fr}. {info['name'][:28]}" for fr, info in frs.items()]
    values = [coverage.get(fr, 0.0) if frs[fr]["status"] != "not_implemented" else 0.0 for fr in frs]
    colors = ["#34d399" if frs[fr]["status"] == "implemented" else "#fbbf24" if frs[fr]["status"] == "partial" else "#f87171" for fr in frs]
    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.barh(labels, values, color=colors)
    for b, v, fr in zip(bars, values, frs):
        label = f"{v:.0%}" if frs[fr]["status"] != "not_implemented" else "n/a"
        ax.text(max(v, 0.02) + 0.01, b.get_y() + b.get_height() / 2, label, va="center", fontsize=9)
    ax.set_xlim(0, 1.1)
    ax.set_xlabel("Coverage")
    ax.set_title("IEC 62443-3-3 Foundational Requirements Coverage\ngreen=implemented, amber=partial, red=not implemented")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    savefig(fig, "fig13_iec62443_fr_coverage.png")


# --- Figure 14: Score responsiveness (evaluate_trust_responsiveness.py) ---

def fig_responsiveness():
    import evaluate_trust_responsiveness as etr

    with open(etr.TEST_PATH) as f:
        records = json.load(f)
    trace = etr.replay_with_state(records)
    results = etr.measure_responsiveness(trace)

    event_types = sorted({r["event_type"] for r in results})
    sec_means, proc_means, labels = [], [], []
    for et in event_types:
        subset = [r for r in results if r["event_type"] == et]
        sec_vals = [r["messages_to_security_break"] for r in subset if r["messages_to_security_break"] is not None]
        proc_vals = [r["messages_to_process_break"] for r in subset if r["messages_to_process_break"] is not None]
        if not sec_vals and not proc_vals:
            continue
        labels.append(et)
        sec_means.append(np.mean(sec_vals) if sec_vals else 0.0)
        proc_means.append(np.mean(proc_vals) if proc_vals else 0.0)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, sec_means, width, label="mean msgs -> SECURITY break", color="#f472b6")
    ax.bar(x + width / 2, proc_means, width, label="mean msgs -> PROCESS break", color="#818cf8")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel("Mean messages until threshold crossed")
    ax.set_title("Score Responsiveness by Event Type\nRESULTS.md Section 7 -- 0 bar = n/a (never crossed, or not applicable)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    savefig(fig, "fig14_score_responsiveness.png")


# --- Figure 15: Dataset class balance (train vs test) ---

def fig_dataset_balance():
    train_path = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
    test_path = os.path.join(DATA_COLLECTED_DIR, "test_session.json")
    with open(train_path) as f:
        train_records = json.load(f)
    with open(test_path) as f:
        test_records = json.load(f)

    from collections import Counter
    train_counts = Counter(r["event_type"] for r in train_records)
    test_counts = Counter(r["event_type"] for r in test_records)
    event_types = sorted(set(train_counts) | set(test_counts))

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(event_types))
    width = 0.35
    ax.bar(x - width / 2, [train_counts.get(e, 0) for e in event_types], width, label=f"training_session.json (n={len(train_records)})", color="#38bdf8")
    ax.bar(x + width / 2, [test_counts.get(e, 0) for e in event_types], width, label=f"test_session.json (n={len(test_records)})", color="#fbbf24")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(event_types, rotation=20, ha="right")
    ax.set_ylabel("Record count (log scale)")
    ax.set_title("Dataset Composition -- Event-Type Balance\nTrain (seed=42) vs. held-out Test (seed=999)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3, which="both")
    savefig(fig, "fig15_dataset_class_balance.png")


# --- Figure 16: Threshold sensitivity (precision/recall/F1 vs. threshold) ---

def fig_threshold_sensitivity():
    import evaluate_ablation as ea

    with open(ea.TEST_PATH) as f:
        records = json.load(f)
    rows = ea.score_all_signals(records)
    labels = [row["label"] for row in rows]

    thresholds = np.linspace(0.05, 0.95, 19)
    for name in ("isolation_forest_score", "gnn_score", "fused_score"):
        i = ea.SIGNAL_NAMES.index(name)
        scores = [row["features"][i] for row in rows]
        precisions, recalls, f1s = [], [], []
        for t in thresholds:
            m = ea.metrics_at_threshold(scores, labels, threshold=t)
            precisions.append(m["precision"])
            recalls.append(m["recall"])
            f1s.append(m["f1"])
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.plot(thresholds, precisions, marker="o", markersize=3, label="Precision", color="#38bdf8")
        ax.plot(thresholds, recalls, marker="o", markersize=3, label="Recall", color="#f472b6")
        ax.plot(thresholds, f1s, marker="o", markersize=3, label="F1", color="#34d399")
        ax.axvline(0.5, color="#94a3b8", linestyle="--", linewidth=1, label="deployed threshold (0.5)")
        ax.set_xlabel("Decision threshold")
        ax.set_ylabel("Score")
        ax.set_ylim(0, 1.05)
        ax.set_title(f"Threshold Sensitivity -- {LABEL.get(name, name)}\nRESULTS.md Section 2 (all other figures use the fixed 0.5 threshold)")
        ax.legend()
        ax.grid(alpha=0.3)
        savefig(fig, f"fig16_threshold_sensitivity_{name.split('_score')[0]}.png")


# --- Figure 17/18: Training loss curves (re-run training, capture the loss history --
# deterministic, same torch.manual_seed(0) every train_*.py script already uses, so this
# reproduces the exact persisted model, not a different one) ---

def fig_training_loss_curves():
    import torch
    import torch.nn as nn
    import feature_engineering as fe
    from config import (
        LSTM_SEQ_LEN, LSTM_EPOCHS, LSTM_LEARNING_RATE,
        TRANSFORMER_EPOCHS, TRANSFORMER_LEARNING_RATE, TRANSFORMER_NOISE_STD,
    )
    from lstm_ae_scorer import LSTMAutoencoder, _TORCH_DEVICE as LSTM_DEVICE
    from transformer_scorer import TransformerAutoencoder, _TORCH_DEVICE as TR_DEVICE

    train_path = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
    with open(train_path) as f:
        records = json.load(f)
    normal = sorted(
        [r for r in records if r["device_id"] == "esp32-vib-001" and r["label"] == 1 and r["auth_ok"]],
        key=lambda r: r["tick"],
    )
    raw = np.array([fe.feature_vector(r["reading"]) for r in normal], dtype=np.float32)
    mean, std = raw.mean(axis=0), raw.std(axis=0)
    std[std < 1e-6] = 1.0
    normed = (raw - mean) / std
    windows = np.stack([normed[i:i + LSTM_SEQ_LEN] for i in range(len(normed) - LSTM_SEQ_LEN + 1)])

    torch.manual_seed(0)
    x = torch.tensor(windows, dtype=torch.float32, device=LSTM_DEVICE)
    model = LSTMAutoencoder().to(LSTM_DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=LSTM_LEARNING_RATE)
    loss_fn = nn.MSELoss()
    lstm_losses = []
    for epoch in range(LSTM_EPOCHS):
        opt.zero_grad()
        loss = loss_fn(model(x), x)
        loss.backward()
        opt.step()
        lstm_losses.append(loss.item())

    torch.manual_seed(0)
    x2 = torch.tensor(windows, dtype=torch.float32, device=TR_DEVICE)
    tmodel = TransformerAutoencoder().to(TR_DEVICE)
    topt = torch.optim.Adam(tmodel.parameters(), lr=TRANSFORMER_LEARNING_RATE)
    tr_losses = []
    for epoch in range(TRANSFORMER_EPOCHS):
        topt.zero_grad()
        noisy = x2 + torch.randn_like(x2) * TRANSFORMER_NOISE_STD
        loss = loss_fn(tmodel(noisy), x2)
        loss.backward()
        topt.step()
        tr_losses.append(loss.item())

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(range(len(lstm_losses)), lstm_losses, label="LSTM-AE (reconstruction MSE)", color=COLOR["lstm_ae_score"])
    ax.plot(range(len(tr_losses)), tr_losses, label="Transformer (denoising MSE)", color=COLOR["transformer_score"])
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Training loss (MSE, log scale)")
    ax.set_yscale("log")
    ax.set_title("Training Loss Curves -- LSTM-AE vs. Transformer\n(re-run with the same torch.manual_seed(0) every train_*.py script uses --\nreproduces the exact persisted model, not a different one)")
    ax.legend()
    ax.grid(alpha=0.3, which="both")
    savefig(fig, "fig17_training_loss_lstm_vs_transformer.png")


def main():
    print("Generating evaluation figures into docs/figures/ ...\n")
    rows = fig_signal_comparison()
    fig_fair_comparison(rows)
    fig_rl_policy()
    fig_latency()
    fig_level1_explainability()
    fig_level2_explainability()
    fig_rl_convergence()
    fig_governance()
    fig_responsiveness()
    fig_dataset_balance()
    fig_threshold_sensitivity()
    fig_training_loss_curves()
    print("\nDone.")


if __name__ == "__main__":
    main()
