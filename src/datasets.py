"""One place that answers "which records train THIS device's models".

Before the 10-node network there was one answer -- `training_session.json` --
and each trainer opened it directly. With ten feature-carrying devices the
answer is per-device, and having each trainer work it out again is how two
trainers end up disagreeing about what a device's training set is.

The split:

  esp32-vib-001   training_session.json  (synthetic + real TRAIN at-rest rows)
                  Unchanged. This device's models are the ones every existing
                  result was measured against, and repointing them at a
                  different corpus would invalidate those numbers for no gain.

  every other     data/collected/network/network_*_train.json
  network node    Their normal rows from the TRAIN split of the network
                  scenarios. esp32-vib-001 rows are excluded here so it cannot
                  be trained twice on overlapping corpora.

PENDING_REAL_HARDWARE_DATA rows carry no features and are dropped before any
trainer sees them -- a device with no captured data gets no model and its
scorer falls back to neutral, which is the honest behaviour.
"""

import glob
import json
import os

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

PRIMARY_DEVICE = "esp32-vib-001"
NETWORK_DIR = os.path.join(_SRC_DIR, "..", "data", "collected", "network")
PRIMARY_SESSION = os.path.join(_SRC_DIR, "..", "data", "collected", "training_session.json")


def training_records() -> list[dict]:
    """Every record any trainer may fit on. TRAIN split only, by construction:
    the network loader globs `*_train.json` and nothing else."""
    records = []
    if os.path.exists(PRIMARY_SESSION):
        with open(PRIMARY_SESSION) as f:
            records.extend(json.load(f))
    for path in sorted(glob.glob(os.path.join(NETWORK_DIR, "network_*_train.json"))):
        with open(path) as f:
            for r in json.load(f):
                if r["device_id"] == PRIMARY_DEVICE:
                    continue          # already covered by PRIMARY_SESSION
                if r.get("reading") is None:
                    continue          # PENDING_REAL_HARDWARE_DATA -- no features to fit
                records.append(r)
    return records


def network_records(scenario: str, split: str) -> list[dict]:
    """One network scenario/split, with PENDING rows kept so callers can count
    and report them rather than silently seeing a shorter list."""
    path = os.path.join(NETWORK_DIR, f"network_{scenario}_{split}.json")
    with open(path) as f:
        return json.load(f)


def scenarios() -> list[str]:
    names = set()
    for path in glob.glob(os.path.join(NETWORK_DIR, "network_*_train.json")):
        names.add(os.path.basename(path)[len("network_"):-len("_train.json")])
    return sorted(names)


if __name__ == "__main__":
    import collections
    recs = training_records()
    by = collections.Counter(r["device_id"] for r in recs)
    print(f"{len(recs)} training records across {len(by)} devices")
    for d, n in sorted(by.items()):
        print(f"  {d:16s} {n:6d}")
    print("scenarios:", scenarios())
