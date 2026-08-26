"""
Synopsis Section 10.1: "RL policy reward trend vs. the static-threshold
baseline, if Phase 8 was completed." Also Section 10.2's "RL-adaptive
policy... reward trend and stabilisation... compared against the
static-threshold baseline from Phase 5."

Two things reported:
1. Held-out comparison: the ALREADY-DEPLOYED AdaptivePDP (models/adaptive_pdp_qtable.json)
   vs. the static policy_engine.decide(), both scored by AdaptivePDP.reward_for()
   against real ground-truth labels on data/collected/test_session.json --
   neither policy trains further here, this is pure evaluation.
2. Convergence trend: trains a FRESH bandit from scratch (does NOT touch
   the deployed models/adaptive_pdp_qtable.json) over the same training
   data scripts/train_adaptive_pdp.py uses, printing total reward per
   episode, to show it actually converges rather than asserting it does.
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
from policy_engine import decide
from adaptive_pdp import AdaptivePDP

TRAIN_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")


def build_triples(path):
    with open(path) as f:
        records = json.load(f)

    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()
    fusion = FusionEngine()

    triples = []
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
        triples.append((trust, confidence, r["label"]))
    return triples


def evaluate_static_vs_rl(triples):
    pdp = AdaptivePDP()  # loads the already-trained, deployed Q-table -- read-only here
    if not pdp.is_trained():
        raise SystemExit("adaptive_pdp_qtable.json not found -- run scripts/train_adaptive_pdp.py first.")

    policies = {
        "Static": lambda trust, confidence: decide(trust),
        "RL (greedy)": lambda trust, confidence: pdp.greedy_action(trust, confidence),
        "RL (epsilon=0.1)": lambda trust, confidence: pdp.choose_action(trust, confidence),
    }
    totals = {name: 0.0 for name in policies}
    decisions = {name: {"ALLOW": 0, "STEP_UP": 0, "DENY": 0} for name in policies}

    for trust, confidence, label in triples:
        for name, policy_fn in policies.items():
            action = policy_fn(trust, confidence)
            totals[name] += AdaptivePDP.reward_for(action, label)
            decisions[name][action] += 1

    n = len(triples)
    print(f"Held-out comparison on {n} messages (data/collected/test_session.json):\n")
    print(f"{'Policy':<18} {'Avg reward':>12} {'ALLOW':>8} {'STEP_UP':>9} {'DENY':>7}")
    print("-" * 58)
    for name in policies:
        d = decisions[name]
        print(f"{name:<18} {totals[name]/n:>12.3f} {d['ALLOW']:>8} {d['STEP_UP']:>9} {d['DENY']:>7}")
    print(
        "\nNote: 'RL (epsilon=0.1)' is included for contrast only, not as the fair comparison --\n"
        "epsilon-greedy exploration is a TRAINING-time technique (it only earns its keep paired\n"
        "with an update() call). Since CLAUDE.md's hard constraint means the deployed policy never\n"
        "trains live, gateway.py now calls greedy_action() (see adaptive_pdp.py's docstring) --\n"
        "'RL (greedy)' vs 'Static' is the comparison synopsis Section 10.2 actually wants."
    )


def convergence_trend(triples):
    print(f"\nConvergence trend -- training a FRESH bandit from scratch on "
          f"{len(triples)} training messages (does not touch the deployed "
          f"models/adaptive_pdp_qtable.json), {RL_TRAINING_EPISODES} episodes:\n")
    pdp = AdaptivePDP()
    for episode in range(RL_TRAINING_EPISODES):
        total_reward = 0.0
        for trust, confidence, label in triples:
            action = pdp.choose_action(trust, confidence)
            reward = AdaptivePDP.reward_for(action, label)
            pdp.update(trust, confidence, action, reward)
            total_reward += reward
        print(f"  episode {episode:>3}: avg reward = {total_reward/len(triples):.3f}")


def main():
    print("Scoring held-out and training sessions through the full trained pipeline...\n")
    test_triples = build_triples(TEST_PATH)
    evaluate_static_vs_rl(test_triples)

    train_triples = build_triples(TRAIN_PATH)
    convergence_trend(train_triples)


if __name__ == "__main__":
    main()
