# Demonstration checklist

Use [READINESS.md](READINESS.md) for the measured scenario matrix and [DATA_CONTRACT.md](DATA_CONTRACT.md) for display limits. Demonstration behavior is implementation evidence; it does not establish generalization, statistical robustness, novelty, deployment reliability or real-world attack coverage.

## Verified presentation / offline sequence

1. From the repository root, run `node design/start-demo.mjs`. Open `http://127.0.0.1:8768`. The page says PRESENTATION / NO LIVE TELEMETRY.
2. Show the two trust channels and the runtime relational model, M6 Set Transformer (superseded GCN 2026-09-07; prior GCN artifacts retained for reproducibility). Select MPU6050 and SW-420 evidence; distinguish two physical identities from the constructed 20-node benchmark.
3. Use the labelled static-policy illustration to explain all four actions. Do not present sliders as runtime decisions.
4. In another terminal run `python design/verify-runtime.py`. Announce **SIMULATED / OFFLINE REPLAY**. This invokes actual gateway ingress and fitted inference with the existing synthetic reading generator, temporary keys and an in-memory audit sink. It starts no broker or HTTP gateway, writes no audit database, publishes no decisions and disables enforcement boundaries.
5. Show the JSON's normal synthetic windows, replay and invalid-HMAC outcomes. Both rejected cases preserve accepted state and bypass model scoring. Security is not forced to drop for an attacker-controlled claimed identity.
6. Show isolated and coordinated synthetic anomalies and the actual per-device M6/process scores and policy outputs. These are sequential scenarios; model history carries forward. Isolated injection can affect neighboring devices through M6's attention over active devices. This is not a controlled comparison between isolated and coordinated detection.
7. Show the controlled-clock SILENT/STALE watchdog results and resumed telemetry. Read the policy value returned by the bandit, even if it differs from the static quadrant illustration.
8. For UI screenshots, run `node design/verify-dashboard.mjs`. Its gateway captures visibly say DEMO MOCK MODE and contain synthetic test fixtures. They verify rendering only; never caption them as physical shake, live attack or actual coordinated inference.
9. Stop the local presentation server with Ctrl+C. The verification runners close their own components. No production state needs recovery.

## Physical/live rehearsal — not verified in this pass

These steps are operator preparation, not claims of completed demonstrations.

1. Provision the broker, certificates, credentials and device firmware following [secure communication](../docs/07_module6_secure_communication.md), [MPU setup](../firmware/HARDWARE_SETUP.md) and [SW setup](../firmware/HARDWARE_SETUP_SW420.md). Existing backend dependencies: `python -m pip install -r requirements.txt`. No frontend installation/build is needed.
2. Start the configured local broker using its existing deployment procedure, then `python src/gateway.py`. Open `http://127.0.0.1:8600` on the gateway host. The gateway serves the canonical command-center HTML itself; the static presentation server does not provide gateway API data.
3. Connect the MPU6050 board as `esp32-vib-001`. Confirm actual accepted timestamps, scores and decision. **Physical normal ALLOW: NOT VERIFIED HERE.** A registered identity alone does not establish connection.
4. Shake/disturb the sensor, then let it settle. Inspect the actual process scores, decision, reason and SHAP. **Heavy-shake physical demonstration: NOT VERIFIED HERE. Raw telemetry spike chart: REQUIRES BACKEND INTEGRATION.** Do not guarantee ALERT or immediate recovery.
5. Disconnect/power off the board. Wait beyond the backend's 20-second staleness window plus watchdog/poll delay. Show OFFLINE only once the backend emits SILENT. **Physical disconnect: NOT VERIFIED HERE; controlled-clock watchdog verified.** Actual last-seen and elapsed-message age require API integration.
6. Restore power and confirm fresh accepted decisions. Current backend has no distinct recovery audit row; the accepted observation replaces the silence event.
7. Run replay/HMAC/coordinated examples in the separate offline runner above. **Live scenario triggers: REQUIRES BACKEND INTEGRATION.** Do not run the legacy simulator against an arbitrary configured broker: it automatically injects mixed scenarios, excludes both physical IDs, and does not implement the constructed 20-node experiment.
8. Inspect the live newest-first decision stream, rejected-event panel, backend reason and available SHAP. Record only observed transitions, with date, provenance and environment. Do not label mock screenshots as physical proof.

SW-420 (`esp32-vib-002`) has TRAIN evidence only; physical VALIDATION/TEST remain pending. A dual-abnormal reproducible demo is **NOT CURRENTLY SUPPORTED** by the dashboard/runner. No live replay/coordinated control is claimed.
