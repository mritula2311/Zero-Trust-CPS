"""
Generates the VALIDATION session -- the third split, which did not previously
exist (docs/REPOSITORY_AUDIT.md 2.3).

Why a third split rather than reusing either of the two: the fusion
meta-learner was trained by replaying `training_session.json` through base
models that had themselves been fitted on `training_session.json`, so it
learned coefficients calibrated to in-sample base-model scores
(docs/REPOSITORY_AUDIT.md 2.1, reviewer concern H). Retraining it on
`test_session.json` would fix the optimism and destroy the held-out set in the
same move. So: base models fit on TRAIN, meta-learner and thresholds fit on
VALIDATION, TEST touched exactly once at the end.

Seed comes from `splits.SIM_SESSION_SEEDS` so the seed for each simulated
session is recorded in one place and frozen. Same output shape as
generate_training_data.py / generate_test_data.py, so nothing downstream needs
to learn a new format.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR
from generate_training_data import generate
from splits import SIM_SESSION_SEEDS

# Two validation sessions, one per fitted stage above the base models -- see
# splits.SIM_SESSION_SEEDS for why they are separate draws and not two halves.
OUTPUTS = {
    "SIM_SESSION_VAL_001": "validation_session.json",         # fusion meta-learner
    "SIM_SESSION_VAL_002": "validation_policy_session.json",  # thresholds + policy
}


def main():
    os.makedirs(DATA_COLLECTED_DIR, exist_ok=True)
    for session_id, filename in OUTPUTS.items():
        # Same size as the test session: every consumer needs enough of the rare
        # classes ('coordinated', 'stealthy_forged_values') to estimate them at all.
        records = generate(ticks=1000, seed=SIM_SESSION_SEEDS[session_id])
        for r in records:
            r["source_type"] = "SIMULATED"
            r["session_id"] = session_id
            r["split"] = "validation"
        path = os.path.join(DATA_COLLECTED_DIR, filename)
        with open(path, "w") as f:
            json.dump(records, f, indent=1)
        by_event = {}
        for r in records:
            by_event[r["event_type"]] = by_event.get(r["event_type"], 0) + 1
        print(f"wrote {len(records)} records to {filename} "
              f"(session {session_id}, seed {SIM_SESSION_SEEDS[session_id]})")
        print("  event type breakdown:", by_event)


if __name__ == "__main__":
    main()
