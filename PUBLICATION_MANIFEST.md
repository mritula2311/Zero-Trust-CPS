# Publication manifest

Final go/no-go artifact for publishing `main` to `origin/main`. This is the
top-level index; the detailed per-file classifications it draws on already
exist and are not repeated here:

- `docs/paper/REPOSITORY_CLEANUP_MANIFEST.md` -- directory-level classification
  of the whole tree (data, models, results, docs, firmware, secrets files).
- `design/CLEANUP_MANIFEST.md` -- file-level classification of everything
  under `design/`.
- `results/final_verification/AUDIT_RECEIPT_PUBLICATION_MANIFEST.md` -- the 12
  machine-generated audit receipts plus 3 narrative documents that carried
  workstation-specific paths, and how each was sanitized.

## Cleanup audit result

A full sweep for `__pycache__/`, `.pytest_cache/`, `node_modules/`, `coverage/`,
`dist/`, `build/`, browser profiles, debug dumps, editor swap files, IDE-local
state, duplicate/backup/`*_old`/`*_final_final`-style filenames, and stray
screenshots found **zero SAFE_TO_DELETE candidates**. The only untracked files
present were this session's own new source files (scanner, tests,
`.gitattributes`, `hash_lib.mjs`, this manifest and its sibling above); nothing
was deleted.

## Classification summary

| Category | Status |
|---|---|
| PUBLISH_REQUIRED (README, source, firmware, gateway/runtime, scripts, tests, dashboard) | Present and unchanged in substance; see git diff for this session's edits |
| PUBLISH_RESEARCH_EVIDENCE (results/, models/, data/collected, canonical result JSON, historical/superseded/negative results) | Preserved; no numeric result, hash, or timestamp altered this session |
| PUBLISH_DOCUMENTATION (docs/, docs/paper/) | Preserved; 2 files path-sanitized only (see audit receipt manifest) |
| PUBLISH_DASHBOARD (design/) | Preserved; governance display and hash normalization fixed this session |
| KEEP_LOCAL_ONLY | None identified inside `zt-cps-starter` -- the genuinely local-only material (`firmware/device_secrets.py`, `src/secrets_local.py`, `.env`, TLS/HMAC key material, runtime databases, graphify cache) is already untracked via `.gitignore` and confirmed absent from the tracked file list this session |
| SAFE_TO_DELETE | None found; nothing deleted |
| HUMAN_REVIEW_REQUIRED | None newly raised this session (`docs/Zero_Trust_CPS_Project_Synopsis.docx` remains flagged `UNKNOWN_REVIEW_REQUIRED` in the repository cleanup manifest from before this session; unchanged) |

## Publication gate

- Tracked-secret scan: clean (no real secret in tracked content; local Wi-Fi
  password reuse flagged as a warning about untracked local configuration --
  see credential scan result in the session report).
- Workstation-path scan: 0 remaining absolute machine-specific paths in any
  tracked file.
- Hash normalization: `.gitattributes` + `design/hash_lib.mjs` canonical
  hashing in place; `design/browser-verification.json` refreshed.
- Governance missing-data display: fixed, regression-tested.
- Repository tests / dashboard verification / documentation links: passing.
- Parent-workspace files (`<WORKSPACE_ROOT>\.agents\`, `.claude\`,
  `astra-baseline-20260905\`, `design-qa\`, `prepush-review-fba7841\`,
  `verification-tools\`, `zt-cps-design-astra\`, the `astra-*.py` scripts,
  `firmware_main_FIXED.py`, `firmware_secrets_backup.json`, `skills-lock.json`,
  `.claudeignore`) are outside this Git repository and were not staged.
