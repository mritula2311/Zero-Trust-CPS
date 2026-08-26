"""
Offline training for Module 5, Phase 8 (RL-Adaptive Access Control).

CLAUDE.md Section 8: training happens here -- Q-learning updates run
against the labelled training session for config.RL_TRAINING_EPISODES
passes; adaptive_pdp.AdaptivePDP.choose_action() in the live gateway path
only ever reads the resulting Q-table (with epsilon-greedy SELECTION, not
learning). Run this LAST -- it replays the session through the fully
trained fusion engine to get each message's (trust, confidence), then
trains against the reward computed from the REAL ground-truth label.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, RL_TRAINING_EPISODES
import feature_engineering as fe
from trust_engine import rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from adaptive_pdp import AdaptivePDP

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")


def build_trust_confidence_label(records):
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()
    fusion = FusionEngine()

    out = []
    for r in sorted(records, key=lambda r: r["tick"]):
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])

        if not r["auth_ok"]:
            if_score = lstm_score = 0.1
        elif device_id == "esp32-vib-001":
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        trust, confidence, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)
        out.append((trust, confidence, r["label"]))

    return out


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    print("building (trust, confidence, label) triples (replaying through the full trained pipeline)...")
    triples = build_trust_confidence_label(records)
    print(f"built {len(triples)} triples")

    pdp = AdaptivePDP()
    for episode in range(RL_TRAINING_EPISODES):
        total_reward = 0.0
        for trust, confidence, label in triples:
            action = pdp.choose_action(trust, confidence)
            reward = AdaptivePDP.reward_for(action, label)
            pdp.update(trust, confidence, action, reward)
            total_reward += reward
        if episode % 5 == 0 or episode == RL_TRAINING_EPISODES - 1:
            print(f"  episode {episode}: total_reward={total_reward:.1f} / {len(triples)} decisions, {len(pdp.q)} states visited")

    pdp.save()
    print(f"trained AdaptivePDP over {RL_TRAINING_EPISODES} episodes, {len(pdp.q)} states, saved to models/adaptive_pdp_qtable.json")


if __name__ == "__main__":
    main()
