"""
Automated invariant tests for the Zero-Trust CPS gateway.

Run from the repository root:

    python -m unittest discover -s tests -v

Uses stdlib `unittest`, not pytest, deliberately: this project keeps its
dependency list short on purpose (`docs/11` records dropping torch-geometric
and pyyaml for the same reason), and a test suite that needs an install before
it can run is a test suite people skip.

WHAT THIS SUITE IS FOR. It does not chase line coverage. Every test below
corresponds to a property that has ALREADY BEEN BROKEN ONCE in this
repository's history, and would have been caught here. The `RESULTS.md`
section in each docstring is the incident it guards against. A test that has
never had a corresponding bug is a test that mostly costs maintenance.

SAFETY. Tests that need an audit database copy the real one into a temporary
directory and point the module-level paths at the copy. `data/audit_log.db` is
never written to by this suite.
"""

import json
import math
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import config                                    # noqa: E402
import feature_engineering as fe                 # noqa: E402


# ---------------------------------------------------------------------------
# 1. Architectural invariant: the two scores are never blended
# ---------------------------------------------------------------------------

class TestTwoScoreSeparation(unittest.TestCase):
    """The single most important architectural property (`docs/04`, ADR-1):
    Security Trust and Process Anomaly are computed from disjoint evidence and
    meet ONLY in the policy lookup."""

    def test_policy_is_the_only_combination_point(self):
        """`decide()` must be a pure function of the two scores plus staleness.
        If it ever grows a third evidence input, the separation has leaked."""
        import inspect
        from policy_engine import decide
        params = list(inspect.signature(decide).parameters)
        self.assertEqual(
            params[:2], ["security_trust_score", "process_trust_score"],
            "decide() must take the two scores as its first two arguments",
        )
        self.assertLessEqual(
            len(params), 3,
            f"decide() takes {params} -- a fourth input means evidence is "
            f"reaching the policy outside the two scores",
        )

    def test_security_scoring_never_sees_a_sensor_reading(self):
        """trust_engine's Security Trust path must not accept sensor data."""
        import inspect
        from trust_engine import RuleBasedTrustEngine
        sig = inspect.signature(RuleBasedTrustEngine.score_security_trust)
        forbidden = {"reading", "feature_vec", "fv", "rms", "process_trust_score"}
        leaked = forbidden.intersection(sig.parameters)
        self.assertFalse(leaked, f"Security Trust scoring accepts physical evidence: {leaked}")

    def test_gnn_ripple_never_makes_a_decision_stricter(self):
        """The GNN's raw output is NOT monotonic in neighbour health -- 25
        violations across a 51-point sweep, ripple inside the saturated regions
        at each end. That was recorded for a long time as "unexplained rather
        than justified", so it is now measured at the level that matters.

        The score ripple is real; the DECISION is what the system acts on, and
        the worst fused excursion it causes is 0.003 against a threshold margin
        of 0.3+. This pins the property worth having -- improving a neighbourhood
        must never make the verdict stricter -- rather than demanding a
        monotonicity the model does not have and does not need. If a future
        change makes the ripple decision-relevant, this fails."""
        from gnn_scorer import GNNScorer
        from fusion_engine import FusionEngine
        from policy_engine import decide
        fusion = FusionEngine()
        strictness = {"ALLOW": 0, "ALERT": 1, "STEP_UP": 2, "BLOCK": 3}
        prev = None
        for i in range(21):
            nb = i / 20
            g = GNNScorer()
            g.score("sensor-002", nb, nb, nb)
            g.score("actuator-001", nb, nb, nb)
            gnn = g.score("esp32-vib-001", 0.9, 0.9, 0.9)
            fused, _, _ = fusion.combine(0.9, 0.9, 0.9, gnn)
            d = strictness[decide(0.909, fused, "FRESH")]
            if prev is not None:
                self.assertLessEqual(
                    d, prev,
                    f"neighbours improving to {nb:.2f} made the decision STRICTER "
                    f"(fused {fused:.4f}) -- the GNN ripple has become "
                    f"decision-relevant, which it was measured not to be")
            prev = d

    def test_static_policy_is_monotonic_in_both_axes(self):
        """Raising either score must never make the outcome stricter. A
        non-monotonic policy is indefensible regardless of its accuracy."""
        from policy_engine import decide
        strictness = {"ALLOW": 0, "ALERT": 1, "STEP_UP": 2, "BLOCK": 3}
        grid = [i / 10 + 0.05 for i in range(10)]
        for proc in grid:
            for a, b in zip(grid, grid[1:]):
                self.assertLessEqual(
                    strictness[decide(b, proc, "FRESH")],
                    strictness[decide(a, proc, "FRESH")],
                    f"security {a}->{b} at process {proc} made the decision stricter",
                )
        for sec in grid:
            for a, b in zip(grid, grid[1:]):
                self.assertLessEqual(
                    strictness[decide(sec, b, "FRESH")],
                    strictness[decide(sec, a, "FRESH")],
                    f"process {a}->{b} at security {sec} made the decision stricter",
                )


# ---------------------------------------------------------------------------
# 2. Isolation Forest score calibration  (RESULTS.md 0.1)
# ---------------------------------------------------------------------------

class TestIsolationForestCalibration(unittest.TestCase):
    """The defect that made a healthy board BLOCK: the old `raw + 0.5` mapping
    capped a perfectly normal reading at 0.621, under PROCESS_THRESHOLD=0.6, so
    the signal could never report 'normal'."""

    @classmethod
    def setUpClass(cls):
        from isolation_forest_scorer import IsolationForestScorer
        cls.scorer = IsolationForestScorer()
        cls.device = "esp32-vib-001"
        if cls.device not in cls.scorer.models:
            raise unittest.SkipTest("no trained Isolation Forest model present")

    def test_decision_boundary_maps_to_neutral(self):
        """raw == 0 is sklearn's own inlier/outlier boundary and must map to
        exactly the neutral midpoint."""
        from isolation_forest_scorer import _calibrate, NEUTRAL_SCORE
        anchor = self.scorer._calibration.get(self.device)
        self.assertIsNotNone(anchor, "calibration metadata missing -- retrain the Isolation Forest")
        self.assertAlmostEqual(_calibrate(0.0, anchor), NEUTRAL_SCORE, places=9)

    def test_a_typical_normal_reading_can_clear_the_live_threshold(self):
        """The regression itself. A median-normal input must score ABOVE
        config.PROCESS_THRESHOLD, not merely above 0.5."""
        from isolation_forest_scorer import _calibrate, NORMAL_SCORE
        anchor = self.scorer._calibration[self.device]
        self.assertAlmostEqual(_calibrate(anchor, anchor), NORMAL_SCORE, places=9)
        self.assertGreater(
            _calibrate(anchor, anchor), config.PROCESS_THRESHOLD,
            "a median-normal reading cannot clear the live threshold -- this is "
            "exactly the defect in RESULTS.md 0.1",
        )

    def test_calibration_is_monotonic(self):
        """The mapping may rescale, never reorder."""
        from isolation_forest_scorer import _calibrate
        anchor = self.scorer._calibration[self.device]
        raws = [-0.4, -0.2, -0.05, 0.0, 0.02, 0.05, 0.08, 0.12]
        scores = [_calibrate(r, anchor) for r in raws]
        self.assertEqual(scores, sorted(scores), "calibration reorders inputs")


# ---------------------------------------------------------------------------
# 3. Firmware equivalence  (RESULTS.md 0.5)
# ---------------------------------------------------------------------------

def _firmware_feature_maths(window, sample_rate_hz=100.0):
    """A transcription of firmware/main.py's on-device maths, with MicroPython's
    `math` substituted for CPython's (identical semantics). Kept here rather
    than imported because firmware/main.py imports MicroPython-only modules."""
    n = len(window)
    mean = sum(window) / n
    rms = (sum(v * v for v in window) / n) ** 0.5
    peak = max(window) - min(window)
    crest = (peak / rms) if rms > 1e-9 else 0.0
    std = (sum((v - mean) ** 2 for v in window) / n) ** 0.5
    kurt = (sum(((v - mean) / std) ** 4 for v in window) / n) - 3.0 if std > 1e-9 else 0.0
    PI = 3.14159265358979
    centered = [v - mean for v in window]
    best_mag, best_freq = -1.0, 0.0
    for k in range(1, n // 2 + 1):
        re = im = 0.0
        for t in range(n):
            angle = -2.0 * PI * k * t / n
            re += centered[t] * math.cos(angle)
            im += centered[t] * math.sin(angle)
        mag = re * re + im * im
        if mag > best_mag:
            best_mag, best_freq = mag, k * sample_rate_hz / n
    return {"rms": round(rms, 4), "peak": round(peak, 4),
            "crest_factor": round(crest, 4), "kurtosis": round(kurt, 4),
            "dominant_freq": round(best_freq, 4)}


class TestFirmwareReferenceEquivalence(unittest.TestCase):
    """The device computes features on-board; the models train against
    `feature_engineering.py`. A disagreement is a train/serve skew that exists
    ONLY on real telemetry and is invisible to every offline evaluation -- a
    hand-rolled sin() once put dominant_freq in the wrong bin 19% of the time."""

    def test_all_five_features_match_the_reference(self):
        random.seed(20260902)
        mismatches = {k: 0 for k in fe.FEATURE_NAMES}
        trials = 150
        for i in range(trials):
            style = i % 3
            if style == 0:                                   # quiet baseline
                w = [max(0.0, random.gauss(1.0, 0.006)) for _ in range(32)]
            elif style == 1:                                 # impulsive shock
                w = [max(0.0, random.gauss(1.0, 0.006)) for _ in range(32)]
                w[random.randrange(32)] = random.uniform(3.0, 4.5)
            else:                                            # low-frequency wander
                w = [1.0 + 0.01 * math.sin(2 * math.pi * 6.25 * t / 100)
                     + random.gauss(0, 0.002) for t in range(32)]
            device = _firmware_feature_maths(w)
            reference = fe.extract_features(w, 100.0)
            for k in fe.FEATURE_NAMES:
                if device[k] != reference[k]:
                    mismatches[k] += 1
        self.assertEqual(
            {k: v for k, v in mismatches.items() if v}, {},
            f"firmware maths diverges from feature_engineering.py over {trials} windows",
        )

    def test_firmware_uses_real_trig_not_an_approximation(self):
        """Guards the specific regression: a truncated Taylor series had 7.5e-2
        max error, enough to select the wrong DFT bin."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "main.py")
        src = open(path, encoding="utf-8").read()
        self.assertIn("math.sin", src, "firmware no longer uses math.sin -- see RESULTS.md 0.5")
        self.assertNotIn("x2 / 6 * (1 - x2 / 20", src, "hand-rolled Taylor sin() is back")


class TestCanonicalisationContract(unittest.TestCase):
    """The firmware builds its signed payload string by hand. If it stops
    matching CPython's json.dumps(sort_keys=True) byte-for-byte, EVERY message
    fails HMAC -- the single most fragile integration point in the system."""

    @staticmethod
    def _format_py_float(v, decimals=4):
        s = "%.*f" % (decimals, v)
        if "." in s:
            while s.endswith("0"):
                s = s[:-1]
            if s.endswith("."):
                s += "0"
        return s

    @staticmethod
    def _canonical_json(fields):
        return "{" + ", ".join('"%s": %s' % (k, fields[k]) for k in sorted(fields)) + "}"

    def test_hand_built_canonical_string_matches_cpython_json(self):
        random.seed(7)
        for _ in range(200):
            payload = {
                "device_id": "esp32-vib-001",
                "ts": random.randrange(1_700_000_000_000, 1_800_000_000_000),
                "boot_id": random.randrange(1, 500),
                "seq": random.randrange(1, 100000),
                "rms": round(random.uniform(0.3, 3.5), 4),
                "peak": round(random.uniform(0.0, 3.0), 4),
                "crest_factor": round(random.uniform(0.0, 2.0), 4),
                "kurtosis": round(random.uniform(-2.0, 30.0), 4),
                "dominant_freq": round(random.choice([3.125, 6.25, 9.375, 12.5, 25.0, 50.0]), 4),
            }
            fields = {k: (('"%s"' % v) if isinstance(v, str)
                          else str(v) if isinstance(v, int)
                          else self._format_py_float(v))
                      for k, v in payload.items()}
            self.assertEqual(
                self._canonical_json(fields),
                json.dumps(payload, sort_keys=True),
                f"canonicalisation drift on {payload}",
            )

    def test_optional_field_does_not_break_ordering(self):
        """step_up_nonce_echo appears only sometimes; sorted-key ordering must
        still hold when it does."""
        payload = {"device_id": "esp32-vib-001", "ts": 1788291422000, "boot_id": 18,
                   "seq": 1182, "rms": 1.0, "peak": 0.0164, "crest_factor": 0.016,
                   "kurtosis": -0.7026, "dominant_freq": 9.375,
                   "step_up_nonce_echo": "cd39bff77caec1bdd0c055d392c3cae2"}
        fields = {k: (('"%s"' % v) if isinstance(v, str)
                      else str(v) if isinstance(v, int)
                      else self._format_py_float(v))
                  for k, v in payload.items()}
        self.assertEqual(self._canonical_json(fields), json.dumps(payload, sort_keys=True))


# ---------------------------------------------------------------------------
# 4. GNN adjacency  (RESULTS.md 0.2)
# ---------------------------------------------------------------------------

class TestGNNAdjacency(unittest.TestCase):
    """normalized_adjacency() is shared by training and inference. Changing it
    without retraining silently invalidates the model, and the textbook A+I
    made a device's verdict depend on whether UNRELATED devices were
    publishing."""

    def test_a_node_owns_the_majority_of_its_own_representation(self):
        import numpy as np
        from gnn_scorer import normalized_adjacency
        a = normalized_adjacency(np.array([True, True, True])).numpy()
        self.assertGreater(
            a[0, 0], sum(a[0, 1:]),
            "neighbours outweigh a node's own evidence -- the defect in RESULTS.md 0.2",
        )

    def test_isolated_node_is_self_only(self):
        import numpy as np
        from gnn_scorer import normalized_adjacency
        a = normalized_adjacency(np.zeros(3, dtype=bool)).numpy()
        self.assertAlmostEqual(a[0, 0], 1.0, places=6)
        self.assertAlmostEqual(float(a[0, 1:].sum()), 0.0, places=6)

    def test_adjacency_is_symmetric(self):
        import numpy as np
        from gnn_scorer import normalized_adjacency
        a = normalized_adjacency(np.array([True, True, False])).numpy()
        self.assertTrue(np.allclose(a, a.T), "adjacency must stay symmetric")


# ---------------------------------------------------------------------------
# 5. RL policy  (RESULTS.md 0.3)
# ---------------------------------------------------------------------------

class TestAdaptivePolicy(unittest.TestCase):
    """A fixed-alpha EMA left Q-values so close together that argmax was
    arbitrary -- the deployed policy answered BLOCK at security 0.91 /
    process 0.87, where the static table correctly answers ALLOW."""

    def test_q_update_is_a_sample_average(self):
        from adaptive_pdp import AdaptivePDP
        pdp = AdaptivePDP()
        pdp.q, pdp._visit_counts = {}, {}
        rewards = [1, -1, 1, 1, -1, 1, 1, 1, -1, 1]
        for r in rewards:
            pdp.update(0.95, 0.95, "ALLOW", r)
        self.assertAlmostEqual(
            pdp.q["9,9"]["ALLOW"], sum(rewards) / len(rewards), places=9,
            msg="Q-value is not the sample mean -- the EMA regression is back",
        )

    def test_unvisited_state_falls_back_to_the_static_policy(self):
        """Absent is safe: an unvisited state must be SEEDED from the static
        table, never decided by dict ordering."""
        from adaptive_pdp import AdaptivePDP
        from policy_engine import decide
        pdp = AdaptivePDP()
        pdp.q, pdp._visit_counts = {}, {}
        for sec in (0.05, 0.25, 0.45, 0.55, 0.75, 0.95):
            for proc in (0.05, 0.35, 0.65, 0.95):
                self.assertEqual(
                    pdp.greedy_action(sec, proc), decide(sec, proc, "FRESH"),
                    f"unvisited state ({sec}, {proc}) did not fall back to the static table",
                )

    def test_greedy_action_never_mutates_learned_values(self):
        """The live path must not learn. greedy_action() may seed an unvisited
        state, but must never change one that already has learned values."""
        from adaptive_pdp import AdaptivePDP
        pdp = AdaptivePDP()
        if not pdp.q:
            self.skipTest("no trained Q-table present")
        key = next(iter(pdp.q))
        before = dict(pdp.q[key])
        sec, proc = [int(x) / 10 + 0.05 for x in key.split(",")]
        for _ in range(5):
            pdp.greedy_action(sec, proc)
        self.assertEqual(pdp.q[key], before, "greedy_action() mutated a learned state")


# ---------------------------------------------------------------------------
# 6. Audit-log integrity  (docs/08)
# ---------------------------------------------------------------------------

class TestAuditIntegrity(unittest.TestCase):
    """Verifies that tamper detection actually detects tampering, against a
    COPY of the real log. Each attack is matched to the check that catches it;
    asserting that the *right* check fires is the point, because they are not
    interchangeable."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(config.AUDIT_DB_PATH):
            raise unittest.SkipTest("no audit database present")
        cls.tmp = tempfile.mkdtemp(prefix="ztcps-audit-")
        cls.db = os.path.join(cls.tmp, "audit.db")
        cls.cp = os.path.join(cls.tmp, "checkpoints.jsonl")
        shutil.copy(config.AUDIT_DB_PATH, cls.db)
        if os.path.exists(config.CHECKPOINT_STORE_PATH):
            shutil.copy(config.CHECKPOINT_STORE_PATH, cls.cp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        # Restore the real paths. This class reloads audit_log and repoints its
        # module-level AUDIT_DB_PATH/CHECKPOINT_STORE_PATH at a temp copy; without
        # this, every later test that writes an audit row fails against a deleted
        # directory. Found by the suite itself on its first run.
        import importlib
        import audit_log
        importlib.reload(audit_log)

    def _fresh_module(self):
        """A copy of audit_log pointed at the temp database."""
        import importlib
        import audit_log
        m = importlib.reload(audit_log)
        m.AUDIT_DB_PATH = self.db
        m.CHECKPOINT_STORE_PATH = self.cp
        return m

    def setUp(self):
        # restore a pristine copy before each attack
        shutil.copy(config.AUDIT_DB_PATH, self.db)
        if os.path.exists(config.CHECKPOINT_STORE_PATH):
            shutil.copy(config.CHECKPOINT_STORE_PATH, self.cp)
        self.audit = self._fresh_module()

    def test_untampered_log_passes_all_checks(self):
        self.assertTrue(self.audit.verify_chain_integrity()[0])
        self.assertTrue(self.audit.verify_against_checkpoints()[0])
        self.assertTrue(self.audit.verify_chain_incremental()[0])

    def test_naive_edit_is_caught_by_the_full_scan(self):
        """Edit a row, leave hashes alone. Only the full scan sees this."""
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT id FROM audit_log ORDER BY id ASC LIMIT 1").fetchone()
        conn.execute("UPDATE audit_log SET decision='TAMPERED' WHERE id=?", (row[0],))
        conn.commit()
        conn.close()
        ok, broken = self.audit.verify_chain_integrity()
        self.assertFalse(ok, "full scan missed a naive edit")
        self.assertEqual(broken, row[0])

    def test_consistent_rewrite_is_caught_by_the_checkpoints(self):
        """Edit a row AND recompute every subsequent hash. The chain is then
        internally valid, so ONLY the independently-keyed checkpoints see it."""
        if not os.path.exists(self.cp):
            self.skipTest("no checkpoint file to verify against")
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id ASC")]
        victim = rows[0]["id"]
        prev = self.audit.GENESIS_HASH
        for r in rows:
            if r["id"] == victim:
                r["decision"] = "TAMPERED"
            h = self.audit.compute_row_hash(self.audit._row_hash_fields(r), prev)
            conn.execute("UPDATE audit_log SET decision=?, prev_hash=?, this_hash=? WHERE id=?",
                         (r["decision"], prev, h, r["id"]))
            prev = h
        conn.commit()
        conn.close()
        self.assertTrue(
            self.audit.verify_chain_integrity()[0],
            "a consistent rewrite should leave the chain internally valid -- if this "
            "fails the test's premise is wrong, not the code",
        )
        self.assertFalse(
            self.audit.verify_against_checkpoints()[0],
            "checkpoints missed a fully consistent rewrite",
        )

    def test_tampered_checkpoint_file_is_detected(self):
        """The checkpoint store itself is HMAC'd; editing it must not help."""
        if not os.path.exists(self.cp):
            self.skipTest("no checkpoint file")
        lines = [l for l in open(self.cp, encoding="utf-8").read().splitlines() if l.strip()]
        if not lines:
            self.skipTest("checkpoint file empty")
        cp0 = json.loads(lines[0])
        cp0["latest_chain_hash"] = "0" * 64
        lines[0] = json.dumps(cp0)
        open(self.cp, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        self.assertFalse(self.audit.verify_against_checkpoints()[0],
                         "a forged checkpoint record was accepted")


# ---------------------------------------------------------------------------
# 7. Module 5 enforcement: auto-quarantine
# ---------------------------------------------------------------------------

class TestAutoQuarantine(unittest.TestCase):
    """BLOCK is advisory unless quarantine is armed. These pin the escalation
    semantics -- especially that the run must be CONSECUTIVE, since the whole
    safety argument rests on scattered BLOCKs never firing it."""

    def setUp(self):
        import gateway
        import trust_engine
        import audit_log
        self.gw, self.te = gateway, trust_engine
        self.device = "sensor-002"
        # _apply_auto_quarantine writes a real audit row. Without redirecting the
        # database, these tests append to data/audit_log.db -- which this suite
        # explicitly promises not to do, and which was caught downstream: 25
        # test-written auto_quarantine rows made the governance validation report
        # 5/7 instead of 7/7. The rows cannot simply be deleted afterwards either,
        # because the log is hash-chained: removing a row breaks the chain, which
        # is the audit design working as intended.
        self._tmp = tempfile.mkdtemp(prefix="ztcps-quarantine-")
        self._saved_db = audit_log.AUDIT_DB_PATH
        self._saved_cp = audit_log.CHECKPOINT_STORE_PATH
        audit_log.AUDIT_DB_PATH = os.path.join(self._tmp, "audit.db")
        audit_log.CHECKPOINT_STORE_PATH = os.path.join(self._tmp, "checkpoints.jsonl")
        audit_log.init_db()
        self._audit = audit_log
        self._enabled = gateway.AUTO_QUARANTINE_ENABLED
        self._threshold = gateway.AUTO_QUARANTINE_CONSECUTIVE_BLOCKS
        gateway.AUTO_QUARANTINE_ENABLED = True
        gateway.AUTO_QUARANTINE_CONSECUTIVE_BLOCKS = 5
        gateway._consecutive_blocks.clear()
        trust_engine.reinstate_device(self.device)

    def tearDown(self):
        self.gw.AUTO_QUARANTINE_ENABLED = self._enabled
        self.gw.AUTO_QUARANTINE_CONSECUTIVE_BLOCKS = self._threshold
        self.gw._consecutive_blocks.clear()
        self.te.reinstate_device(self.device)
        self._audit.AUDIT_DB_PATH = self._saved_db
        self._audit.CHECKPOINT_STORE_PATH = self._saved_cp
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_disabled_by_default_in_config(self):
        """The shipped default must stay OFF -- a scoring defect once produced
        953 BLOCKs on a physically healthy board."""
        self.assertFalse(
            config.AUTO_QUARANTINE_ENABLED,
            "auto-quarantine must ship disabled; see config.py's comment for the evidence",
        )

    def test_below_threshold_does_not_quarantine(self):
        for _ in range(4):
            self.gw._apply_auto_quarantine(self.device, "BLOCK")
        self.assertFalse(self.te.is_revoked(self.device))

    def test_threshold_quarantines_and_revokes(self):
        for _ in range(5):
            self.gw._apply_auto_quarantine(self.device, "BLOCK")
        self.assertTrue(self.te.is_revoked(self.device))

    def test_any_non_block_resets_the_run(self):
        """The safety property. Scattered BLOCKs must never accumulate."""
        for _ in range(4):
            self.gw._apply_auto_quarantine(self.device, "BLOCK")
        self.gw._apply_auto_quarantine(self.device, "ALLOW")
        for _ in range(4):
            self.gw._apply_auto_quarantine(self.device, "BLOCK")
        self.assertFalse(
            self.te.is_revoked(self.device),
            "an ALLOW failed to reset the consecutive-BLOCK run",
        )

    def test_quarantine_is_reversible(self):
        for _ in range(5):
            self.gw._apply_auto_quarantine(self.device, "BLOCK")
        self.assertTrue(self.te.is_revoked(self.device))
        self.te.reinstate_device(self.device)
        self.assertFalse(self.te.is_revoked(self.device))

    def test_nothing_happens_when_disabled(self):
        self.gw.AUTO_QUARANTINE_ENABLED = False
        for _ in range(50):
            self.gw._apply_auto_quarantine(self.device, "BLOCK")
        self.assertFalse(self.te.is_revoked(self.device))


# ---------------------------------------------------------------------------
# 8. Governance validation is falsifiable  (docs/10 7.1)
# ---------------------------------------------------------------------------

class TestGovernanceValidationIsFalsifiable(unittest.TestCase):
    """A check that cannot fail is not a check. Each tenet's own stated
    falsifier must be rejected when injected."""

    def _validate(self, rows, tenet):
        import governance_validation as gv
        return next(r for r in gv.validate(rows) if r["tenet"] == tenet)

    def _row(self, **kw):
        base = {"device_id": "sensor-002", "auth_ok": 1, "decision": "ALLOW",
                "transport": "mqtt", "security_trust_score": 0.9,
                "process_trust_score": 0.9, "rule_score": 0.9,
                "fused_score": 0.5, "reason": ""}
        base.update(kw)
        return base

    def test_t1_rejects_an_unregistered_device(self):
        import governance_validation as gv
        self.assertEqual(self._validate([self._row(device_id="ghost-999")], 1)["status"], gv.FAIL)

    def test_t2_rejects_an_unencrypted_transport(self):
        import governance_validation as gv
        self.assertEqual(self._validate([self._row(transport="plain-tcp")], 2)["status"], gv.FAIL)

    def test_t3_rejects_a_verdict_with_no_scores_of_its_own(self):
        import governance_validation as gv
        row = self._row(security_trust_score=None, process_trust_score=None)
        self.assertEqual(self._validate([row], 3)["status"], gv.FAIL)

    def test_t4_rejects_a_policy_that_ignores_its_inputs(self):
        import governance_validation as gv
        rows = [self._row(security_trust_score=s, process_trust_score=p)
                for s, p in ((0.1, 0.1), (0.9, 0.9), (0.1, 0.9), (0.9, 0.1))]
        self.assertEqual(self._validate(rows, 4)["status"], gv.FAIL)

    def test_t6_rejects_access_granted_without_authentication(self):
        import governance_validation as gv
        self.assertEqual(self._validate([self._row(auth_ok=0)], 6)["status"], gv.FAIL)

    def test_t7_rejects_a_pipeline_contributing_nothing(self):
        import governance_validation as gv
        self.assertEqual(self._validate([self._row(fused_score=0.9)], 7)["status"], gv.FAIL)

    def test_untestable_is_reported_not_passed(self):
        """A steady-state window cannot distinguish re-evaluation from caching,
        and must say so rather than defaulting to PASS."""
        import governance_validation as gv
        rows = [self._row() for _ in range(5)]      # every decision identical
        self.assertEqual(self._validate(rows, 3)["status"], gv.UNFALSIFIABLE)


# ---------------------------------------------------------------------------
# 9. Sampling rate and label provenance  (RESULTS.md 13.4c)
# ---------------------------------------------------------------------------

class TestSamplingContract(unittest.TestCase):
    """`dominant_freq` is computed as k * SAMPLE_RATE_HZ / n, so the declared
    rate must be the ACHIEVED rate or every reported frequency is scaled by a
    constant that is not true. It was out by 12.3x once already."""

    def _firmware_source(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "main.py")
        return open(path, encoding="utf-8").read()

    def test_sample_window_paces_itself(self):
        """The regression: a bare list comprehension read as fast as I2C allowed
        (~1231 Hz against a declared 100 Hz)."""
        src = self._firmware_source()
        self.assertNotIn(
            "return [read_accel_magnitude_g() for _ in range(WINDOW_SIZE)]", src,
            "sample_window() is unpaced again -- it will not sample at SAMPLE_RATE_HZ",
        )
        self.assertIn("ticks_add", src, "sample_window() must schedule against a deadline")
        self.assertIn("sleep_us", src, "sample_window() does not wait between samples")

    def test_declared_rates_agree_across_the_boundary(self):
        """The firmware and the reference implementation must agree, or the
        models are trained on a different frequency axis than the board reports."""
        src = self._firmware_source()
        fw_rate = next(l for l in src.split("\n") if l.startswith("SAMPLE_RATE_HZ"))
        fw_size = next(l for l in src.split("\n") if l.startswith("WINDOW_SIZE"))
        self.assertEqual(int(fw_rate.split("=")[1].strip()), int(config.FEATURE_SAMPLE_RATE_HZ))
        self.assertEqual(int(fw_size.split("=")[1].split("#")[0].strip()), config.FEATURE_WINDOW_SIZE)

    def test_anti_alias_filter_is_configured_below_nyquist(self):
        """Pacing the sampling loop moved Nyquist from 615 Hz down to 50 Hz,
        below the sensor's 260 Hz default bandwidth -- which turned a correct
        rate into an aliased signal. The DLPF must keep the sensor's passband
        under Nyquist, or the two fixes cancel out."""
        src = self._firmware_source()
        self.assertIn("0x1A", src, "MPU6050 CONFIG register is never written -- no anti-alias filter")
        cfg_line = next((l for l in src.split(chr(10)) if l.startswith("MPU6050_DLPF_CFG")), None)
        self.assertIsNotNone(cfg_line, "MPU6050_DLPF_CFG is not defined")
        cfg = int(cfg_line.split("=")[1].split("#")[0].strip())
        bandwidth_hz = {0: 260, 1: 184, 2: 94, 3: 44, 4: 21, 5: 10, 6: 5}[cfg]
        nyquist = config.FEATURE_SAMPLE_RATE_HZ / 2
        self.assertLess(
            bandwidth_hz, nyquist,
            f"DLPF_CFG={cfg} passes {bandwidth_hz} Hz, at or above the {nyquist} Hz "
            f"Nyquist limit -- content above Nyquist folds into the measured band",
        )

    def test_firmware_drains_the_inbound_queue(self):
        """`check_msg()` handles at most ONE pending message. The gateway publishes
        a signed decision for every telemetry message, so a single call per publish
        cycle leaves the queue permanently saturated -- a step-up challenge waits
        behind queued decisions, is processed past the 10 s timeout, and echoes a
        stale nonce. Observed live as 32-34 step-up TIMEOUT/MISMATCH failures and
        spurious BLOCKs on a board that was answering correctly."""
        src = self._firmware_source()
        pump = src[src.index("client.check_msg()") - 400:src.index("client.check_msg()") + 200]
        self.assertIn(
            "for _ in range(", pump,
            "firmware calls check_msg() once per cycle -- it must drain the queue, "
            "or step-up challenges arrive after STEP_UP_CHALLENGE_TIMEOUT_SECONDS")

    def test_no_stale_dt_ms_claim(self):
        """config.py once documented a `dt_ms=10 sampling loop` that did not
        exist, which is what hid the defect."""
        cfg = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "src", "config.py"), encoding="utf-8").read()
        self.assertNotIn("matches firmware/main.py's dt_ms=10 sampling loop", cfg)


class TestOperatorMarkedLabels(unittest.TestCase):
    """Timed-schedule labels were shown not to match physical reality
    (`at_rest_1` held a higher max rms than `moderate_shake`). Operator-marked
    labels must only ever apply inside a confirmed interval."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import collect_hardware_session as c
        self.c = c
        self._saved = c.marked_intervals
        c.marked_intervals = [("gentle_tap", 100.0, 130.0), ("at_rest", 200.0, 240.0)]

    def tearDown(self):
        self.c.marked_intervals = self._saved

    def test_mid_interval_is_labelled(self):
        self.assertEqual(self.c.label_for_wall_time(115.0), "gentle_tap")
        self.assertEqual(self.c.label_for_wall_time(220.0), "at_rest")

    def test_keypress_margins_are_excluded(self):
        """The samples nearest each mark are the least trustworthy -- the
        keypress and the physical action are not simultaneous."""
        m = self.c.MARK_MARGIN_S
        self.assertIsNone(self.c.label_for_wall_time(100.0 + m / 2))
        self.assertIsNone(self.c.label_for_wall_time(130.0 - m / 2))

    def test_between_events_is_unlabelled_not_guessed(self):
        self.assertIsNone(self.c.label_for_wall_time(165.0))
        self.assertIsNone(self.c.label_for_wall_time(0.0))

    def test_no_model_artifact_is_older_than_its_training_data(self):
        """The transformer sat at a build from the previous day through roughly
        six full retrains, because the documented training order --
        IF -> LSTM-AE -> GNN -> fusion -> RL -- silently omits it. Every number
        published about it in that window was measured on a model trained against
        superseded data: accuracy read 0.694 when the current build reads 0.754,
        and its apparent 0.970 recall on `stealthy_forged_values` (against the
        deployed fusion's 0.606) evaporated to 0.606 on a fresh build. A stale
        artifact does not announce itself -- it just quietly answers questions
        about a dataset that no longer exists."""
        import glob
        data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "data", "collected", "training_session.json")
        if not os.path.exists(data):
            raise unittest.SkipTest("no training_session.json")
        data_mtime = os.path.getmtime(data)
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models")
        stale = []
        for f in glob.glob(os.path.join(models_dir, "*")):
            if os.path.getmtime(f) < data_mtime:
                stale.append(os.path.basename(f))
        self.assertFalse(
            stale,
            f"model artifact(s) older than training_session.json: {sorted(stale)} -- "
            f"retrain the FULL chain (IF -> LSTM-AE -> Transformer -> GNN -> fusion -> RL)")

    def test_audit_db_and_its_checkpoint_store_are_not_co_located(self):
        """The checkpoint store attests the audit database. Putting them in one
        directory means a single deletion or a single mis-scoped restore removes
        the evidence and its witness together, which defeats the point of having
        a witness. Previously recorded as 'partly historical'; it is a property,
        and this is the guard that keeps it one."""
        import audit_log
        db = os.path.dirname(os.path.abspath(audit_log.AUDIT_DB_PATH))
        cp = os.path.dirname(os.path.abspath(audit_log.CHECKPOINT_STORE_PATH))
        self.assertNotEqual(
            db, cp,
            f"audit DB and checkpoint store share {db} -- a single rm takes out "
            f"both the evidence and the witness that would detect its tampering")

    def test_shortest_accepted_event_yields_a_scoreable_window(self):
        """The regression this guards: MIN_EVENT_SECONDS was a hardcoded 16.0
        while evaluate_real_hardware.py drops the first LSTM_SEQ_LEN-1 records of
        every block. A minimum-length event therefore survived margin trimming
        with 6 messages against a window length of 8 and contributed NOTHING --
        silently, since the collector still reported it as recorded."""
        from config import LSTM_SEQ_LEN
        usable = self.c.MIN_EVENT_SECONDS - 2 * self.c.MARK_MARGIN_S
        messages = int(usable / self.c.TELEMETRY_INTERVAL_S)
        # 2*LSTM_SEQ_LEN: evaluate_real_hardware.py drops 2*LSTM_SEQ_LEN-1 per block,
        # because a window that merely FILLS still contains the block's settling
        # disturbance (measured: one 0.0768 g spike in a baseline block failed all
        # 6 of its scored windows).
        self.assertGreaterEqual(
            messages, 2 * LSTM_SEQ_LEN,
            f"a {self.c.MIN_EVENT_SECONDS:g}s event leaves {messages} messages, "
            f"under the {2 * LSTM_SEQ_LEN}-message requirement: worth nothing downstream")

    def test_synthetic_resting_region_spans_every_observed_session(self):
        """ADR-18. The same board rested at 1.041, 1.056 and 1.011 g on three
        separate occasions. Centring the simulator on the newest median was
        implemented, measured (real-hardware FP 2/49 -> 0/49), and then the next
        live resting board landed at -4.0 sigma. Every observed resting state
        must stay inside the synthetic normal region, or the models are being
        fitted to whichever session happened to be captured last."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import device_simulator as sim
        # Stationary std of the mean-reverting DC state, from its own constants.
        std = sim.REST_DC_WALK / math.sqrt(1.0 - sim.REST_PERSISTENCE ** 2)
        for observed in (1.041, 1.056, 1.011):
            sigma = abs(observed - sim.REST_DC_CENTRE) / std
            self.assertLess(
                sigma, 3.0,
                f"a real resting board at {observed} g sits {sigma:.1f} sigma from "
                f"REST_DC_CENTRE={sim.REST_DC_CENTRE} (std {std:.4f}) -- widen the "
                f"region, do not re-centre it on one session (ADR-18)")
            self.assertTrue(
                sim.REST_DC_MIN <= observed <= sim.REST_DC_MAX,
                f"{observed} g falls outside the clamp "
                f"[{sim.REST_DC_MIN}, {sim.REST_DC_MAX}]")

    def test_every_labelled_event_targets_more_than_the_minimum(self):
        """One window per event is the floor, not the goal -- the false-positive
        rate on a resting board is measured from these blocks."""
        for name, target, _ in self.c.LABELLED_EVENTS:
            self.assertGreater(target, self.c.MIN_EVENT_SECONDS, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
