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
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, RL_TRAINING_EPISODES, is_feature_vector, TRAINING_SEED
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

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
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

    # UNLEARNABLE-CLASS EXCLUSION. 'combined' is the stealthy_forged_values
    # scenario: a compromised device reporting deliberately innocuous, fully
    # in-range values behind valid credentials. docs/04_module3_trust_
    # evaluation.md Section B.8 states plainly that this is NOT detectable
    # from telemetry -- its feature vectors are, by construction, drawn from
    # the same distribution as genuinely normal ones. A policy keyed on
    # (security_trust, process_trust) therefore cannot separate it from
    # normal traffic, and training against it does not teach detection: it
    # only teaches the policy to BLOCK the region where normal traffic lives.
    # With inverse-frequency weighting that effect was severe -- measured on
    # state 9,8 (security 0.9-1.0, process 0.8-0.9): 3295 genuinely normal
    # messages vs 69 stealthy ones, a 48:1 legitimate majority, which the
    # 22.66x 'combined' weight flipped to 1564 vs 948 of weighted reward mass.
    # The trained policy answered BLOCK for a healthy device at security=0.91
    # / process=0.87, where the static 2x2 table (policy_engine.decide())
    # correctly answers ALLOW. Excluding the class restores a monotonic policy
    # (ALERT while the process score is low, ALLOW once it recovers) and keeps
    # inverse-frequency weighting for physical_fault/security_concern, which
    # ARE separable in this state space and still drive ALERT/STEP_UP.
    # BLOCK remains reachable: the static table still returns it for the
    # low-security/low-process quadrant, and gateway.py forces it outright on
    # a failed step-up challenge.
    triples = [t for t in triples if t[2] != "combined"]
    print(f"excluded 'combined'/stealthy_forged_values triples as unlearnable from this "
          f"state space (see comment above) -- {len(triples)} triples remain")

    weights = situation_weights(triples)
    print(f"situation weights (inverse-frequency, mirrors train_fusion_meta_learner.py's "
          f"class_weight='balanced'): {dict(sorted(weights.items()))}")

    # Reproducible, from-scratch training. AdaptivePDP() loads any existing
    # adaptive_pdp_qtable.json in its constructor -- reset to empty so a
    # re-run trains fresh against the current dataset instead of accumulating
    # onto a stale prior table (whose states may no longer even be reachable
    # if the data changed). random.seed() pins epsilon-greedy exploration so
    # the committed Q-table is reproducible from the same inputs.
    random.seed(TRAINING_SEED)
    pdp = AdaptivePDP()
    pdp.q = {}
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
