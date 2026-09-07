# Paper readiness verification — 2026-09-07 documentation reconciliation

Records the checks actually performed for the documentation-reconciliation pass that
followed the M6 (Set Transformer) runtime deployment (`3c827e8` and its follow-ups
`ed738fd`, `a2a59cb`, `9f72d9b`, `3007902`; local `main` = `origin/main` throughout,
nothing pushed by this pass). It does not re-verify the deployment itself — see
[docs/paper/13_RESULTS_MASTER_TABLES.md O2](paper/13_RESULTS_MASTER_TABLES.md) for the
artifact-identity inspection that confirms what is actually loaded at runtime.

## Scope of this pass

The M6 switch left `gnn_score`/`GNNScorer` as compatibility names for what the gateway
now actually runs (`SetTransformerScorer`), and left several paper/root documents and
`design/*.html` describing the prior GCN-era runtime. This pass:

1. Corrected that stale "runtime is GCN" language across `docs/paper/*`, root docs
   (`README.md`, `METHODOLOGY.md`, `PRD.md`, `RESULTS.md`, `SESSION_LOG.md`,
   `ZERO_TRUST_CPS_KB.md`, `docs/CLAIM_EVIDENCE_MATRIX.md`, `docs/FINAL_PROJECT_VERIFICATION.md`,
   `docs/MANUAL_EXTERNAL_REVIEW.md`, `docs/PAPER_GNN_BASELINE_VERIFICATION.md`,
   `docs/README.md`, `docs/00_overview.md`, `docs/04_module3_trust_evaluation.md`) and
   `design/zero-trust-cps-command-center.html` / `design/Main.dc.html` /
   `design/extracted/Main.dc.html`, without claiming a verified comparative or physical
   deployment result beyond what the artifacts actually support.
2. Fixed `src/explainability.py`'s Level-2 text to stop saying "GNN"/"graph" for what
   is now a Set Transformer peer-attribution ("Relational score most affected by peer
   device..."), with a new regression test
   (`tests/test_sensor_explanations.py::TestRelationalExplanationLabels`).
3. Fixed a factually stale comment in `src/config.py` (`FUSION_MODEL_PATH_M6_VARIANT`):
   it claimed the M6 fusion variant was "never loaded by src/fusion_engine.py" and that
   overwriting `FUSION_MODEL_PATH` was "a decision this file does not make" — but the
   deployment commit did overwrite it (`fusion_meta_learner.joblib` and
   `fusion_meta_learner_m6_variant.joblib` are byte-identical, SHA-256 `d5e2bfee...`,
   per 13 O2). Comment-only change, no behavior change.
4. Regenerated the derived evidence artifacts under `results/final_verification/` and
   `docs/paper/13_RESULTS_MASTER_TABLES.md` from current source (see commands below), and
   created this file, closing four dangling links to it from
   `docs/paper/00_PAPER_MASTER_GUIDE.md`, `docs/paper/25_OPEN_ITEMS_BEFORE_SUBMISSION.md`,
   `docs/README.md` and `PUBLICATION_MANIFEST.md`.

## Explicitly not done in this pass

No hardware capture, model training, or experimental re-run happened here. In
particular, this pass did **not** fix the comparator-artifact-mismatch bug it surfaced
while reviewing `scripts/evaluate_ablation_m6.py`, `scripts/evaluate_real_hardware.py`,
`scripts/evaluate_policy_comparison.py` and `scripts/evaluate_explainability_level2.py`:
those scripts' "GCN" arms call `FusionEngine()` / import `GNNScorer` directly, which
now silently resolves to the M6-fitted fusion model (since deployment overwrote the
default `FUSION_MODEL_PATH`) paired with true GCN relational scores — a mismatched
pairing, not a reproduction of the historical GCN-era result. Re-running any of those
commands today does not currently produce a valid GCN baseline. See
[docs/paper/24_REPRODUCIBILITY_GUIDE.md](paper/24_REPRODUCIBILITY_GUIDE.md)'s "Artifact
selection required before experimental reproduction" table and
[docs/paper/17_CLAIM_EVIDENCE_MATRIX.md](paper/17_CLAIM_EVIDENCE_MATRIX.md) C03/C05/C15
for the exact fix required (explicit GCN-backup fusion selection, valid-only training
class weights, replay-clock alignment) before any new comparative claim can be made.
That is scoped as separate, future, explicitly-versioned work — not silently attempted
here.

## Verification commands run

All from the repository root, this checkout, 2026-09-07.

| Command | Result |
|---|---|
| `python -m unittest discover -s tests` | **169 tests, OK** |
| `python scripts/build_paper_results.py` | Rendered results reference from 19 hashed artifacts; exit 0 |
| `python scripts/audit_repository_evidence.py` | 245 tracked evidence files, 1,183 history blobs, 369 working files inspected; 0 credential/private-key/token matches; verdict: no match detected (absence of unknown secrets not provable) |
| `python scripts/verify_paper_package.py` | 73 markdown files, 372 local links checked, 66 result artifacts indexed, 0 numeric-source errors, 0 missing canonical files; **0 broken links after this file was added** (previously 4, all pointing here) |
| `python design/check-package.py` | `ok: true`, 19 files scanned, 0 findings, secret scan PASS |
| `python design/verify-runtime.py` | Completed; exercised real fitted-model inference (fusion, M6 relational scorer, offline bandit) against synthetic readings, entirely offline; `gnn_score` values in its output are M6 (compatibility field name, per point 3 above) |
| `node design/verify-dashboard.mjs` | `ok: true`, 14 viewport checks, 18 interactions |

`pytest` was not used for this pass; stdlib `unittest` is the canonical runner per
[docs/paper/24_REPRODUCIBILITY_GUIDE.md](paper/24_REPRODUCIBILITY_GUIDE.md).

## What remains open

Unchanged by this pass — see [docs/paper/17_CLAIM_EVIDENCE_MATRIX.md](paper/17_CLAIM_EVIDENCE_MATRIX.md)
for the current claim gate and [docs/paper/25_OPEN_ITEMS_BEFORE_SUBMISSION.md](paper/25_OPEN_ITEMS_BEFORE_SUBMISSION.md)
for the full list. Headline items: the comparator-mismatch fix and re-run described
above; M6 training's valid-only class-weight and replay-clock corrections; a matched
M6 policy retrain with recorded producing hashes; a physical M6 acquisition-to-enforcement
trial; external Wi-Fi credential rotation (not performed by any documentation pass).
**[CLOSED 2026-09-07, after this pass]** SW-420 physical VALIDATION/TEST capture — was
TRAIN-only at the time this document was written; now closed (`results/sw420_real_hardware/`,
doc 13 Q2). Kept here as an accurate record of this pass's own scope; see 25 for current status.
None of the remaining items block writing the bounded paper described in the current claim gate;
they block the specific claims listed there.

Local `main` was not pushed by this pass.

## Follow-up, 2026-09-07 (later same-day passes — superseded the "explicitly not done" section above)

The comparator-artifact-mismatch bug this pass surfaced but explicitly deferred (`## Explicitly not done in this pass`) WAS fixed later the same day, in two further passes: (1) a comparator-repair pass added `src/relational_pin.py` and fixed `evaluate_ablation_m6.py`/`evaluate_real_hardware.py`/`evaluate_policy_comparison.py`/`evaluate_explainability_level2.py` to require an explicit checkpoint/fusion pin, and found and fixed the class-weight training defect in `scripts/train_set_transformer.py` (results in `results/comparator_repair/`, `results/gcn_m6_corrected_comparison/`, `docs/paper/13_RESULTS_MASTER_TABLES.md` O4); (2) a final pass fixed the identical ambient-config bug in `train_adaptive_pdp.py`, added a deterministic offline-replay clock, trained and evaluated a corrected-M6 policy and a fair GCN baseline, and — after a full gate review — promoted the corrected checkpoint/fusion/policy to be the deployed artifacts (`results/m6_corrected_policy/`, `docs/paper/13_RESULTS_MASTER_TABLES.md` O5). The "headline items" list above (comparator-mismatch fix, class-weight correction, matched M6 policy retrain) is therefore RESOLVED, not open — see `docs/paper/17_CLAIM_EVIDENCE_MATRIX.md` and `docs/paper/25_OPEN_ITEMS_BEFORE_SUBMISSION.md` for current status. SW-420 physical VALIDATION/TEST, a physical M6 acquisition-to-enforcement trial, and external Wi-Fi credential rotation remain open, unchanged by these passes. Both later passes' commits were pushed to `origin/main`.
