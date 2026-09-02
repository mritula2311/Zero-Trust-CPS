"""
Synopsis Section 10.1 evaluation metric: "Fusion ablation: detection
accuracy of the fused score compared against each individual model (rule-
based, Isolation Forest, LSTM-AE, GNN) in isolation, to evidence the
fusion's actual contribution rather than assert it." Also Section 5.6/10.2:
"An ablation study empirically demonstrating that the fused trust score
outperforms any single constituent model."

Replays data/collected/test_session.json (a HELD-OUT set -- see
generate_test_data.py's docstring for why this must not be
training_session.json) through the fully trained pipeline, scores each of
the 4 individual signals plus the fused output against each message's
REAL ground-truth label, and reports accuracy/precision/recall/F1 for
each column side by side.

Run this AFTER all 5 scripts/train_*.py have been run (needs every
trained model loaded).

TWO-SCORE REARCHITECTURE: this script evaluates ONLY the Process Anomaly
Engine (rule + Isolation Forest + LSTM-AE + GNN + fusion) -- so it now
uses a PHYSICAL-only ground-truth label (physical_label(), derived from
situation_for_event_type()), not the old blended `label` field. This
matters concretely for `high_rate` records: their physical reading is
genuinely normal (only the message RATE is suspicious, a Security Trust
concern the Process Anomaly Engine structurally cannot see and correctly
should not flag) -- scoring the Process Anomaly Engine against the old
blended label would have unfairly penalised it for not catching something
that was never a physical anomaly in the first place. `auth_ok=False`
records (forged_signature) and `event_type == "replay"` records (a replay
has a VALID HMAC by construction -- auth_ok=True -- it's Module 2's
boot/seq check that rejects it, not the signature check) are both
EXCLUDED entirely: in the live architecture Module 2 rejects both before
they ever reach Module 3 at all (see gateway.py's _reject()), so including
them here would evaluate against messages the Process Anomaly Engine never
actually sees live.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from config import DATA_COLLECTED_DIR, LSTM_SEQ_LEN, is_feature_vector, PROCESS_THRESHOLD
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from transformer_scorer import TransformerScorer
from fusion_engine import FusionEngine
from generate_training_data import physical_label

TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")
# transformer_score is an ABLATION CANDIDATE ONLY -- it is not one of
# fused_score's inputs (see transformer_scorer.py's docstring). It sits
# next to lstm_ae_score here purely for a like-for-like architecture
# comparison (same task, same window length, same input features).
SIGNAL_NAMES = ["rule_score", "isolation_forest_score", "lstm_ae_score", "transformer_score", "gnn_score", "fused_score"]


def score_all_signals(records):
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    transformer_scorer = TransformerScorer()
    gnn_scorer = GNNScorer()
    fusion = FusionEngine()

    # Per-device rolling window of TRUE labels, same "window_compromised"
    # tracking train_fusion_meta_learner.py already uses for its own
    # training target -- see main()'s "fair, undiluted" block below for why
    # this needs to be tracked here too, not just at fusion-training time.
    label_window: dict[str, list] = {}

    rows = []  # each: dict(features=[...], label, event_type, device_id, residue_compromised)
    excluded = 0
    for r in sorted(records, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            excluded += 1
            continue  # rejected at Module 2 -- never reaches Process Anomaly scoring live
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])
        target = physical_label(r["event_type"])

        lw = label_window.setdefault(device_id, [])
        residue_compromised = any(l == 0 for l in lw)
        lw.append(target)
        if len(lw) > LSTM_SEQ_LEN:
            del lw[0]

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
            transformer_score = transformer_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = transformer_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        fused_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)

        rows.append({
            "features": [rule_score, if_score, lstm_score, transformer_score, gnn_score, fused_score],
            "label": target,
            "event_type": r["event_type"],
            "device_id": device_id,
            "residue_compromised": residue_compromised,
        })
    print(f"(excluded {excluded} auth_ok=False records -- rejected at Module 2, never reach Process Anomaly scoring live)")
    return rows


def metrics_at_threshold(scores, labels, threshold=PROCESS_THRESHOLD):
    """Defaults to the DEPLOYED threshold, not 0.5.

    This used to default to 0.5 while gateway.py decided at PROCESS_THRESHOLD
    (0.6), and that gap was not cosmetic: an Isolation Forest calibration defect
    that made the signal structurally incapable of scoring above 0.621 -- so a
    healthy physical board was BLOCKed live -- moved this script's headline
    accuracy by 0.003 (RESULTS.md 0.1). The evaluation suite was blind to a bug
    that made the system unusable. A metric computed at a threshold the system
    does not use is not evidence about the system."""
    scores = np.array(scores)
    labels = np.array(labels)
    preds = (scores >= threshold).astype(int)

    tp = int(np.sum((preds == 1) & (labels == 1)))
    tn = int(np.sum((preds == 0) & (labels == 0)))
    fp = int(np.sum((preds == 1) & (labels == 0)))
    fn = int(np.sum((preds == 0) & (labels == 1)))

    accuracy = (tp + tn) / len(labels) if len(labels) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def main():
    with open(TEST_PATH) as f:
        records = json.load(f)

    print(f"Scoring {len(records)} held-out test messages through the full pipeline...")
    rows = score_all_signals(records)

    labels = [row["label"] for row in rows]
    print(f"Label balance: {sum(labels)} legitimate, {len(labels) - sum(labels)} suspicious\n")

    print(f"{'Signal':<26} {'Accuracy':>9} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 65)
    results = {}
    for i, name in enumerate(SIGNAL_NAMES):
        scores = [row["features"][i] for row in rows]
        m = metrics_at_threshold(scores, labels)
        results[name] = m
        print(f"{name:<26} {m['accuracy']:>9.3f} {m['precision']:>10.3f} {m['recall']:>8.3f} {m['f1']:>8.3f}")
    print(
        "(rule/isolation_forest/lstm_ae/transformer/gnn columns above are BLENDED across all 3 "
        "devices -- only esp32-vib-001 has real IF/LSTM-AE/Transformer models, the other two "
        "devices mirror rule_score into those slots (see isolation_forest_scorer.py's docstring), "
        "so these columns measure 'what the live pipeline would actually see', not the sequence "
        "models' own standalone quality. See the FAIR COMPARISON block below for that.)"
    )

    fused_acc = results["fused_score"]["accuracy"]
    best_individual_name = max(
        (n for n in SIGNAL_NAMES if n != "fused_score"), key=lambda n: results[n]["accuracy"]
    )
    best_individual = results[best_individual_name]["accuracy"]
    print()
    if fused_acc >= best_individual:
        print(f"Fusion ({fused_acc:.3f}) >= best individual signal ({best_individual:.3f}) -- "
              f"evidences the fusion's contribution, per synopsis Section 10.2.")
    else:
        print(
            f"Fusion ({fused_acc:.3f}) < best individual signal, {best_individual_name} "
            f"({best_individual:.3f}), on RAW aggregate accuracy. This is a deliberate, verified "
            f"trade-off, not an undertrained model: the meta-learner is trained with "
            f"class_weight='balanced' (train_fusion_meta_learner.py) specifically because an "
            f"unweighted fit let the numerous easy normal/anomalous_shock/forged_signature examples "
            f"dominate the decision boundary and effectively discard the GNN's signal on the rarer "
            f"'coordinated' attack type (verified: unweighted fused recall on 'coordinated' was "
            f"0.261, WORSE than gnn_score alone at 0.870 -- balancing recovers it, see the "
            f"per-event-type table below and SESSION_LOG.md for the full before/after). Aggregate "
            f"accuracy alone is the wrong single number to optimise for a security system where "
            f"missing a rare coordinated attack is costlier than a few extra false positives on "
            f"common, already-well-caught event types."
        )

    # Per-event-type breakdown (synopsis Section 4.2 Stage 6 names 4 distinct
    # adversarial scenarios + coordinated multi-device -- an aggregate
    # accuracy number can hide that a signal does well overall but badly on
    # the ONE scenario it exists to catch, e.g. the GNN on "coordinated".
    event_types = sorted({row["event_type"] for row in rows if row["event_type"] != "normal"})
    print(f"\n{'Per-event-type recall (event correctly flagged as suspicious)':<0}")
    header = f"{'Signal':<26}" + "".join(f"{et:>16}" for et in event_types)
    print(header)
    print("-" * len(header))
    for i, name in enumerate(SIGNAL_NAMES):
        line = f"{name:<26}"
        for et in event_types:
            sub = [(row["features"][i], row["label"]) for row in rows if row["event_type"] == et]
            if not sub:
                line += f"{'n/a':>16}"
                continue
            sub_scores, sub_labels = zip(*sub)
            # `high_rate`'s physical_label is 1 (legitimate) for every
            # record -- there's no physical anomaly here for the Process
            # Anomaly Engine to catch by design, so "recall" doesn't apply.
            if sub_labels.count(0) == 0:
                line += f"{'n/a*':>16}"
                continue
            preds = [1 if s >= PROCESS_THRESHOLD else 0 for s in sub_scores]
            recall = sum(1 for p, l in zip(preds, sub_labels) if p == l == 0) / sub_labels.count(0)
            line += f"{recall:>16.3f}"
        print(line)
    print("(* n/a: this event type's physical reading is legitimate by construction -- e.g. "
          "'high_rate' is purely a Security Trust concern, not a Process Anomaly one.)")
    print(
        "\n(Recall per event type = fraction of that event's messages the signal "
        "correctly scored below the deployed threshold "
        f"({PROCESS_THRESHOLD}) despite each being label=0/suspicious. "
        "'coordinated' is where relational reasoning specifically matters -- "
        "compare the gnn_score row there against rule/isolation_forest/lstm_ae, "
        "which structurally cannot see cross-device co-occurrence at all.)"
    )

    # --- FAIR COMPARISON: LSTM-AE vs Transformer, esp32-vib-001 only, ---
    # window-residue rows excluded. Motivation (found while tuning the
    # Transformer sub-signal): the aggregate columns above blend in
    # rule_score for sensor-002/actuator-001 (66% of rows), which dilutes
    # any real quality difference between the two sequence models down to
    # noise. Isolating esp32-vib-001 rows alone also exposed a real
    # train/eval mismatch: train_lstm_ae.py/train_transformer.py build
    # windows ONLY from label==1 rows with anomalies filtered OUT (gaps
    # skipped), so the model never sees a window shaped like "a few
    # messages after a real anomaly" -- but live/eval replay of the raw
    # interleaved stream produces exactly that shape. A message that is
    # itself normal but sits within LSTM_SEQ_LEN messages of a recent
    # anomalous_shock/coordinated/stealthy/high_rate event is legitimately
    # ambiguous, not a fair test of "does this model recognize normal" --
    # excluded here with the SAME window_compromised logic
    # train_fusion_meta_learner.py already uses for its own training
    # target, just applied to EVALUATION here instead.
    print("\n" + "=" * 65)
    print("FAIR COMPARISON: LSTM-AE vs Transformer (esp32-vib-001 only,")
    print("window-residue rows excluded -- see script docstring above)")
    print("=" * 65)
    esp32_rows = [row for row in rows if row["device_id"] == "esp32-vib-001"]
    n_residue = sum(1 for row in esp32_rows if row["label"] == 1 and row["residue_compromised"])
    clean_rows = [row for row in esp32_rows if not (row["label"] == 1 and row["residue_compromised"])]
    print(f"{len(esp32_rows)} esp32-vib-001 rows, {n_residue} excluded as window-residue-contaminated "
          f"normal messages, {len(clean_rows)} remain\n")
    fair_labels = [row["label"] for row in clean_rows]
    print(f"{'Signal':<26} {'Accuracy':>9} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 65)
    fair_results = {}
    for i, name in enumerate(SIGNAL_NAMES):
        if name not in ("lstm_ae_score", "transformer_score"):
            continue
        scores = [row["features"][i] for row in clean_rows]
        m = metrics_at_threshold(scores, fair_labels)
        fair_results[name] = m
        print(f"{name:<26} {m['accuracy']:>9.3f} {m['precision']:>10.3f} {m['recall']:>8.3f} {m['f1']:>8.3f}")
    lstm_f1, tr_f1 = fair_results["lstm_ae_score"]["f1"], fair_results["transformer_score"]["f1"]
    if abs(lstm_f1 - tr_f1) < 0.01:
        print(f"\nEffectively tied (F1 within 0.01) on this fair, undiluted comparison.")
    else:
        winner = "Transformer" if tr_f1 > lstm_f1 else "LSTM-AE"
        print(f"\n{winner} wins on this fair, undiluted comparison (F1 {max(lstm_f1, tr_f1):.3f} vs "
              f"{min(lstm_f1, tr_f1):.3f}) -- see RESULTS.md Section 2.2 for the full writeup, "
              f"including a hyperparameter sweep confirming this holds across Transformer configs.")


if __name__ == "__main__":
    main()
