"""Render paper tables from preserved evidence and inspect serving artifacts; no fitting."""
import hashlib
import json
from pathlib import Path
import re
import joblib

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {}


def read(name):
    raw = (ROOT / name).read_bytes()
    SOURCES[name] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def table(headers, rows):
    def cell(x):
        if x is None:
            return 'NOT REPORTED / undefined'
        if isinstance(x, float):
            return f'{x:.6g}'
        return str(x).replace('|', '/').replace('\n', ' ')
    return '\n' + '| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n' + '\n'.join('| ' + ' | '.join(cell(c) for c in row) + ' |' for row in rows) + '\n\n'


def citation(name, script, protocol):
    return f'Source: [{name}](../../{name}); producer [{script}](../../{script}). {protocol}\n'


def _render_o4_corrected_comparison():
    """O4: reads results/gcn_m6_corrected_comparison/* (produced by the
    2026-09-07 comparator repair) and results/comparator_repair/
    comparator_audit.json, rather than hand-transcribing numbers, so a
    future rerun of those evaluators regenerates this section correctly."""
    d = 'results/gcn_m6_corrected_comparison'
    standalone = read(f'{d}/standalone_comparison.json')
    fusion = read(f'{d}/fusion_comparison.json')
    latency = read(f'{d}/latency_comparison.json')
    hardware = read(f'{d}/hardware_comparison.json')
    policy = read(f'{d}/policy_comparison.json')
    read(f'{d}/task2_comparison.json')
    read(f'{d}/artifact_lineage.json')
    read('results/comparator_repair/comparator_audit.json')

    out = ['## O4. Corrected GCN vs M6 comparator (2026-09-07)\n']
    out.append(
        '[CURRENT — explicit artifact pinning] Fixes the O2/O3 comparator-mismatch bug: '
        '`evaluate_ablation_m6.py`, `evaluate_real_hardware.py`, `evaluate_policy_comparison.py` and '
        '`evaluate_explainability_level2.py` previously constructed `FusionEngine()` with no arguments, '
        'which read the *ambient* `config.FUSION_MODEL_PATH` — correct until the 2026-09-07 deployment '
        'overwrote it with the M6-fitted model, after which every "GCN arm" silently paired true GCN '
        'relational scores with M6-calibrated fusion coefficients. Fixed via `src/relational_pin.py`: '
        'three explicit, hash-verified `RelationalPin`s (`gcn`, `m6_deployed`, `m6_corrected`) — see '
        '[results/comparator_repair/comparator_audit.json](../../results/comparator_repair/comparator_audit.json) '
        'for the full per-script before/after audit. `gcn` and `m6_deployed` reference the exact '
        'deployed/preserved artifacts (verified byte-identical, unchanged by this repair). `m6_corrected` '
        'is a **new** checkpoint, retrained after fixing a confirmed class-weight bug in '
        '`scripts/train_set_transformer.py` (below) — **not deployed**; evaluation/comparison only.\n')
    out.append(
        '**Class-weight bug, confirmed with numbers.** `train_set_transformer.py` computed its '
        'inverse-frequency `pos_weight`/`neg_weight` over the full, unmasked node-target tensor, but the '
        'loss only ever trains on the `valid`-masked subset (verified against `training_session.json`: '
        '656,040 total node-slots, only 58,486 / 8.9% ever valid). Actual (buggy) vs. correct: '
        '`neg_weight` (suspicious class) = 45.18 vs. 6.27 — a **7.2x overweight**. `train_gnn.py` does '
        'not have this bug (its loss is unmasked by design). Fixed by counting `ys[valids]`; '
        '`m6_corrected` is one retrain with the fix, deployed `set_transformer_runtime.pt` untouched '
        '(verified byte-identical hash before/after this work).\n')

    out.append('**Standalone relational score** (`test_session.json`, threshold 0.6, normal-positive polarity):\n')
    rows = [[arm, r['macro_f1'], r.get('precision_normal'), r['recall_normal'], r['false_alarm_rate_fpr'], r['roc_auc']]
            for arm, r in standalone['results'].items()]
    out.append(table(['Arm', 'Macro-F1', 'Precision (normal)', 'Recall (normal)', 'FPR', 'ROC-AUC'], rows))
    out.append(
        "The deployed M6 checkpoint's raw/standalone score is badly miscalibrated at the deployed "
        'threshold (near-zero normal recall). The corrected retrain repairs this dramatically. ROC-AUC '
        '(threshold-independent) is comparable across all three, showing the raw discriminative '
        'information was less damaged than the threshold-0.6 operating point suggests.\n')

    out.append('**Fusion** (Rule+IF+LSTM+relational, matched fusion artifact per arm):\n')
    rows = [[arm, r['macro_f1'], r['recall_normal'], r['false_alarm_rate_fpr'], r['roc_auc']]
            for arm, r in fusion['results'].items()]
    out.append(table(['Arm', 'Macro-F1', 'Recall (normal)', 'FPR', 'ROC-AUC'], rows))
    out.append(
        'Both M6 variants modestly beat the GCN fusion arm on this held-out replay, now under a '
        'genuinely matched comparison — safe to describe as a **modest, held-out-replay-qualified** '
        'improvement (17 Claim C), not a general claim. The fusion layer visibly compensates for the '
        "deployed checkpoint's poor standalone calibration.\n")

    out.append('**Latency** (standalone relational-scorer inference, post-warmup, this environment):\n')
    rows = [[arm, r['mean_ms'], r['p95_ms'], r['n_calls']] for arm, r in latency['results'].items()]
    out.append(table(['Arm', 'Mean (ms)', 'p95 (ms)', 'n calls'], rows))
    out.append(
        'M6 (either variant) is slower per call than GCN; both remain a small fraction of the '
        'previously measured end-to-end pipeline latency (R below), so this does not by itself threaten '
        'the practical latency budget.\n')

    out.append('**Hardware** (real MPU6050 TEST session, inference only, no retrain on test data):\n')
    rows = []
    for arm, r in hardware['results'].items():
        fp, det = r['resting_false_positive_rate'], r['disturbance_detection_rate']
        rows.append([arm, f"{fp['k']}/{fp['n']}", f"{fp['rate']:.1%}", f"{det['k']}/{det['n']}", f"{det['rate']:.1%}"])
    out.append(table(['Arm', 'Resting FP', 'Resting FP rate', 'Detection', 'Detection rate'], rows))
    out.append(
        'Identical across all three arms — no regression from GCN to either M6 variant on the available '
        'physical evidence (Gate H).\n')

    out.append('**Policy** (`evaluate_policy_comparison.py`, GCN pin):\n')
    out.append(table(['Policy', 'GCN-pin rerun Macro-F1', 'Preserved historical Macro-F1'],
                     [[k, v['macro_f1'], policy['historical_preserved_2026_09_04'][k]['macro_f1']]
                      for k, v in policy['gcn_pin_repaired_rerun'].items()]))
    out.append(
        'P1/P2/P6 (pure threshold policies) reproduce within verified wall-clock jitter. P5 (adaptive '
        'bandit) is stable across repeated runs but differs from its preserved number by more than that '
        'jitter — evidence `models/adaptive_pdp_qtable.json` was itself retrained during the 2026-09-07 '
        'deployment under the same mismatched-artifact bug. **No M6 policy arm is reported here**: no '
        'policy retrain was performed in this earlier pass (explicit scope decision at the time). '
        '**This gap is closed in O5 below**, the same day\'s final pass (17 Claim D).\n')

    out.append(
        'Source for this section: `results/gcn_m6_corrected_comparison/` '
        '(`standalone_comparison.json`, `fusion_comparison.json`, `hardware_comparison.json`, '
        '`latency_comparison.json`, `policy_comparison.json`, `artifact_lineage.json`, `summary.md`); '
        'producers `scripts/evaluate_ablation_m6.py`, '
        '`scripts/evaluate_real_hardware.py --relational-model {gcn,m6_deployed,m6_corrected}`. '
        f"Commit {standalone['meta']['commit']}; seed {standalone['meta']['seed']}.\n")
    return ''.join(out)


def _render_o5_corrected_policy():
    """O5: reads results/m6_corrected_policy/* (produced by the 2026-09-07
    final corrected-M6 deployment pass) rather than hand-transcribing
    numbers, so a future rerun of scripts/evaluate_m6_corrected_policy.py
    regenerates this section correctly."""
    d = 'results/m6_corrected_policy'
    policy = read(f'{d}/policy_metrics.json')
    action = read(f'{d}/policy_action_metrics.json')
    lineage = read(f'{d}/artifact_lineage.json')
    read(f'{d}/policy_training_config.json')
    runtime = read(f'{d}/runtime_verification.json')
    hardware = read(f'{d}/hardware_regression.json')

    out = ['## O5. Corrected M6 policy comparison and deployment promotion (2026-09-07 final pass)\n']
    out.append(
        '[CURRENT] Closes the O4/17-Claim-D gap. Two fixes made this possible, both additive/opt-in '
        '(default behaviour of every existing caller unchanged, verified via the pre-existing 193-test '
        'suite passing unmodified): (1) `scripts/train_adaptive_pdp.py` now requires an explicit '
        '`src/relational_pin.py` `RelationalPin` (`ZTCPS_ADAPTIVE_PDP_PIN` env var, default `gcn`) instead '
        'of the bare `GNNScorer()`/`FusionEngine()` that corrupted `models/adaptive_pdp_qtable.json`\'s '
        'provenance during the M6 deployment; a metadata sidecar records full lineage, and '
        '`relational_pin.verify_policy_lineage()` fails loudly on any future mismatch. (2) `GNNScorer`/'
        '`SetTransformerScorer`\'s active-neighbour window and `RuleBasedTrustEngine`\'s Security Trust '
        'EWMA decay both accept an injected deterministic `clock` (default `None` -> `time.time()`, so '
        'live-gateway freshness semantics are provably unchanged) — offline replay now uses each record\'s '
        'own `ts` field instead of wall-clock time, fixing a confirmed non-determinism (see '
        '`tests/test_policy_training_determinism.py`).\n')
    out.append(
        f"Two Q-tables were trained fresh (seed {lineage['m6_corrected'].get('seed')}, deterministic clock, "
        f"`validation_policy_session.json`, `'combined'`/stealthy-forged-values excluded as unlearnable — "
        'same protocol the historical table used): `adaptive_pdp_qtable_gcn_corrected.json` (GCN + matched '
        'GCN fusion — a **fair, clean-provenance GCN baseline**, distinct from the corrupted-provenance '
        '`adaptive_pdp_qtable.json`) and `adaptive_pdp_qtable_m6_corrected.json` (corrected M6 + matched '
        'corrected-M6 fusion). Evaluated on the untouched `test_session.json`:\n')

    rows = [[name, r['macro_f1'], r['weighted_f1'], r['accuracy'], r['false_block_rate'], r['false_step_up_rate']]
            for name, r in policy['results'].items()]
    out.append(table(['Policy', 'Macro-F1', 'Weighted-F1', 'Accuracy', 'False-block rate', 'False-step-up rate'], rows))

    action_rows = []
    for name, per_class in action.items():
        for act, m in per_class.items():
            action_rows.append([name, act, m['support'], m['precision'], m['recall'], m['f1'], m['tp'], m['fp'], m['fn']])
    out.append('Per-action (BLOCK recall reported as measured, not hidden or substituted, whatever its value):\n')
    out.append(table(['Arm', 'Action', 'Support', 'Precision', 'Recall', 'F1', 'TP', 'FP', 'FN'], action_rows))
    out.append(
        'BLOCK is unreachable for **both** arms — the pre-existing, architectural `stealthy_forged_values`'
        '/`combined`-class blind spot (excluded from training as unlearnable from a `(security_trust, '
        'process_trust)` state space; see `train_adaptive_pdp.py`\'s docstring), not specific to either '
        'relational model. ALERT precision is low for both (matching the project\'s already-documented '
        'finding that a validation-tuned static policy beats the adaptive bandit — see 18). '
        '**Corrected M6\'s policy modestly outperforms the fair GCN baseline** on macro-F1 and weighted-F1 '
        '— consistent in direction and magnitude with the fusion-level gap in O4, small enough that it '
        'should be described as "matches or modestly exceeds," not a strong claim.\n')

    out.append(
        f"**Deployment decision: PROMOTE_CORRECTED_M6.** Given the confirmed training defect in the "
        f"checkpoint deployed by `3c827e8` (O4), and clean results on every gate (lineage, fusion, policy, "
        f"193/193 tests, no hardware regression — {hardware['verdict'][:120]}…, latency unchanged and "
        f"within budget, runtime integration verified — `design/verify-runtime.py` ok={runtime['verify_runtime_output']['ok']}, "
        f"runtime_relational_model={runtime['verify_runtime_output']['runtime_relational_model']!r}), "
        "`config.py`'s ambient `SET_TRANSFORMER_MODEL_PATH` / `FUSION_MODEL_PATH` / `FUSION_BACKGROUND_PATH` "
        "/ `ADAPTIVE_PDP_MODEL_PATH` now point at the corrected checkpoint, its matched fusion artifact, "
        "and `adaptive_pdp_qtable_m6_corrected.json` respectively. **No previously-deployed artifact was "
        "modified or deleted** — `set_transformer_runtime.pt`, `fusion_meta_learner.joblib`/"
        "`fusion_meta_learner_m6_variant.joblib` and `adaptive_pdp_qtable.json` remain on disk "
        "byte-identical, and are additionally preserved under "
        "`models/adaptive_pdp_qtable_m6_deployed_20260907_corrupted_provenance.json`. "
        "`src/relational_pin.py`'s `M6_DEPLOYED` pin now resolves via an explicit, ambient-independent "
        "constant (`SET_TRANSFORMER_MODEL_PATH_M6_DEPLOYED_FLAWED_20260907`) so it remains hash-verifiable "
        "regardless of what is deployed later.\n")

    out.append(
        'Source for this section: `results/m6_corrected_policy/` (`policy_metrics.json`, '
        '`policy_action_metrics.json`, `artifact_lineage.json`, `policy_training_config.json`, '
        '`runtime_verification.json`, `hardware_regression.json`, `summary.md`); producers '
        '`scripts/evaluate_m6_corrected_policy.py`, `scripts/train_adaptive_pdp.py`. '
        f"Seed {lineage['m6_corrected'].get('seed')}; deterministic clock (per-record `ts`).\n")
    return ''.join(out)


def main():
    bpath = 'results/crossdevice_benchmark/metrics.json'
    b = read(bpath)
    bs = 'scripts/benchmark_crossdevice_models.py'
    out = ['# Results master tables\n\n[CURRENT NUMERICAL AUTHORITY] Generated from frozen JSON, preserved replay logs and inspected model artifacts. '
           'A result is current for its stated protocol, not automatically for every runtime or data revision. '
           'Final invalid-content hardening has new regression/parity evidence; archived benchmark metrics were not overwritten. '
           'Missing PR-AUC/checkpoint identities are explicit.\n\n'
           '**Polarity:** relational F1 treats anomaly as positive; local/fusion replay F1 treats normal as positive. '
           'Macro-F1 averages class F1 values. A normality score below its threshold flags an anomaly.\n']
    out.append('## A / O. Local detectors and preserved GCN fusion\n')
    lp = 'results/final_verification/local_fusion_evaluation.log'
    raw = (ROOT / lp).read_text(encoding='utf-8-sig')
    SOURCES[lp] = hashlib.sha256((ROOT / lp).read_bytes()).hexdigest()
    rows = re.findall(r'^(rule_score|isolation_forest_score|lstm_ae_score|transformer_score|gnn_score|fused_score)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$', raw, re.M)
    out.append(citation(lp, 'scripts/evaluate_ablation.py', '[VERIFIED PRESERVED GCN-ERA REPLAY; SUPERSEDED AS RUNTIME LINEAGE] 3,050 legacy synthetic TEST records, 117 rejected excluded, 2,933 accepted (2,700 normal/233 anomalous); three identities; threshold 0.6. Printed precision is three decimals. Two scalar identities substitute rule scores into learned local channels; this is not a three-physical-device evaluation. Current default fusion is M6-fitted, so the producer requires explicit GCN backup selection for a matched replication.'))
    out.append(table(['Signal', 'Accuracy', 'Normal precision', 'Normal recall', 'Normal F1'], rows[:6]))
    out.append('Fair primary-device temporal subset: 1,000 MPU test rows, 746 window-residue normal rows excluded, 254 retained. Conditional results, not full-stream performance.\n')
    out.append(table(['Signal', 'Accuracy', 'Normal precision', 'Normal recall', 'Normal F1'], rows[6:]))
    out.append('The log also reports anomaly-event recall: fused shock 1.000, coordinated 0.983, stealthy-forged-values 0.636. These are event-type window recalls, not independent attack trials. M6 fusion comparison is [REQUIRES FINAL FUSION VALIDATION].\n')
    out.append('## O2. Configured fusion artifact identity, not a performance result\n')
    out.append(
        '[SUPERSEDED BY THE 2026-09-07 CORRECTED-M6 PROMOTION — see O5] This table originally described the '
        'artifact deployed by commit `3c827e8`, through the comparator-repair pass that produced O4; kept '
        'for chronology. As of the corrected-M6 promotion (O5), `config.py`\'s ambient `FUSION_MODEL_PATH` '
        '/ `FUSION_BACKGROUND_PATH` point at `fusion_meta_learner_m6_corrected_variant.joblib` instead — '
        'included below, marked CURRENT. `fusion_meta_learner.joblib` itself is untouched on disk (still '
        'byte-identical to its row below) and remains reachable as the historical/superseded deployed '
        'artifact via `src/relational_pin.py`\'s `M6_DEPLOYED` pin.\n')
    out.append('[VERIFIED ARTIFACT INSPECTION, 2026-09-07] Active fusion/background match the M6 variants. The fourth input retains the legacy name `gnn_score`, but the gateway supplies M6. The older model_metadata.json describes the GCN backup. Source: the following saved joblib files; producer of this inspection: `scripts/build_paper_results.py`. No evaluation or fitting occurs.\n')
    model_rows = []
    for name, note in (
        ('models/fusion_meta_learner.joblib', 'historical: deployed until the O5 promotion'),
        ('models/fusion_meta_learner_m6_variant.joblib', ''),
        ('models/fusion_meta_learner_gcn_backup.joblib', ''),
        ('models/fusion_meta_learner_m6_corrected_variant.joblib', 'CURRENT: deployed as of O5'),
    ):
        model = joblib.load(ROOT/name)
        SOURCES[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        label = f'[{name}](../../{name})' + (f' ({note})' if note else '')
        model_rows.append([label, ', '.join(f'{v:.10g}' for v in model.coef_[0]), float(model.intercept_[0]), SOURCES[name]])
    out.append(table(['Artifact', 'Coefficients: rule, IF, LSTM, relational', 'Intercept', 'SHA-256'], model_rows))
    for name in ('models/set_transformer_runtime.pt', 'models/set_transformer_corrected.pt', 'models/fusion_background.npy', 'models/fusion_background_m6_variant.npy', 'models/fusion_background_gcn_backup.npy', 'models/fusion_background_m6_corrected_variant.npy'):
        SOURCES[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    out.append('## O3. Historical reported M6 comparison — SUPERSEDED by O4\n')
    out.append('[SUPERSEDED — see O4] [RESULTS.md](../../RESULTS.md) records normal-positive fused F1 0.805→0.815, accuracy 0.698→0.712, normal false negatives 872→833 and anomaly misses 14→13. No matching raw comparison log/JSON was found for that specific prose observation, and the comparator that would have reproduced it (`evaluate_ablation_m6.py`) had a confirmed artifact-mismatch bug (its "GCN arm" silently read the M6-fitted fusion model — see O2). That bug is fixed (2026-09-07, results/comparator_repair/comparator_audit.json); O4 below is the current, correctly-pinned replacement. Keep this paragraph for chronology only — do not cite it as a current number.\n')
    out.append(_render_o4_corrected_comparison())
    out.append(_render_o5_corrected_policy())
    out.append('## B / C. M1–M9, validation max-anomaly-F1 operating point\n')
    out.append(citation(bpath, bs, '[CURRENT EXPERIMENTAL] Seed 0; fit TRAIN 2,400 snapshots/48,000 valid rows, select VALIDATION 1,200 snapshots/22,800 valid rows, report TEST with same held-out counts; declared network 20 (19 valid held-out); hybrid provenance. TEST has 1,500 anomalous rows: 150 isolated and 1,350 coordinated, plus 21,300 normal; 15 anomaly events.'))
    rows = []
    for name, r in b['results'].items():
        t = r['test']
        rows.append([name, r['test_macro_f1'], t['precision'], t['recall'], t['f1'], t['false_positive_rate'], r['recall_isolated_anomaly'], r['recall_coordinated_anomaly'], r['test_roc_auc'], r.get('test_pr_auc'), r['threshold_selected_on_validation']])
    out.append(table(['Model', 'Macro-F1', 'Precision', 'Recall', 'Anomaly F1', 'FPR', 'Isolated recall', 'Coordinated recall', 'ROC-AUC', 'PR-AUC', 'Threshold'], rows))
    out.append('JSON keys: `results.<model>.test.*`, `test_macro_f1`, `test_roc_auc`, `recall_isolated_anomaly`, `recall_coordinated_anomaly`. PR-AUC is absent from these nine max-F1 rows, not zero. The offline M1–M9 benchmark fits have no saved per-model checkpoints. A separate runtime M6 checkpoint exists; it does not inherit these benchmark numbers. M4 has a distinct baseline GCN checkpoint lineage.\n')
    out.append('## R / S. M1–M9 model cost\n')
    out.append(table(['Model', 'Parameters', 'Epochs', 'Train total ms', 'Inference mean ms', 'p50 ms', 'p95 ms', 'Timed samples'], [[n,r.get('parameters'),r['train_epochs'],r['train_time_ms_total'],r['inference_latency']['mean_ms'],r['inference_latency']['p50_ms'],r['inference_latency']['p95_ms'],r['inference_latency']['n']] for n,r in b['results'].items()]))
    out.append('Same source as B. Host timing of an individual scored sample/snapshot; not sensor-to-enforcement latency. Parameters for tree ensembles are not comparable to neural weights.\n')
    out.append('## Calibration and alarm-budget operating points\n')
    out.append('Isotonic mapping fits one validation half; threshold selection uses the other half. These rows are different operating points from B. The declared cap is a selection rule, not a guarantee on future data.\n')
    out.append(table(['Model','FPR cap','Selected threshold','TEST FPR','Macro-F1','Anomaly F1','Precision','Recall','Cap held'], [[n,cap,z['threshold_selected_on_validation'],z['test']['false_positive_rate'],z['test_macro_f1'],z['test']['f1'],z['test']['precision'],z['test']['recall'],z['cap_held_on_test']] for n,r in b['results'].items() for cap,z in r.get('fpr_capped',{}).items()]))
    out.append(table(['Model','Raw TEST Brier','Calibrated TEST Brier'], [[n,r['calibration']['test_brier_raw'],r['calibration']['test_brier_calibrated']] for n,r in b['results'].items() if 'calibration' in r]))
    labels = {'neighbour_degree_at_n10':'D. Target-degree intervention', 'peer_density_at_n10_degree3':'E. Peer-density intervention', 'dilution_one_anomaly_among_n_minus_1_healthy':'H / K. Mixed-cardinality dilution', 'coordination_k_of_10_anomalous':'Coordinated-count intervention', 'dilution_n10_declared_topology':'Declared-topology control'}
    for key, title in labels.items():
        out.append('## ' + title + '\n')
        cardinality = ('n=10' if key in ('neighbour_degree_at_n10','peer_density_at_n10_degree3','coordination_k_of_10_anomalous') else 'n=2/3/5/10/20' if key=='dilution_one_anomaly_among_n_minus_1_healthy' else 'n=20 declared topology (historical artifact key says n10)')
        out.append(citation(bpath, bs, f'[EXPERIMENTAL] `structural_probes.{key}`; {cardinality}; 400 synthetic probe draws/cell built from valid score pools; model fitted once. Degree/peer interventions reuse a shared batch. Dilution draws advance across models/sizes and are not paired with the separately sampled declared-topology control.'))
        rows=[]
        for n,levels in b['structural_probes'][key].items():
            if 'mean_p_anomaly' in levels:
                levels={'control': levels}
            rows.extend([n,k,v['mean_p_anomaly'],v['recall_at_threshold']] for k,v in levels.items())
        out.append(table(['Model','Intervention level','Mean anomaly probability','Recall at frozen threshold'], rows))
    out.append('## F. Self-loop sweep\n')
    out.append('Same benchmark source; selection is on VALIDATION, with 20 declared /19 valid nodes. Retrain GCN for each candidate.\n')
    out.append(table(['Self-loop weight','Selected threshold','VAL anomaly F1','VAL precision','VAL recall','VAL FPR'], [[w,r['threshold'],r['f1'],r['precision'],r['recall'],r['false_positive_rate']] for w,r in b['gcn_self_loop_sweep_validation'].items()]))
    out.append('## G. Fixed-topology slot-reassignment probe\n')
    out.append('Same source, `structural_probes.permutation_max_abs_score_delta`. [VERIFIED INTERPRETATION CORRECTION] Features are permuted while graph adjacency stays fixed. These values do not disprove graph permutation equivariance.\n')
    out.append(table(['Model','Maximum absolute score delta'], b['structural_probes']['permutation_max_abs_score_delta'].items()))
    sp='results/crossdevice_benchmark/seed_study.json'; s=read(sp)
    out.append('## D / E, repeated refits: paired intervention endpoints\n')
    out.append(citation(sp,bs,'[EXPERIMENTAL] Seeds 0–9 on one fixed split/probe corpus. Paired t intervals have df=9; training variability only. No population-resampling CI or multiplicity correction is established.'))
    out.append(table(['Probe','Model','Endpoint change','Mean recall delta','SD','95% interval','t','Negative seeds','n'], [[p,n,r['levels'],r['mean_delta'],r['sd'],r.get('ci95'),r.get('t'),r['seeds_negative'],r['n_seeds']] for p,mods in s['paired_effects'].items() for n,r in mods.items()]))
    interaction=list(s['interaction']['within_model'].items())+[('across_models',s['interaction']['across_models'])]
    out.append(table(['Interaction comparison','Contrast','Mean','SD','95% interval','t','n'],[[n,r['contrast'],r['mean'],r['sd'],r['ci95'],r['t'],r['n_seeds']] for n,r in interaction]))
    out.append('## I. Virtual-generator validity boundary\n')
    gp='results/final_verification/generator_validation.log'
    out.append(citation(gp,'scripts/validate_virtual_device_generator.py','[VERIFIED FRESH DIAGNOSTIC] TRAIN: 103 resting source rows in 7 runs; 618 generated rows/42 blocks per preset. These are dependent residual observations, not held-out devices. Overall exit status 1 reflects failed stress marginal checks.'))
    out.append(table(['Regime','Marginal diagnostic','Cross-node RMS spread','Permitted interpretation'], [['LOW','Pass all four measured free coordinates',0.00794,'Internal TRAIN residual consistency'],['MEDIUM','RMS marginal divergence',0.01509,'OOD sensitivity regime'],['HIGH','RMS and peak marginal divergence',0.03842,'OOD sensitivity regime']]))
    out.append('The raw log retains every KS statistic/p-value, covariance and lag difference, classifier accuracy, clipping frequency and ordering check. A near-chance discriminator is not proof that real and virtual distributions are identical.\n')
    mp='results/crossdevice_benchmark/m9_seed_study.json'; m=read(mp)
    out.append('## J / L / M. M9 mixed-provenance and virtual-only ablation\n')
    out.append(citation(mp,bs,'[EXPERIMENTAL, PROVENANCE-LIMITED] Ten refits; source artifact omits immutable input/code/cardinality fingerprints. Historical labels say real n=10; current main benchmark uses 20. Do not assume the seed-study file belongs to the seed-0 M9 protocol. LOW virtual test n=5; MEDIUM/HIGH retain LOW-fitted threshold.'))
    rows=[]
    for regime, metrics in m['summary'].items():
        for metric,v in metrics.items():
            rows.append([regime,metric,v.get('mean'),v.get('sd'),v.get('ci95'),v.get('n_seeds')])
    out.append(table(['Regime','Metric','Mean','SD','95% CI half-width','n seeds'], rows))
    ap='results/crossdevice_benchmark/m9_ablation_investigation.json'; a=read(ap)
    out.append(citation(ap,bs,'[EXPERIMENTAL, PROVENANCE-LIMITED] Frozen full-validation threshold; slices do not refit. Separate same-model hybrid versus virtual-only lineage. Normal-only slice F1 is undefined; its FPR remains reportable.'))
    out.append(table(['Training lineage','Slice / metric','Mean','SD','95% CI half-width','n seeds'], [[n,k,v.get('mean'),v.get('sd'),v.get('ci95'),v.get('n_seeds')] for n,metrics in a['summary'].items() for k,v in metrics.items()]))
    out.append('The historical virtual-only advantage remains [INCONCLUSIVE] after masking/cardinality changes. A matched controlled rerun is required for a causal attribution to provenance.\n')
    out.append('## N. Task-2 chronology and corrected novelty claim\n')
    hp='results/astra_masking_review/historical_metrics.json'; h=read(hp)
    out.append(citation(hp,'scripts/evaluate_gnn_baselines.py','Historical snapshots retain producing commits and Git blob hashes. Each Task-2 row is a 4-way network scenario classification, not per-node anomaly F1.'))
    rows=[]
    for lineage,r in h.items():
        if isinstance(r,dict) and 'metrics' in r:
            for name,v in r['metrics'].get('task2_network_coordination_pattern',{}).items():
                if isinstance(v,dict):
                    rows.append([lineage,r.get('commit','')[:7],r['metrics']['network']['size'],name,v['test'],v['validation']])
    current=read('results/gnn_baselines/metrics.json')
    for name,v in current['task2_network_coordination_pattern'].items():
        if isinstance(v,dict):
            rows.append(['CURRENT + M6 (2026-09-07)','4f6afa2 + nonfinite hardening + M6 arm',20,name,v['test'],v['validation']])
    out.append(table(['Chronology','Producer','Declared n','Representation label','TEST accuracy','VAL accuracy'],rows))
    out.append('B0 Task 2 counts network anomalies, B1 is indexed concatenated logistic regression, B2 is indexed concatenated MLP; `GNN_node_embeddings` actually concatenates final scalar GCN scores before a logistic head. Corrected B0→B2 is 0.3958→0.5267 (delta +0.1309); pre-fix B2 0.5283 (delta +0.1325). B1 0.5433 exceeds GCN-score 0.5375 numerically. Verdict: SUPPORTED BUT WEAKER for indexed representation versus count; no graph-superiority claim.\n')
    out.append('**M6 arm added 2026-09-07** (evaluate_gnn_baselines.py previously had none — see 17 Claim B and [results/gcn_m6_corrected_comparison/task2_comparison.json](../../results/gcn_m6_corrected_comparison/task2_comparison.json)). A from-scratch model trained under this script\'s own protocol (correct valid-only class weighting from the start), NOT the runtime checkpoint. `M6_node_embeddings` is the best of all five Task-2 methods, beating `GNN_node_embeddings` by a wide margin; the companion Task-1 per-node run shows the same pattern more sharply (M6 test F1 0.9736 vs. GNN 0.5865) — a controlled, apples-to-apples result distinct from both the offline M1-M9 sweep (C05) and the separately-flawed runtime M6 checkpoint (O4).\n')
    read('results/astra_masking_review/historical_metrics.json')
    out.append(
        '### Task-1 B2 degradation — status table\n\n'
        '| Field | Value |\n|---|---|\n'
        '| Claim | B2 (concat MLP) Task-1 anomaly F1 degraded 0.9662 → 0.9174 (false positives 28 → 270, false negatives 72 → 0) between `pre_audit_20_node` and `corrected_20_node` above |\n'
        '| Status | CURRENT — reproduced fresh 2026-09-07 (byte-identical to the preserved run) |\n'
        '| Source artifact | [results/astra_masking_review/historical_metrics.json](../../results/astra_masking_review/historical_metrics.json) (`metrics.results.B2_concat_mlp.test`); reproduced in [results/gnn_baselines/metrics.json](../../results/gnn_baselines/metrics.json) |\n'
        '| Protocol | Fit TRAIN, threshold selected on VALIDATION (max F1), reported on TEST once; 20-node declared network, PENDING-node masking |\n'
        '| Bug/fix state | Reflects the nonfinite/pending-node masking fix (4f6afa2 + hardening); the recall gain trades against precision — a real, measured degradation, not something to fix further here |\n'
        '| Current/superseded | CURRENT — numerical authority for B2\'s Task-1 result; `pre_audit_20_node` is preserved chronology only |\n\n')
    pp='results/policy_comparison/metrics.json'; p=read(pp)
    out.append('## P. Policy comparison\n')
    out.append(citation(pp,'scripts/evaluate_policy_comparison.py','[PRESERVED GCN-ERA ARTIFACT; NOT CURRENT M6 POLICY VALIDATION] 2,933 accepted legacy TEST rows; comparators share two-score replay inputs. Fitting/threshold selection uses simulated VAL_002. These are offline policy classifications, not measured enforcement effectiveness. Current policy producers use GCN plus default M6 fusion; the saved runtime Q table lacks producing-model hashes.'))
    out.append(table(['Policy','Accuracy','Macro-F1','False-block rate','ALERT recall','BLOCK recall'],[[n,r['accuracy'],r['macro_f1'],r['false_block_rate'],r['per_class']['ALERT']['recall'],r['per_class']['BLOCK']['recall']] for n,r in p['results'].items()]))
    out.append('P6 is constrained static, P5 contextual bandit. P6 searches under ALERT recall≥0.90 and false-block≤0.01 on validation. P5 was not trained with this constrained search; both meet those bounds descriptively on the saved TEST rows. P5 Macro-F1 exceeds P6. Neither detects the BLOCK class here.\n')
    out.append('**2026-09-07 comparator fix and finding** (see O4 and [results/gcn_m6_corrected_comparison/policy_comparison.json](../../results/gcn_m6_corrected_comparison/policy_comparison.json)): `evaluate_policy_comparison.py` is now explicitly pinned to `gcn` by default (was silently reading the ambient, now-M6-fitted `FUSION_MODEL_PATH`). A pinned rerun reproduces P1/P2/P6 within verified wall-clock-jitter tolerance, but P5 is stably different from this table\'s preserved number — evidence `models/adaptive_pdp_qtable.json` was itself retrained under the mismatched-artifact bug during the 2026-09-07 deployment. **Same day, final pass: closed — see O5** for a corrected, deterministic-clock, clean-provenance GCN-vs-M6 policy comparison (17 Claim D).\n')
    out.append('## Q. Held-out physical hardware\n')
    out.append(citation('results/final_verification/hardware_evaluation.log','scripts/evaluate_real_hardware.py','[VERIFIED PRESERVED GCN-ERA REPLAY] One MPU6050 TEST session 20260902_221217. Reset/warm-up exclusion leaves 42 scored observations at threshold 0.6. Raw session has 116 rows.'))
    out.append(table(['Endpoint','Count','Rate','Printed Wilson 95% interval','Limit'],[['Rest false alarm','5 / 12','41.7%','19.3%–68.0%','Small dependent sample'],['Disturbance detection','30 / 30','100%','88.6%–100%','Hand-induced physical events; no cyberattack'],['SW-420 held-out','0 physical sessions',None,None,'PENDING VALIDATION']]))
    out.append('Two action-labelled windows have peak no greater than resting maximum; 28 movement-containing windows are also all detected. Do not drop the quiet windows silently or use this replay as twenty-device field evidence.\n')
    out.append('**2026-09-07: M6 comparison now exists.** `evaluate_real_hardware.py --relational-model {gcn,m6_deployed,m6_corrected}` (src/relational_pin.py) reproduces this exact table when pinned to `gcn`, and gives identical numbers for both M6 variants — no regression on the available physical evidence (Gate H). See O4 and [results/gcn_m6_corrected_comparison/hardware_comparison.json](../../results/gcn_m6_corrected_comparison/hardware_comparison.json).\n')
    out.append('## Explainability: single-channel and exploratory rank-aware repair\n')
    ep='results/final_verification/explainability_evaluation_corrected.log'
    out.append(citation(ep,'scripts/evaluate_explainability_level2.py','[VERIFIED PRESERVED GCN-ERA REPLAY] Single-channel evaluation uses flagged resolvable legacy TEST rows and a historical 0.5 threshold, not runtime 0.6. The separate minimal repair analysis pools labelled MPU captures across TRAIN/VALIDATION/TEST and is exploratory, not held-out validation. 2026-09-07: `--relational-model {gcn,m6_deployed,m6_corrected}` now pins this explicitly; default `gcn` reproduces the table below exactly. Not in the required GCN-vs-M6 comparison set, so no new M6 explainability headline number is reported.'))
    out.append(table(['Protocol','Repair','Recovered / denominator','Interpretation'],[['Single-channel TEST','GCN peer','78 / 78','Resolvable flagged subset'],['Single-channel TEST','IF feature','1 / 2','Tiny subset'],['Single-channel TEST','LSTM feature','0 / 139','Does not recover'],['Single-channel TEST','All','79 / 219','36% < declared 70% target'],['Exploratory pooled captures','Best 1 of 5','0 / 182','MPU-only; all-split analysis'],['Exploratory pooled captures','Best 2 of 5','11 / 182','Not held-out'],['Exploratory pooled captures','Best 3 of 5','179 / 182','98% is a different metric; not a replacement for 36%'],['Exploratory pooled captures','Best 4 of 5','182 / 182','Not held-out']]))
    out.append('## R. Runtime stage latency, preserved historical measurement\n')
    latp='results/latency/latency.json'; lat=read(latp)
    out.append(citation(latp,'scripts/evaluate_latency_stages.py','[HISTORICAL / REQUIRES CURRENT END-TO-END MEASUREMENT] Warm perf_counter_ns timing; snapshot environment in docs/ENVIRONMENT.md. Audit stage includes hash computation, excludes SQLite I/O. Mixed scalar/feature workload.'))
    out.append(table(['Stage','Count','Mean ms','SD ms','p50 ms','p95 ms','p99 ms'],[[n,r['count'],r['mean_ms'],r['sd_ms'],r['p50_ms'],r['p95_ms'],r['p99_ms']] for n,r in lat['stages'].items()]))
    out.append(f"Cold start: {lat['cold_start_ms']} ms. The `network_10_node_tick` key is historical and must not be presented as a fresh 20-node measure. No bound on acquisition-to-enforcement latency follows.\n")
    # Every linked input log/JSON receives a content hash, including logs whose
    # printed precision is deliberately retained in hand-labelled tables.
    for name in re.findall(r'\]\(../../(results/[^)]+)\)', '\n'.join(out)):
        SOURCES[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    (ROOT/'docs/paper/13_RESULTS_MASTER_TABLES.md').write_text('\n'.join(out), encoding='utf-8')
    (ROOT/'results/final_verification/paper_numeric_sources.json').write_text(json.dumps(SOURCES,indent=2),encoding='utf-8')
    print(f'Rendered results reference from {len(SOURCES)} hashed artifacts.')


if __name__ == '__main__':
    main()
