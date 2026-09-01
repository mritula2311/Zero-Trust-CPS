"""
Offline training for Module 5 (RL-Adaptive Access Control).

adaptive_pdp.AdaptivePDP.choose_action() in the live gateway path only ever
reads the resulting Q-table (with epsilon-greedy SELECTION, not learning).
Run this LAST -- it replays the training session through the fully trained
Process Anomaly pipeline AND a fresh Security Trust engine, then trains
against the reward computed from the REAL ground-truth event_type.

TWO-SCORE REARCHITECTURE: state is now
(security_trust_score, process_trust_score) instead of (trust, confidence),
and training excludes every record with auth_ok=False OR event_type ==
"replay" -- both represent messages Module 2 rejects outright in the live
architecture (see gateway.py's _reject() / trust_engine.IdentityTargetingRisk),
so they never reach the policy layer live and shouldn't be trained on as
if they did.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, RL_TRAINING_EPISODES
import feature_engineering as fe
from trust_engine import RuleBasedTrustEngine, rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
from gnn_scorer import GNNScorer
from fusion_engine import FusionEngine
from adaptive_pdp import AdaptivePDP
from generate_training_data import situation_for_event_type

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")


def build_training_triples(records: list[dict]) -> list[tuple[float, float, str]]:
    """Replays the labelled session IN ORDER through the full two-score
    pipeline, exactly as gateway.py's process_telemetry() would -- Security
    Trust Score is STATEFUL (EWMA + decay per device, via one shared
    trust_engine instance across the whole replay), so record order
    matters."""
    trust_engine = RuleBasedTrustEngine()
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    gnn_scorer = GNNScorer()
    fusion = FusionEngine()

    triples = []
    for r in sorted(records, key=lambda rec: rec["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            # Rejected at Module 2 in the live architecture -- never reaches
            # the policy layer. A replay has a VALID HMAC (auth_ok=True) by
            # construction; it's the boot/seq check that rejects it, not
            # the signature check -- so this needs an explicit event_type
            # check, not just the auth_ok filter.
            continue
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])

        if device_id == "esp32-vib-001":
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        gnn_score = gnn_scorer.score(device_id, rule_score, if_score, lstm_score)
        process_trust_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, gnn_score)

        is_flood = r.get("simulated_flood", False)
        security_trust_score, _ = trust_engine.score_security_trust(device_id, is_flood, step_up_result=None)

        situation = situation_for_event_type(r["event_type"])
        triples.append((security_trust_score, process_trust_score, situation))

    return triples


def situation_weights(triples: list[tuple[float, float, str]]) -> dict[str, float]:
    """Inverse-frequency weighting (same formula sklearn's
    class_weight='balanced' uses), applied to the reward during Q-learning
    -- the direct RL analogue of train_fusion_meta_learner.py's
    class_weight='balanced' fix, and needed for the same underlying reason.
    'normal' outnumbers 'physical_fault'/'security_concern'/'combined' by
    roughly 10-20x in this dataset; without weighting, a discretized state
    bucket that both a 'normal' example and a rarer situation's example
    happen to land in gets dominated by whichever reward sign visits it
    more often -- verified empirically before adding this: unweighted
    training left 'physical_fault' recall at 0.125 (WORSE than the static
    table's trivial 1.000), even though the fused Process Anomaly signal
    itself cleanly separates physical_fault events (1.000 ablation recall)
    -- the raw score was fine, the imbalanced Q-learning signal was not."""
    counts: dict[str, int] = {}
    for _, _, situation in triples:
        counts[situation] = counts.get(situation, 0) + 1
    n_classes = len(counts)
    total = len(triples)
    return {s: total / (n_classes * c) for s, c in counts.items()}


def main():
    with open(SESSION_PATH) as f:
        records = json.load(f)

    print("building (security_trust, process_trust, situation) triples "
          "(replaying through the full two-score pipeline)...")
    triples = build_training_triples(records)
    excluded = sum(1 for r in records if not r["auth_ok"] or r["event_type"] == "replay")
    print(f"built {len(triples)} triples (excluded {excluded} rejected/auth_ok=False/replay records)")

    weights = situation_weights(triples)
    print(f"situation weights (inverse-frequency, mirrors train_fusion_meta_learner.py's "
          f"class_weight='balanced'): {dict(sorted(weights.items()))}")

    pdp = AdaptivePDP()
    for episode in range(RL_TRAINING_EPISODES):
        total_reward = 0.0
        for security_trust, process_trust, situation in triples:
            action = pdp.choose_action(security_trust, process_trust)
            reward = AdaptivePDP.reward_for(action, situation) * weights[situation]
            pdp.update(security_trust, process_trust, action, reward)
            total_reward += reward
        if episode % 5 == 0 or episode == RL_TRAINING_EPISODES - 1:
            print(f"  episode {episode}: total_reward={total_reward:.1f} / {len(triples)} decisions, "
                  f"{len(pdp.q)} states visited")

    pdp.save()
    print(f"trained AdaptivePDP over {RL_TRAINING_EPISODES} episodes, {len(pdp.q)} states, "
          f"saved to models/adaptive_pdp_qtable.json")


if __name__ == "__main__":
    main()
