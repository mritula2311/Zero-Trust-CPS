# Open items before submission

Paper writing and submission have different gates. The [claim matrix](17_CLAIM_EVIDENCE_MATRIX.md) permits bounded architecture and frozen benchmark writing now; it does not permit unsupported deployment or superiority claims.

## PAPER-WRITING BLOCKER

None for the evidence-bounded scope in the master guide. Describe the configured, corrected-M6 implementation (deployed 2026-09-07) separately from the standalone benchmark and preserved GCN-era replay. Do not depend on unverified physical end-to-end operation.

## SUBMISSION BLOCKER — RESOLVED 2026-09-07 (kept for chronology)

The four items below described a real gap as of the 2026-09-06 comparator audit. All four are now fixed and evidence-backed; see `docs/paper/13_RESULTS_MASTER_TABLES.md` O4/O5, `docs/paper/17_CLAIM_EVIDENCE_MATRIX.md` Claims C/D, and `docs/paper/18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md`'s deployment-limitations section. Kept here, marked done, rather than deleted, so the paper's methodology section can cite the fix rather than silently presenting a clean history.

- ~~Select a reproducible experimental scope... current default evaluators mix GCN scores with promoted M6 fusion.~~ **DONE.** `src/relational_pin.py` requires an explicit, hash-verified `RelationalPin` (`gcn`/`m6_deployed`/`m6_corrected`) everywhere a comparator previously read ambient config; `results/comparator_repair/comparator_audit.json` records the full per-script audit.
- ~~If claiming current M6 comparative effectiveness, correct the comparison's GCN artifact selection, calculate training weights only from valid targets, align replay activity clocks, and run a separately versioned retrain/evaluation.~~ **DONE.** Class-weight bug fixed in `scripts/train_set_transformer.py` (verified 7.2x overweight → correct), a corrected checkpoint retrained and, after a full gate review, promoted to deployed (`13 O4/O5`). Replay-clock alignment fixed via an injected deterministic clock, opt-in, live semantics unchanged (`tests/test_policy_training_determinism.py`). Old evidence preserved throughout — nothing was deleted or overwritten in place.
- ~~If claiming a trained/evaluated M6 policy chain, align train_adaptive_pdp.py with serving and persist its producing model/data hashes.~~ **DONE.** `train_adaptive_pdp.py` now requires an explicit pin (`ZTCPS_ADAPTIVE_PDP_PIN`) and writes a metadata sidecar (model hash, fusion hash, training data hash, seed, clock protocol, commit hash) next to every Q-table it produces; `relational_pin.verify_policy_lineage()` fails loudly on a future mismatch. A corrected-M6 policy and a fair, clean-provenance GCN baseline were both trained and evaluated (`results/m6_corrected_policy/`). BLOCK recall is 0/33 for both arms, reported as measured, not hidden.
- Resolve each claim-scoped physical gap or omit the claim: MPU resting false alarms remain 5/12; no physical M6 acquisition-to-enforcement trial is recorded. **STILL OPEN** for both — unchanged by the corrected-M6 promotion, not invented here. **[CLOSED 2026-09-07]** SW-420 physical VALIDATION/TEST: two independent sessions captured, 0/108 resting FP and 115/115 detection on TEST (`results/sw420_real_hardware/summary.md`) — a real minimum sample, not a large one, and read with the "structurally easier discrimination problem, not a better pipeline" qualifier in [18](18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md). The remaining gaps prohibit low physical FPR and validated live-M6 acquisition-to-enforcement claims; they do not prevent writing the bounded paper.

## REMAINING SUBMISSION BLOCKER

- Verify related work from primary publications and replace the clearly marked literature plan with sourced comparisons. Avoid priority claims until supported.
- Freeze the paper's exact source/data/model/environment versions and figure inputs. Regenerate and visually verify selected publication figures; present metric polarity, denominators and protocol with every result.
- MPU 5/12 resting false alarms and no physical M6 acquisition-to-enforcement trial (see above) remain the live physical-evidence gaps. SW-420 physical VALIDATION/TEST closed 2026-09-07 (see above).

## OPTIONAL STRENGTHENING

- Freeze new immutable M1–M9/M9 experiment fingerprints if rerunning; original seed-study cardinality metadata remains incomplete. There is no persisted M9 n=15 test and virtual-only versus hybrid superiority is inconclusive.
- Use matched 10-versus-20-node, masking and composition experiments to separate their effects. Test proper joint feature/adjacency permutations before formal empirical graph-equivariance claims.
- Define all-invalid low-level model behavior. Benchmark masking tests and runtime inactive-feature canonicalization do not establish every training/API boundary.
- Preserve raw source-row identities and compare raw-session-only SW training; investigate fragmented MPU temporal training under a separate downstream rebuild.
- Add independent sessions/devices, grouped generator validation, refit uncertainty and multiplicity treatment. LOW remains an internal diagnostic; MEDIUM/HIGH remain OOD stress regimes.

## DEMO / DEPLOYMENT FOLLOW-UP

Physical heavy-shake-to-webpage behavior, recovery, disconnect and real enforcement remain unverified. Measure acquisition, broker transit, queueing, explanation and persistence in end-to-end latency. Validate actual firmware peer certificates, narrower freshness requirements, durable replay/revocation and fail-closed model readiness before production claims. Raw telemetry histories and explicit model-loaded/provenance status require dashboard/backend work. These enhancements are not prerequisites for beginning the paper.

## SECURITY FOLLOW-UP

**EXTERNAL CREDENTIAL ROTATION PENDING.** This audit did not rotate the external Wi-Fi credential; user confirmation and external configuration are required. Keep secret files ignored and untracked. A clean scoped scan does not prove no unknown historical credential exists. External rotation alone does not block documentation publication or paper writing. Any newly detected current tracked secret would block publication.

No new hardware capture, training run, experimental result or literature-priority proof was created by this cleanup. The [readiness audit](../PAPER_READINESS_VERIFICATION.md) records the checks actually performed.
