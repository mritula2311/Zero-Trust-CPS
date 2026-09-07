# Publication manifest

Current publication scope: verified documentation reconciliation, accurate runtime explanation labels, regression checks and refreshed verification receipts. Begin paper writing at the [master guide](docs/paper/00_PAPER_MASTER_GUIDE.md); see the [readiness audit](docs/PAPER_READINESS_VERIFICATION.md) for findings and gates.

| Category | Decision |
|---|---|
| Runtime/source | Preserve behavior and learned artifacts; correct the public relational explanation label only |
| Canonical paper package | Retain all 27 documents; reconcile architecture, evidence lineage, claims, limitations and reproducibility |
| Root histories and audit receipts | Preserve historical evidence; mark its scope and link current authority |
| Data, models and experimental results | Preserve numerical values and model/capture bytes; no training or experimental overwrite |
| Dashboard | Reconcile public model/evidence labels; verify browser behavior and canonical content hashes |
| Local agent guidance | `CLAUDE.md` was removed in `3007902`; reviewed predecessor for unique research content; keep ignored |
| Private local files | Secret files, databases, caches, temporary reviews and browser profiles remain untracked |
| Historical binary synopsis | HUMAN_REVIEW_REQUIRED before reuse as paper content; retained, not current authority |

The [cleanup manifest](docs/paper/REPOSITORY_CLEANUP_MANIFEST.md) records the root-file audit and agent-content mapping. The [design manifest](design/CLEANUP_MANIFEST.md) describes retained interface files. Earlier sanitization decisions remain in the [audit receipt manifest](results/final_verification/AUDIT_RECEIPT_PUBLICATION_MANIFEST.md).

Publication requires passing unit tests, runtime/dashboard checks, complete paper-package and local-link checks, current canonical dashboard hashes, a scoped tracked-secret scan, and no current documentation contradiction. Historical audit failures remain clearly labelled historical; unresolved research extensions remain in [open items](docs/paper/25_OPEN_ITEMS_BEFORE_SUBMISSION.md).

**EXTERNAL CREDENTIAL ROTATION PENDING** is a security/deployment follow-up and does not by itself block this documentation publication. No credential values are published. No force push or history rewrite is permitted.
