#!/usr/bin/env bash
# Set the application version everywhere it is declared.
#   scripts/set_version.sh 1.0.0
set -euo pipefail
V="${1:?version required, e.g. 1.0.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 - "$V" <<'EOF'
import json, re, sys, pathlib
v = sys.argv[1]
def sub(path, pattern, repl, count=1):
    p = pathlib.Path(path); s = p.read_text()
    new, n = re.subn(pattern, repl, s, count=count, flags=re.M)
    assert n == count, f"{path}: expected {count} replacement(s), made {n}"
    p.write_text(new)
sub("pyproject.toml", r'^version = "[^"]+"', f'version = "{v}"')
sub("packages/phewas_core/pyproject.toml", r'^version = "[^"]+"', f'version = "{v}"')
sub("packages/phewas_core/phewas_core/__init__.py", r'^__version__ = "[^"]+"', f'__version__ = "{v}"')
sub("packages/phewas_server/pyproject.toml", r'^version = "[^"]+"', f'version = "{v}"')
sub("packages/phewas_server/phewas_server/__init__.py", r'^__version__ = "[^"]+"', f'__version__ = "{v}"')
sub("apps/desktop/src-tauri/Cargo.toml", r'^version = "[^"]+"', f'version = "{v}"')
for path in ("apps/desktop/src-tauri/tauri.conf.json", "apps/desktop/package.json", "apps/web/package.json"):
    p = pathlib.Path(path); d = json.loads(p.read_text()); d["version"] = v
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
print("version", v)
EOF
(cd apps/desktop/src-tauri && cargo update -p phewas-browser --offline >/dev/null 2>&1 || true)
for d in apps/web apps/desktop; do
    (cd "$d" && npm install --package-lock-only --ignore-scripts >/dev/null 2>&1 || true)
done
uv lock >/dev/null 2>&1 || true
echo "now: uv.lock / Cargo.lock / package-lock.json refreshed where possible; review git diff and commit"
