# Repository cleanup manifest

Created before any deletion/rename decisions. Preservation takes priority over cosmetic cleanup. No tracked research file is scheduled for deletion, and no source module is renamed. The initial branch was clean at cf4d82c; [inventory](../../results/final_verification/repository_inventory.json) fingerprints the evidence.

| File / group | Classification | Decision / reason | Unique evidence / replacement / references |
|---|---|---|---|
| docs/paper canonical 27 files | KEEP_CURRENT | New authoritative paper reference | Canonical replacements for paper-writing entry points; docs/README links |
| README, METHODOLOGY, PRD, ZERO_TRUST_CPS_KB, numbered docs | KEEP_HISTORICAL / KEEP_REPRODUCIBILITY | Retain background and original decisions; mark paper-claim authority explicitly | New paper package supersedes current claim summaries; unique background not deleted |
| RESULTS.md, SESSION_LOG.md | KEEP_HISTORICAL | Chronological findings, including wrong/superseded interpretations | Never flatten history into current numbers |
| docs/PAPER_GNN_BASELINE_VERIFICATION.md | KEEP_CURRENT / KEEP_PRIVATE_AUDIT | Exact baseline history and narrow corrected claim | Referenced by 13/16/17 |
| docs/REPOSITORY_AUDIT, REVIEW_RESPONSE_TRACKER, MANUAL_EXTERNAL_REVIEW | KEEP_PRIVATE_AUDIT | Audit/reconciliation context | Preserve review evidence; current paper gate in 17 |
| data/collected raw labelled/unlabelled captures | KEEP_RAW_EVIDENCE | Includes obsolete sampling sessions and first SW capture | No replacement; excluded sessions remain recoverable |
| data/collected network/virtual files and splits | KEEP_REPRODUCIBILITY | Frozen benchmark inputs, provenance and exclusions | No deletion; hash inventory |
| models and models.archived-* | KEEP_REPRODUCIBILITY | Current and prior fitted chain | Canonical metrics depend on model lineage |
| results/crossdevice_benchmark | KEEP_CURRENT / KEEP_HISTORICAL | Current point comparison plus provenance-limited seed studies | Each protocol classified in 13; no overwrite |
| results/gnn_baselines and archived directory | KEEP_CURRENT / KEEP_HISTORICAL | Corrected and prior runs | Historical versions remain separate |
| results/astra_masking_review | KEEP_PRIVATE_AUDIT / KEEP_REPRODUCIBILITY | Red/green tests, exact replay and historical blobs | No deletion |
| results/final_verification | KEEP_PRIVATE_AUDIT / KEEP_REPRODUCIBILITY | New execution logs, inventory and checks | Prior red failures are labelled evidence, not cleaned away |
| docs/figures | KEEP_HISTORICAL / GENERATED | Prior chart evidence; regeneration needed before publication | Figure plan 19; no automatic duplicates deleted |
| docs/Zero_Trust_CPS_Project_Synopsis.docx | UNKNOWN_REVIEW_REQUIRED | Historical proposal; binary content not reviewed/rendered here | Retain; not authority for current paper claims |
| graphify-out cache | KEEP_PRIVATE_AUDIT | Ignored local directory; no usable graph.json | Rebuild optional; no task need to delete |
| firmware/device_secrets.py, src/secrets_local.py | KEEP_PRIVATE_AUDIT | Gitignored deployment configuration | Values not printed or modified |
| External credential backup and baseline workspace | KEEP_PRIVATE_AUDIT | Outside this repository's cleanup scope | Explicitly preserved |

## Rename/deletion ledger

Renames: **none**. The names `coap_server.py`, `GNN_node_embeddings`, historical n10 artifact keys and versioned archives carry tooling/provenance meaning; their interpretation is corrected without breaking paths. A name containing “old,” “v2” or “archived” is not evidence of redundancy.

Deletions: **none**. No candidate demonstrated absence of unique evidence plus a verified canonical replacement. Therefore no SAFE_TO_DELETE row was approved. No deletion-reference migration is required. Unknown binary/ignored/private material is retained for human review.

Organization improves through the paper package, canonical docs index, source-linked tables and machine-readable audit inventories. This conservative cleanup is intentional: removing archival research artifacts would undermine the requested reconciliation reference.
