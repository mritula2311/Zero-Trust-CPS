"""Session-level TRAIN / VALIDATION / TEST allocation -- single source of truth.

Every script that reads `data/collected/*_labelled.json` goes through this
module rather than globbing directly. The reason is the defect this module
exists to close (docs/REPOSITORY_AUDIT.md 2.2): `merge_real_hardware_data.py`
globbed every labelled session into the training set, and
`evaluate_real_hardware.py` globbed the same files again for evaluation, so a
single physical acquisition session contributed rows to both. The splits were
not disjoint, and nothing in the repository could notice.

The invariant, enforced by tests/test_invariants.py::TestSessionSplit:

    every physical acquisition session belongs to exactly one split.

A session id is the timestamp stem of its filename --
`hardware_session_20260902_171313_labelled.json` -> `20260902_171313`. That
mapping lives here, in `session_id_of()`, so no caller re-derives it.

Sessions absent from the manifest raise rather than defaulting into a split.
Defaulting is how a newly captured session silently lands in TRAIN.
"""

import json
import os
import re

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
SPLIT_MANIFEST_PATH = os.path.join(_SRC_DIR, "..", "data", "splits", "session_split.json")

# Simulated-session seeds. Frozen: regenerating SIM_SESSION_TEST_001 while
# tuning would quietly convert the final test set into a tuning set.
# TRAIN keeps generate_training_data.generate()'s historical default (42) and
# TEST keeps generate_test_data.py's (999) so this refactor does not silently
# change what those two datasets contain; VAL is new.
#
# There are TWO validation sessions, not one, and they are disjoint draws
# rather than two halves of one draw. The stacking chain has two fitted stages
# above the base models -- the fusion meta-learner, then the policy/threshold
# layer that consumes its output -- and training both on the same session would
# leave the policy reading in-sample fusion scores, reintroducing at stage two
# exactly the optimism the VALIDATION split removed at stage one.
# Separate seeds rather than a tick-wise split of one session because the
# replay is stateful (rolling LSTM window, GNN graph snapshot): cutting one
# session in half creates a seam mid-window, whereas two independent draws
# each start clean.
SIM_SESSION_SEEDS = {
    "SIM_SESSION_TRAIN_001": 42,
    "SIM_SESSION_VAL_001": 4242,    # fusion meta-learner
    "SIM_SESSION_VAL_002": 4243,    # threshold selection + policy comparison
    "SIM_SESSION_TEST_001": 999,
}

_SESSION_RE = re.compile(r"(\d{8}_\d{6})")


def session_id_of(path_or_name: str) -> str:
    """`.../hardware_session_20260902_171313_labelled.json` -> `20260902_171313`."""
    m = _SESSION_RE.search(os.path.basename(path_or_name))
    if not m:
        raise ValueError(f"cannot derive a session id from {path_or_name!r}")
    return m.group(1)


def _load() -> dict:
    with open(SPLIT_MANIFEST_PATH) as f:
        return json.load(f)


def splits() -> dict[str, set[str]]:
    """{'train': {...}, 'validation': {...}, 'test': {...}} of real session ids."""
    m = _load()
    return {
        "train": set(m["train_sessions"]),
        "validation": set(m["validation_sessions"]),
        "test": set(m["test_sessions"]),
    }


def excluded() -> dict[str, str]:
    """session_id -> why it is in no split at all."""
    return dict(_load()["excluded_sessions"])


def simulated_splits() -> dict[str, list[str]]:
    s = _load()["simulated_sessions"]
    return {k.replace("_sessions", ""): v for k, v in s.items() if k.endswith("_sessions")}


def split_of(session_id: str) -> str:
    """'train' | 'validation' | 'test'. Raises for an unallocated session --
    a new capture must be added to the manifest deliberately, never defaulted."""
    for name, ids in splits().items():
        if session_id in ids:
            return name
    if session_id in excluded():
        raise KeyError(
            f"session {session_id} is explicitly EXCLUDED from every split "
            f"({excluded()[session_id]}) -- it must not be loaded")
    raise KeyError(
        f"session {session_id} is not in {SPLIT_MANIFEST_PATH}. Add it to a split "
        f"deliberately; sessions are never defaulted into TRAIN.")


def labelled_session_paths(split: str, data_dir: str | None = None) -> list[str]:
    """Every `*_labelled.json` path belonging to `split`, sorted.

    Files on disk whose session is excluded or unallocated are skipped with a
    printed note rather than raising -- an old or not-yet-allocated capture
    sitting in the directory should not break a training run, but it must be
    visible that it was skipped."""
    import glob
    if data_dir is None:
        from config import DATA_COLLECTED_DIR
        data_dir = DATA_COLLECTED_DIR
    wanted = splits()[split]
    out = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*_labelled.json"))):
        sid = session_id_of(path)
        if sid in wanted:
            out.append(path)
        elif sid not in splits()["train"] | splits()["validation"] | splits()["test"]:
            print(f"  [splits] skipping {os.path.basename(path)}: session {sid} is not allocated to any split")
    return out


def assert_disjoint() -> None:
    """Raises if any session id appears in more than one split. Called by the
    test suite and by every script that consumes a split."""
    s = splits()
    for a in s:
        for b in s:
            if a < b:
                overlap = s[a] & s[b]
                if overlap:
                    raise AssertionError(
                        f"session(s) {sorted(overlap)} appear in both {a} and {b} splits")
    exc = set(excluded())
    for name, ids in s.items():
        clash = ids & exc
        if clash:
            raise AssertionError(
                f"session(s) {sorted(clash)} are both allocated to {name} and marked excluded")


if __name__ == "__main__":
    assert_disjoint()
    for name, ids in splits().items():
        print(f"{name:11s} {sorted(ids)}")
    print(f"excluded    {sorted(excluded())}")
    print("simulated   ", simulated_splits())
    print("\ndisjointness: OK")
