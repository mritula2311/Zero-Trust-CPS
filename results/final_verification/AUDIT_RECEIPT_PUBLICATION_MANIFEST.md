# Audit receipt publication manifest

Twelve tracked audit receipts/logs under `results/astra_masking_review/` and
`results/final_verification/` embedded absolute workstation paths (the local
repository checkout path and the local Windows user profile path) inside
pytest/unittest captured output and JSON state snapshots. These paths carried
no reproducibility value of their own -- they are an artifact of where the
audit happened to run, not part of any experiment result -- so they are
sanitized to generic placeholders in place. No numerical result, hash,
timestamp, test outcome, or other content was changed; only the path
substrings below were substituted:

- the local repository checkout path -> `<REPO_ROOT>`
- its parent workspace directory -> `<WORKSPACE_ROOT>`
- the local Windows user profile path (both long and 8.3 short-name forms)
  -> `<HOME>` / `<HOME_8_3>`

A byte-for-byte copy of each file exactly as it stood before this pass is kept
outside this repository (local machine only, not tracked, not published) so
the original evidence remains available for anyone auditing this change.

| # | File | Classification | Action |
|---|---|---|---|
| 1 | `results/astra_masking_review/full_suite.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; test output otherwise unchanged |
| 2 | `results/astra_masking_review/nonfinite_red.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; test output otherwise unchanged |
| 3 | `results/final_verification/explainability_evaluation.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; test output otherwise unchanged |
| 4 | `results/final_verification/initial_repository_state.json` | PUBLISH_SANITIZED | `workspace` field repointed to `<REPO_ROOT>`; all other fields (HEAD, hashes, counts) unchanged |
| 5 | `results/final_verification/pytest_after_fixes.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; pass/fail counts unchanged |
| 6 | `results/final_verification/pytest_collection.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; collection results unchanged |
| 7 | `results/final_verification/pytest_final.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; pass/fail counts unchanged |
| 8 | `results/final_verification/pytest_initial.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; pass/fail counts unchanged |
| 9 | `results/final_verification/repository_inventory.json` | PUBLISH_SANITIZED | `workspace` field repointed to `<REPO_ROOT>`; `worktrees` field's absolute checkout paths repointed to `<REPO_ROOT>`/`<WORKSPACE_ROOT>`; all file hashes/sizes and git state fields unchanged. `scripts/audit_repository_evidence.py` itself was fixed so both fields stay sanitized on every future regeneration, not just this one. |
| 10 | `results/final_verification/targeted_tests.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; test output otherwise unchanged |
| 11 | `results/final_verification/unittest.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; pass/fail counts unchanged |
| 12 | `results/final_verification/unittest_final.log` | PUBLISH_SANITIZED | Workstation paths replaced in place; pass/fail counts unchanged |

## Narrative documents (sanitized in a follow-up pass)

`SESSION_LOG.md`, `docs/FINAL_PROJECT_VERIFICATION.md`, and
`docs/paper/24_REPRODUCIBILITY_GUIDE.md` referenced the absolute local
workspace directory path as narrative provenance text describing where an
audit was run or where a file lives outside the repository; none of them ever
contained the local user-profile path. Classified `PUBLISH_SANITIZED`: the four occurrences (two in
`SESSION_LOG.md`, one each in the other two files) were replaced with
`<REPO_ROOT>` / `<WORKSPACE_ROOT>` in place. This is a path substitution only
-- the sentence, its claim, and its position in the chronology are otherwise
byte-for-byte identical, so it does not constitute rewriting historical
narrative or softening a finding, only removing an incidental machine
identifier from it.

## Superseding the prior classification

`docs/paper/REPOSITORY_CLEANUP_MANIFEST.md` labels the `results/astra_masking_review`
and `results/final_verification` directories `KEEP_PRIVATE_AUDIT` at the
directory level. That label described intent, not enforcement: the files are
still Git-tracked and would still publish on push. This manifest is the
enforcement step for the twelve files above -- sanitized content that is safe
to publish, with the original raw evidence preserved outside the repository.
