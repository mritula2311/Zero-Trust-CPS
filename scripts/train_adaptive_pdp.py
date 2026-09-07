"""
Offline training for Module 5 (RL-Adaptive Access Control).

adaptive_pdp.AdaptivePDP.choose_action() in the live gateway path only ever
reads the resulting Q-table (with epsilon-greedy SELECTION, not learning).
Run this LAST -- it replays a session through the fully trained
Process Anomaly pipeline AND a fresh Security Trust engine, then trains
against the reward computed from the REAL ground-truth event_type.

TERMINOLOGY (docs/REPOSITORY_AUDIT.md 2.6). Despite the RL_* config names
this is not reinforcement learning. The update rule in adaptive_pdp.py is
an incremental SAMPLE AVERAGE, there is no discount factor and no
next-state bootstrapping, and the reward is a fixed function of
(state, action) alone. It is a CONTEXTUAL BANDIT with sample-average
action-value estimation -- which is the right method here, because the
problem genuinely has no state transitions to credit. The names are kept
to avoid a rename touching every call site; the method is described
correctly in docs/ADAPTIVE_POLICY_SPEC.md and the manuscript.

SPLIT (docs/REPOSITORY_AUDIT.md 2.1/2.3). This used to replay
`training_session.json`, on which every base model was fitted. It now
replays `validation_policy_session.json` (SIM_SESSION_VAL_002) -- a
DIFFERENT validation draw from the one the fusion meta-learner was fitted
on (SIM_SESSION_VAL_001). Two draws, not one, because this stage consumes
fusion's output: sharing a session would leave the policy reading
in-sample fusion scores, which is the same optimism one level up.

TWO-SCORE REARCHITECTURE: state is now
(security_trust_score, process_trust_score) instead of (trust, confidence),
and training excludes every record with auth_ok=False OR event_type ==
"replay" -- both represent messages Module 2 rejects outright in the live
architecture (see gateway.py's _reject() / trust_engine.IdentityTargetingRisk),
so they never reach the policy layer live and shouldn't be trained on as
if they did.

EXPLICIT RELATIONAL/FUSION ARTIFACT PINNING (comparator-repair follow-up,
2026-09-07). This script used to build its relational scorer and fusion
engine via bare GNNScorer() + FusionEngine(), which both read whatever
config.GNN_MODEL_PATH / config.FUSION_MODEL_PATH currently mean. That was a
correct pairing until the M6 deployment (3c827e8) overwrote
FUSION_MODEL_PATH with the M6-fitted model -- after which this script's own
"GCN" training run (it always used GNNScorer(), true GCN, regardless of
what got deployed) silently trained against M6-calibrated fusion
coefficients instead of GCN-matched ones. That is exactly how
models/adaptive_pdp_qtable.json's provenance got corrupted (see
results/gcn_m6_corrected_comparison/summary.md finding 2 and
artifact_lineage.json's policy_artifact_note). Fixed by requiring an
explicit src/relational_pin.py RelationalPin -- selected via
ZTCPS_ADAPTIVE_PDP_PIN (gcn / m6_deployed / m6_corrected, default gcn,
which reproduces the pre-M6-deployment intended pairing and carries no
ambient-config dependency), never the ambient default. The output path is
independently selectable via ZTCPS_ADAPTIVE_PDP_OUTPUT (default: the
ambient config.ADAPTIVE_PDP_MODEL_PATH, unchanged from before this fix, so
this script's default invocation still writes where it always has) --
kept separate from the pin selection so training a new comparator artifact
never has to overwrite the historically deployed table by accident. A
metadata sidecar (relational_pin.policy_meta_path()) is always written
alongside the Q-table recording the pin's identity (checkpoint + fusion
hashes), training data hash, seed, clock protocol and commit hash, so
relational_pin.verify_policy_lineage() can catch a future evaluator
pairing this Q-table with the wrong pin instead of silently mis-scoring it
-- see that function's docstring.

DETERMINISTIC CLOCK (same follow-up). GNNScorer/SetTransformerScorer's
active-neighbour window AND RuleBasedTrustEngine's Security Trust EWMA
decay both used real time.time() even during this offline, record-by-record
replay -- so both which devices counted as "active" and how much a
device's trust decayed between messages depended on how fast the host
machine executed the loop, not on the data. Verified non-deterministic:
repeated runs of the pre-fix comparator produced different s_sec/s_proc
values from identical inputs (see
results/gcn_m6_corrected_comparison/policy_comparison.json's "finding", and
tests/test_policy_training_determinism.py's
test_repeated_replays_produce_identical_triples, which failed before this
fix on a real second-decimal discrepancy in security_trust_score). This
script now injects one deterministic clock, shared by both the relational
scorer and the trust engine, derived from each replayed record's own `ts`
field (already a simulated wall-clock timestamp in milliseconds -- see
scripts/generate_training_data.py), so the same data + seed + artifacts
always produce the same triples, independent of wall-clock execution speed.
"""

import hashlib
import json
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR, RL_TRAINING_EPISODES, RL_EPSILON, ADAPTIVE_PDP_MODEL_PATH, is_feature_vector, TRAINING_SEED
import feature_engineering as fe
from trust_engine import RuleBasedTrustEngine, rule_range_score
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer
import relational_pin as rp
from adaptive_pdp import AdaptivePDP
from generate_training_data import situation_for_event_type

SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "validation_policy_session.json")


def deterministic_clock(box: dict):
    """Returns a zero-arg callable reading box["t"] -- the caller updates
    box["t"] to each replayed record's own timestamp (seconds) before
    scoring it, giving GNNScorer/SetTransformerScorer a clock that depends
    only on the data, never on wall-clock execution speed."""
    return lambda: box["t"]


def build_training_triples(records: list[dict], pin: rp.RelationalPin = rp.GCN) -> list[tuple[float, float, str]]:
    """Replays the labelled session IN ORDER through the full two-score
    pipeline, exactly as gateway.py's process_telemetry() would -- Security
    Trust Score is STATEFUL (EWMA + decay per device, via one shared
    trust_engine instance across the whole replay), so record order
    matters.

    `pin` selects an explicit, hash-verified relational checkpoint + matched
    fusion artifact (see module docstring) -- never the ambient
    config.GNN_MODEL_PATH / config.FUSION_MODEL_PATH. The relational scorer
    is given a deterministic clock driven by each record's own `ts` field
    instead of wall-clock time.time(), so this replay is fully reproducible
    for a fixed (data, pin, seed)."""
    clock_box = {"t": 0.0}
    trust_engine = RuleBasedTrustEngine(clock=deterministic_clock(clock_box))
    if_scorer = IsolationForestScorer()
    lstm_scorer = LSTMAEScorer()
    relational_scorer = pin.load_relational_scorer(clock=deterministic_clock(clock_box))
    fusion = pin.load_fusion_engine()

    triples = []
    for r in sorted(records, key=lambda rec: rec["tick"]):
        if not r["auth_ok"] or r["event_type"] == "replay":
            # Rejected at Module 2 in the live architecture -- never reaches
            # the policy layer. A replay has a VALID HMAC (auth_ok=True) by
            # construction; it's the boot/seq check that rejects it, not
            # the signature check -- so this needs an explicit event_type
            # check, not just the auth_ok filter.
            continue
        clock_box["t"] = r["ts"] / 1000.0
        device_id = r["device_id"]
        rule_score, _ = rule_range_score(device_id, r["reading"])

        if is_feature_vector(device_id):
            fv = fe.feature_vector(r["reading"])
            if_score = if_scorer.score(device_id, fv)
            lstm_score = lstm_scorer.score(device_id, fv)
        else:
            if_score = lstm_score = rule_score

        relational_score = relational_scorer.score(device_id, rule_score, if_score, lstm_score)
        process_trust_score, _, _ = fusion.combine(rule_score, if_score, lstm_score, relational_score)

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


def _git_head() -> str | None:
    try:
        repo_root = os.path.join(os.path.dirname(__file__), "..")
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                              capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    pin_name = os.environ.get("ZTCPS_ADAPTIVE_PDP_PIN", "gcn")
    if pin_name not in rp.KNOWN_PINS:
        raise SystemExit(f"ZTCPS_ADAPTIVE_PDP_PIN={pin_name!r} is not a known pin "
                          f"(one of {sorted(rp.KNOWN_PINS)})")
    pin = rp.KNOWN_PINS[pin_name]
    pin.verify()
    output_path = os.environ.get("ZTCPS_ADAPTIVE_PDP_OUTPUT", ADAPTIVE_PDP_MODEL_PATH)

    with open(SESSION_PATH) as f:
        records = json.load(f)

    print(f"pin={pin_name!r} (relational family={pin.family!r}) -> output {output_path}")
    print("building (security_trust, process_trust, situation) triples "
          "(replaying through the full two-score pipeline, deterministic clock)...")
    triples = build_training_triples(records, pin=pin)
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
    pdp = AdaptivePDP(path=output_path)
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
          f"saved to {output_path}")

    meta = {
        "pin_name": pin.name,
        "relational_family": pin.family,
        "relational_checkpoint": pin.relational_checkpoint,
        "relational_checkpoint_sha256": pin.relational_checkpoint_sha256,
        "fusion_model_path": pin.fusion_model_path,
        "fusion_model_sha256": pin.fusion_model_sha256,
        "fusion_background_path": pin.fusion_background_path,
        "fusion_background_sha256": pin.fusion_background_sha256,
        "training_data_path": SESSION_PATH,
        "training_data_sha256": _sha256_file(SESSION_PATH),
        "seed": TRAINING_SEED,
        "clock_protocol": "deterministic, per-record ts/1000.0 (seconds) -- not wall-clock time.time()",
        "training_config": {
            "rl_training_episodes": RL_TRAINING_EPISODES,
            "rl_epsilon": RL_EPSILON,
            "excluded_situation_classes": ["combined"],
            "triples_used": len(triples),
        },
        "commit_hash": _git_head(),
        "output_path": output_path,
        "states_visited": len(pdp.q),
    }
    meta_path = rp.policy_meta_path(output_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"wrote lineage metadata to {meta_path}")


if __name__ == "__main__":
    main()
