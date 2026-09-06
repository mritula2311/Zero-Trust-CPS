# Dashboard and research presentation

This package reflects the reconciled research state at local main `4ffbe81d93cfafc70b179e6cd8405c210a5baf9a`. It contains two distinct views:

| Entry | Purpose | Data and behavior |
|---|---|---|
| [Main.dc.html](Main.dc.html) | Research presentation | Preserved measurements, selectable sensor evidence, and an explicitly labelled static-policy illustration. No gateway requests or live controls. |
| [zero-trust-cps-command-center.html](zero-trust-cps-command-center.html) | Gateway dashboard | Read-only `/api/*` observations. Served unchanged by the existing gateway at its dashboard root. Handles loading, empty data, disconnection and recovery. |
| [extracted/Main.dc.html](extracted/Main.dc.html) | Retained presentation entry | Same presentation, with a relative base URL for shared styles, script and document links. |

The presentation preserves the command-center palette and panel layout. `presentation.css` and `presentation.js` replace the missing `support.js`/`DCLogic` dependency. Keep these assets with the HTML files. Both canvas manifests retain their entry filenames and have enough height for the updated presentation. Verification covers ordinary browser rendering; no proprietary canvas editor/import workflow was exercised.

Open `Main.dc.html` directly, or serve the repository root locally:

```powershell
python -m http.server 8768 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8768/design/Main.dc.html`. The adjacent gateway-view link previews that HTML, but a static server cannot supply its API. For actual observations, open the existing gateway's configured dashboard address. This package does not start the gateway, connect hardware, change policy configuration, or supply synthetic fallback telemetry.

## Research boundaries carried by both views

- Task-2 claim: **SUPPORTED BUT WEAKER**. B0 is a network-level count, not a single-node baseline.
- M6 is the selected standalone relational candidate; it is not deployed and its fusion remains untested.
- Runtime relational inference remains GCN, followed by logistic fusion.
- Physical evidence comprises one MPU6050 identity and one SW-420 identity. SW-420 TRAIN capture exists; VALIDATION/TEST are pending.
- The 20-node benchmark is constructed from two physical-source identities and eighteen simulated identities.
- Security Trust and Process Trust remain separate until policy evaluation. Serving does not train or explore.

The presentation's sliders illustrate the static 0.6/0.6 two-score policy only; they do not reproduce the offline bandit. All four actions are shown: ALLOW, ALERT, STEP_UP and BLOCK. Missing SHAP values in the gateway view remain missing rather than becoming measured zero contributions.

Numerical authority: [master result tables](../docs/paper/13_RESULTS_MASTER_TABLES.md), [benchmark artifact](../results/crossdevice_benchmark/metrics.json), [claim gate](../docs/paper/17_CLAIM_EVIDENCE_MATRIX.md) and [hardware provenance](../docs/paper/04_HARDWARE_DATA_AND_PROVENANCE.md).

## Reproducible browser verification

Requires Node.js 24 and an installed Chrome/Chromium browser. No npm packages are needed. From the repository root:

```powershell
node design/verify-dashboard.mjs
```

The runner uses an isolated temporary browser profile and a loopback fixture server. Optional `CHROME_PATH` selects the browser executable; `DASHBOARD_QA_DIR` selects the screenshot/report output directory. By default outputs use a temporary directory printed on completion. The runner closes its browser and server; it never contacts a production gateway or physical device. On this Windows environment, the sandboxed renderer timed out, so the successful browser run used approved execution outside the sandbox.

[Recorded verification](browser-verification.json): 14 viewport/artboard checks across the three HTML entries, including 320/768/1024/1440 px and the two 1600 px artboards; 10 interaction/state checks; 18 numerical comparisons against the canonical JSON; local presentation reference checks; zero uncaught browser runtime exceptions. Keyboard selection, all four static actions, exact 0.6 boundary behavior, populated/rejected observations, absent SHAP, empty registry, and API outage/recovery were exercised. The presentation issued zero API requests. Desktop, mobile and lower-panel screenshots were visually inspected. These checks do not establish live hardware deployment or full accessibility certification.

All changes and verification assets in this task are confined to `design/`. Research code, datasets, fitted models and measured result artifacts are unchanged.
