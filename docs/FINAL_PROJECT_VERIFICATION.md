# Final project verification and research-integrity report

Audit date: 2026-09-06. This report records the inspected branch, executed offline checks, documentation package and remaining evidence gaps. It does not certify a live physical deployment, reproduce every expensive historical fit, or constitute the research paper. The [master guide](paper/00_PAPER_MASTER_GUIDE.md), [results](paper/13_RESULTS_MASTER_TABLES.md) and [claim gate](paper/17_CLAIM_EVIDENCE_MATRIX.md) define the paper-writing reference.

## 1. Repository state

Workspace: `<REPO_ROOT>`; branch: `<historical-review-branch>`. Initial HEAD: `cf4d82c4f7522ec9133d1e86324f8c47a3043288`. Reviewed local main and origin/main: `4f6afa25e4721c13a4e9f0355548f8ca07c70a5a`; main ahead/behind: 0/0. Initial tree was clean and docs/paper did not exist. This is newer than the supplied c5cd38d context. No fetch was performed: origin/main denotes the accessible tracking ref, not a freshly queried server head. Only one worktree was registered; inaccessible clones, other unpushed work and uncommitted work outside it are not verified. [Initial state](../results/final_verification/initial_repository_state.json) and [inventory](../results/final_verification/repository_inventory.json) preserve exact observations. Code/test audit HEAD is `9abecb8edfe7885c75cdc335f33c6ce589561ccd`; subsequent documentation/evidence commits are listed by Git and the delivery response.

## 2. Full architecture verdict

[VERIFIED IMPLEMENTATION / DEPLOYMENT CANDIDATE] The gateway authenticates telemetry, computes separate Security and Process Trust, and combines them at policy evaluation. Current Process Trust uses rule, per-device IF/LSTM and runtime GCN scores in logistic fusion. M6 selection is a separate research result. The [architecture](paper/02_SYSTEM_ARCHITECTURE.md) includes a diagram and a [24-component, 15-field matrix](../results/final_verification/subsystem_matrix.csv).

## 3. Architecture contract verification

Security Trust originates in `trust_engine.score_security_trust`: authenticated rate/step-up observations, bounded time decay and EWMA, initialized at 0.8. Process Trust originates in `fusion_engine.combine`: logistic normality from rule/IF/LSTM/GCN. They first meet in the gateway call to `adaptive_pdp.greedy_action(sec, proc)`, or `policy_engine.decide(sec, proc, status)` with the static configuration. Runtime does not fit, backpropagate or update the bandit from rewards; unseen bandit buckets initialize deterministically. Authentication gates precede process inference. Rejected traffic cannot train runtime models because no runtime training occurs; offline dataset authenticity still depends on curated annotations and file integrity.

## 4. Security pipeline verdict

[VERIFIED CODE/TESTS] Actual order is envelope/type parsing, identity, revocation, HMAC, finite reading, replay predicate, freshness, accepted sequence commit, rate/step-up, scoring and policy. Rejections update separate identity-targeting/audit evidence without poisoning accepted trust, sequence history or process buffers. Failed-HMAC logging cooldown does not throttle authenticated traffic. Expired previous-key housekeeping can clear registry key metadata: the guarantee is not that every registry byte is immutable on all rejected calls. Firmware signing was checked against the real gateway verifier for both modalities and optional nonce inclusion.

## 5. Security deployment verdict

[PARTIALLY VALIDATED] Gateway startup fails closed on missing TLS/broker authentication or template gateway credentials. It does not require all learned artifacts to load; neutral/mean fallback remains possible. MPU certificate verification is opt-in and SW firmware lacks equivalent required CA verification. Firmware TLS, persistent replay state and full model readiness require deployment validation. The second transport is HTTPS, despite historical CoAP naming. No live broker/firmware session was exercised. The [credential scan](../results/final_verification/credential_scan.json) reports zero configured-secret/private-key/selected provider-token matches in its recorded history and working-file scope. Unknown or rotated historical credentials cannot be exhaustively excluded; local secret files remain ignored and untouched.

## 6. Hardware verdict

[VERIFIED CAPTURE PROVENANCE] Two physical identities have captures: one ESP32/MPU6050 and one ESP32/SW-420. MPU has two accepted TRAIN sessions (114 transcript-reconstructed and 152 operator-labelled rows), VALIDATION 47 rows and TEST 116 rows. Four earlier unpaced sessions remain preserved but excluded. A fresh offline held-out replay scored 42 post-warm-up windows: 30/30 disturbances detected, 5/12 resting windows flagged. This is a small dependent replay sample, not field reliability or measured cyberattack enforcement.

## 7. SW-420 verdict

[TRAIN ONLY] First physical capture `20260905_162002` contains 321 rows, including 140 all-zero resting readings. Four-channel checkpoints exist. Physical VALIDATION/TEST are absent. Neither two MPU6050 devices nor same-modality manufacturing generalization can be claimed. Exact flashed firmware/build provenance remains incomplete.

## 8. 20-node provenance verdict

[VERIFIED CONSTRUCTED BENCHMARK] The canonical network contains 2 REAL_HARDWARE source identities and 18 LEGACY_SIMULATED identities; it is HYBRID. It contains no additional REAL_DERIVED_VIRTUAL identities. The separate generator provides five virtual identities for M9. Held-out SW data within this constructed network benchmark is still pending (`PENDING_REAL_HARDWARE_DATA`, unaffected by the 2026-09-07 standalone SW-420 closure below — a separate pipeline), leaving 19 valid nodes. Physical-source network rows are resampled with replacement. The runtime registry has 22 entries, including two legacy scalar identities; these counts do not imply concurrent physical connections. The complete node table is in [provenance](paper/04_HARDWARE_DATA_AND_PROVENANCE.md). **[2026-09-07]** A standalone, non-network SW-420 held-out evaluation now exists outside this benchmark: `results/sw420_real_hardware/` (0/70 and 0/108 resting FP, 109/109 and 115/115 detection).

## 9. Feature-schema verdict

[VERIFIED] MPU order: rms, peak, crest_factor, kurtosis, dominant_freq; width 5. Implemented peak is peak-to-peak and crest factor is peak-to-peak/RMS. SW order: trigger_rate, duty_cycle, burst_max_ms, inter_event_cv; width 4. Firmware, parser, vectorization and saved per-device metadata agree. Fixed relational inputs are local score vectors, not raw heterogeneous sensor vectors.

## 10. Temporal-data verdict

[VERIFIED CONSTRUCTION; DATA LIMITATIONS] Normal sequence construction splits on source/session/scenario/phase and acquisition-tick discontinuities before filtering. It does not concatenate removed events into continuous training windows. Existing resampled/interleaved network streams remain fragmented: primary support is 4,070 normal rows across 1,046 runs and 244 length-eight windows. SW nominal support includes repeated raw-source observations and is not an independent sample count. A rebuilt temporal corpus would require a new training/result lineage.

## 11. Train/validation/test verdict

[VERIFIED CURRENT FIT PATHS] Scalers/normalizers fit TRAIN; model/threshold selection uses designated validation; fusion uses VAL_001 and policy fitting uses VAL_002. Physical sessions are split separately. No test-based parameter selection was found in inspected fit paths. Synthetic splits share a generator family, resampled rows are dependent within a split, and immutable original run provenance is incomplete for several historical artifacts. The exploratory repair-set study includes TRAIN and must not be described as held-out evaluation.

## 12. Pending-node masking verdict

[FIXED AND REGRESSION-TESTED] Canonicalization now occurs before set-model and pooled-training arithmetic and before live dense GCN arithmetic. GAT handles isolated all-masked query rows without contaminating valid outputs. Existing graph/attention/pooling masks and fixed-width validity inputs remain in place. Finite-input parity was preserved in a bounded real-corpus comparison; historical headline artifacts were not overwritten. All-invalid low-level snapshot semantics still need an explicit API contract; that input is not present in the current benchmark. This is not a universal missing-data robustness guarantee.

## 13. Task-2 / novelty claim #3 verdict

**SUPPORTED BUT WEAKER.** B0 is a global anomalous-node count; B1/B2 are indexed concatenated logistic/MLP representations. The misleading `GNN_node_embeddings` label contains final scalar GCN scores plus a logistic head. Corrected TEST accuracy: B0 0.3958, B1 0.5433, B2 0.5267, GCN-score 0.5375. B0-to-B2 delta is +0.1309; prior 20-node delta +0.1325 and 10-node values remain historical. Indexed context improves over a count here; GNN necessity or superiority is unsupported. Cardinality, masking and changed upstream training are not causally separated.

## 14. Local model verdict

Rule/IF/LSTM remain implemented runtime components. Temporal Transformer is ablation-only: fair conditional MPU comparison gives both LSTM and Transformer accuracy 0.945 and normal-class F1 0.935. Full-stream results differ and the residue exclusion must be disclosed. SW fitted artifacts lack held-out physical validation. Checkpoint parameter counts are recorded in [local models](paper/06_LOCAL_ANOMALY_MODELS.md).

## 15. M1–M9 verification table

Recorded seed-0 TEST results, validation maximum anomaly-F1 threshold protocol. Anomaly-positive FPR; Macro-F1 averages the two classes. These are preserved standalone results, not newly retrained end-to-end scores. [Full table and source](paper/13_RESULTS_MASTER_TABLES.md) include recall, threshold, cost and protocol variants.

| Model | Macro-F1 | FPR | Status |
|---|---:|---:|---|
| M1 concat MLP | 0.9443 | 0.0162 | Fixed-width baseline |
| M2 gradient boosting | 0.9513 | 0.0112 | Fixed-width baseline |
| M3 Deep Sets | 0.9837 | 0.0043 | Set baseline |
| M4 GCN | 0.7755 | 0.0494 | Declared-topology baseline; separate runtime lineage |
| M5 GATv2 | 0.9857 | 0.0034 | Experimental graph attention |
| M6 Set Transformer | 0.9898 | 0.0025 | Selected standalone candidate |
| M7 NP-ST | 0.9850 | 0.0039 | Ablation; no established advantage over M6 |
| M8 mixed-cardinality ST | 0.9713 | 0.0079 | Cardinality-training experiment |
| M9 mixed-provenance ST | 0.9842 | 0.0041 | Provenance-training experiment |

## 16. Final relational model recommendation

Retain M6 as the selected standalone candidate on recorded Macro-F1/FPR evidence. Do not declare it the final deployed model. Selection remains conditional on the recorded constructed corpus and operating point; superiority is not established statistically across populations.

## 17. Standalone versus fused-model status

M6 serving checkpoint/adapter, fusion refit, calibration and controlled local-only versus local-plus-M6 comparison are absent. Current runtime uses `models/gnn.pt`, a time-coactive GCN with self-loop weight 3. Benchmark M4 uses declared topology and a separate checkpoint/self-loop selection. Final selected-model end-to-end validation remains open.

## 18. Topology-mechanism verdict

Degree and peer-density interventions support conditional architecture-sensitive propagation/aggregation interpretations. Paired probe batches and fixed-split seed comparisons are documented. Dilution advances RNG across model/size runs, while declared-topology controls use different draws; those contrasts are not pure paired adjacency interventions. No physical-network causal mechanism is established.

## 19. Permutation-test verdict

The historical probe permutes features while keeping adjacency fixed. It is a topology reassignment experiment, not joint graph relabelling, and cannot refute graph permutation equivariance. It also treats probe nodes as valid. The invalid interpretation is rejected and the original numbers remain preserved. Proper joint permutation is a follow-up.

## 20. Virtual-generator verdict

The generator exists and is deterministic under its stated identities/seeds. Fresh validation uses 103 TRAIN resting rows in seven runs, producing 618 rows/42 blocks per preset. LOW passes the recorded internal diagnostics. MEDIUM fails RMS marginal agreement; HIGH fails RMS/peak. Overall exit 1 records expected stress-diagnostic failures, not an unhandled exception. Independent-device/population realism remains unvalidated.

## 21. M8 verdict

M8 trains subsets of sizes 2, 3, 5 and 10 from the 20-node corpus. Its seed-0 Macro-F1 0.9713 and FPR 0.0079 do not improve on M6 at the recorded operating point. This is an experiment on subset cardinality, not proof that larger physical networks generalize.

## 22. M9 verdict

The current training pool can include 20 hybrid identities plus five generated identities; training samples sizes 2, 3, 5, 10 and 15. Older docstrings/cardinality labels are not authoritative. Separate seed artifacts lack immutable producing input/code fingerprints. LOW virtual-test mean F1 0.6812 and FPR 0.1641 worsen to HIGH F1 0.2952 and FPR 0.8341. Near-one recall with excessive false alarms does not establish robustness; virtual-only advantage remains inconclusive.

## 23. Fusion verdict

The actual fusion is a four-input balanced logistic model trained on VAL_001, with saved background data for SHAP. No input scaler is stored in that chain. Fresh legacy TEST replay gives accuracy 0.698, normal precision 0.992, normal recall 0.677 and normal F1 0.805. High normal precision does not establish overall improvement over the rule baseline. M6 is absent from these coefficients and results.

## 24. Policy verdict

Runtime defaults to a fixed offline contextual bandit; the static two-score table remains available. This is not sequential reinforcement learning. Saved P5/P6 results have Macro-F1 0.5271/0.2777, false-block rate 0/0, ALERT recall 0.96/0.99, and BLOCK recall 0/0. P6 uses declared validation constraints; P5 was not fit with the same constrained search. Both meet those bounds descriptively on TEST, but P6 is not globally best. Wall-clock trust decay complicates exact replay unless timestamps are controlled.

## 25. Explainability verdict

Level 1 uses actual SHAP LinearExplainer contributions in log-odds space, not additive probability contributions or causal explanations. The single-channel legacy TEST repair result is 79/219 (36%), below its 70% target. Correcting mixed-sensor input makes the exploratory MPU-only repair analysis run: best-three repair recovers 179/182, but uses all splits and a different metric. It cannot replace the 36% held-out subset result or be called 98% held-out explainability.

## 26. Statistical-reporting verdict

Metric polarity, denominators, thresholds, seeds and protocol lineage are explicit in the master tables. Ten-seed paired intervals describe refit variability on fixed data, not independent-device uncertainty. Wilson hardware intervals retain their small/dependent-sample limitation. Main max-F1 M1–M9 PR-AUC is absent, not zero; calibrated secondary tables are a separate protocol. No unsupported significance or causal attribution is permitted.

## 27. Verified paper contributions

Safe implemented design statements include separate cyber/physical trust channels at policy evaluation and model explanation/audit capabilities. Results/discussion can report rejection-state isolation, tested pending-input invariants, a constructed heterogeneous M1–M9 comparison, indexed-context versus count results, and the scoped generator/policy experiments. Literature priority is not established.

## 28. Contributions requiring qualifiers

M6 is selected standalone; hardware evidence spans two modalities but only MPU has held-out sessions; generator LOW validation is internal; topology results are conditional constructed interventions; Task-2 contextual benefit is narrower than GNN necessity. All quantitative statements must retain split, metric and provenance labels.

## 29. Claims that must not be made

Do not claim twenty physical devices, two MPU6050s, deployed M6 fusion, GNN necessity/superiority, full reinforcement learning, general population realism, low physical false-alarm reliability, formal graph-equivariance failure, 98% held-out repair quality, or complete acquisition-to-enforcement latency. No novel/first-in-literature claim is authorized without verified related work.

## 30. Negative results preserved

GCN isolated-anomaly failure, topology dilution/sensitivity, Transformer/NP-ST non-advantage, M9 stress false alarms, virtual-only ambiguity, generator stress-diagnostic failures, hardware resting false alarms, poor single-channel repair, and zero policy BLOCK recall remain in the canonical narrative and original artifacts. Red regression logs remain labelled audit evidence.

## 31. Superseded results preserved

Early 10-node, rebuilt 10-node, pre-fix 20-node and corrected 20-node Task-2 artifacts remain separately identifiable. Historical RESULTS sections, archived model directories, old sampling captures, prior review logs and historical timing remain intact. Broad old claims now have a prominent paper-authority notice rather than silent number replacement.

## 32. Paper documents created

All 27 required files exist under docs/paper: numbered 00 through 25 plus REPOSITORY_CLEANUP_MANIFEST.md. The [master index](paper/00_PAPER_MASTER_GUIDE.md) links every file. The package covers architecture, data, models, protocols, numerical tables, claims, limitations, figures, literature-search positioning, outline, terminology and reproduction. No research paper or fabricated citations were created.

## 33. Files renamed

None. No name-only change justified breaking tooling or historical provenance. Existing misleading labels are explained explicitly.

## 34. Files deleted

None. No candidate satisfied the evidence-preservation requirement for SAFE_TO_DELETE. The manifest records the decision before cleanup.

## 35. Files retained for historical/reproducibility purposes

All raw captures, datasets, fitted models and archives, benchmark JSONs, negative results, figures, prior audit logs, tests, metadata and reproduction scripts were retained. Local ignored secret configuration and outside-workspace backups were not modified. Evidence preservation is checked against the initial Git tree.

## 36. Unknown files requiring human review

`docs/Zero_Trust_CPS_Project_Synopsis.docx` was not rendered/content-audited and remains UNKNOWN_REVIEW_REQUIRED for publication reuse. Ignored/private material is outside paper authority. No assumption of duplicate content or safe deletion was made.

## 37. Cleanup manifest status

The [manifest](paper/REPOSITORY_CLEANUP_MANIFEST.md) records current, historical, reproducibility, raw-evidence, private-audit and unknown classifications; rename/deletion ledgers are empty. Organization improved through canonical entry points and inventories rather than evidence removal.

## 38. Document index status

[docs/README](README.md) separates project, paper, experiment, hardware, historical and audit documentation. Existing root/module documents are retained as supporting/history with explicit authority notices. Machine-readable Markdown/stale-claim/result inventories are under results/final_verification. Automated file-target and hash validation is scoped explicitly; remote URLs and section anchors are not validated by that check.

## 39. Final repository tree

```text
zt-cps-starter/
  README.md                  project entry; points to current paper reference
  RESULTS.md, SESSION_LOG.md preserved chronology
  firmware/                  MPU and SW code, setup, capture log
  src/                       gateway, trust, models, fusion, policy, audit
  scripts/                   capture, generators, offline fitting/evaluation, audit tools
  tests/                     security, schema, temporal, masking, research contracts
  config/                    generator/topology configuration
  data/                      raw captures, labelled sessions, constructed splits
  models/                    current fitted runtime/research artifacts
  models.archived-*/         preserved previous model lineage
  results/                   canonical and historical measured artifacts
    astra_masking_review/     previous baseline audit/replay
    final_verification/       this audit's logs, hashes, matrices, inventories
  docs/
    README.md                canonical document index
    FINAL_PROJECT_VERIFICATION.md
    paper/                   authoritative 27-document paper reference
    figures/                 preserved previous charts
  design/                    retained design material
```

Local certs, caches and graphify state are retained; they are not paper evidence or a reason to publish private configuration.

## 40. Test results

Initial pytest: 143 passed, 161 subtests passed, three warnings. Final suite: **150 collected, 150 passed, 0 failed, 0 skipped, 185 subtests passed, 3 warnings**. Warnings are SHAP/Matplotlib pending deprecations. [Final pytest log](../results/final_verification/pytest_final.log) is authoritative for runtime. Final unittest: **150 tests, OK**, no failures/errors/skips, in [unittest log](../results/final_verification/unittest_final.log). Targeted masking/explanation regressions and real firmware signing tests are included in the final suite; earlier targeted/red-green logs remain preserved. [Documentation validation](../results/final_verification/documentation_validation.json) reports file/link/hash results. Hardware, local/fusion, generator and corrected explanation commands were also executed. No test was skipped or weakened to obtain these results.

## 41. Reproducibility status

Fresh offline replays and test execution are logged; canonical JSONs/checkpoints/captures were preserved. [Reproducibility guide](paper/24_REPRODUCIBILITY_GUIDE.md) lists exact commands, inputs, seeds, outputs and gaps. M1–M9/seed studies were audited rather than unnecessarily refit; original per-run commit/checkpoint fingerprints are incomplete and individual M1–M9 checkpoints were not persisted. Rebuild commands overwrite artifacts and therefore require a preserved disposable research copy. The environment is recorded, not fully locked. No new hardware session or remote deployment was reproduced.

## 42. Paper blockers — P0

These block specific proposed claims, not every possible bounded paper: integrated M6 efficacy lacks serving/fusion evidence; low physical false-alarm reliability contradicts the current 5/12 result; formal permutation claims require a correct probe; literature novelty requires primary-source comparison. **[CLOSED 2026-09-07]** Heterogeneous held-out physical performance — standalone SW-420 VALIDATION/TEST now exist (`results/sw420_real_hardware/`); the network-benchmark's own SW-420 slot remains a separate, still-pending gap (§8 above). The package already excludes unsupported wording. A narrower paper can omit those claims while retaining limitations.

## 43. Important pre-submission items — P1

Freeze full producing provenance; perform matched corrected-mask 10/20 comparisons; track original resampled row identity and temporal support; specify all-invalid API behavior; validate generator on independent blocks/sessions; match policy constraints and timestamp replay; measure full latency; verify physical firmware certificates and model-readiness behavior; regenerate figures and pin the environment.

## 44. Optional strengthening work — P2

Additional same-modality devices, independent sites/load regimes, grouped uncertainty, broader correlated faults, missingness mechanisms and cost-matched model comparisons would strengthen defined claims. They are not evidence already supplied by the constructed benchmark.

## 45. Recommended next experiments

First freeze a new experiment lineage with exact input/code/checkpoint hashes. Then compare local-only, local+GCN and local+M6 with matched fusion/calibration/policy splits; collect independent SW VALIDATION/TEST; run matched 10/20 corrected-mask and joint graph-permutation controls; evaluate generator generalization on independent sessions; finally measure acquisition-to-enforcement latency and constrained policy outcomes under controlled timestamps. Do not tune on the existing TEST to improve its false-alarm result.

## 46. Exact documents to read first when writing the paper

Read [00 Master](paper/00_PAPER_MASTER_GUIDE.md), [22 Factsheet](paper/22_PAPER_READY_FACTSHEET.md), [02 Architecture](paper/02_SYSTEM_ARCHITECTURE.md), [12 Protocol](paper/12_EXPERIMENTAL_PROTOCOL.md), [13 Results](paper/13_RESULTS_MASTER_TABLES.md), [17 Claims](paper/17_CLAIM_EVIDENCE_MATRIX.md), [18 Limitations](paper/18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md), [25 Open items](paper/25_OPEN_ITEMS_BEFORE_SUBMISSION.md), [24 Reproduction](paper/24_REPRODUCIBILITY_GUIDE.md), then [21 Outline](paper/21_FINAL_PAPER_OUTLINE.md).

## 47. Recommended paper writing order

Experimental methodology, results, architecture/methods, discussion, limitations, introduction, related work, abstract and conclusion. Verify related-work sources before novelty wording. Abstract claims must pass the gate in document 17.

## 48. Local commits created

`e0c11e0` — fix invalid relational inputs before arithmetic. `948e310` — scope repair-set evaluation to the recorded modality. `9abecb8` — test actual firmware signing against the gateway. `97e611e` — correct source/console descriptions of benchmark provenance and probe interpretation. `fec297c` — create the canonical 27-document paper package and table renderer. Historical-document indexing and verification tools/evidence are committed separately afterward with neutral messages. The final delivery records their exact hashes; inspect `git log cf4d82c..HEAD --oneline` for the complete local audit sequence.

## 49. Confirmation main was not modified

All edits and local commits were made on `<historical-review-branch>`. Local main remains `4f6afa25e4721c13a4e9f0355548f8ca07c70a5a`. No checkout of main for edits, merge, reset, rebase or history rewrite was performed.

## 50. Confirmation nothing was pushed to main

No push was performed to main or any other branch. No remote publication or merge was requested by this audit. Accessible origin/main remains the original recorded tracking ref.

PROJECT VERIFIED BUT PAPER BLOCKERS REMAIN
