"""Render paper reference tables from preserved artifacts, without fitting models."""
import hashlib
import json
from pathlib import Path
import re

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


def main():
    bpath = 'results/crossdevice_benchmark/metrics.json'
    b = read(bpath)
    bs = 'scripts/benchmark_crossdevice_models.py'
    out = ['# Results master tables\n\n[CURRENT] Numerical reference generated directly from frozen JSON and fresh replay logs. '
           'A result is current for its stated protocol, not automatically for every runtime or data revision. '
           'Final invalid-content hardening has new regression/parity evidence; archived benchmark metrics were not overwritten. '
           'Missing PR-AUC/checkpoint identities are explicit.\n\n'
           '**Polarity:** relational F1 treats anomaly as positive; local/fusion replay F1 treats normal as positive. '
           'Macro-F1 averages class F1 values. A normality score below its threshold flags an anomaly.\n']
    out.append('## A / O. Local detectors and actual GCN fusion\n')
    lp = 'results/final_verification/local_fusion_evaluation.log'
    raw = (ROOT / lp).read_text(encoding='utf-8-sig')
    SOURCES[lp] = hashlib.sha256((ROOT / lp).read_bytes()).hexdigest()
    rows = re.findall(r'^(rule_score|isolation_forest_score|lstm_ae_score|transformer_score|gnn_score|fused_score)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$', raw, re.M)
    out.append(citation(lp, 'scripts/evaluate_ablation.py', '[VERIFIED FRESH REPLAY] 3,050 legacy synthetic TEST records, 117 rejected excluded, 2,933 accepted (2,700 normal/233 anomalous); three identities; threshold 0.6. Printed precision is three decimals. No training in this command.'))
    out.append(table(['Signal', 'Accuracy', 'Normal precision', 'Normal recall', 'Normal F1'], rows[:6]))
    out.append('Fair primary-device temporal subset: 1,000 MPU test rows, 746 window-residue normal rows excluded, 254 retained. Conditional results, not full-stream performance.\n')
    out.append(table(['Signal', 'Accuracy', 'Normal precision', 'Normal recall', 'Normal F1'], rows[6:]))
    out.append('The log also reports anomaly-event recall: fused shock 1.000, coordinated 0.983, stealthy-forged-values 0.636. These are event-type window recalls, not independent attack trials. M6 fusion comparison is [REQUIRES FINAL FUSION VALIDATION].\n')
    out.append('## B / C. M1–M9, validation max-anomaly-F1 operating point\n')
    out.append(citation(bpath, bs, '[CURRENT EXPERIMENTAL] Seed 0; fit TRAIN 2,400 snapshots/48,000 valid rows, select VALIDATION 1,200 snapshots/22,800 valid rows, report TEST with same held-out counts; declared network 20 (19 valid held-out); hybrid provenance. TEST has 1,500 anomalous rows: 150 isolated and 1,350 coordinated, plus 21,300 normal; 15 anomaly events.'))
    rows = []
    for name, r in b['results'].items():
        t = r['test']
        rows.append([name, r['test_macro_f1'], t['precision'], t['recall'], t['f1'], t['false_positive_rate'], r['recall_isolated_anomaly'], r['recall_coordinated_anomaly'], r['test_roc_auc'], r.get('test_pr_auc'), r['threshold_selected_on_validation']])
    out.append(table(['Model', 'Macro-F1', 'Precision', 'Recall', 'Anomaly F1', 'FPR', 'Isolated recall', 'Coordinated recall', 'ROC-AUC', 'PR-AUC', 'Threshold'], rows))
    out.append('JSON keys: `results.<model>.test.*`, `test_macro_f1`, `test_roc_auc`, `recall_isolated_anomaly`, `recall_coordinated_anomaly`. PR-AUC is absent from these nine max-F1 rows, not zero. No standalone M1–M9 checkpoints are persisted. M4 has a distinct baseline GCN checkpoint lineage.\n')
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
            rows.append(['CURRENT corrected','4f6afa2 + nonfinite hardening',20,name,v['test'],v['validation']])
    out.append(table(['Chronology','Producer','Declared n','Representation label','TEST accuracy','VAL accuracy'],rows))
    out.append('B0 Task 2 counts network anomalies, B1 is indexed concatenated logistic regression, B2 is indexed concatenated MLP; `GNN_node_embeddings` actually concatenates final scalar GCN scores before a logistic head. Corrected B0→B2 is 0.3958→0.5267 (delta +0.1309); pre-fix B2 0.5283 (delta +0.1325). B1 0.5433 exceeds GCN-score 0.5375 numerically. Verdict: SUPPORTED BUT WEAKER for indexed representation versus count; no graph-superiority claim.\n')
    pp='results/policy_comparison/metrics.json'; p=read(pp)
    out.append('## P. Policy comparison\n')
    out.append(citation(pp,'scripts/evaluate_policy_comparison.py','[CURRENT PRESERVED ARTIFACT] 2,933 accepted legacy TEST rows; comparators share two-score replay inputs. Fitting/threshold selection uses simulated VAL_002. These are offline policy classifications, not measured enforcement effectiveness.'))
    out.append(table(['Policy','Accuracy','Macro-F1','False-block rate','ALERT recall','BLOCK recall'],[[n,r['accuracy'],r['macro_f1'],r['false_block_rate'],r['per_class']['ALERT']['recall'],r['per_class']['BLOCK']['recall']] for n,r in p['results'].items()]))
    out.append('P6 is constrained static, P5 contextual bandit. P6 searches under ALERT recall≥0.90 and false-block≤0.01 on validation. P5 was not trained with this constrained search; both meet those bounds descriptively on the saved TEST rows. P5 Macro-F1 exceeds P6. Neither detects the BLOCK class here.\n')
    out.append('## Q. Held-out physical hardware\n')
    out.append(citation('results/final_verification/hardware_evaluation.log','scripts/evaluate_real_hardware.py','[VERIFIED FRESH REPLAY] One MPU6050 TEST session 20260902_221217. Reset/warm-up exclusion leaves 42 scored observations at threshold 0.6. Raw session has 116 rows.'))
    out.append(table(['Endpoint','Count','Rate','Printed Wilson 95% interval','Limit'],[['Rest false alarm','5 / 12','41.7%','19.3%–68.0%','Small dependent sample'],['Disturbance detection','30 / 30','100%','88.6%–100%','Hand-induced physical events; no cyberattack'],['SW-420 held-out','0 physical sessions',None,None,'PENDING VALIDATION']]))
    out.append('Two action-labelled windows have peak no greater than resting maximum; 28 movement-containing windows are also all detected. Do not drop the quiet windows silently or use this replay as twenty-device field evidence.\n')
    out.append('## Explainability: single-channel and exploratory rank-aware repair\n')
    ep='results/final_verification/explainability_evaluation_corrected.log'
    out.append(citation(ep,'scripts/evaluate_explainability_level2.py','[VERIFIED FRESH REPLAY] Single-channel evaluation uses flagged resolvable legacy TEST rows and a historical 0.5 threshold, not runtime 0.6. The separate minimal repair analysis pools labelled MPU captures across TRAIN/VALIDATION/TEST and is exploratory, not held-out validation.'))
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
