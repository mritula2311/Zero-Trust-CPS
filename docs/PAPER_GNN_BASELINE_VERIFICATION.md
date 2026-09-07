# GNN baseline cross-review and paper evidence ledger

> **[Paper-reference authority, 2026-09-07]** The [verified paper package](paper/00_PAPER_MASTER_GUIDE.md) governs current research claims. This document is retained as supporting implementation/history; earlier measurements and interpretations are historical unless reconfirmed there. Runtime uses a corrected M6 (Set Transformer) fusion, deployed 2026-09-07 after a confirmed training defect was found and fixed in the originally-deployed checkpoint (preserved as historical evidence); M6 was also the selected standalone candidate in the separate M1-M9 benchmark. SW-420 has TRAIN capture only.


Date: 2026-09-06. Reviewed local main:
`4f6afa25e4721c13a4e9f0355548f8ca07c70a5a`.
Review branch: `<historical-review-branch>`. Code/test repair:
`6d74a0e`. Nothing was pushed.

## Verdict and paper wording

**The finite pending-content repair is valid, but the original unrestricted
masking and reporting claims require corrections.** The exact reviewed main
passes 138 unittest tests. The Astra branch adds five checks and removes
nonfinite pending values before arithmetic; its complete suite passes 143
tests with no failures or skips. Evidence is under
[`results/astra_masking_review`](../results/astra_masking_review/).

The request's cross-device “novelty #3” corresponds here to claim-matrix C2.
This is distinct from METHODOLOGY §6's numbered contribution 3, which concerns
hardware-in-the-loop training. That unrelated contribution is not relabeled.

**C2: SUPPORTED BUT WEAKER**, for indexed representations versus a global
count. The literal claim of improvement over a single-device Task-2 baseline
**REQUIRES CONTROLLED FOLLOW-UP**: that baseline has not been measured here.
B0 Task 2 already aggregates all valid devices. Safe paper wording:

> In the current constructed 20-node benchmark, concat logistic regression
> achieved four-way coordination-pattern classification accuracy of 0.5433,
> compared with 0.3958 for a global anomalous-node-count baseline. Concat MLP
> and the GNN scalar-output-vector classifier achieved 0.5267 and 0.5375,
> respectively. These descriptive results support the use of node-indexed
> representations over this aggregate count within the evaluated protocol.

Do not call the differences statistically significant. No appropriate paired,
event/session-aware superiority test was performed. Snapshot windows and reused
source observations must not be treated as independent physical trials. B1 is
the strongest observed TEST comparison, not a model selected by highest
VALIDATION Task-2 accuracy: that ranking favors GNN (0.5475).

**C3: GNN superiority is not established.** The GCN loses to B0/B1/B2 on
Task 1 and beats B3; it loses to B1 on Task 2 and beats B0/B2. There is no
separate B3 Task-2 classifier. Neither a universal GNN-loss statement nor a
causal attribution to graph structure follows.

## Authoritative historical artifacts

All four columns below come from the same exact artifact path,
`results/gnn_baselines/metrics.json`, at the stated commits. The complete
JSON objects, full commit IDs, Git blob IDs and SHA-256 digests are preserved
in [`historical_metrics.json`](../results/astra_masking_review/historical_metrics.json).

| Run | Commit | Meaning |
|---|---|---|
| H10-early | `ba562f7` | Original saved 10-node run; GNN adjacency did not yet mask pending nodes; predates corrected model-chain rebuild. |
| H10-rebuilt | `de3654a` | Later 10-node run after contiguous-window chain rebuild and GNN adjacency masking. Concat pending-content repair was still absent. |
| H20-pre-audit | `162d4a6` | 20-node artifact introduced at `c5cd38d`, unchanged at `162d4a6`; concat masking not yet repaired. |
| H20-corrected | `4f6afa2` | Current 20-node finite pending-content repair, including validity channels and explicit rule/count gating. |

### Task 1: per-node TEST anomaly F1

| Model | H10-early | H10-rebuilt | H20-pre-audit | H20-corrected |
|---|---:|---:|---:|---:|
| B0 own-score logistic | 0.9771 | 0.9736 | 0.9708 | 0.9708 |
| B1 concat logistic | 0.7785 | 0.7762 | 0.7351 | 0.7371 |
| B2 concat MLP | 0.9852 | 0.9823 | **0.9662** | **0.9174** |
| B3 coordinated rule | 0.6156 | 0.6184 | 0.3082 | 0.3082 |
| GNN | 0.8381 | 0.8760 | 0.5865 | 0.5865 |

### Task 2: four-way scenario TEST accuracy

| Model | H10-early | H10-rebuilt | H20-pre-audit | H20-corrected |
|---|---:|---:|---:|---:|
| B0 global anomalous-node count | 0.4142 | 0.4175 | 0.3958 | 0.3958 |
| B1 concat logistic | 0.6433 | 0.6533 | 0.5208 | **0.5433** |
| B2 concat MLP | 0.6567 | 0.6567 | 0.5283 | 0.5267 |
| GNN scalar-output-vector head | 0.6058 | 0.6117 | 0.5375 | 0.5375 |

The discrepancy is **different historical runs plus stale unlabeled
documentation**, not B1 versus B2, Task 1 versus Task 2, or rounding.
ZERO_TRUST_CPS_KB and REVIEW_RESPONSE_TRACKER used H10-early, while the claim
matrix and RESULTS §0.13.20/24 used H10-rebuilt. The identical B2 Task-2 value
0.6567 concealed the difference. `de3654a` changed adjacency masking and rebuilt
upstream models together; individual historical changes cannot be attributed
solely to either intervention. Both genuine runs remain historical evidence,
not current corrected results or independent validations.

## Material corrected-result changes

The H20 correction leaves the selection procedure, seeds, class weights,
training splits, threshold grid and self-loop sweep unchanged. It changes
the representation: Task-1 concat width **80→100** and Task-2 width **60→80**.
Zeroing and explicit validity channels were introduced together. A fixed seed
does not imply identical MLP initialization after an input-dimension change.
Therefore the observed correction is the combined procedure's effect, not
an isolated quantitative estimate of placeholder leakage.

“No threshold changed” is false if it means the selected number: B1 Task-1
threshold changed **0.85→0.125** under the unchanged validation selection rule.
B2 remained at 0.975 and GNN selected self-loop 5.0, threshold 0.15.

| B2 Task-1 TEST measure | Pre-audit | Corrected |
|---|---:|---:|
| F1 | 0.9662 | **0.9174** |
| True positives | 1428 | 1500 |
| False positives | 28 | **270** |
| False negatives | 72 | 0 |
| Precision | 0.9808 | 0.8475 |
| Recall | 0.9520 | 1.0000 |
| False-positive rate | 0.0013 | 0.0127 |

The B2 Task-2 gain over B0 changed +0.1325→+0.1309, a −0.0016 movement.
B1's gain changed +0.1250→+0.1475, a +0.0225 movement. GNN's gain is +0.1417.
Calling all these changes “barely moved” or substituting B1 for B2 without
identifying the model is misleading. None isolates a network-size effect.

## Masking verification from production code

| Path | Reviewed-main finding | Independent evidence |
|---|---|---|
| B0 Task 1 | Already unaffected by other nodes' raw values, for a valid target. | Own-feature extraction selects only that target's three scores. New test supplies the **unmasked** concat row and compares against original target values. |
| B1/B2 Task 1 | Previously affected; repaired for finite content. | Production `main` calls `masked_concat_features` for every split before fits and predictions. Invalid blocks are zeroed, validity inserted before target one-hot. |
| B3 Task 1 | Previously affected; finite repair correct. | Its network anomaly count ANDs threshold decisions with explicit validity. A single true anomaly plus a pending zero block cannot trigger k=2. |
| B0 Task 2 | Previously affected; explicit validity gating correct. | `anomalous_node_count` excludes invalid nodes. The historical 0.9 placeholder was above the 0.6 process threshold, so its old numerical count happened to be unchanged. |
| B1/B2 Task 2 | Previously affected; finite repair correct. | `snapshot_matrix` zeroes invalid raw blocks and appends validity before real sklearn fit/score calls. |
| GNN and Task-2 head | Already unaffected for tested finite content after `de3654a`; nonfinite boundary was not safe. | Both adjacency endpoints and self-loops are validity-gated; loss and Task-1 metric rows are masked. `_GCN` yields exactly 0.5 at pending output columns. The entire vector passed to the real Task-2 head is invariant, including those columns. |

The artifact key `GNN_node_embeddings` is historical naming: its inputs are
**scalar P(normal) outputs per node**, not hidden embeddings. The GNN is
trained and selected for Task 1; only its logistic head fits Task 2. B0 has
three own features on Task 1 but a global count on Task 2. The models share
upstream scores, not byte-identical classifier inputs; GNN also has topology.

The original 11 tests call production helpers and `_GCN`; representation
equality is a useful guarantee for B1/B2, not an implementation copied inside
the tests. Gaps were the absence of entry-point fitting/selection checks,
literal provenance assertions, a pre-mask B0 test, and nonfinite content.
The five new checks in
[`test_gnn_baseline_audit_integration.py`](../tests/test_gnn_baseline_audit_integration.py)
cover those gaps. The entry-point test replaces only expensive replay inputs,
uses the actual 20-node layout with two simultaneous pending nodes, and shortens
GNN training to two epochs. Real sklearn fits, selection, GNN training,
Task-2 heads and serialization run. The scientific replay uses full settings.

Six deliberate mutations were detected with assertion failures, not incidental
exceptions: removing concat zeroing, B3 gating, snapshot zeroing, count gating,
GNN adjacency gating, and bypassing masking in `main`. Original-code results
are in [`adversarial_probes.json`](../results/astra_masking_review/adversarial_probes.json).

### Additional Astra fix: nonfinite invalid values

On reviewed main, `NaN * 0` and `Inf * 0` are not zero. Nonfinite pending
values survived concat masking and contaminated valid GNN outputs because
linear layers run before adjacency multiplication. This falsifies the
unrestricted raw-content claim even though ±1e6 and plausible wrong values pass.

Two regression tests first produced six failing subcases on reviewed main
([red log](../results/astra_masking_review/nonfinite_red.log)). The Astra patch
assigns invalid concat entries to zero, uses conditional selection for snapshot
blocks, and zeroes invalid GNN inputs before training/inference arithmetic.
It does not replace nonfinite **valid** observations or change `valid=None`'s
all-active meaning. Pending labels still have to satisfy the existing binary
label interface; this is a raw-feature-content contract.

All 16 focused masking tests pass
([green log](../results/astra_masking_review/masking_green.log)). Four finite
probes (0.9, −1e6, +1e6, 0.42; two pending nodes) show exact original-versus-Astra
representation, trained-weight and output parity
([finite parity](../results/astra_masking_review/finite_parity.json)).

## Cardinality, provenance and confounds

The actual topology has 20 identities: 10 MPU6050-type and 10 SW-420-type.
`esp32-vib-001` is the physical MPU6050; `esp32-vib-002` is the physical SW-420.
The latter has TRAIN capture `20260905_162002`, with no held-out session yet.
The remaining 18 are simulated, not physical devices. Raw rows say SIMULATED;
the benchmark documentation's LEGACY_SIMULATED category distinguishes them
from virtual-generator research streams.

Across the four scenarios, TRAIN has 2400 snapshots and 48,000 valid node rows.
VALIDATION and TEST each have 1200 snapshots, 22,800 valid node rows and 1200
pending rows. Every stored tick contains each of the 20 IDs exactly once.
Validity is constant across the four scenarios within each split: all TRAIN
nodes are observed; SW-420 alone is pending in both held-out splits. Thus the
validity vector itself is not a varying within-split scenario label here,
although its train/held-out shift remains a limitation.

The 10→20 comparison simultaneously changes cardinality, sensor composition,
provenance and upstream models. Added nodes also change normal context and
class balance. No documentation should attribute the changed effect to size
alone. A corrected 10-node control would be necessary for such causal
attribution, but is **not required** to describe H20-corrected. A true
single-device Task-2 control is a separate follow-up if that stronger claim
is retained.

## Reproduction and environment

The [environment/input manifest](../results/astra_masking_review/environment_and_inputs.json)
records package versions, compute device and source/data/model hashes.
Python is 3.12.10; NumPy 2.4.4, scikit-learn 1.9.0 and PyTorch 2.11.0+cu128.
Dependencies are lower-bound specifications, not a portable lockfile; the
manifest records this machine's actual environment without changing dependencies.

The original-code full replay was launched before the Astra code edits, with
only output paths redirected to avoid overwriting the reviewed artifacts:

```powershell
python -u -c "import sys; from pathlib import Path; sys.path.insert(0,'scripts'); import evaluate_gnn_baselines as e; out=Path('results/astra_masking_review'); e.RESULTS_DIR=str(out); e.NETWORK_GNN_PATH=str(out/'gnn_network.pt'); e.main()"
```

Run that command in a checkout of the exact reviewed commit to reproduce the
original implementation; running it on the Astra branch includes its nonfinite
hardening. [replay.log](../results/astra_masking_review/replay.log) and the saved
metrics/sweep provide the full scientific replay evidence. **Both JSON artifacts
match the exact Git artifacts completely**, and replay GNN weights match the
saved reviewed model exactly. This comparison is recorded in
[`verification.json`](../results/astra_masking_review/verification.json).
It uses existing trained upstream models, not a new six-stage
retraining or a new physical capture.

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_gnn_baseline*.py' -v
```

`unittest` is canonical in README, CLAUDE, METHODOLOGY and EXPERIMENTAL_PROTOCOL.
No project instruction requires pytest. Its absence is **expected (A)**;
no dependency was installed to manufacture a pytest result. Generic agent
skill examples are not this repository's runner specification.

The baseline run passed 138 tests in 28.812 s. The Astra suite passed 143 in
19.227 s ([full log](../results/astra_masking_review/full_suite.log)); these times
are not a performance comparison. No tests failed or skipped. Five baseline
ResourceWarnings originated in pre-existing unclosed file reads/writes in
`test_invariants.py` (lines 243, 485, 491, 651 and 709 at reviewed main).
They are test resource hygiene worth fixing, not failures or evidence of
metric corruption. Three SHAP/matplotlib PendingDeprecationWarnings are
separate third-party warnings. Warning visibility/count can depend on filters
and object cleanup; the reported three ResourceWarnings were not reproduced
as an exact count here. No warnings were suppressed to claim success.

## Scope and remaining work

This review executes the offline evaluator and repository suite, audits code,
checks actual dataset provenance, resolves historical artifacts and corrects
the paper-facing claims. It does not establish broker/TLS deployment behavior,
new hardware capture, industrial validity, or statistical superiority. The
provided attachment contains the updated verification requirements, not a
separate earlier full paper-package specification; this ledger covers every
explicit check in that attachment. Historical RESULTS entries remain in order,
with corrections appended at §0.13.25 and supersession notes at §0.13.20/24.
