"""
Offline training for Module 3, Phase 7 (Fusion Engine).

CLAUDE.md Section 8: training happens here; fusion_engine.FusionEngine
only ever loads the resulting artifacts and runs inference. Run this
AFTER train_isolation_forest.py, train_lstm_ae.py, and train_gnn.py -- it
replays a session through all three (now-trained) scorers to build the
[rule, if, lstm, gnn] -> label dataset, per synopsis Section 4.2 Stage 4
("train the four trust-signal models independently, then train the
stacking meta-learner on top of their outputs").

LEAKAGE FIX (docs/REPOSITORY_AUDIT.md 2.1, reviewer concern H). This
script used to replay `training_session.json` -- the SAME session the
three base models were fitted on. Base-model scores on their own training
data are optimistic, so the meta-learner learned coefficients calibrated
to in-sample behaviour it will never see at inference. It now replays
`validation_session.json` (a distinct simulated session, seed 4242, that
no base model has seen) plus the real VALIDATION-split hardware session.

    TRAIN       -> Isolation Forest, LSTM-AE, Transformer, GNN
    VALIDATION  -> this meta-learner, and threshold selection
    TEST        -> touched once, at the end, by evaluation only

Held-out stacking, not out-of-fold stacking: with a base-model chain this
stateful (the LSTM-AE carries a rolling window; the GNN carries a graph
snapshot) a k-fold refit would mean k full retrains of every model and k
sets of artifacts, and the honest gain over one clean held-out split is
not worth that. The choice is recorded here rather than left implicit.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import joblib
from sklearn.linear_model import LogisticRegression

from config import DATA_COLLECTED_DIR, MODELS_DIR, FUSION_MODEL_PATH, FUSION_BACKGROUND_PATH, FUSION_SHAP_BACKGROUND_SIZE, LSTM_SEQ_LEN, is_feature_vector
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from generate_training_data import physical_label
import splits

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "validation_session.json")

# NOT included: the real VALIDATION-split hardware session (20260902_173108).
# Measured before deciding, not assumed: that session holds 47 records, and the
# 2*LSTM_SEQ_LEN per-block warmup discard that evaluate_real_hardware.py
# applies for good reason (CLAUDE.md, "Filling the LSTM window is not the same
# as clearing it") leaves ~15 scoreable rows. Fifteen rows cannot meaningfully
# move a four-coefficient logistic fit against ~2900 synthetic ones, and adding
# a second stateful replay path to carry them would be complexity bought for no
# measurable effect. The real validation session is used where its size IS
# sufficient -- threshold selection (scripts/select_thresholds.py), which needs
# a decision boundary rather than a fit.


def build_dataset(records):
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()

    # Mirrors lstm_scorer's OWN internal per-device rolling window
    # (lstm_ae_scorer.py's `self._history`), but tracking each window
    # slot's TRUE label instead of its feature vector. Why this exists:
    # lstm_ae_scorer.py is STATEFUL -- a single anomalous message's effect
    # on reconstruction error persists in the window for the next
    # LSTM_SEQ_LEN-1 messages after it, verified empirically (see
    # SESSION_LOG.md): a shock at tick 7 holds lstm_score at the hard
    # floor (0.0) through tick 14, only clearing at tick 15. Most of those
    # 7 "recovery" messages are themselves perfectly legitimate
    # (label=1) -- but training the meta-learner against the raw
    # per-message label taught it that lstm_score=0.0 routinely co-occurs
    # with label=1, which is EXACTLY backwards from lstm_score's intended
    # meaning. Confirmed by inspecting the trained model directly:
    # coefficient on lstm_ae_score came out at -0.46 (negative), the only
    # one of the four signals with the wrong sign (isolation_forest_score
    # +4.41, gnn_score +5.51 -- both correctly positive).
    #
    # Fix: a `window_compromised` flag, true when ANY message currently
    # sitting in this device's LSTM window (before the current message
    # enters it) was itself a true anomaly -- computed from the window's
    # ACTUAL live state during this same replay, not guessed from
    # event_type or tick arithmetic (verified a "coordinated" event's
    # randomised severity can occasionally contaminate the window too, not
    # just "anomalous_shock" -- an event_type-based heuristic would have
    # missed that case).
    #
    # First attempt RELABELLED these residue messages as suspicious
    # (label=0) instead of excluding them -- fixed the sign, but caused a
    # real regression (verified, not assumed): 'coordinated' recall
    # collapsed from 0.913 to 0.304, because relabelling ~300 residue
    # messages as "suspicious" shifted the overall class balance from
    # ~10:90 to ~36:64, which dilutes class_weight="balanced"'s upweighting
    # of the genuinely rare 'coordinated' pattern -- the exact regression
    # SESSION_LOG.md's earlier entry already fought to fix once. These
    # residue messages are legitimately AMBIGUOUS (not confidently either
    # class), so the correct move is to EXCLUDE them from the meta-learner's
    # training set entirely rather than forcing them into either class --
    # this removes the wrong-sign-teaching examples without inflating the
    # suspicious class or disturbing the balance class_weight="balanced"
    # was tuned around. Only affects which rows this function contributes
    # to X/y. The scorers still see and are updated by EVERY record that
    # actually reaches this replay in tick order (excluding a row from
    # training must not skip advancing lstm_scorer's/gnn_scorer's own
    # internal state, or every score computed after an excluded row would
    # be wrong).
    #
    # TWO-SCORE REARCHITECTURE: two further fixes on top of the above.
    # (1) The ground-truth target is physical_label(event_type), not the
    #     old blended `label` -- a `high_rate` record's features are
    #     genuinely normal (only the message RATE is suspicious, a
    #     Security Trust concern), so pairing them with label=0 injected
    #     pure noise: examples where every one of the four input features
    #     looked completely ordinary, paired with a "suspicious" target the
    #     features gave no reason to predict. This alone caused a real,
    #     measured regression when first discovered (fused aggregate
    #     accuracy on the held-out test set dropped to ~0.68, 'coordinated'
    #     recall to ~0.30) -- see SESSION_LOG.md for the numbers.
    # (2) `auth_ok=False` and `event_type=="replay"` records are SKIPPED
    #     entirely (no scorer calls, no state advancement, no X/y row) --
    #     Module 2 rejects both before they ever reach Module 3 live, so
    #     there is no live analogue of "what would fusion see right after
    #     a rejected message" for the meta-learner to train against. The
    #     old AUTH_FAIL_SENTINEL_SCORE injection made sense under the
    #     single-score architecture (every message, rejected or not, fed
    #     the one trust score); it does not under this one.
    label_window: dict[str, list[int]] = {}

    X, y = [], []
    for r in sorted(records, key=lambda r: r["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            continue  # rejected at Module 2 -- never reaches Module 3 live
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])
        target = physical_label(r["event_type"])
        window_compromised = False

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
            lw = label_window.setdefault(device_id, [])
            window_compromised = any(l == 0 for l in lw)
            lw.append(target)
            if len(lw) > LSTM_SEQ_LEN:
                del lw[0]
        else:
            if_score = lstm_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)

        if target == 1 and window_compromised:
            continue  # ambiguous residue -- excluded, not relabelled (see above)

        X.append([rule_score, if_score, lstm_score, gnn_score])
        y.append(target)

    return np.array(X), np.array(y)


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    splits.assert_disjoint()
    print(f"meta-training on VALIDATION split: {os.path.basename(SESSION_PATH)} "
          f"({len(records)} records). Base models were fitted on TRAIN and are frozen here.")
    print("building fusion training set (replaying through trained IF/LSTM-AE/GNN scorers)...")
    X, y = build_dataset(records)
    print(f"built {len(X)} examples, class balance: {np.bincount(y.astype(int))}")

    if len(set(y.tolist())) < 2:
        raise SystemExit("only one class present in labels -- need both 0 and 1 examples to train a classifier")

    # class_weight="balanced" -- with suspicious examples at ~10% of the
    # training set and "coordinated" a further subset of those (~4% of the
    # total), an unweighted fit lets the numerous easy-to-separate normal
    # examples dominate the hyperplane, discounting whatever the
    # comparatively rare minority-pattern gnn_score signal is saying (see
    # SESSION_LOG.md -- this was verified empirically, not assumed: without
    # this, fused_score's recall on "coordinated" was WORSE than gnn_score
    # alone, meaning fusion was actively discarding the one signal built to
    # catch that scenario).
    model = LogisticRegression(max_iter=500, class_weight="balanced")
    model.fit(X, y)
    train_acc = model.score(X, y)
    print(f"trained LogisticRegression, training accuracy={train_acc:.3f}, coefficients={model.coef_[0].round(3)}")

    rng = np.random.default_rng(0)
    background_idx = rng.choice(len(X), min(FUSION_SHAP_BACKGROUND_SIZE, len(X)), replace=False)
    background = X[background_idx]

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model, FUSION_MODEL_PATH)
    np.save(FUSION_BACKGROUND_PATH, background)
    print(f"saved fusion model to {FUSION_MODEL_PATH}, SHAP background ({len(background)} samples) to {FUSION_BACKGROUND_PATH}")


if __name__ == "__main__":
    main()
