# Dashboard readiness receipt

Completion pass on the existing dashboard branch, based on reconciled research main `4ffbe81d93cfafc70b179e6cd8405c210a5baf9a`. Initial presentation and gateway interface reused; no files moved/deleted and no backend, model, dataset or policy changes. The research presentation remains `design/Main.dc.html`; live gateway HTML remains `design/zero-trust-cps-command-center.html`. Canonical package is `design/`.

## Completion checklist

| Requirement | Status | Implementation / file | Limitation |
|---|---|---|---|
| Existing design inventory / reuse | PASS | CLEANUP_MANIFEST.md | Ten initial files; functional presentation, partial live API view |
| Cleanup classifications | PASS | CLEANUP_MANIFEST.md | Legacy CSS selectors retained for human review |
| README completeness / organization | PASS | README.md | Static source; no compiled build; working paths preserved |
| Live / mock / simulation labelling | PASS | Both HTML entries, browser runner, runtime runner | API cannot attest message provenance |
| MPU6050 physical normal / heavy shake | NOT VERIFIED | DEMO_CHECKLIST.md | Hardware not exercised; raw feature chart requires integration |
| SW-420 physical demo | NOT VERIFIED | DEMO_CHECKLIST.md | One physical identity; VALIDATION/TEST pending |
| Disconnect / OFFLINE | PASS for backend event rendering and offline watchdog | Gateway HTML, verify-runtime.py | No physical disconnect measured; true last-seen/connected status unavailable |
| Replay demo | PASS for isolated gateway path | verify-runtime.py; rejected-event panel | Terminal-only; live trigger requires integration |
| Invalid-HMAC demo | PASS for isolated gateway path | verify-runtime.py; rejected-event panel | Rejection leaves accepted trust unchanged, not an artificial Security Trust drop |
| Isolated synthetic anomaly | PASS for sampled offline inference | verify-runtime.py | Existing generator; neighboring devices can also alert |
| Coordinated synthetic anomaly | PASS for sampled offline inference | verify-runtime.py | Sequential history, three legacy identities, not constructed 20-node/live validation |
| Dual-abnormal demonstration | NOT CURRENTLY SUPPORTED | DEMO_CHECKLIST.md | No verified reproducible scenario/control |
| Separate Security / Process Trust | PASS; existing rendering preserved | Gateway HTML and presentation | No pre-policy blended trust |
| Four final policy actions | PASS; existing direct backend display preserved | Gateway HTML | REJECTED/SILENT are events; do not substitute static quadrant output |
| Event timeline / alerts | PASS | Newest-first audit stream, trust history, rejection panel | Bounded API window; malformed drops may not be audited; audit timestamp is not sensor time |
| Explanation panel | PASS | Backend reason, Level-2 summary, fusion SHAP | Missing attribution remains missing; no invented SHAP |
| Demo scenario matrix | PASS | Matrix below | Explicit scope per row |
| Practical demo checklist | PASS | DEMO_CHECKLIST.md | Physical rehearsal steps marked unverified |
| Runtime model / candidate labels | PASS; updated 2026-09-07 | Both HTML entries | Runtime M6 Set Transformer (superseded GCN); held-out fusion comparison validated, not live-hardware validated |
| Physical vs simulated identities | PASS | Both HTML entries | Hardware identity does not authenticate physical message origin |
| Explicit UNKNOWN / OFFLINE | PASS | Gateway cards and chain checks | OFFLINE follows backend SILENT; no browser timer guesses connection status |
| Raw telemetry / per-feature histories | REQUIRES BACKEND INTEGRATION | DATA_CONTRACT.md | MPU five / SW four values absent from dashboard API |
| Per-check security, model-loaded/pending, schema/all-invalid status | REQUIRES BACKEND INTEGRATION | DATA_CONTRACT.md | Accepted auth observations and rejection reasons available; complete status objects absent |
| Live scenario controls | REQUIRES BACKEND INTEGRATION | DATA_CONTRACT.md | No signing material or automatic attacks in frontend |
| Safe one-command start | PASS | start-demo.mjs | Loopback static presentation only; live backend startup separate |
| Browser checks | PASS | browser-verification.json | Synthetic fixture server; not physical or transport proof |
| Offline gateway checks | PASS | verify-runtime.py | Actual ingress/scorers/bandit; controlled clock/keys; network, persistence and enforcement disabled |
| Secret scan / absolute runtime paths | PASS | check-package.py | Scoped source pattern scan, not a security certification |
| Publication hygiene / generated files | PASS | .gitignore, CLEANUP_MANIFEST.md | Sanitized browser receipt intentionally retained; raw screenshots/profiles excluded |
| External documentation pointers | INSPECTED; RECONCILIATION FOLLOW-UP | Root README, docs/README, paper 02/22/24 | This design-only pass adds internal operation/reference links; integration owner can add canonical package backlinks when reconciling |

## Actual runtime observations

Command executed: `python design/verify-runtime.py`. Python 3.12, repository-fitted IF/LSTM/GCN/fusion and configured offline bandit. Seed 42, 40 warmup cycles, two seconds between cycles; scenario order is exactly the order below. This is an in-memory gateway run using existing synthetic generators, including a software stand-in for the MPU physical identity. No board, broker, HTTP ingestion, audit database or enforcement was exercised. This runner does not replace live dashboard data with its output.

| Scenario | Source | Security | Process | Actual result | Verification scope |
|---|---|---|---|---|---|
| Normal | SIMULATED / OFFLINE REPLAY | 0.912 each | MPU 0.9742; scalar peers 0.9715 | ALLOW each | Actual accepted gateway decisions after warmup |
| Physical heavy vibration | Physical MPU6050 | UNKNOWN | UNKNOWN | UNKNOWN | NOT VERIFIED; no physical action performed |
| Disconnect | Controlled-clock watchdog after synthetic activity | 0.702 each at silence audit | Absent in row; STALE status | SILENT, not a policy action | Backend watchdog executed; physical disconnect unverified |
| Replay | Captured signed synthetic actuator message repeated | Snapshot 0.912, accepted state unchanged | No update | REJECTED / replay_or_stale_sequence | Real ingress, no model calls, complete trust-state equality assertion |
| Invalid HMAC | Same synthetic envelope with invalid signature | Snapshot 0.912, accepted state unchanged | No update | REJECTED / hmac_mismatch | Real signature gate, no model calls, complete trust-state equality assertion |
| Isolated anomaly | SIMULATED MPU stand-in injection | 0.912 each | MPU 0.0009; both scalar peers 0.4774 | ALERT all three | Existing generator and runtime GCN; injection is isolated, response is not |
| Coordinated anomaly | SIMULATED three legacy identities | 0.912 each | MPU 0.0009; both scalar peers 0.4774 | ALERT all three | Immediately follows isolated scenario; not independent comparative evidence |
| Resumed normal telemetry | SIMULATED after silence | 0.776 each | MPU 0.0806; sensor 0.6951; actuator 0.7697 | ALLOW all three | Actual bandit output; MPU process history still abnormal |
| Dual-abnormal | None | UNKNOWN | UNKNOWN | UNKNOWN | NOT CURRENTLY SUPPORTED by this runner/dashboard |

The resumed MPU example is why the UI must not infer an action from the conceptual quadrant. Fresh accepted telemetry and a policy ALLOW do not imply model history has returned to normal. The production simulator excludes the two configured physical IDs and only runs remaining legacy scalar identities; it is not a safe universal scenario launcher or the 20-node benchmark.

## Validation and evidence limits

`node design/verify-dashboard.mjs`: passed 14 viewport/artboard checks, 17 interaction/state checks and 18 artifact-value comparisons, zero uncaught browser runtime exceptions. Includes populated narrow layouts, API outage/recovery, malformed schema, unknown numeric scores/checks, watchdog OFFLINE and replay/HMAC labels. Screenshot fixtures are visibly marked DEMO MOCK MODE. No accessibility certification or physical scenario screenshots are claimed.

`python -m unittest discover -s tests -p test_gateway_input_validation.py`: 15 tests passed. Existing SHAP dependency deprecation warnings and the expected unprovisioned-secret warning occurred; no local secrets were copied. This suite isolates model boundaries and is complementary to the real-inference offline runner.

`python design/check-package.py`: PASS across 18 files for source/syntax, local documentation links and publication checks, zero findings. JavaScript requires no build step; source files are deployable. Browser screenshots are kept in temporary local output, not Git. The two presentation files and shared presentation assets remain unchanged in this completion pass.

`node design/start-demo.mjs`: started and stopped successfully. HTTP checks confirmed presentation, README and linked result-reference responses (200), unavailable gateway API (503), and denied unlisted local-secret/environment paths (404). No secret content was read or served by these checks.

Research constraints, updated 2026-09-07: Task-2 SUPPORTED BUT WEAKER; B0 network-level count baseline; M6 now the deployed runtime relational model (superseded GCN), validated at fusion level on held-out synthetic replay only, not live-hardware validated; one MPU6050 and one SW-420 physical identity; SW VALIDATION/TEST pending; 20-node benchmark constructed; Security and Process Trust separate until policy. Demonstrations support only the observed implementation behavior, not broader research claims.
