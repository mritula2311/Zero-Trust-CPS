"""
The four figures that carry this project's CLAIMS, which the existing
generate_evaluation_graphs.py does not cover.

That script produces 17 figures describing the pipeline's behaviour on synthetic
data. None of them shows the real-hardware result, the two-score separation on a
physical event, the explainability diagnosis, or the seed spread -- i.e. none of
them shows the four things this work actually contributes (METHODOLOGY.md #1-#5).

Deliberately four, not forty. Each one answers a question a reviewer will ask,
and a figure that only restates a table is not generated.

    python scripts/generate_paper_figures.py
"""

import glob
import json
import os
import statistics as st
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from config import DATA_COLLECTED_DIR, PROCESS_THRESHOLD, LSTM_SEQ_LEN, FEATURE_NAMES
import evaluate_real_hardware as E
import feature_engineering as fe

FIGURES_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "figures")
os.makedirs(FIGURES_DIR, exist_ok=True)

CYAN, VIOLET, AMBER, RED, GREY = "#2aa9b5", "#7c5cd6", "#d8a33a", "#c8503f", "#8a8f98"


def savefig(fig, name):
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def _labelled_rows():
    rows = []
    for p in sorted(glob.glob(os.path.join(DATA_COLLECTED_DIR, "*_labelled.json"))):
        for r in json.load(open(p)):
            r["_session"] = os.path.basename(p)
            rows.append(r)
    return rows


# --------------------------------------------------------------------------
# A. The headline: real-hardware discrimination, per phase, with the resting
#    band drawn so the reader can see WHY detection is easy and where it is not.
# --------------------------------------------------------------------------
def fig_real_hardware():
    rows = _labelled_rows()
    scored = E.score_all(rows)
    by = {}
    for r in scored:
        by.setdefault(r["phase"], []).append(r)
    order = [p for p in ["at_rest", "gentle_tap", "tilt_rotate", "fault_weak",
                         "fault_strong", "sharp_impact", "moderate_shake"] if p in by]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6),
                                   gridspec_kw={"width_ratios": [1.15, 1]})

    # left: fused score distribution per phase
    data = [[x["fused"] for x in by[p]] for p in order]
    bp = ax1.boxplot(data, vert=True, patch_artist=True, widths=0.6,
                     medianprops=dict(color="black", linewidth=1.4))
    for patch, p in zip(bp["boxes"], order):
        patch.set_facecolor(CYAN if p == "at_rest" else VIOLET)
        patch.set_alpha(0.65)
    ax1.axhline(PROCESS_THRESHOLD, color=RED, ls="--", lw=1.2,
                label=f"deployed threshold {PROCESS_THRESHOLD}")
    ax1.set_xticklabels([f"{p}\n(n={len(by[p])})" for p in order], fontsize=8)
    ax1.set_ylabel("fused Process Anomaly score")
    ax1.set_title("Real hardware: fused score by physical state\n"
                  "operator-marked labels, 4 sessions", fontsize=10)
    ax1.legend(fontsize=8, loc="center right")
    ax1.grid(axis="y", alpha=0.25)

    # right: peak amplitude per phase on a log axis, with the resting ceiling.
    # This is the honest part -- it shows detection is carried by amplitude.
    rest_pk = [r["reading"]["peak"] for r in rows
               if r["phase"] == "at_rest" and r.get("label_source") == "operator_mark"]
    ceiling = float(np.percentile(rest_pk, 99))
    pk = [[r["reading"]["peak"] for r in rows if r["phase"] == p] for p in order]
    bp2 = ax2.boxplot(pk, vert=True, patch_artist=True, widths=0.6,
                      medianprops=dict(color="black", linewidth=1.4))
    for patch, p in zip(bp2["boxes"], order):
        patch.set_facecolor(CYAN if p == "at_rest" else VIOLET)
        patch.set_alpha(0.65)
    ax2.axhline(ceiling, color=AMBER, ls="--", lw=1.2,
                label=f"resting p99 = {ceiling:.4f} g")
    ax2.set_yscale("log")
    ax2.set_xticklabels(order, rotation=20, ha="right", fontsize=8)
    ax2.set_ylabel("peak amplitude (g, log scale)")
    ax2.set_title("Why detection is easy — and where the floor is NOT measured\n"
                  "every event class sits well above the resting band", fontsize=10)
    ax2.legend(fontsize=8)
    ax2.grid(axis="y", alpha=0.25)

    normal = [r for r in scored if r["phase"] in E.NORMAL_PHASES]
    events = [r for r in scored if r["phase"] not in E.NORMAL_PHASES]
    fp = sum(1 for r in normal if r["fused"] < PROCESS_THRESHOLD)
    dt = sum(1 for r in events if r["fused"] < PROCESS_THRESHOLD)
    lo, hi = E.wilson(fp, len(normal))
    fig.suptitle(f"False positives {fp}/{len(normal)} (95% CI [{lo:.1%}, {hi:.1%}])   ·   "
                 f"Detection {dt}/{len(events)}", fontsize=11, y=1.02)
    savefig(fig, "figA_real_hardware_discrimination.png")


# --------------------------------------------------------------------------
# B. The architectural claim, on a real physical event: the two axes move
#    independently. This is the figure a blended score cannot produce.
# --------------------------------------------------------------------------
def fig_two_score_separation():
    import sqlite3
    from config import AUDIT_DB_PATH
    con = sqlite3.connect("file:%s?mode=ro" % AUDIT_DB_PATH.replace("\\", "/"), uri=True)
    rows = list(con.execute(
        """SELECT security_trust_score, process_trust_score, decision
           FROM audit_log WHERE device_id='esp32-vib-001'
             AND security_trust_score IS NOT NULL AND process_trust_score IS NOT NULL
           ORDER BY id DESC LIMIT 4000"""))[::-1]
    if len(rows) < 40:
        print("skip figB: not enough scored history")
        return
    # find the longest run where the two axes DISAGREE about the threshold --
    # that is a physical disturbance on an authenticated device.
    dis = [(s >= 0.6) != (p >= 0.6) for s, p, _ in rows]
    best_i = best_n = cur_i = cur_n = 0
    for i, d in enumerate(dis + [False]):
        if d:
            if cur_n == 0:
                cur_i = i
            cur_n += 1
        else:
            if cur_n > best_n:
                best_i, best_n = cur_i, cur_n
            cur_n = 0
    if best_n < 5:
        print("skip figB: no disturbance episode in recent history")
        return
    pad = 12
    a, b = max(0, best_i - pad), min(len(rows), best_i + best_n + pad)
    seg = rows[a:b]
    x = np.arange(len(seg)) * 2.0  # 2 s telemetry cadence
    sec = [r[0] for r in seg]
    proc = [r[1] for r in seg]

    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axvspan((best_i - a) * 2.0, (best_i - a + best_n) * 2.0,
               color=VIOLET, alpha=0.10,
               label="physical disturbance (axes disagree)")
    ax.plot(x, sec, color=CYAN, lw=2.0, label="Security Trust  (identity, rate, freshness)")
    ax.plot(x, proc, color=VIOLET, lw=2.0, label="Process Anomaly  (physical reading only)")
    ax.axhline(0.6, color=RED, ls="--", lw=1.1, label="decision threshold 0.6")
    ax.set_xlabel("seconds")
    ax.set_ylabel("score  (1 = healthy)")
    ax.set_ylim(-0.03, 1.03)
    ax.set_title("The two-score separation on a real physical event\n"
                 "a shaken but correctly-authenticated board: Process collapses, Security does not",
                 fontsize=10)
    ax.legend(fontsize=8, loc="center left")
    ax.grid(alpha=0.25)
    sec_rng = f"{min(sec):.3f}–{max(sec):.3f}"
    ax.text(0.99, 0.06, f"Security held {sec_rng} throughout\n"
                        f"Process floor {min(proc):.5f}",
            transform=ax.transAxes, ha="right", fontsize=8, color=GREY)
    savefig(fig, "figB_two_score_separation_live.png")


# --------------------------------------------------------------------------
# C. The explainability contribution: anomaly rank vs instrument rank.
# --------------------------------------------------------------------------
def fig_anomaly_rank():
    import itertools
    import torch
    from lstm_ae_scorer import LSTMAEScorer, _TORCH_DEVICE
    D = "esp32-vib-001"
    s = LSTMAEScorer()
    if D not in s.models:
        print("skip figC: no LSTM-AE model")
        return
    stt, model = s.stats[D], s.models[D]
    rows = _labelled_rows()
    wins, prev, buf = [], None, []
    for r in rows:
        key = (r["_session"], r["phase"])
        if key != prev:
            buf, prev = [], key
        buf.append(fe.feature_vector(r["reading"]))
        if len(buf) > LSTM_SEQ_LEN:
            buf.pop(0)
        if len(buf) == LSTM_SEQ_LEN and r["phase"] != "at_rest":
            wins.append(np.array(buf))
    if not wins:
        print("skip figC: no disturbance windows")
        return

    def err(x):
        with torch.no_grad():
            return float(((model(x) - x) ** 2).mean())

    def score(e):
        z = (e - stt["baseline_error_mean"]) / stt["baseline_error_std"]
        return float(np.clip(0.9 - 0.25 * max(z, 0.0), 0.0, 1.0))

    ks, recovered, med_err = [], [], []
    for k in range(0, 5):
        flips, errs = 0, []
        for w in wins:
            arr = (w - stt["mean"]) / stt["std"]
            x = torch.tensor(arr, dtype=torch.float32, device=_TORCH_DEVICE).unsqueeze(0)
            if k == 0:
                e = err(x)
            else:
                e = None
                for cand in itertools.combinations(range(len(FEATURE_NAMES)), k):
                    pert = x.clone()
                    for c in cand:
                        pert[:, :, c] = 0.0
                    e2 = err(pert)
                    e = e2 if e is None or e2 < e else e
            errs.append(e)
            flips += score(e) >= 0.5
        ks.append(k); recovered.append(100.0 * flips / len(wins)); med_err.append(np.median(errs))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2))
    bars = ax1.bar([str(k) for k in ks], recovered,
                   color=[RED if k <= 1 else (AMBER if k == 2 else CYAN) for k in ks], alpha=0.85)
    for b, v in zip(bars, recovered):
        ax1.text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.0f}%", ha="center", fontsize=9)
    ax1.axvline(0.5, color=GREY, ls=":", lw=1)
    ax1.text(0.55, 80, "standard Level-2 test\nrepairs exactly ONE channel",
             fontsize=8, color=RED)
    ax1.set_xlabel("channels repaired jointly (best k of 5)")
    ax1.set_ylabel("windows recovering to legitimate (%)")
    ax1.set_ylim(0, 112)
    ax1.set_title(f"Anomaly rank vs instrument rank\n{len(wins)} real disturbance windows",
                  fontsize=10)
    ax1.grid(axis="y", alpha=0.25)

    ax2.semilogy([str(k) for k in ks], med_err, "o-", color=VIOLET, lw=2, ms=7)
    thr = stt["baseline_error_mean"] + ((0.9 - 0.5) / 0.25) * stt["baseline_error_std"]
    ax2.axhline(thr, color=RED, ls="--", lw=1.2, label=f"recovery needs error ≤ {thr:.2f}")
    ax2.set_xlabel("channels repaired jointly (best k of 5)")
    ax2.set_ylabel("median reconstruction error (log)")
    ax2.set_title("A rank-1 repair cannot undo a rank-3 anomaly\n"
                  "single-channel repair achieves 3.7×, ~9700× is required", fontsize=10)
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.25, which="both")
    savefig(fig, "figC_anomaly_rank_explainability.png")


# --------------------------------------------------------------------------
# D. Seed sensitivity: which reported numbers are properties, which are draws.
# --------------------------------------------------------------------------
SEED_RESULTS = {   # scripts/… sweep output, RESULTS.md 0.10.11 (seeds 0-4)
    "Isolation Forest": [0.916, 0.914, 0.916, 0.918, 0.916],
    "LSTM-AE":          [0.753, 0.753, 0.753, 0.753, 0.753],
    "Transformer":      [0.754, 0.754, 0.754, 0.754, 0.754],
    "GNN":              [0.909, 0.886, 0.912, 0.900, 0.914],
    "Fused":            [0.717, 0.711, 0.716, 0.715, 0.717],
}
RL_VS_STATIC = {"RL (adaptive)": [0.538, 0.534, 0.538, 0.535, 0.538],
                "Static 2×2":    [0.279, 0.277, 0.278, 0.278, 0.279]}


def fig_seed_sensitivity():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2),
                                   gridspec_kw={"width_ratios": [1.4, 1]})
    names = list(SEED_RESULTS)
    means = [st.mean(SEED_RESULTS[n]) for n in names]
    sds = [st.stdev(SEED_RESULTS[n]) for n in names]
    cols = [RED if n == "GNN" else CYAN for n in names]
    ax1.bar(names, means, yerr=sds, capsize=6, color=cols, alpha=0.85,
            error_kw=dict(ecolor="black", lw=1.2))
    for i, (m, sd) in enumerate(zip(means, sds)):
        ax1.text(i, m + sd + 0.012, f"±{sd:.3f}", ha="center", fontsize=8)
    ax1.set_ylabel("held-out accuracy")
    ax1.set_ylim(0.6, 1.0)
    ax1.set_title("Seed sensitivity, 5 seeds, full chain retrained\n"
                  "the GNN is the least stable signal — and the heaviest-weighted",
                  fontsize=10)
    ax1.tick_params(axis="x", labelsize=8)
    ax1.grid(axis="y", alpha=0.25)

    ns = list(RL_VS_STATIC)
    ms = [st.mean(RL_VS_STATIC[n]) for n in ns]
    ss = [st.stdev(RL_VS_STATIC[n]) for n in ns]
    ax2.bar(ns, ms, yerr=ss, capsize=6, color=[VIOLET, GREY], alpha=0.85,
            error_kw=dict(ecolor="black", lw=1.2))
    for i, (m, sd) in enumerate(zip(ms, ss)):
        ax2.text(i, m + sd + 0.012, f"{m:.3f} ± {sd:.3f}", ha="center", fontsize=8)
    sep = (ms[0] - ms[1]) / max(ss[0], 1e-9)
    ax2.set_ylabel("macro-F1")
    ax2.set_ylim(0, 0.68)
    ax2.set_title(f"RL vs static policy\nseparated by ~{sep:.0f} sd — a property, not a draw",
                  fontsize=10)
    ax2.grid(axis="y", alpha=0.25)
    savefig(fig, "figD_seed_sensitivity.png")


def main():
    print("Generating the four figures that carry this project's claims.\n"
          "(generate_evaluation_graphs.py covers pipeline behaviour on synthetic data;\n"
          " these cover the real-hardware result, the architecture, the explainability\n"
          " diagnosis, and reproducibility.)\n")
    fig_real_hardware()
    fig_two_score_separation()
    fig_anomaly_rank()
    fig_seed_sensitivity()
    print("\nDone.")


if __name__ == "__main__":
    main()
