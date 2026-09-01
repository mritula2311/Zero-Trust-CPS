"""
docs/10_testing_and_attack_simulation.md Section 4: "RL policy reward trend
vs. the static-threshold baseline" (Section 5's ablation-style comparison)
AND Section 4.1's multi-class confusion matrix -- the final Module 5
decision has four possible outputs (ALLOW/STEP_UP/ALERT/BLOCK) against four
ground-truth situation classes, which plain precision/recall/F1 (the right
tool for each individual Module 3 signal) is the wrong tool to evaluate
alone.

TWO-SCORE REARCHITECTURE: everything here now operates on
(security_trust_score, process_trust_score, situation) triples instead of
(trust, confidence, label) -- see train_adaptive_pdp.py's
build_training_triples(), reused directly here so the replay logic (a
STATEFUL Security Trust engine, one shared instance across the whole
ordered replay) never has two independent implementations that could drift
apart.

Three things reported:
1. Held-out comparison: the ALREADY-DEPLOYED AdaptivePDP
   (models/adaptive_pdp_qtable.json) vs. the static 2x2 policy_engine.decide(),
   both scored by AdaptivePDP.reward_for() against real ground-truth
   situations on data/collected/test_session.json.
2. Convergence trend: trains a FRESH bandit from scratch (does NOT touch
   the deployed Q-table) over the training data, to show it actually
   converges rather than asserting it does.
3. Multi-class confusion matrix + macro-F1 for both policies on the
   held-out set.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, RL_TRAINING_EPISODES
import json
from policy_engine import decide
from adaptive_pdp import AdaptivePDP, ACTIONS, CORRECT_ACTION_FOR_SITUATION
from train_adaptive_pdp import build_training_triples, situation_weights

TRAIN_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
TEST_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")

SITUATIONS = ["normal", "physical_fault", "security_concern", "combined"]


def _load_triples(path):
    with open(path) as f:
        records = json.load(f)
    return build_training_triples(records)


def evaluate_static_vs_rl(triples):
    pdp = AdaptivePDP()  # loads the already-trained, deployed Q-table -- read-only here
    if not pdp.is_trained():
        raise SystemExit("adaptive_pdp_qtable.json not found -- run scripts/train_adaptive_pdp.py first.")

    policies = {
        "Static": lambda sec, proc: decide(sec, proc),
        "RL (greedy)": lambda sec, proc: pdp.greedy_action(sec, proc),
        "RL (epsilon=0.1)": lambda sec, proc: pdp.choose_action(sec, proc),
    }
    totals = {name: 0.0 for name in policies}
    decisions = {name: {a: 0 for a in ACTIONS} for name in policies}

    for security, process, situation in triples:
        for name, policy_fn in policies.items():
            action = policy_fn(security, process)
            totals[name] += AdaptivePDP.reward_for(action, situation)
            decisions[name][action] += 1

    n = len(triples)
    print(f"Held-out comparison on {n} authenticated messages (data/collected/test_session.json):\n")
    print(f"{'Policy':<18} {'Avg reward':>12} {'ALLOW':>7} {'ALERT':>7} {'STEP_UP':>9} {'BLOCK':>7}")
    print("-" * 66)
    for name in policies:
        d = decisions[name]
        print(f"{name:<18} {totals[name]/n:>12.3f} {d['ALLOW']:>7} {d['ALERT']:>7} {d['STEP_UP']:>9} {d['BLOCK']:>7}")
    print(
        "\nNote: 'RL (epsilon=0.1)' is included for contrast only, not as the fair comparison --\n"
        "epsilon-greedy exploration is a TRAINING-time technique. gateway.py calls greedy_action()\n"
        "(see adaptive_pdp.py's docstring) -- 'RL (greedy)' vs 'Static' is the real comparison."
    )
    return policies


def confusion_matrix(triples, policy_fn, label: str):
    """Actual situation x predicted action -- the multi-class evaluation
    docs/10_testing_and_attack_simulation.md Section 4.1 asks for, since
    the four-way decision has four outcomes against four situation types,
    not just "attack vs. normal"."""
    counts = {s: {a: 0 for a in ACTIONS} for s in SITUATIONS}
    for security, process, situation in triples:
        action = policy_fn(security, process)
        counts[situation][action] += 1

    print(f"\nConfusion matrix -- {label} (rows: actual situation, columns: predicted action)\n")
    header = f"{'Actual \\ Predicted':<28}" + "".join(f"{a:>10}" for a in ACTIONS)
    print(header)
    print("-" * len(header))
    for s in SITUATIONS:
        row = counts[s]
        print(f"{s:<28}" + "".join(f"{row[a]:>10}" for a in ACTIONS))

    # macro-F1: each situation's "positive" is predicting its own correct
    # action (docs/10 Section 4.1's exact definition) -- average the
    # per-class F1, not one pooled number.
    f1s = []
    for s in SITUATIONS:
        correct_action = CORRECT_ACTION_FOR_SITUATION[s]
        tp = counts[s][correct_action]
        fn = sum(counts[s][a] for a in ACTIONS) - tp
        fp = sum(counts[other][correct_action] for other in SITUATIONS if other != s)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1s.append(f1)
        print(f"  {s:<20} correct_action={correct_action:<8} precision={precision:.3f} recall={recall:.3f} F1={f1:.3f}")
    macro_f1 = sum(f1s) / len(f1s)
    print(f"  macro-F1 = {macro_f1:.3f}")
    if "combined" in SITUATIONS:
        combined_recall = counts["combined"][CORRECT_ACTION_FOR_SITUATION["combined"]] / max(
            1, sum(counts["combined"].values())
        )
        print(
            f"  ('combined' includes stealthy_forged_values -- a low recall here "
            f"({combined_recall:.3f}) is the expected, honestly-reported result "
            f"per docs/04_module3_trust_evaluation.md Section B.8, not a bug.)"
        )
    return macro_f1


def convergence_trend(triples):
    # Mirrors scripts/train_adaptive_pdp.py's deployed training procedure exactly,
    # INCLUDING its exclusion of the unlearnable 'combined'/stealthy_forged_values
    # class (see the long comment there). Without this the convergence figure would
    # be charting a bandit trained differently from the one actually deployed --
    # precisely the figure-vs-script drift this project's figures are supposed to
    # be immune to. The CONFUSION MATRICES above deliberately still score
    # 'combined', because not detecting it is a result worth reporting honestly;
    # it is only excluded from what the policy TRAINS on.
    triples = [t for t in triples if t[2] != "combined"]
    print(f"\nConvergence trend -- training a FRESH bandit from scratch on "
          f"{len(triples)} training messages (does not touch the deployed "
          f"models/adaptive_pdp_qtable.json), {RL_TRAINING_EPISODES} episodes, "
          f"situation-balanced reward (same weighting scripts/train_adaptive_pdp.py "
          f"uses for the deployed model -- see situation_weights()'s docstring):\n")
    weights = situation_weights(triples)
    pdp = AdaptivePDP()
    # AdaptivePDP() loads the already-deployed adaptive_pdp_qtable.json in its
    # constructor, so without this reset the "fresh" bandit would actually be
    # warm-started from the fully-trained table -- episode 0 would already
    # show near-optimal reward and the from-scratch convergence claim in this
    # function's docstring/header would be false. Start from an empty Q-table
    # so the trend genuinely demonstrates learning rather than asserting it.
    pdp.q = {}
    for episode in range(RL_TRAINING_EPISODES):
        total_reward = 0.0
        for security, process, situation in triples:
            action = pdp.choose_action(security, process)
            reward = AdaptivePDP.reward_for(action, situation) * weights[situation]
            pdp.update(security, process, action, reward)
            total_reward += reward
        print(f"  episode {episode:>3}: avg reward = {total_reward/len(triples):.3f}")


def main():
    print("Scoring held-out and training sessions through the full two-score pipeline...\n")
    test_triples = _load_triples(TEST_PATH)
    policies = evaluate_static_vs_rl(test_triples)

    deployed_pdp = policies["RL (greedy)"]
    static_policy = policies["Static"]
    confusion_matrix(test_triples, static_policy, "Static 2x2 table")
    confusion_matrix(test_triples, deployed_pdp, "RL (greedy, deployed)")

    train_triples = _load_triples(TRAIN_PATH)
    convergence_trend(train_triples)


if __name__ == "__main__":
    main()
