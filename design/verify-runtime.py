"""Offline demonstration verification; real gateway inference, no network or DB writes.

Uses temporary signing keys, a controlled clock, existing synthetic generators,
and in-memory audit capture. It does not certify physical hardware or transport.
Run from the repository root: python design/verify-runtime.py
"""
import copy
import hashlib
import hmac
import io
import json
import random
import secrets
import socket
import sys
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def run():
    with ExitStack() as stack:
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=RuntimeError("Offline verification forbids network connections")))
        stack.enter_context(redirect_stdout(io.StringIO()))
        import gateway as g
        import device_simulator as simulator
        import trust_engine
        import config

        assert g.fusion_engine.is_trained(), "Fitted fusion model required"
        assert g.gnn_scorer.model is not None, "Fitted runtime GCN required"
        clock = [1800000000.0]
        stack.enter_context(patch("time.time", side_effect=lambda: clock[0]))
        stack.enter_context(patch.object(g, "trust_engine", g.RuleBasedTrustEngine()))
        stack.enter_context(patch.object(g, "identity_targeting_risk", g.IdentityTargetingRisk()))
        stack.enter_context(patch.object(g, "_silence_alerted", set()))
        for name in ("_publish_decision", "_publish_challenge", "_apply_auto_quarantine"):
            stack.enter_context(patch.object(g, name))
        # Patch the shared registry in place so every runtime module sees the
        # same schema, temporary credentials and active identities.
        registry = copy.deepcopy(config.DEVICE_REGISTRY)
        for info in registry.values():
            info.update(secret=secrets.token_hex(32), secret_previous=None, status="active")
        stack.enter_context(patch.dict(config.DEVICE_REGISTRY, registry, clear=True))
        rows = []
        def record(device_id, **fields):
            rows.append(dict(device_id=device_id, **fields))
        stack.enter_context(patch.object(g.audit_log, "log_decision", side_effect=record))
        random.seed(42)
        sequences = {}
        devices = simulator.LEGACY_DEVICE_IDS

        def send(device, anomalous=False, coordinated=False):
            sequences[device] = sequences.get(device, 0) + 1
            reading = simulator.make_reading(device, anomalous=anomalous, coordinated=coordinated)
            payload = dict(device_id=device, ts=int(clock[0]*1000), boot_id=1, seq=sequences[device])
            payload.update(reading if isinstance(reading, dict) else dict(value=reading))
            signature = hmac.new(registry[device]["secret"].encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
            envelope = dict(payload=payload, signature=signature)
            count = len(rows)
            g.process_telemetry(envelope, "offline-verification", False)
            assert len(rows)==count+1 and rows[-1]["decision"] in ("ALLOW","ALERT","STEP_UP","BLOCK"), "Expected an accepted telemetry decision"
            return envelope

        outcomes = []
        def snapshot(scenario, selected):
            outcomes.append(dict(scenario=scenario, source="SIMULATED / OFFLINE REPLAY", observations=[{
                k:r.get(k) for k in ("device_id", "decision", "security_trust_score", "process_trust_score", "process_status", "rule_score", "if_score", "lstm_score", "gnn_score", "reason")
            } for r in selected]))

        # Warm up the actual sequence scorers without introducing a rate attack.
        for _ in range(40):
            clock[0] += 2
            for device in devices:
                accepted = send(device)
        snapshot("normal synthetic windows", rows[-3:])
        before = copy.deepcopy(vars(g.trust_engine))
        for label, envelope in (("replay", accepted), ("invalid HMAC", dict(accepted, signature="0"*64))):
            with ExitStack() as guards:
                scorers = [guards.enter_context(patch.object(s, "score", wraps=s.score)) for s in (g.if_scorer,g.lstm_scorer,g.gnn_scorer)]
                g.process_telemetry(envelope, "offline-verification", False)
                for scorer in scorers:
                    scorer.assert_not_called()
            assert vars(g.trust_engine) == before, "Rejected input changed accepted state"
            assert rows[-1]["decision"] == "REJECTED"
            snapshot(label, rows[-1:])

        clock[0] += 2
        start = len(rows)
        for device in devices:
            send(device, anomalous=device=="esp32-vib-001")
        snapshot("isolated synthetic anomaly", rows[start:])
        clock[0] += 2
        start = len(rows)
        for device in devices:
            send(device, coordinated=True)
        snapshot("coordinated synthetic anomaly", rows[start:])

        clock[0] += max(config.STALE_AFTER_SECONDS, config.PROCESS_STALE_AFTER_SECONDS) + 1
        class EndSweep(Exception):
            pass
        start = len(rows)
        with patch("time.sleep", side_effect=[None, EndSweep()]):
            try:
                g._silence_watchdog_loop()
            except EndSweep:
                pass
        silent = [r for r in rows[start:] if r["device_id"] in devices]
        assert len(silent)==3 and all(r["decision"]=="SILENT" and r["process_status"]=="STALE" for r in silent)
        snapshot("silence watchdog (controlled clock)", silent)
        clock[0] += 2
        start = len(rows)
        for device in devices:
            send(device)
        snapshot("resumed synthetic telemetry", rows[start:])
        return dict(ok=True, mode="OFFLINE REPLAY / SIMULATED", runtime_relational_model="GCN", policy_source="offline bandit" if g.USE_RL_POLICY else "static", rejected_state_unchanged=True, outcomes=outcomes,
                    limitations="Transport, physical hardware, persistent audit and enforcement are not exercised. Publish/challenge/quarantine boundaries are disabled. Fixed generator seed and controlled clock are a scenario sample, not statistical evidence. Dual-abnormal scenario NOT CURRENTLY SUPPORTED by this runner.")


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
