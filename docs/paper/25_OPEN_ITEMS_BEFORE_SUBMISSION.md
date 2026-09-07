# Open items before submission

Paper writing and submission have different gates. The [claim matrix](17_CLAIM_EVIDENCE_MATRIX.md) permits bounded architecture and frozen benchmark writing now; it does not permit unsupported deployment or superiority claims.

## PAPER-WRITING BLOCKER

None for the evidence-bounded scope in the master guide once this reconciliation's publication checks pass. Describe the configured M6 implementation separately from the standalone benchmark and preserved GCN-era replay. Do not depend on unverified M6 comparative gains or physical end-to-end operation.

## SUBMISSION BLOCKER

- Verify related work from primary publications and replace the clearly marked literature plan with sourced comparisons. Avoid priority claims until supported.
- Freeze the paper's exact source/data/model/environment versions and figure inputs. Regenerate and visually verify selected publication figures; present metric polarity, denominators and protocol with every result.
- Select a reproducible experimental scope. For archived GCN replay claims, explicitly pin matching GCN scorer/fusion/background artifacts in an isolated reproduction; current default evaluators mix GCN scores with promoted M6 fusion. Record commands, hashes, outputs and execution-clock assumptions. Historical logs may be discussed as archived evidence with these limits, but must not be described as reproduced by today's default commands.
- If claiming current M6 comparative effectiveness, correct the comparison's GCN artifact selection, calculate training weights only from valid targets, align replay activity clocks, and run a separately versioned retrain/evaluation. Preserve the old evidence. Compare local-only versus local-plus-M6 if claiming complementarity.
- If claiming a trained/evaluated M6 policy chain, align `train_adaptive_pdp.py` with serving and persist its producing model/data hashes. Its current producer still uses GCN plus default M6 fusion; the saved table has no lineage metadata. Preserve P5/P6 zero BLOCK recall in the archived experiment.
- Resolve each claim-scoped physical gap or omit the claim: SW-420 physical VALIDATION/TEST are pending; MPU resting false alarms remain 5/12; no physical M6 acquisition-to-enforcement trial is recorded. These gaps prohibit heterogeneous held-out accuracy, low physical FPR and validated live-M6 claims; they do not prevent writing the bounded paper.

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
