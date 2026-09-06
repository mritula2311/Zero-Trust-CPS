# System architecture reconstructed from implementation

[VERIFIED: code; DEPLOYMENT CANDIDATE: current checkout] The runtime paths below are implemented and exercised by tests/offline replay. This audit did not flash hardware or connect to a live broker. “Runtime” identifies the serving code; it is not evidence of a currently running deployment.

```mermaid
flowchart TD
  F[ESP32 telemetry: modality-specific features] --> T[MQTT TLS or HTTPS ingestion]
  T --> A[Envelope/schema, identity, revocation, HMAC, finite reading, replay, freshness]
  A -->|rejected| R[Identity-targeting risk and rejection audit]
  A -->|accepted| S[Rate and step-up evidence: Security Trust]
  A -->|accepted| L[Rule, per-device IF and LSTM-AE]
  L --> G[Runtime GCN on three local scores per node]
  L --> U[Four-score logistic fusion]
  G --> U
  U --> P[Process Trust and freshness state]
  S --> D[Static table or offline contextual-bandit policy]
  P --> D
  D --> E[Decision/challenge publication and quarantine]
  D --> X[SHAP, local perturbation explanation, hash-chained audit]
```

## Exact boundary and computations

`gateway._process_telemetry` holds `_pipeline_lock` through accepted-message scoring and decision persistence. It computes Security Trust at `score_security_trust(device_id, is_flood, step_up_result)` and Process Trust at `fusion_engine.combine(rule, IF, LSTM, GCN)`. The first computational meeting is the gateway policy branch: `adaptive_pdp.greedy_action(security_trust_score, process_trust_score)` when `USE_RL_POLICY=True`, otherwise `policy_engine.decide(security_trust_score, process_trust_score, process_status)`. Merely storing both values in the gateway or audit row is not a fusion of evidence.

Security Trust starts at 0.8, applies bounded elapsed-time decay, then EWMA weight 0.35 to an authenticated observation: normal rate 0.95; flood 0.2; step-up success adds a bounded 0.1; failure observations decrease with the failure count. Decay is `min(0.3, 0.01*max(elapsed,0))`; score is clipped to [0,1] and rounded to three decimals. Signature failures update a separate identity-targeting record. Identity/HMAC/revocation are gates, not physical model inputs. See [trust engine](../../src/trust_engine.py), `score_security_trust`, `get_security_trust` and state classes.

Process Trust is logistic `P(normal)` from four detector scores. The process-state store retains the last numerical value on silence and marks it STALE after 20 seconds; it does not drift an unresolved anomaly toward normal. Current static thresholds are 0.6/0.6. The static `process_status` argument does not change table action by itself. The bandit accepts only the two numerical scores; the watchdog and step-up overrides are separate serving behaviours.

## Verification matrix

The [master CSV](../../results/final_verification/subsystem_matrix.csv) expands the following summary into the requested 15 fields for all 24 subsystems, including separate implementation, training, deployment, artifact and paper-description columns.

Unless specified otherwise, runtime components do not train; tests are contract coverage, not measured line coverage. “Artifact absent” is a reproduction limitation, not a passing result.

| Component / purpose | Implementation: class/function | Input → output | Algorithm / training | Inference / deployment | Test or artifact | Research limitation / paper-safe description |
|---|---|---|---|---|---|---|
| Firmware / acquire and sign | `firmware/main.py`, `main_sw420.py`: feature and telemetry functions | Sensor windows → signed feature envelope | DSP; no training | MicroPython code; captures support physical use | `test_invariants.py`, raw captures | Exact flashed revision/build unknown |
| Gateway ingestion | `gateway.process_telemetry`, `on_message` | JSON envelope → decision/audit | Locked staged validation | Runtime | `test_gateway_input_validation.py` | MQTT wire operation not remeasured here |
| Identity | Registry lookup in `_process_telemetry` | Claimed ID → known/unknown | Static registry | Pre-HMAC gate | `test_invariants.py` | Claimed ID is not proof of sender |
| Authentication | `gateway.verify_signature` | Payload, signature, key → boolean | HMAC-SHA256 | Runtime gate | canonicalization and rejection tests | No hardware root of trust |
| Revocation | `trust_engine.is_revoked`, `revoke_device` | ID → rejection override | In-memory registry status | Before HMAC | invariant tests | Durable lifecycle management limited |
| HMAC / rotation | `verify_signature_with_rotation` | Current/previous key → verification | Grace-window key rotation | Runtime | invariant tests | Secret provisioning outside tracked source |
| Replay | `check_boot_replay`, `commit_boot_seq` | Boot/sequence → accept; committed baseline | Strict monotonic counters | Commit after all gates | boot-state isolation tests | Gateway replay baseline not durable across restart |
| Freshness | `check_timestamp_freshness` | Signed timestamp → boolean | Absolute 600-second window | Runtime gate | freshness/malformed tests | Demo tolerance is wide |
| Security Trust | `score_security_trust` | Authenticated rate/step-up → trust | Decay + EWMA, no learning | Runtime | separation/state tests | Does not identify every compromised-key attack |
| Physical telemetry | `_extract_reading`, `feature_names_for` | Registry modality + payload → typed reading | Exact field selection | After authentication | hardware schema tests | Semantically false but finite values can authenticate |
| Preprocessing | `feature_engineering.feature_vector`; `datasets.normal_sequences` | Named fields/runs → ordered vectors/windows | Saved TRAIN mean/std | Training/inference separated | temporal/schema tests; model metadata | Resampled network trajectories are not contiguous physical acquisitions |
| Local detectors | `rule_range_score`, `IsolationForestScorer`, `LSTMAEScorer` | Local reading/window → normality scores | Rule; offline IF and LSTM-AE | Runtime | local replay; checkpoint metadata | Scalar devices mirror rule into IF/LSTM slots |
| Temporal Transformer | `TransformerScorer` | Eight-step window → score | Offline denoising Transformer AE | Ablation only | fair local comparison | No measured deployment advantage |
| Relational runtime | `GNNScorer.score`, `_GCN` | Per-node [rule,IF,LSTM] → P(normal) | Offline GCN; 32 hidden, 3 layers | Runtime candidate | masking tests; `models/gnn.pt` | Active-time graph differs from benchmark topology |
| Relational research | Benchmark M1–M9 factories | Constructed score snapshots → per-node probabilities | Offline sklearn/PyTorch | Experimental | crossdevice metrics | No persisted per-model M1–M9 checkpoints |
| Fusion | `FusionEngine.combine` | Four local/GCN scores → trust/confidence | Balanced logistic regression on VAL_001 | Runtime | `fusion_meta_learner.joblib`; replay | M6 complementarity untested |
| Process Trust | `update_process_anomaly`, `get_process_anomaly` | Fused normality → retained score/status | State store; no training | Runtime | staleness tests | Confidence is probability decisiveness, not uncertainty calibration |
| Policy | `decide`; `AdaptivePDP.greedy_action` | Two trusts → four actions | Static table / offline sample-average bandit | Bandit selected by config | policy comparison metrics | No sequential Bellman learning |
| Explainability | `FusionEngine._explain`; `explainability.level2_explain` | Scores/models → additive log-odds and perturbation explanation | SHAP LinearExplainer; repair probes | Runtime and experimental evaluation | explanation tests/log | Repair/rank metrics differ; some use historical 0.5 |
| Audit logging | `audit_log.log_decision`, integrity/checkpoint verification | Decision → SQLite chain/checkpoints | SHA-256 chain, separate HMAC key | Runtime | audit-chain invariants | Local key/storage compromise is outside guarantee |
| Virtual generator | `VirtualDevice`, `generate_virtual_network_data.py` | TRAIN/VAL/TEST source blocks + seed → generated streams | Affine transform + covariance-aware AR(1) + drift | Offline experiment | generator tests/validation log | Single-source internal realism diagnostic |
| Benchmark generation | `generate_network_data.py` | Real pools + legacy simulator → 20-node scenarios | Seeded resampling/scenario injection | Offline | schema/generation tests; network files | Physical-source rows sampled with replacement |
| Hardware capture | `collect_hardware_session.py`, `merge_real_hardware_data.py` | Gateway records + operator marks → labelled data | Capture/curation; no learner | Operator-dependent | raw captures/split manifest | No fresh capture during audit |
| Experiment scripts | `train_*.py`, `evaluate_*.py`, benchmark | Frozen splits/checkpoints → metrics | Offline training/evaluation | Research only | preserved logs/JSON | Some scripts print rather than persist JSON |

Paths in the matrix resolve under [src](../../src), [scripts](../../scripts), [tests](../../tests) and [firmware](../../firmware). Evidence indexing and producer/command mappings are in [12](12_EXPERIMENTAL_PROTOCOL.md), [13](13_RESULTS_MASTER_TABLES.md) and [24](24_REPRODUCIBILITY_GUIDE.md).

## Runtime versus research candidate

The gateway instantiates `GNNScorer`, not any class from `benchmark_crossdevice_models.py`. Its `models/gnn.pt` uses time-coactive registry nodes and self-loop weight 3; benchmark M4 uses declared network topology, a validation-selected weight 5 and `models/gnn_network.pt`. These checkpoints are different. M6 would require an explicit serving adapter, matched score construction, retrained fusion, calibration, model identity and end-to-end evaluation. Selecting its standalone architecture implements none of those steps.

Runtime registry includes the two physical identities, two legacy scalar identities and eighteen dynamically registered simulated feature nodes: 22 entries. The network benchmark uses the 20 feature-carrying entries. The legacy replay exercises three identities. Do not equate registry shape, benchmark cardinality and simultaneously connected physical devices.

## Failure and training contracts

Parsing/type validation precedes identity; identity and revocation precede HMAC; finite-reading checks precede replay and freshness; only then does `commit_boot_seq` mutate accepted state. The expected conceptual ordering has therefore been refined by code: malformed envelope fields must be checked before a registry lookup is safe. `_reject` updates targeting risk and audit records but uses a read-only trust peek; it does not update accepted sequences, model histories, Security Trust, Process Trust or quarantine counters. Logging cooldown applies only after a failed HMAC, so attackers cannot throttle authenticated traffic by claiming its ID.

Runtime scorer methods load checkpoints, set evaluation mode and use inference calls; gateway never calls fit, backward, optimizer step or bandit update. Bandit `_get_q` can initialize an unseen bucket from the static policy; this is deterministic memoization, not reward-based online training. Offline scripts use stored `auth_ok`/event annotations rather than cryptographically revalidating historical captures. The no-training-on-rejection property is established for runtime and declared offline filters, not arbitrary maliciously edited dataset files.

Model-file absence can activate neutral score or mean-fusion fallbacks. Startup rejects unconfigured MQTT TLS/broker credentials but does not require every learned checkpoint. This is a deployment limitation: serving availability is not proof that the complete trained chain is loaded. See [03](03_THREAT_MODEL_AND_ZERO_TRUST_DESIGN.md) and [10](10_FUSION_AND_PROCESS_TRUST.md).
