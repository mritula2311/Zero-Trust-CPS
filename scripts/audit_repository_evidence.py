"""Read-only evidence inventory; never emit credential values or alter artifacts."""
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/final_verification'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def fingerprint(path):
    return {'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    OUT.mkdir(exist_ok=True)
    tracked = git('ls-files', '-z').decode().split('\0')[:-1]
    inventory = {}
    for name in tracked:
        p = ROOT / name
        if (p.is_file() and not name.startswith('results/final_verification/')
                and name.startswith(('data/', 'models/', 'config/', 'results/', 'src/', 'scripts/', 'firmware/'))):
            inventory[name] = fingerprint(p)
    state = {k: git(*args).decode().strip() for k, args in {
        'branch': ('branch', '--show-current'), 'head': ('rev-parse', 'HEAD'),
        'main': ('rev-parse', 'main'), 'origin_main': ('rev-parse', 'origin/main'),
        'main_ahead_behind': ('rev-list', '--left-right', '--count', 'origin/main...main'),
        'worktrees': ('worktree', 'list'), 'status': ('status', '--short'),
    }.items()}
    state.update(workspace=str(ROOT), python=sys.version, platform=platform.platform(),
                 packages={p: importlib.metadata.version(p) for p in
                           ('numpy', 'torch', 'scikit-learn', 'scipy', 'shap', 'joblib')})
    (OUT / 'repository_inventory.json').write_text(json.dumps({'state': state, 'files': inventory}, indent=2), encoding='utf-8')

    # Compare literal local credentials against all reachable historical blobs.
    # Values stay in memory; report only paths, object IDs, and counts.
    values = set()
    for name in ('src/secrets_local.py', 'firmware/device_secrets.py'):
        p = ROOT / name
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any(any(k in n for k in ('SECRET', 'PASSWORD')) for n in names):
                    try:
                        configured = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
                    candidates = configured.values() if isinstance(configured, dict) else [configured]
                    for v in candidates:
                        if isinstance(v, str) and len(v) >= 12 and not v.startswith('CHANGE-ME'):
                            values.add(v.encode())
    hits, private_keys, token_shapes, inspected = [], [], [], 0
    token_pattern = re.compile(rb'(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|AKIA[A-Z0-9]{16}|sk-proj-[A-Za-z0-9_-]{40,})')
    private_key_pattern = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{32,}-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')

    def inspect(blob, location):
        if any(v in blob for v in values):
            hits.append(location)
        if token_pattern.search(blob):
            token_shapes.append(location)
        if private_key_pattern.search(blob):
            private_keys.append(location)

    working = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')[:-1]
    working_inspected = 0
    for name in sorted(set(working)):
        path = ROOT / name
        if path.is_file():
            inspect(path.read_bytes(), {'scope': 'working tree', 'path': name})
            working_inspected += 1
    entries = git('rev-list', '--objects', '--all').decode().splitlines()
    proc = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for entry in entries:
        oid, _, name = entry.partition(' ')
        if not name:
            continue
        proc.stdin.write((oid + '\n').encode()); proc.stdin.flush()
        header = proc.stdout.readline().decode().split()
        if len(header) != 3:
            continue
        blob = proc.stdout.read(int(header[2])); proc.stdout.read(1)
        if header[1] != 'blob':
            continue
        inspected += 1
        inspect(blob, {'scope': 'reachable history', 'object': oid, 'path': name})
    proc.stdin.close(); proc.wait()
    report = {'scope': 'All reachable Git blobs and nonignored working files compared to locally configured credential literals, private-key blocks and selected provider-token patterns. Not an exhaustive secret detector; rotated/unavailable historical credentials remain unknown.',
              'blobs_inspected': inspected, 'local_credential_values_compared': len(values),
              'working_files_inspected': working_inspected,
              'matches': hits, 'private_key_candidates': private_keys,
              'provider_token_candidates': token_shapes,
              'tracked_sensitive_paths': [n for n in tracked if n in ('src/secrets_local.py', 'firmware/device_secrets.py') or n.endswith(('.key', '.pem', '.pfx'))],
              'verdict': ('CREDENTIAL ROTATION REQUIRED' if hits or private_keys else
                          'TOKEN CANDIDATE REVIEW REQUIRED' if token_shapes else
                          'No configured-secret, private-key or selected provider-token match detected; unknown-secret absence not proven.')}
    (OUT / 'credential_scan.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'tracked_evidence_files': len(inventory), 'history_blobs_inspected': inspected,
                      'working_files_inspected': working_inspected,
                      'credential_match_count': len(hits), 'private_key_candidates': len(private_keys),
                      'provider_token_candidates': len(token_shapes), 'verdict': report['verdict']}))


if __name__ == '__main__':
    main()
