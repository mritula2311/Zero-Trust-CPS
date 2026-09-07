"""
The R1-R15 figure set for the corrected-M6 paper evidence (2026-09-07 final
pass). Supersedes every figure previously under docs/figures/ (fig1-fig17,
figA-figD from generate_evaluation_graphs.py / generate_paper_figures.py) --
those were generated before the comparator repair and the corrected-M6
promotion and are deleted alongside this script landing (see git history to
recover them).

Every figure reads directly from a results/*.json or results/*.log artifact,
or recomputes with the exact same replay logic an evaluate_*.py script uses
(never a second implementation) -- no number here is invented. Where an
artifact is GCN-era/preserved (R6's per-signal log predates the M6 switch),
the figure says so in its title/caption, matching docs/paper/13's own
[VERIFIED PRESERVED GCN-ERA REPLAY] labelling.

    python scripts/generate_corrected_m6_figures.py
"""
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import joblib

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIGURES_DIR = os.path.join(ROOT, "docs", "figures")
os.makedirs(FIGURES_DIR, exist_ok=True)

# Same palette as generate_paper_figures.py, extended with one more slot for
# a third comparison arm (gcn / m6_deployed-flawed / m6_corrected).
CYAN, VIOLET, AMBER, RED, GREY = "#2aa9b5", "#7c5cd6", "#d8a33a", "#c8503f", "#8a8f98"
ARM_COLOR = {"gcn": GREY, "m6_deployed": RED, "m6_corrected": CYAN,
             "gcn_corrected": GREY, "flawed": RED, "corrected": CYAN}
ARM_LABEL = {"gcn": "GCN", "m6_deployed": "M6 (deployed, flawed)",
             "m6_corrected": "M6 (corrected)", "gcn_corrected": "GCN (fair baseline)"}


def savefig(fig, name):
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def rj(relpath):
    with open(os.path.join(ROOT, relpath)) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# R1 -- Corrected relational-model comparison (Essential)
# ---------------------------------------------------------------------------
def r1_relational_model_comparison():
    d = rj("results/gcn_m6_corrected_comparison/standalone_comparison.json")["results"]
    arms = ["gcn", "m6_deployed", "m6_corrected"]
    metrics = ["macro_f1", "roc_auc", "false_alarm_rate_fpr"]
    metric_labels = ["Macro-F1", "ROC-AUC", "FPR"]

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    x = np.arange(len(metrics))
    width = 0.26
    for i, arm in enumerate(arms):
        vals = [d[arm][m] for m in metrics]
        ax.bar(x + (i - 1) * width, vals, width, label=ARM_LABEL[arm], color=ARM_COLOR[arm])
        for xi, v in zip(x + (i - 1) * width, vals):
            ax.text(xi, v + 0.015, f"{v:.3f}", ha="center", va="bottom", fontsize=7, rotation=90)
    ax.set_xticks(x)
    ax.set_xticklabels(metric_labels)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Value")
    ax.set_title("R1: Corrected relational-model comparison — standalone score\n"
                  "(test_session.json, threshold 0.6, doc 13 O4)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r1_relational_model_comparison.png")


# ---------------------------------------------------------------------------
# R2 -- M1-M9 relational benchmark (High)
# ---------------------------------------------------------------------------
def r2_m1_m9_benchmark():
    d = rj("results/crossdevice_benchmark/metrics.json")["results"]
    names = list(d.keys())
    macro_f1 = [d[n]["test_macro_f1"] for n in names]
    fpr = [d[n]["test"]["false_positive_rate"] for n in names]
    labels = [n.split("_", 1)[1].replace("_", " ") for n in names]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    y = np.arange(len(names))
    colors = [CYAN if n == "M6_set_transformer" else (RED if n == "M4_gcn" else VIOLET) for n in names]
    ax1.barh(y, macro_f1, color=colors)
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=8)
    ax1.invert_yaxis()
    ax1.set_xlabel("Test Macro-F1")
    ax1.set_xlim(0, 1.05)
    for yi, v in zip(y, macro_f1):
        ax1.text(v + 0.01, yi, f"{v:.4f}", va="center", fontsize=7)

    ax2.barh(y, fpr, color=colors)
    ax2.set_xlabel("Test FPR")
    for yi, v in zip(y, fpr):
        ax2.text(v + 0.002, yi, f"{v:.4f}", va="center", fontsize=7)

    fig.suptitle("R2: M1-M9 standalone relational benchmark (20-node constructed network, "
                  "seed 0, doc 13 B)", y=1.02)
    savefig(fig, "r2_m1_m9_benchmark.png")


# ---------------------------------------------------------------------------
# R3 -- Task-2 comparison (Essential)
# ---------------------------------------------------------------------------
def r3_task2_comparison():
    d = rj("results/gcn_m6_corrected_comparison/task2_comparison.json")["task2_network_coordination_pattern_4way_accuracy"]
    order = ["B0_anomalous_node_count", "B1_concat_logreg", "B2_concat_mlp",
             "GNN_node_embeddings", "M6_node_embeddings"]
    labels = ["B0 count", "B1 concat LR", "B2 concat MLP", "GNN (GCN)", "M6 Set\nTransformer"]
    test_vals = [d[k]["test"] for k in order]
    val_vals = [d[k]["validation"] for k in order]
    colors = [GREY, VIOLET, AMBER, RED, CYAN]

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    x = np.arange(len(order))
    width = 0.35
    ax.bar(x - width / 2, val_vals, width, label="Validation", color=colors, alpha=0.5)
    ax.bar(x + width / 2, test_vals, width, label="Test", color=colors)
    for xi, v in zip(x + width / 2, test_vals):
        ax.text(xi, v + 0.01, f"{v:.4f}", ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("4-way scenario accuracy")
    ax.set_ylim(0, 0.75)
    ax.set_title("R3: Task-2 network-coordination-pattern comparison\n"
                  "(evaluate_gnn_baselines.py, M6 arm added 2026-09-07, doc 13 N)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r3_task2_comparison.png")


# ---------------------------------------------------------------------------
# R4 -- Policy per-action performance (Essential)
# ---------------------------------------------------------------------------
def r4_policy_per_action():
    d = rj("results/m6_corrected_policy/policy_action_metrics.json")
    actions = ["ALLOW", "ALERT", "STEP_UP", "BLOCK"]
    arms = ["gcn_corrected", "m6_corrected"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), sharex=True)
    x = np.arange(len(actions))
    width = 0.35
    for i, arm in enumerate(arms):
        rec = [d[arm][a]["recall"] for a in actions]
        prec = [d[arm][a]["precision"] for a in actions]
        off = (i - 0.5) * width
        ax1.bar(x + off, rec, width, label=ARM_LABEL[arm], color=ARM_COLOR[arm])
        ax2.bar(x + off, prec, width, label=ARM_LABEL[arm], color=ARM_COLOR[arm])
    for ax, title in ((ax1, "Recall"), (ax2, "Precision")):
        ax.set_xticks(x)
        ax.set_xticklabels(actions)
        ax.set_ylim(0, 1.05)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
    ax1.legend(fontsize=8)
    ax1.set_ylabel("Value")
    fig.suptitle("R4: Policy per-action performance — corrected M6 vs. fair GCN baseline\n"
                  "(test_session.json, deterministic clock, doc 13 O5). BLOCK is 0 for both arms.", y=1.03)
    savefig(fig, "r4_policy_per_action.png")


# ---------------------------------------------------------------------------
# R5 -- Hardware disturbance vs resting behavior (High)
# ---------------------------------------------------------------------------
def r5_hardware_behavior():
    d = rj("results/gcn_m6_corrected_comparison/hardware_comparison.json")["results"]
    arms = ["gcn", "m6_deployed", "m6_corrected"]

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    x = np.arange(2)  # resting FP, detection
    width = 0.26
    for i, arm in enumerate(arms):
        fp = d[arm]["resting_false_positive_rate"]
        det = d[arm]["disturbance_detection_rate"]
        vals = [fp["rate"], det["rate"]]
        lo = [fp["rate"] - fp["wilson_95ci"][0], det["rate"] - det["wilson_95ci"][0]]
        hi = [fp["wilson_95ci"][1] - fp["rate"], det["wilson_95ci"][1] - det["rate"]]
        xi = x + (i - 1) * width
        ax.bar(xi, vals, width, yerr=[lo, hi], capsize=3, label=ARM_LABEL[arm], color=ARM_COLOR[arm])
        ax.text(xi[0], vals[0] + hi[0] + 0.03, f"{fp['k']}/{fp['n']}", ha="center", fontsize=7)
        ax.text(xi[1], vals[1] + hi[1] + 0.03, f"{det['k']}/{det['n']}", ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(["Resting false-positive rate", "Disturbance detection rate"])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Rate (Wilson 95% CI)")
    ax.set_title("R5: Real MPU6050 hardware — disturbance vs. resting behaviour\n"
                  "(held-out TEST session, 42 scored windows, doc 13 O4/Q)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r5_hardware_behavior.png")


# ---------------------------------------------------------------------------
# R6 -- Local detector attack-class recall (High)
# GCN-era preserved replay -- see doc 13 A. Values transcribed from the
# frozen local_fusion_evaluation.log table (no live rerun of this exact
# per-signal breakdown exists post-M6; labelled honestly as historical).
# ---------------------------------------------------------------------------
def r6_local_detector_recall():
    signals = ["rule_score", "isolation_forest_score", "lstm_ae_score",
               "transformer_score", "gnn_score", "fused_score"]
    signal_labels = ["rule", "IF", "LSTM-AE", "Transformer", "GNN\n(GCN-era)", "fused"]
    events = ["anomalous_shock", "coordinated", "stealthy_forged_values"]
    # source: results/final_verification/local_fusion_evaluation.log,
    # "Per-event-type recall" table.
    recall = {
        "rule_score":              [0.000, 0.000, 0.000],
        "isolation_forest_score":  [1.000, 0.316, 0.212],
        "lstm_ae_score":           [1.000, 0.308, 0.606],
        "transformer_score":       [1.000, 0.308, 0.606],
        "gnn_score":               [1.000, 1.000, 0.667],
        "fused_score":             [1.000, 0.983, 0.636],
    }
    colors = ["#94a3b8", "#38bdf8", "#818cf8", "#f472b6", "#34d399", "#111827"]

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    x = np.arange(len(events))
    width = 0.13
    for i, s in enumerate(signals):
        ax.bar(x + (i - 2.5) * width, recall[s], width, label=signal_labels[i], color=colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels(["anomalous_shock", "coordinated", "stealthy_forged_values"])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Recall (event correctly flagged suspicious)")
    ax.set_title("R6: Local-detector per-attack-class recall\n"
                  "[VERIFIED PRESERVED GCN-ERA REPLAY — 13 A; not the M6 runtime's own breakdown]")
    ax.legend(fontsize=7, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.32))
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r6_local_detector_attack_recall.png")


# ---------------------------------------------------------------------------
# R7 -- GCN vs M6 latency (Medium)
# ---------------------------------------------------------------------------
def r7_latency():
    d = rj("results/gcn_m6_corrected_comparison/latency_comparison.json")["results"]
    arms = ["gcn", "m6_deployed", "m6_corrected"]

    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    x = np.arange(len(arms))
    mean = [d[a]["mean_ms"] for a in arms]
    p95 = [d[a]["p95_ms"] for a in arms]
    width = 0.35
    ax.bar(x - width / 2, mean, width, label="mean", color=[ARM_COLOR[a] for a in arms])
    ax.bar(x + width / 2, p95, width, label="p95", color=[ARM_COLOR[a] for a in arms], alpha=0.5)
    for xi, v in zip(x - width / 2, mean):
        ax.text(xi, v + 0.05, f"{v:.2f}", ha="center", fontsize=8)
    for xi, v in zip(x + width / 2, p95):
        ax.text(xi, v + 0.05, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([ARM_LABEL[a] for a in arms], fontsize=8)
    ax.set_ylabel("Latency (ms)")
    ax.set_title("R7: Standalone relational-scorer inference latency\n"
                  "(post-warmup, n=200 calls, doc 13 O4)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r7_latency.png")


# ---------------------------------------------------------------------------
# R8 -- Fusion comparison (High)
# ---------------------------------------------------------------------------
def r8_fusion_comparison():
    d = rj("results/gcn_m6_corrected_comparison/fusion_comparison.json")["results"]
    arms = ["gcn", "m6_deployed", "m6_corrected"]
    metrics = ["macro_f1", "roc_auc", "recall_normal", "false_alarm_rate_fpr"]
    metric_labels = ["Macro-F1", "ROC-AUC", "Recall\n(normal)", "FPR"]

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    x = np.arange(len(metrics))
    width = 0.26
    for i, arm in enumerate(arms):
        vals = [d[arm][m] for m in metrics]
        ax.bar(x + (i - 1) * width, vals, width, label=ARM_LABEL[arm], color=ARM_COLOR[arm])
        for xi, v in zip(x + (i - 1) * width, vals):
            ax.text(xi, v + 0.015, f"{v:.3f}", ha="center", va="bottom", fontsize=7, rotation=90)
    ax.set_xticks(x)
    ax.set_xticklabels(metric_labels)
    ax.set_ylim(0, 1.05)
    ax.set_title("R8: Fusion comparison — rule+IF+LSTM+relational, matched fusion per arm\n"
                  "(held-out replay, doc 13 O4; both M6 variants beat GCN modestly)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r8_fusion_comparison.png")


# ---------------------------------------------------------------------------
# R9 -- Topology sensitivity (Medium)
# ---------------------------------------------------------------------------
def r9_topology_sensitivity():
    sp = rj("results/crossdevice_benchmark/metrics.json")["structural_probes"]["neighbour_degree_at_n10"]
    models = list(sp.keys())
    colors = {"M3_deep_sets": VIOLET, "M4_gcn": RED, "M5_gatv2": AMBER, "M6_set_transformer": CYAN,
              "M7_np_st": "#1f6f5c", "M8_set_transformer_mixed_n": "#5c4a1f"}

    fig, ax = plt.subplots(figsize=(7, 4.4))
    for m in models:
        degrees = sorted(int(k) for k in sp[m].keys())
        recall = [sp[m][str(k)]["recall_at_threshold"] for k in degrees]
        ax.plot(degrees, recall, marker="o", label=m.split("_", 1)[1].replace("_", " "),
                color=colors.get(m, GREY))
    ax.set_xlabel("Active neighbour degree (n=10)")
    ax.set_ylabel("Recall at frozen threshold")
    ax.set_ylim(0, 1.05)
    ax.set_title("R9: Target-degree topology-sensitivity probe\n"
                  "(400 synthetic draws/cell, fixed threshold, doc 13 D)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    savefig(fig, "r9_topology_sensitivity.png")


# ---------------------------------------------------------------------------
# R10 -- Generator validity / OOD behavior (Medium)
# ---------------------------------------------------------------------------
def r10_generator_validity():
    # source: results/final_verification/generator_validation.log, doc 13 I
    regimes = ["LOW", "MEDIUM", "HIGH"]
    spread = [0.00794, 0.01509, 0.03842]
    status = ["Pass all four\nmeasured coords", "RMS marginal\ndivergence", "RMS+peak marginal\ndivergence"]
    colors = [CYAN, AMBER, RED]

    fig, ax = plt.subplots(figsize=(6, 4.4))
    bars = ax.bar(regimes, spread, color=colors)
    for b, s in zip(bars, status):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.001, s,
                ha="center", va="bottom", fontsize=7.5)
    ax.set_ylabel("Cross-node RMS spread")
    ax.set_title("R10: Virtual-generator validity boundary\n"
                  "(TRAIN residual consistency, LOW/MEDIUM/HIGH presets, doc 13 I)")
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r10_generator_validity.png")


# ---------------------------------------------------------------------------
# R11 -- Explainability contribution distribution (Optional)
# ---------------------------------------------------------------------------
def r11_explainability_contributions():
    gcn = joblib.load(os.path.join(ROOT, "models", "fusion_meta_learner_gcn_backup.joblib"))
    m6c = joblib.load(os.path.join(ROOT, "models", "fusion_meta_learner_m6_corrected_variant.joblib"))
    channels = ["rule", "IF", "LSTM-AE", "relational"]

    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    x = np.arange(len(channels))
    width = 0.35
    ax.bar(x - width / 2, gcn.coef_[0], width, label="GCN fusion", color=GREY)
    ax.bar(x + width / 2, m6c.coef_[0], width, label="Corrected-M6 fusion", color=CYAN)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(channels)
    ax.set_ylabel("Logistic-regression coefficient (log-odds weight)")
    ax.set_title("R11: Fusion input-channel contribution — GCN vs. corrected-M6\n"
                  "(saved fusion_meta_learner coefficients, doc 13 O2)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(fig, "r11_explainability_contributions.png")


# ---------------------------------------------------------------------------
# R12 -- Policy confusion matrix (Optional)
# ---------------------------------------------------------------------------
def r12_policy_confusion_matrix():
    def load_csv(name):
        path = os.path.join(ROOT, "results", "m6_corrected_policy", name)
        with open(path) as f:
            rows = list(csv.reader(f))
        header = rows[0][1:]
        matrix = np.array([[int(v) for v in r[1:]] for r in rows[1:]], dtype=float)
        return header, matrix

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax, (name, title) in zip(axes, [
        ("confusion_matrix_m6_corrected_policy_gcn_corrected.csv", "GCN (fair baseline)"),
        ("confusion_matrix_m6_corrected_policy_m6_corrected.csv", "Corrected M6"),
    ]):
        labels, m = load_csv(name)
        row_norm = m / m.sum(axis=1, keepdims=True)
        im = ax.imshow(row_norm, cmap="Blues", vmin=0, vmax=1)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title(title, fontsize=9)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, int(m[i, j]), ha="center", va="center",
                        fontsize=8, color="white" if row_norm[i, j] > 0.5 else "black")
    fig.suptitle("R12: Policy confusion matrix (rows: actual, columns: predicted; "
                 "test_session.json, deterministic clock)", y=1.03)
    savefig(fig, "r12_policy_confusion_matrix.png")


# ---------------------------------------------------------------------------
# R13 -- Hardware score distributions (Very useful if artifacts support it)
# Recomputes via the SAME evaluate_real_hardware.score_all() replay logic,
# pinned explicitly to gcn and m6_corrected -- not a second implementation.
# ---------------------------------------------------------------------------
def r13_hardware_score_distributions():
    import evaluate_real_hardware as E
    import relational_pin as rp

    rows = E.load_sessions("test")
    order = [p for p in ["at_rest", "gentle_tap", "tilt_rotate", "fault_weak",
                          "fault_strong", "sharp_impact", "moderate_shake"]]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for ax, pin, title, color in [
        (axes[0], rp.GCN, "GCN", GREY),
        (axes[1], rp.M6_CORRECTED, "Corrected M6 (deployed)", CYAN),
    ]:
        scored = E.score_all(rows, pin)
        by = {}
        for r in scored:
            by.setdefault(r["phase"], []).append(r["fused"])
        present = [p for p in order if p in by]
        data = [by[p] for p in present]
        bp = ax.boxplot(data, vert=True, patch_artist=True, widths=0.6,
                         medianprops=dict(color="black", linewidth=1.4))
        for patch, p in zip(bp["boxes"], present):
            patch.set_facecolor(CYAN if p == "at_rest" else color)
            patch.set_alpha(0.65)
        ax.axhline(0.6, color=RED, ls="--", lw=1.1, label="threshold 0.6")
        ax.set_xticks(range(1, len(present) + 1))
        ax.set_xticklabels(present, rotation=35, ha="right", fontsize=8)
        ax.set_title(title, fontsize=9)
        ax.legend(fontsize=7)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Fused Process Trust score")
    fig.suptitle("R13: Real hardware fused-score distribution by phase — GCN vs. corrected M6\n"
                 "(held-out TEST session, same replay logic as evaluate_real_hardware.py)", y=1.04)
    savefig(fig, "r13_hardware_score_distributions.png")


# ---------------------------------------------------------------------------
# R14 -- Ablation / masking correction impact (High)
# ---------------------------------------------------------------------------
def r14_correction_impact():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.4))

    # (a) class-weight bug fix -- standalone Macro-F1
    ax1.bar(["Before\n(flawed)", "After\n(corrected)"], [0.0735944, 0.7925591],
            color=[RED, CYAN])
    for i, v in enumerate([0.0735944, 0.7925591]):
        ax1.text(i, v + 0.02, f"{v:.4f}", ha="center", fontsize=9)
    ax1.set_ylim(0, 1.0)
    ax1.set_ylabel("Standalone Macro-F1")
    ax1.set_title("Class-weight bug fix\n(train_set_transformer.py, 13 O4)")
    ax1.grid(axis="y", alpha=0.25)

    # (b) pending-node masking fix -- B2 concat-MLP Task-1 F1 (this one is a
    # measured DEGRADATION, reported honestly, not a win)
    ax2.bar(["Before\n(pre-audit)", "After\n(corrected masking)"], [0.9662, 0.9174],
            color=[AMBER, VIOLET])
    for i, v in enumerate([0.9662, 0.9174]):
        ax2.text(i, v + 0.01, f"{v:.4f}", ha="center", fontsize=9)
    ax2.set_ylim(0, 1.05)
    ax2.set_ylabel("Task-1 anomaly F1 (B2 concat MLP)")
    ax2.set_title("Pending-node masking fix\n(FN 72→0, FP 28→270 — a real tradeoff, 13 N)")
    ax2.grid(axis="y", alpha=0.25)

    fig.suptitle("R14: Before/after impact of two independent correctness fixes", y=1.03)
    savefig(fig, "r14_correction_impact.png")


# ---------------------------------------------------------------------------
# R15 -- Seed / statistical robustness (Optional)
# ---------------------------------------------------------------------------
def r15_seed_robustness():
    pe = rj("results/crossdevice_benchmark/seed_study.json")["paired_effects"]["degree"]
    models = list(pe.keys())
    means = [pe[m]["mean_delta"] for m in models]
    # M3/M6 have zero variance across seeds (sd=0.0, "note" field instead of a
    # t-interval) -- a genuinely zero-width interval, not missing data.
    ci95 = [pe[m].get("ci95", [pe[m]["mean_delta"], pe[m]["mean_delta"]]) for m in models]
    lo = [mean - c[0] for mean, c in zip(means, ci95)]
    hi = [c[1] - mean for mean, c in zip(means, ci95)]
    colors = [CYAN if "M6" in m else (RED if "M4" in m else VIOLET) for m in models]
    labels = [m.split("_", 1)[1].replace("_", " ") for m in models]

    fig, ax = plt.subplots(figsize=(7, 4.4))
    y = np.arange(len(models))
    ax.errorbar(means, y, xerr=[lo, hi], fmt="o", capsize=4, color="black", zorder=3)
    for yi, c in zip(y, colors):
        ax.scatter(means[yi], yi, color=c, s=60, zorder=4)
    ax.axvline(0, color="grey", ls="--", lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Mean recall delta, degree 1→9 (10 seeds, 95% t-interval)")
    ax.set_title("R15: Seed/statistical robustness — target-degree effect\n"
                  "(paired refits, df=9, doc 13 D/E)")
    ax.grid(axis="x", alpha=0.25)
    savefig(fig, "r15_seed_robustness.png")


ALL_FIGURES = [
    r1_relational_model_comparison, r2_m1_m9_benchmark, r3_task2_comparison,
    r4_policy_per_action, r5_hardware_behavior, r6_local_detector_recall,
    r7_latency, r8_fusion_comparison, r9_topology_sensitivity,
    r10_generator_validity, r11_explainability_contributions,
    r12_policy_confusion_matrix, r13_hardware_score_distributions,
    r14_correction_impact, r15_seed_robustness,
]


def main():
    for fn in ALL_FIGURES:
        fn()
    print(f"\n{len(ALL_FIGURES)} figures written to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
