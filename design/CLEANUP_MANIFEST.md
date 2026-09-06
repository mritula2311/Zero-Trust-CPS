# Design inventory and cleanup manifest

Inventory at the start of this completion pass: ten files, working vanilla HTML/CSS/JavaScript, no package manager, compiled framework, component imports or client router. The gateway page has inline SVG charts and seven REST reads. `Main.dc.html` has static measured tables and explicitly labelled policy illustrations. Initial status: FUNCTIONAL presentation; PARTIAL live monitoring because the API lacks raw telemetry and device-status fields. No rewrite needed.

| File / group | Classification | Decision |
|---|---|---|
| `zero-trust-cps-command-center.html` | KEEP_RUNTIME | Gateway's configured HTML entry; inline styles/script avoid a new asset route |
| `Main.dc.html` | KEEP_SOURCE | Canonical research presentation entry |
| `presentation.css`, `presentation.js` | KEEP_ASSET | Shared local assets, no external CDN or missing support runtime |
| `canvas.json` | KEEP_SOURCE | Presentation artboard source; browser rendering verified, proprietary import not exercised |
| `extracted/Main.dc.html`, `extracted/canvas.json` | KEEP_HISTORICAL | Compatibility/export entry with relative base URL; duplicate retained to preserve existing references |
| `verify-dashboard.mjs`, `verify-runtime.py`, `check-package.py` | KEEP_SOURCE | Repeatable browser, isolated gateway and publication checks, not build outputs |
| `start-demo.mjs` | KEEP_RUNTIME | Loopback static presentation launcher; public file allowlist |
| `README.md`, `DATA_CONTRACT.md`, `DEMO_CHECKLIST.md`, `READINESS.md`, this manifest | KEEP_REFERENCE | Operation, limitations, audit and review evidence |
| `browser-verification.json` | KEEP_REFERENCE | Deliberately retained sanitized verification receipt with source hashes, no local screenshot paths |
| `.gitignore` | KEEP_SOURCE | Local output and publication hygiene rules |
| Unused legacy selectors within `presentation.css` | HUMAN_REVIEW | Retained to avoid cosmetic cleanup or canvas-export regression; no broken dependency |
| Local test screenshots, profiles, caches and raw execution output | SAFE_TO_DELETE | Regenerable, outside the public package or ignored; do not commit |

No tracked files moved or deleted. No abandoned temporary HTML, missing image assets, placeholder imports, node_modules or secrets were found. Retained duplicates are intentional; source history preserves older prototypes. No new archive or framework scaffold is needed. Canonical folder stays `design/`, because changing the gateway's existing configured HTML path would add integration work without improving readiness.
