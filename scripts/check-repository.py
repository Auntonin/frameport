"""Audit staged/tracked content before publishing. Diagnostics contain paths, not secrets."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {".gitignore", ".gitattributes", "README.md", "SECURITY.md", "LICENSE", "requirements.txt", "requirements-build.txt", "setup.ps1", "start.cmd", "app.py", "build-release.ps1", "package-release.py"}
BINARY_FILES = {"assets/app.ico", "assets/app.png", "tools/webp/cwebp.exe"}
FORBIDDEN_PARTS = {".private", "data", "browser", "input", "ready-to-upload", "release", "build", "dist", "backups", "__pycache__", ".git"}
SECRET_PATTERNS = [
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"AKIA[A-Z0-9]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"https?://[^/\s]+:[^/@\s]+@"),
]

def permitted(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(p in FORBIDDEN_PARTS or p.startswith(".venv") for p in path.parts):
        return False
    if name in ROOT_FILES or name in BINARY_FILES:
        return True
    if name == "profiles/example.json" or name in {"assets/version.txt", "tools/webp/COPYING", "tools/webp/PATENTS", "tools/webp/AUTHORS"}:
        return True
    return len(path.parts) >= 2 and ((path.parts[0] in {"importer", "tests", "scripts"} and path.suffix == ".py") or (path.parts[0] == "docs" and path.suffix == ".md"))

def audit(files):
    issues = []
    for name, content in files.items():
        if not permitted(name):
            issues.append(name + ": not on the source allowlist")
            continue
        if name not in BINARY_FILES and any(pattern.search(content) for pattern in SECRET_PATTERNS):
            issues.append(name + ": possible secret; inspect locally")
        if len(content) > 2 * 1024 * 1024:
            issues.append(name + ": unexpectedly large source file")
    return issues

def git(*arguments):
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z") if args.staged else git("ls-files", "-z")
    files = {}
    for raw in names.split(b"\0"):
        if raw:
            name = raw.decode("utf-8")
            files[name] = git("show", ":" + name) if args.staged else (ROOT / name).read_bytes()
    issues = audit(files)
    for issue in issues:
        print(issue, file=sys.stderr)
    if issues:
        return 1
    print(f"Repository content audit passed: {len(files)} source files")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
