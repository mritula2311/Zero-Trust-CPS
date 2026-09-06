"""Portable source, link and publication checks; reports findings without values."""
import ast
import json
import re
import subprocess
from pathlib import Path

folder = Path(__file__).resolve().parent
root = folder.parent
ignored = {"node_modules", "coverage", "dist", ".cache", "qa-output", "screenshots", "__pycache__"}
files = [p for p in folder.rglob("*") if p.is_file() and not (set(p.relative_to(folder).parts) & ignored)]
findings = []
patterns = {
    "absolute local path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    "private key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "credential literal": re.compile(r'''(?i)\b(?:api_key|password|secret|access_token)\s*[:=]\s*["']([^"'\r\n]{16,})["']'''),
    "access key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
}
for path in files:
    name = path.relative_to(root).as_posix()
    if path.name.startswith(".env") or path.suffix in {".log", ".key", ".pem", ".db", ".png"}:
        findings.append(dict(file=name, kind="unexpected publication file"))
    text = path.read_text(encoding="utf-8-sig")
    for kind, pattern in patterns.items():
        for match in pattern.finditer(text):
            findings.append(dict(file=name, line=text[:match.start()].count("\n")+1, kind=kind))
    if path.suffix == ".py":
        ast.parse(text, filename=name)
    if path.suffix in {".js", ".mjs"}:
        subprocess.run(["node", "--check", str(path)], check=True, capture_output=True)
    if path.suffix == ".html":
        for code in re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", text):
            if code.strip():
                subprocess.run(["node", "--check"], input=code, text=True, check=True, capture_output=True)
    if path.suffix == ".md":
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            if not (path.parent / target.split("#")[0]).exists():
                findings.append(dict(file=name, kind="missing local documentation target"))

# Ignored outputs may exist locally; none may be tracked for publication.
tracked = subprocess.check_output(["git", "ls-files", "design"], cwd=root, text=True).splitlines()
for name in tracked:
    if set(Path(name).parts) & ignored:
        findings.append(dict(file=name, kind="tracked generated output"))
print(json.dumps(dict(ok=not findings, scanned_files=len(files), findings=findings,
                     secret_scan="FAIL" if any(f["kind"] in patterns for f in findings) else "PASS",
                     scope="Source pattern scan, syntax, local Markdown links and publication filenames; matching values never printed"), indent=2))
raise SystemExit(bool(findings))
