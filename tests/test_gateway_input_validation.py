"""Ingress regressions: malformed telemetry cannot alter device state.

Run: python -m unittest discover -s tests -p test_gateway_input_validation.py -v
All audit, publication, and model boundaries are isolated from live data.
"""

import copy
import os
import sys
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


class TestGatewayInputValidation(unittest.TestCase):
    def test_gateway_startup_refuses_plaintext_or_unconfigured_auth(self):
        for tls, auth, password in ((False, True, "test-password"),
                                    (True, False, "test-password"),
                                    (True, True, "CHANGE-ME-password")):
            with self.subTest(tls=tls, auth=auth), \
                    patch.object(self.gateway, "MQTT_USE_TLS", tls), \
                    patch.object(self.gateway, "MQTT_USE_AUTH", auth), \
                    patch.object(self.gateway, "MQTT_GATEWAY_PASSWORD", password), \
                    patch.object(self.gateway.audit_log, "init_db") as init_db:
                with self.assertRaises(RuntimeError):
                    self.gateway.run()
                init_db.assert_not_called()

    def test_placeholder_device_key_cannot_authenticate(self):
        import hashlib
        import hmac
        import json
        envelope = self.envelope()
        key = "CHANGE-ME-generate-your-own-secret"
        envelope["signature"] = hmac.new(key.encode(), json.dumps(
            envelope["payload"], sort_keys=True).encode(), hashlib.sha256).hexdigest()
        with patch.dict(self.gateway.DEVICE_REGISTRY["sensor-002"], secret=key):
            self.assertFalse(self.gateway.verify_signature(
                "sensor-002", envelope["payload"], envelope["signature"]))

    def test_first_replay_check_does_not_create_auth_state(self):
        before = copy.deepcopy(vars(self.engine))
        self.assertFalse(self.engine.check_boot_replay("sensor-002", 1, 1)[0])
        self.assertEqual(vars(self.engine), before)

    def setUp(self):
        import gateway

        self.gateway = gateway
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.engine = gateway.RuleBasedTrustEngine()
        self.stack.enter_context(patch.object(gateway, "trust_engine", self.engine))
        self.stack.enter_context(patch.object(
            gateway, "identity_targeting_risk", gateway.IdentityTargetingRisk()))
        # Synthetic keys only: these tests never sign with a deployed key.
        self.stack.enter_context(patch.object(gateway, "DEVICE_REGISTRY", {
            "sensor-002": {"secret": "test-only-key"},
            "esp32-vib-001": {"secret": "test-only-key"},
        }))
        self.stack.enter_context(patch.object(gateway, "is_revoked", return_value=False))
        for name in ("_reject", "_publish_decision", "_publish_challenge", "_apply_auto_quarantine"):
            self.stack.enter_context(patch.object(gateway, name))
        self.stack.enter_context(patch.object(gateway.audit_log, "log_decision"))
        self.stack.enter_context(patch("builtins.print"))
        self.stack.enter_context(patch.object(gateway, "USE_RL_POLICY", False))
        self.scorers = []
        for name in ("if_scorer", "lstm_scorer", "gnn_scorer"):
            scorer = Mock()
            scorer.score.return_value = 0.9
            self.scorers.append(scorer)
            self.stack.enter_context(patch.object(gateway, name, scorer))
        self.fusion = Mock(last_shap=None)
        self.fusion.combine.return_value = (0.9, 0.9, "test score")
        self.fusion.is_trained.return_value = False
        self.stack.enter_context(patch.object(gateway, "fusion_engine", self.fusion))

    def envelope(self, device_id="sensor-002"):
        payload = {"device_id": device_id, "ts": int(time.time() * 1000),
                   "boot_id": 2, "seq": 2}
        if self.gateway.is_feature_vector(device_id):
            payload.update({name: 1.0 for name in self.gateway.feature_names_for(device_id)})
        else:
            payload["value"] = 25.0
        return {"payload": payload, "signature": "0" * 64}

    def assert_dropped_without_state_change(self, envelope, authenticated=True, seeded=False):
        engine = self.gateway.RuleBasedTrustEngine()
        if seeded:
            engine.commit_boot_seq("sensor-002", 1, 1)
            engine.score_security_trust("sensor-002", False, None)
            engine.update_process_anomaly("sensor-002", 0.85)
            engine.commit_boot_seq("esp32-vib-001", 1, 1)
            engine.score_security_trust("esp32-vib-001", False, None)
            engine.update_process_anomaly("esp32-vib-001", 0.85)
        before = copy.deepcopy(vars(engine))
        for scorer in self.scorers:
            scorer.reset_mock()
        self.fusion.reset_mock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.gateway, "trust_engine", engine))
            if authenticated:
                # Model a correctly authenticated message with an invalid schema.
                stack.enter_context(patch.object(self.gateway, "verify_signature", return_value=True))
            self.gateway.process_telemetry(envelope, "mqtt", True)
        self.assertEqual(vars(engine), before, "malformed telemetry mutated claimed device state")
        for scorer in self.scorers:
            scorer.score.assert_not_called()
        self.fusion.combine.assert_not_called()

    def test_non_object_envelopes_and_payloads_are_dropped(self):
        for value in (None, [], "text", 42, True):
            with self.subTest(envelope=value):
                self.assert_dropped_without_state_change(value)
            with self.subTest(payload=value):
                self.assert_dropped_without_state_change({"payload": value, "signature": "0" * 64})

    def test_nonstring_device_ids_are_dropped(self):
        for value in ([], {}, None, 42, True):
            with self.subTest(device_id=value):
                envelope = self.envelope()
                envelope["payload"]["device_id"] = value
                self.assert_dropped_without_state_change(envelope)

    def test_malformed_signatures_are_dropped_without_hmac_type_errors(self):
        for value in (None, [], {}, 42, True, "\u00e9" * 64):
            with self.subTest(signature=value):
                envelope = self.envelope()
                envelope["signature"] = value
                self.assert_dropped_without_state_change(envelope, authenticated=False)

    def test_invalid_timestamps_cannot_create_or_modify_state(self):
        for seeded in (False, True):
            for value in (True, False, "123", None, [], {}, float("nan"), float("inf"), -float("inf")):
                with self.subTest(timestamp=value, seeded=seeded):
                    envelope = self.envelope()
                    envelope["payload"]["ts"] = value
                    self.assert_dropped_without_state_change(envelope, seeded=seeded)

    def test_invalid_boot_and_sequence_cannot_poison_replay_state(self):
        for seeded in (False, True):
            for field in ("boot_id", "seq"):
                for value in (True, False, "2", None, [], {}, 2.5, float("nan"), float("inf")):
                    with self.subTest(field=field, value=value, seeded=seeded):
                        envelope = self.envelope()
                        envelope["payload"][field] = value
                        self.assert_dropped_without_state_change(envelope, seeded=seeded)

    def test_missing_readings_are_dropped_before_state_or_models_change(self):
        for device_id in ("sensor-002", "esp32-vib-001"):
            envelope = self.envelope(device_id)
            fields = (self.gateway.feature_names_for(device_id)
                      if self.gateway.is_feature_vector(device_id) else ["value"])
            for field in fields:
                with self.subTest(device_id=device_id, missing=field):
                    missing = copy.deepcopy(envelope)
                    del missing["payload"][field]
                    self.assert_dropped_without_state_change(missing, seeded=True)

    def test_invalid_readings_are_dropped_before_state_or_models_change(self):
        for device_id in ("sensor-002", "esp32-vib-001"):
            fields = (self.gateway.feature_names_for(device_id)
                      if self.gateway.is_feature_vector(device_id) else ["value"])
            for field in fields:
                for value in (None, True, "1.0", [], {}, float("nan"), float("inf"), -float("inf")):
                    with self.subTest(device_id=device_id, field=field, value=value):
                        envelope = self.envelope(device_id)
                        envelope["payload"][field] = value
                        self.assert_dropped_without_state_change(envelope, seeded=True)

    def test_valid_numeric_readings_reach_scoring(self):
        for device_id in ("sensor-002", "esp32-vib-001"):
            with self.subTest(device_id=device_id):
                with patch.object(self.gateway, "verify_signature", return_value=True):
                    self.gateway.process_telemetry(self.envelope(device_id), "mqtt", True)
                self.assertEqual(self.engine.auth_state[device_id].last_seen_seq, 2)
                self.assertIn(device_id, self.engine.security_state)
                self.assertIn(device_id, self.engine.process_state)
                self.assertEqual(self.engine.process_state[device_id].score, 0.9)
        self.assertEqual(self.fusion.combine.call_count, 2)

    def test_forged_claim_cooldown_cannot_block_authentic_telemetry(self):
        import trust_engine

        risk = self.gateway.identity_targeting_risk
        with patch.object(trust_engine, "IDENTITY_TARGETING_RISK_THRESHOLD_60S", 1):
            with patch.object(trust_engine, "IDENTITY_TARGETING_COOLDOWN_SECONDS", 60):
                risk.record("sensor-002", "hmac_mismatch")
        self.assertTrue(risk.is_throttled("sensor-002"))

        with patch.object(self.gateway, "verify_signature", return_value=True):
            self.gateway.process_telemetry(self.envelope(), "mqtt", True)

        self.assertIn("sensor-002", self.engine.auth_state,
                      "forged identity claims blocked an authentic device")
        self.assertEqual(self.engine.auth_state["sensor-002"].last_seen_seq, 2)
        self.assertIn("sensor-002", self.engine.security_state)
        self.assertEqual(self.engine.process_state["sensor-002"].score, 0.9)
        self.fusion.combine.assert_called_once()

    def test_invalid_ascii_signature_cannot_reach_scoring_even_during_cooldown(self):
        import trust_engine

        for throttled in (False, True):
            with self.subTest(throttled=throttled):
                if throttled:
                    with patch.object(trust_engine, "IDENTITY_TARGETING_RISK_THRESHOLD_60S", 1):
                        with patch.object(trust_engine, "IDENTITY_TARGETING_COOLDOWN_SECONDS", 60):
                            self.gateway.identity_targeting_risk.record("sensor-002", "hmac_mismatch")
                    self.assertTrue(self.gateway.identity_targeting_risk.is_throttled("sensor-002"))
                self.assert_dropped_without_state_change(self.envelope(), authenticated=False)

    def test_invalid_utf8_does_not_escape_mqtt_callback(self):
        with patch.object(self.gateway, "process_telemetry") as process:
            self.gateway.on_message(None, None, SimpleNamespace(payload=b"\xff"))
        process.assert_not_called()

    def test_malformed_json_does_not_reach_processing(self):
        with patch.object(self.gateway, "process_telemetry") as process:
            self.gateway.on_message(None, None, SimpleNamespace(payload=b"{"))
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
