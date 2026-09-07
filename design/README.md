# Dashboard and research presentation

This package follows the [current paper architecture](../docs/paper/02_SYSTEM_ARCHITECTURE.md). It contains two distinct views:

| Entry | Purpose | Data and behavior |
|---|---|---|
| [Main.dc.html](Main.dc.html) | Research presentation | Preserved measurements, selectable sensor evidence, and an explicitly labelled static-policy illustration. No gateway requests or live controls. |
| [zero-trust-cps-command-center.html](zero-trust-cps-command-center.html) | Gateway dashboard | Read-only `/api/*` observations. Served unchanged by the existing gateway at its dashboard root. Handles loading, empty data, disconnection and recovery. |
| [extracted/Main.dc.html](extracted/Main.dc.html) | Retained presentation entry | Same presentation, with a relative base URL for shared styles, script and document links. |

The presentation preserves the command-center palette and panel layout. `presentation.css` and `presentation.js` replace the missing `support.js`/`DCLogic` dependency. Keep these assets with the HTML files. Both canvas manifests retain their entry filenames and have enough height for the updated presentation. Verification covers ordinary browser rendering; no proprietary canvas editor/import workflow was exercised.

Canonical folder: **`design/`**. `Main.dc.html` is the presentation entry; `zero-trust-cps-command-center.html` is the live gateway entry. Both existing paths are preserved. There is no React/Vue framework, package install, transpilation or production bundle: HTML/CSS/JavaScript are the deployable source. Python is needed only for backend/offline verification; Node.js 24 runs the local launcher and browser tests.

Open `Main.dc.html` directly, or start the safe local presentation server from the repository root:

```powershell
node design/start-demo.mjs
```

Then open `http://127.0.0.1:8768`. The launcher binds loopback and serves only public presentation files and linked references. Ctrl+C stops it. The adjacent gateway-view link previews that HTML and honestly reports an unavailable API. For actual observations, start the provisioned backend with `python src/gateway.py` and open `http://127.0.0.1:8600` on that host. The gateway serves the live HTML directly. This package does not provision credentials, connect hardware, change policy configuration, or supply synthetic fallback telemetry. Follow [startup order and physical rehearsal limits](DEMO_CHECKLIST.md).

Production build command: **not applicable**; deploy the existing HTML via the gateway's configured dashboard path. Development command: the local launcher above. Backend requirements and installation remain in the [project README](../README.md) and `requirements.txt`; use `python -m pip install -r requirements.txt` in the project's Python environment. Gateway startup additionally requires its existing secure broker/certificate/credential provisioning.

LIVE API MODE means same-origin REST observations. It does not attest to physical hardware. The presentation is explicitly non-live. DEMO MOCK MODE is confined to the browser verification fixture server and labelled on its screenshots; there is no production mock toggle. The terminal-only offline verifier is labelled SIMULATED / OFFLINE REPLAY and executes real inference without a broker. Neither fixture mode is quantitative physical evidence.

See the [data contract](DATA_CONTRACT.md), [verified scenario matrix and limitations](READINESS.md), [demo checklist](DEMO_CHECKLIST.md), and [file retention manifest](CLEANUP_MANIFEST.md). Raw telemetry histories, true last-seen/connected count, model-loaded/pending status, per-message provenance and live scenario controls **REQUIRE BACKEND INTEGRATION**. Dual-abnormal demo is **NOT CURRENTLY SUPPORTED**. No physical shake or disconnect was executed in this pass.

## Research boundaries carried by both views

- Task-2 claim: **SUPPORTED BUT WEAKER**. B0 is a network-level count, not a single-node baseline.
- M6 is selected in the standalone M1–M9 benchmark. A separate checkpoint is configured in gateway serving and M6-fitted fusion. Correctly pinned comparative evaluation, training-weight correction and policy lineage remain open; no physical end-to-end M6 validation is claimed.
- Runtime relational inference is M6 (Set Transformer), followed by logistic fusion. Prior GCN artifacts are retained (`models/*_gcn_backup.*`) for reproducibility.
- Physical evidence comprises one MPU6050 identity and one SW-420 identity. SW-420 TRAIN/VALIDATION/TEST captures all exist as of 2026-09-07 (`results/sw420_real_hardware/`); its slot in the separate constructed 20-node network benchmark remains PENDING_REAL_HARDWARE_DATA in VALIDATION/TEST.
- The 20-node benchmark is constructed from two physical-source identities and eighteen simulated identities.
- Security Trust and Process Trust remain separate until policy evaluation. Serving does not train or explore.

The presentation's sliders illustrate the static 0.6/0.6 two-score policy only; they do not reproduce the offline bandit. All four actions are shown: ALLOW, ALERT, STEP_UP and BLOCK. Missing SHAP values in the gateway view remain missing rather than becoming measured zero contributions.

Numerical authority: [master result tables](../docs/paper/13_RESULTS_MASTER_TABLES.md), [benchmark artifact](../results/crossdevice_benchmark/metrics.json), [claim gate](../docs/paper/17_CLAIM_EVIDENCE_MATRIX.md) and [hardware provenance](../docs/paper/04_HARDWARE_DATA_AND_PROVENANCE.md).

## Reproducible browser verification

Requires Node.js 24 and an installed Chrome/Chromium browser. No npm packages are needed. From the repository root:

```powershell
node design/verify-dashboard.mjs
python design/verify-runtime.py
python design/check-package.py
```

The runner uses an isolated temporary browser profile and a loopback fixture server. Optional `CHROME_PATH` selects the browser executable; `DASHBOARD_QA_DIR` selects the screenshot/report output directory. By default outputs use a temporary directory printed on completion. The runner closes its browser and server; it never contacts a production gateway or physical device. On this Windows environment, the sandboxed renderer timed out, so the successful browser run used approved execution outside the sandbox.

[Recorded verification](browser-verification.json): 14 viewport/artboard checks across the three HTML entries, including 320/768/1024/1440 px and the two 1600 px artboards; 18 interaction/state checks including populated 320/1440 layouts; 18 numerical comparisons against the canonical JSON; local presentation reference checks; zero uncaught browser runtime exceptions. Keyboard selection, all four static actions, exact 0.6 boundary behavior, populated/rejected observations, absent SHAP, unknown scores/checks, watchdog OFFLINE, invalid response schema and API outage/recovery were exercised. The presentation issued zero API requests. These checks do not establish live hardware deployment or full accessibility certification.

Screenshot output is temporary and excluded from Git. Gateway screenshots show synthetic fixtures and a visible DEMO MOCK MODE label; presentation screenshots show preserved research values and labelled illustrations. No physical heavy-shake or coordinated-live screenshot is supplied. Keep these captions when using any image in an implementation chapter or presentation.

The package scanner checks JavaScript/Python syntax, local documentation links, credential-pattern findings, machine-specific absolute paths and unwanted publication files without printing matching values. It is a scoped source scan, not a security certification. Browser and runtime checks are separate from that scan.

All changes and verification assets in this task are confined to `design/`. Research code, datasets, fitted models and measured result artifacts are unchanged.
