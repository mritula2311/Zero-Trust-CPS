"""Validate local Markdown links, canonical package, numeric hashes and inventory.

Does not access network, mutate evidence or print secrets. Reports historical
inline path references separately from clickable links rather than treating
wildcard examples as missing files.
"""
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/final_verification'
EXPECTED = ['00_PAPER_MASTER_GUIDE','01_RESEARCH_PROBLEM_AND_MOTIVATION','02_SYSTEM_ARCHITECTURE',
 '03_THREAT_MODEL_AND_ZERO_TRUST_DESIGN','04_HARDWARE_DATA_AND_PROVENANCE',
 '05_PROCESS_FEATURES_AND_PREPROCESSING','06_LOCAL_ANOMALY_MODELS','07_RELATIONAL_MODELS_M1_M9',
 '08_TOPOLOGY_AND_ROBUSTNESS_ANALYSIS','09_VIRTUAL_DEVICE_GENERATION','10_FUSION_AND_PROCESS_TRUST',
 '11_POLICY_ENGINE','12_EXPERIMENTAL_PROTOCOL','13_RESULTS_MASTER_TABLES','14_STATISTICAL_ANALYSIS',
 '15_HARDWARE_VALIDATION','16_ABLATIONS_AND_NEGATIVE_RESULTS','17_CLAIM_EVIDENCE_MATRIX',
 '18_LIMITATIONS_AND_THREATS_TO_VALIDITY','19_FIGURE_AND_TABLE_PLAN','20_RELATED_WORK_POSITIONING',
 '21_FINAL_PAPER_OUTLINE','22_PAPER_READY_FACTSHEET','23_TERMINOLOGY_AND_NOTATION',
 '24_REPRODUCIBILITY_GUIDE','25_OPEN_ITEMS_BEFORE_SUBMISSION','REPOSITORY_CLEANUP_MANIFEST']
PATTERNS = [r'GNN is necessary',r'only GNN',r'GNN superiority',r'reinforcement learning',r'full RL',
 r'two MPU6050',r'20 physical',r'15 physical',r'virtual generator not built',r'NP-ST proposed',
 r'Transformer proposed',r'PENDING_REAL_HARDWARE_DATA',r'0\.1467',r'0\.0000',r'0\.4175',r'0\.6567',
 r'0\.4142',r'0\.3958',r'0\.5283']


def write_csv(name, headers, rows):
    with (OUT/name).open('w', encoding='utf-8', newline='') as f:
        w=csv.writer(f); w.writerow(headers); w.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')[:-1]
    docs = set(p for p in ROOT.rglob('*.md') if not any(x in p.parts for x in ('.git','graphify-out','.claude','__pycache__')))
    broken, stale, inventory, checked = [], [], [], 0
    for p in sorted(docs):
        name=p.relative_to(ROOT).as_posix()
        text=p.read_text(encoding='utf-8-sig')
        if name.startswith('docs/paper/') or name=='docs/README.md': kind='AUTHORITATIVE'
        elif name.startswith('results/') or name in ('docs/FINAL_PROJECT_VERIFICATION.md','docs/MANUAL_EXTERNAL_REVIEW.md','docs/PAPER_GNN_BASELINE_VERIFICATION.md','docs/REPOSITORY_AUDIT.md','docs/REVIEW_RESPONSE_TRACKER.md'): kind='PRIVATE AUDIT'
        elif name in ('RESULTS.md','SESSION_LOG.md') or name.startswith('data/'): kind='HISTORICAL'
        else: kind='SUPPORTING'
        inventory.append([name,kind,'CURRENT paper reference' if kind=='AUTHORITATIVE' else 'Historical research claims; supporting implementation/chronology',len(text)])
        in_fence=False
        for lineno,line in enumerate(text.splitlines(),1):
            if line.lstrip().startswith('```'):
                in_fence=not in_fence
            for pattern in PATTERNS:
                if re.search(pattern,line,re.I):
                    if kind=='AUTHORITATIVE':
                        state='CURRENT' if not re.search(r'avoid|not |no |invalid|wrong|histor|supersed|reject|inconclusive',line,re.I) else 'HISTORICAL / SUPERSEDED / PROHIBITED CLAIM (explicit context)'
                    else: state='HISTORICAL' if kind in ('HISTORICAL','SUPPORTING') else 'AUDIT EVIDENCE / historical or scoped current'
                    stale.append([name,lineno,pattern,state,line.strip()])
            if in_fence:
                continue
            for match in re.finditer(r'\[[^\]\n]*\]\(([^)]+)\)',line):
                target=match.group(1).strip().strip('<>')
                if re.match(r'^(https?://|mailto:|#)',target):
                    continue
                target=unquote(target.split('#')[0])
                if not target:
                    continue
                checked+=1
                if not (p.parent/target).exists():
                    broken.append({'file':name,'line':lineno,'target':target})
    missing=[n+'.md' for n in EXPECTED if not (ROOT/'docs/paper'/f'{n}.md').is_file()]
    empty=[n for n in EXPECTED if (ROOT/'docs/paper'/f'{n}.md').exists() and (ROOT/'docs/paper'/f'{n}.md').stat().st_size<300]
    source_errors=[]
    numeric_path=OUT/'paper_numeric_sources.json'
    if numeric_path.exists():
        for name,digest in json.loads(numeric_path.read_text()).items():
            p=ROOT/name
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                source_errors.append(name)
    else: source_errors.append('paper_numeric_sources.json missing')
    write_csv('markdown_inventory.csv',['file','classification','authority','characters'],inventory)
    write_csv('stale_claim_occurrences.csv',['file','line','pattern','classification','context'],stale)
    source_occurrences=[]
    for directory in ('src','scripts','firmware','tests','config'):
        for p in sorted((ROOT/directory).rglob('*.py')):
            name=p.relative_to(ROOT).as_posix()
            # Only tracked/nonignored source; local credential files are outside
            # the claims inventory and handled by the redacted credential scan.
            if name not in tracked and name not in ('scripts/audit_repository_evidence.py','scripts/build_paper_results.py','scripts/verify_paper_package.py'):
                continue
            for lineno,line in enumerate(p.read_text(encoding='utf-8-sig').splitlines(),1):
                for pattern in PATTERNS:
                    if re.search(pattern,line,re.I):
                        state='CURRENT'
                        reason=('Audit search pattern, not a project claim' if name.endswith('verify_paper_package.py') else
                                'Explicit current/historical numerical reconciliation' if name.endswith('build_paper_results.py') else
                                'Current pending-data contract or explicitly qualified terminology')
                        source_occurrences.append([name,lineno,pattern,state,reason,line.strip()])
    write_csv('source_claim_occurrences.csv',['file','line','pattern','classification','reason','context'],source_occurrences)
    artifacts=[]
    for p in sorted((ROOT/'results').rglob('*')):
        if p.is_file():
            name=p.relative_to(ROOT).as_posix()
            if 'astra_masking_review' in name or '/final_verification/' in name: status='PRIVATE AUDIT / KEEP_REPRODUCIBILITY'
            elif 'archived' in name: status='HISTORICAL / SUPERSEDED'
            elif '/latency/' in name or '/simulator_validation/' in name: status='HISTORICAL'
            elif 'm9_' in name or 'seed_study' in name: status='EXPERIMENTAL / ORIGINAL PROVENANCE LIMITED'
            else: status='CURRENT FOR RECORDED PROTOCOL'
            producer=('benchmark_crossdevice_models.py' if 'crossdevice_benchmark' in name else
                      'evaluate_gnn_baselines.py' if 'gnn_baselines' in name else
                      'evaluate_policy_comparison.py' if 'policy_comparison' in name else
                      'evaluate_latency_stages.py' if '/latency/' in name else
                      'evaluate_simulator_validation.py' if 'simulator_validation' in name else 'preserved audit execution')
            if 'crossdevice_benchmark' in name:
                seed='0 (main metrics); 0-9 (seed-study/ablation artifacts)'
                split='Constructed TRAIN / validation threshold selection / held-out TEST; virtual regimes separate'
                metric='Anomaly-positive F1/precision/recall/FPR; Macro-F1; ROC-AUC; paired probe changes'
                checkpoint='Local IF/LSTM and baseline GCN lineage; individual M1-M9 fits not persisted'
            elif 'gnn_baselines' in name:
                seed='0'; split='Network TRAIN / VALIDATION / TEST'
                metric='Task1 anomaly detection; Task2 four-class accuracy; self-loop selected on validation'
                checkpoint='models/gnn_network.pt; upstream per-device IF/LSTM'
            elif 'policy_comparison' in name:
                seed='Producer-defined deterministic fits; wall-clock replay caveat'
                split='VAL_002 fit/select; 2933 accepted legacy TEST rows'
                metric='Four-class accuracy/Macro-F1, per-class recall, false-block rate'
                checkpoint='Current local/GCN/fusion chain and offline bandit Q table'
            elif '/latency/' in name:
                seed='Not a fitting experiment'; split='Historical warm legacy/network workload'
                metric='Milliseconds per stage; partial pipeline; excludes acquisition/broker/SQLite I/O'
                checkpoint='Historical runtime chain; no producing checkpoint hashes in timing JSON'
            elif 'simulator_validation' in name:
                seed='Recorded in source/JSON; historical protocol'
                split='Historical synthetic/hardware comparison; not current SW held-out validation'
                metric='Distribution/discriminator diagnostics; consult preserved JSON'
                checkpoint='No predictive deployment checkpoint'
            else:
                seed='Per execution log/JSON; not an independent headline benchmark'
                split='Audit tests/replays/metadata; failed red logs explicitly preserved'
                metric='Contract outcomes, replay metrics or inventory; filename and log define scope'
                checkpoint='Original artifacts unchanged; any audit GCN copy remains separate'
            artifacts.append([name,status,producer,seed,split,metric,checkpoint,'docs/paper/12_EXPERIMENTAL_PROTOCOL.md; docs/paper/13_RESULTS_MASTER_TABLES.md; docs/paper/24_REPRODUCIBILITY_GUIDE.md'])
    write_csv('result_artifact_inventory.csv',['file','classification','producer','seeds','split_and_protocol','metric_definitions','checkpoint','document_references'],artifacts)
    report={'markdown_files':len(docs),'local_links_checked':checked,'broken_links':broken,
            'missing_canonical_files':missing,'undersized_documents':empty,'numeric_source_errors':source_errors,
            'stale_occurrences_classified':len(stale),'result_artifacts_indexed':len(artifacts),
            'source_claim_occurrences_classified':len(source_occurrences),
            'scope':'Local clickable Markdown file/directory targets (not remote URLs or section anchors); all listed historical phrase/number occurrences retained with context; numeric-source hashes verified.',
            'ok':not(broken or missing or empty or source_errors)}
    (OUT/'documentation_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['ok'] else 1)


if __name__=='__main__':
    main()
