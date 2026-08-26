"""
Generates a HELD-OUT evaluation session, separate from
generate_training_data.py's training_session.json (different random seed,
so it's not just a shuffled copy of data every model has already seen).
Every scripts/evaluate_*.py script reads data/collected/test_session.json,
never training_session.json -- evaluating on training data would inflate
every accuracy number and make the ablation study (scripts/evaluate_ablation.py)
meaningless.

Same synthetic-but-honestly-labeled caveat as generate_training_data.py:
replace with a real recorded session (synopsis Section 4.2 Stage 6) when
you have one -- same output shape, so every evaluate_*.py script keeps
working unchanged.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import DATA_COLLECTED_DIR
from generate_training_data import generate

OUTPUT_PATH = os.path.join(DATA_COLLECTED_DIR, "test_session.json")


def main():
    os.makedirs(DATA_COLLECTED_DIR, exist_ok=True)
    records = generate(ticks=200, seed=999)  # different seed and size from training_session.json
    with open(OUTPUT_PATH, "w") as f:
        json.dump(records, f, indent=1)
    by_event = {}
    for r in records:
        by_event[r["event_type"]] = by_event.get(r["event_type"], 0) + 1
    print(f"wrote {len(records)} held-out test records to {OUTPUT_PATH}")
    print("event type breakdown:", by_event)


if __name__ == "__main__":
    main()
