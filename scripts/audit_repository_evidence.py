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

# Values shorter than this are excluded from the broad history/working-tree
# substring scan, since a very short literal risks matching unrelated blobs
# by coincidence. This is a noise floor for that one scan only -- it must
# never gate the reused-public-identifier check below, which is an exact
# equality test against known identifiers and carries no such false-positive
# risk regardless of length.
PLAUSIBLE_SECRET_MIN_LEN = 6
PLACEHOLDER_PREFIXES = ('CHANGE-ME', 'CHANGE_ME', 'YOUR_', 'REPLACE_WITH', 'EXAMPLE_')
PLACEHOLDER_EXACT = {'TEST_ONLY', 'TESTONLY'}
# Substrings (checked against the value with all non-alphanumeric characters
# stripped, so hyphen/underscore/case variants all match) that mark a value as
# a synthetic test or attack-simulation fixture rather than a real secret --
# e.g. attack_live_gateway.py's WRONG_SECRET = "attacker-guessed-secret-00000",
# or a test's "test-only-signing-contract-key". These don't follow a fixed
# prefix the way CHANGE-ME does, so they need substring, not startswith.
SYNTHETIC_VALUE_MARKERS = ('ATTACKER', 'TESTONLY', 'WRONGSECRET', 'WRONGKEY',
                           'WRONGPASSWORD', 'DUMMY', 'FAKESECRET', 'PLACEHOLDER')
# Substrings of an assignment target's name that mark it credential-sensitive.
# Deliberately broad (SECRET/PASSWORD/TOKEN/KEY) since this only runs against
# two known local files (src/secrets_local.py, firmware/device_secrets.py), not
# the whole codebase, so the false-positive cost of over-matching is near zero.
SENSITIVE_NAME_MARKERS = ('SECRET', 'PASSWORD', 'TOKEN', 'KEY')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def fingerprint(path):
    return {'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def is_placeholder(value):
    """True for known safe template values (case-insensitive), never a real secret."""
    if not value:
        return True
    upper = value.upper()
    if upper in PLACEHOLDER_EXACT:
        return True
    if any(upper.startswith(p) for p in PLACEHOLDER_PREFIXES):
        return True
    normalized = re.sub(r'[^A-Z0-9]', '', upper)
    return any(marker in normalized for marker in SYNTHETIC_VALUE_MARKERS)


def collect_credential_assignments(paths):
    """Parse each path for `NAME = "value"` / dict-literal assignments where NAME
    contains a marker in SENSITIVE_NAME_MARKERS (SECRET/PASSWORD/TOKEN/KEY, e.g.
    WIFI_PASSWORD, DEVICE_SECRET, HMAC_KEY, API_KEY). Returns
    [(source_path, field_label, value), ...]. Field labels look like
    'WIFI_PASSWORD' or 'DEVICE_SECRETS[esp32-vib-001]'; callers must report
    only these labels, never the value."""
    out = []
    for p in paths:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(any(k in n.upper() for k in SENSITIVE_NAME_MARKERS) for n in names):
                continue
            try:
                configured = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            if isinstance(configured, dict):
                for key, v in configured.items():
                    if isinstance(v, str):
                        out.append((p, f'{names[0]}[{key}]', v))
            elif isinstance(configured, str):
                out.append((p, names[0], configured))
    return out


def find_hardcoded_credentials_in_tracked_source(root):
    """Every tracked .py file must obtain credential-sensitive values only by
    importing them from the gitignored local-secret files (src/secrets_local.py,
    firmware/device_secrets.py) -- never by assigning a literal to a
    credential-sensitive name directly. A literal assignment in ANY OTHER
    tracked file means a real secret was pasted straight into source (this is
    exactly how firmware/main_sw420.py leaked a live Wi-Fi password, HMAC
    secret and MQTT password in a public commit -- collect_credential_assignments
    only ever looked at the two local files, so it never saw this). Returns
    'path:FIELD' labels only, never the value."""
    tracked_py = [root / name for name in
                  subprocess.check_output(['git', 'ls-files', '*.py'], cwd=root, text=True).splitlines()]
    assignments = collect_credential_assignments(tracked_py)
    return [f'{p.relative_to(root).as_posix()}:{label}' for p, label, v in assignments
            if not is_placeholder(v)]


def derive_public_identifiers(root, extra=()):
    """Known-public identifiers a credential must not equal: the repo owner/slug
    published in PRD.md's Repository line, the Git commit author name and the
    local-part of their email (both already public in any pushed history), plus
    any caller-supplied identifiers (used by tests to stay hermetic)."""
    identifiers = set(extra)
    prd = root / 'PRD.md'
    if prd.exists():
        m = re.search(r'github\.com/([^/\s`]+)/([^/\s`|]+)', prd.read_text(encoding='utf-8-sig'))
        if m:
            identifiers.add(m.group(1))
            identifiers.add(m.group(2))
    try:
        author = subprocess.check_output(['git', 'log', '-1', '--format=%an\x1f%ae'],
                                          cwd=root, stderr=subprocess.DEVNULL).decode().strip()
        name, _, email = author.partition('\x1f')
        if name:
            identifiers.add(name)
        if email:
            identifiers.add(email.split('@', 1)[0])
    except subprocess.CalledProcessError:
        pass
    return {i.strip() for i in identifiers if i and i.strip()}


def find_reused_identifiers(assignments, identifiers):
    """Credential-sensitive values that exactly equal a known public identifier
    (case-insensitive), independent of length. Returns 'path:FIELD' labels only,
    never the value."""
    lowered = {i.lower() for i in identifiers}
    return [f'{p.name}:{label}' for p, label, v in assignments
            if not is_placeholder(v) and v.lower() in lowered]


def select_scan_values(assignments, reused_identifier_matches, min_len=PLAUSIBLE_SECRET_MIN_LEN):
    """Values to search for in the working tree / Git history: any non-placeholder
    value at least min_len long, plus -- regardless of length -- any value already
    flagged as a reused public identifier, since that risk was proven by exact
    equality rather than by the noise-prone broad substring scan."""
    values = {v for _, _, v in assignments if not is_placeholder(v) and len(v) >= min_len}
    values |= {v for p, label, v in assignments if f'{p.name}:{label}' in reused_identifier_matches}
    return values


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
    # `git worktree list` (and, in principle, `git status`) can embed absolute
    # workstation paths -- e.g. every other registered worktree's checkout
    # path -- so replace this checkout's path and its parent directory with
    # portable markers before anything is written to a tracked artifact.
    state['worktrees'] = (state['worktrees'].replace(str(ROOT), '<REPO_ROOT>')
                          .replace(str(ROOT.parent), '<WORKSPACE_ROOT>')
                          .replace(str(ROOT).replace('\\', '/'), '<REPO_ROOT>')
                          .replace(str(ROOT.parent).replace('\\', '/'), '<WORKSPACE_ROOT>'))
    # Never embed the live absolute checkout path in a tracked artifact: this
    # script always runs from the repository root by construction (ROOT is
    # derived from __file__), so a portable marker carries the same meaning
    # without leaking a workstation-specific path into version control.
    state.update(workspace='<REPO_ROOT>', python=sys.version, platform=platform.platform(),
                 packages={p: importlib.metadata.version(p) for p in
                           ('numpy', 'torch', 'scikit-learn', 'scipy', 'shap', 'joblib')})
    (OUT / 'repository_inventory.json').write_text(json.dumps({'state': state, 'files': inventory}, indent=2), encoding='utf-8')

    # Compare literal local credentials against all reachable historical blobs.
    # Values stay in memory; report only paths, object IDs, field labels and counts.
    secret_paths = [ROOT / 'src/secrets_local.py', ROOT / 'firmware/device_secrets.py']
    assignments = collect_credential_assignments(secret_paths)
    identifiers = derive_public_identifiers(ROOT)
    reused_identifier_matches = find_reused_identifiers(assignments, identifiers)
    hardcoded_in_tracked_source = find_hardcoded_credentials_in_tracked_source(ROOT)
    values = {v.encode() for v in select_scan_values(assignments, reused_identifier_matches)}
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
        if name.startswith('results/final_verification/'):
            continue  # this tool's own prior report can echo public identifiers; not new exposure
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
    report = {'scope': 'All reachable Git blobs and nonignored working files compared to locally configured credential literals, private-key blocks and selected provider-token patterns; an exact-equality check of credential-sensitive fields against known public repository identifiers (independent of literal length); and every tracked .py file checked for a credential-sensitive name assigned a literal value directly, rather than imported from the two designated local-secret files. Not an exhaustive secret detector; rotated/unavailable historical credentials remain unknown.',
              'blobs_inspected': inspected, 'local_credential_values_compared': len(values),
              'working_files_inspected': working_inspected,
              'matches': hits, 'private_key_candidates': private_keys,
              'provider_token_candidates': token_shapes,
              'reused_public_identifier_fields': reused_identifier_matches,
              'hardcoded_credential_in_tracked_source_fields': hardcoded_in_tracked_source,
              'public_identifiers_checked_against': sorted(identifiers),
              'tracked_sensitive_paths': [n for n in tracked if n in ('src/secrets_local.py', 'firmware/device_secrets.py') or n.endswith(('.key', '.pem', '.pfx'))],
              'verdict': ('CREDENTIAL ROTATION REQUIRED' if hits or private_keys or reused_identifier_matches or hardcoded_in_tracked_source else
                          'TOKEN CANDIDATE REVIEW REQUIRED' if token_shapes else
                          'No configured-secret, private-key, reused-identifier, hardcoded-in-source or selected provider-token match detected; unknown-secret absence not proven.')}
    (OUT / 'credential_scan.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'tracked_evidence_files': len(inventory), 'history_blobs_inspected': inspected,
                      'working_files_inspected': working_inspected,
                      'credential_match_count': len(hits), 'private_key_candidates': len(private_keys),
                      'provider_token_candidates': len(token_shapes),
                      'reused_public_identifier_fields': reused_identifier_matches,
                      'hardcoded_credential_in_tracked_source_fields': hardcoded_in_tracked_source,
                      'verdict': report['verdict']}))


if __name__ == '__main__':
    main()
