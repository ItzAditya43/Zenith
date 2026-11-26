#!/usr/bin/env bash
# Set Zenith's version everywhere it lives: package.json + lockfiles,
# tauri.conf.json, Cargo.toml (and Cargo.lock via cargo itself — never edit
# that file by hand, a pattern edit there once changed a dependency's
# version and broke every release build), pyproject.toml, FastAPI app.
#   scripts/bump-version.sh 1.2.8
set -euo pipefail
cd "$(dirname "$0")/.."
NEW="${1:?usage: scripts/bump-version.sh X.Y.Z}"
[[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a version: $NEW" >&2; exit 1; }

python3 - "$NEW" <<'PY'
import json, re, sys
new = sys.argv[1]
for p in ("frontend/package.json", "desktop/package.json", "desktop/src-tauri/tauri.conf.json"):
    d = json.load(open(p)); d["version"] = new
    open(p, "w").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
for p in ("frontend/package-lock.json", "desktop/package-lock.json"):
    d = json.load(open(p)); d["version"] = new; d["packages"][""]["version"] = new
    open(p, "w").write(json.dumps(d, indent=2) + "\n")
for p in ("desktop/src-tauri/Cargo.toml", "backend/pyproject.toml"):
    s = open(p).read()
    s = re.sub(r'(?m)^version = "[^"]+"', f'version = "{new}"', s, count=1)  # the [package]/[project] line is first
    open(p, "w").write(s)
p = "backend/app/main.py"
s = open(p).read()
s = re.sub(r'version="\d+\.\d+\.\d+",', f'version="{new}",', s, count=1)
open(p, "w").write(s)
PY

(cd desktop/src-tauri && cargo update -p zenith --offline -q 2>/dev/null || cargo check -q)
grep -A1 'name = "zenith"' desktop/src-tauri/Cargo.lock | grep -q "\"$NEW\"" || { echo "Cargo.lock didn't pick up $NEW" >&2; exit 1; }
echo "Version set to $NEW. Add CHANGELOG.md and frontend/src/lib/changelog.ts entries, then tag v$NEW."
