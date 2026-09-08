#!/usr/bin/env bash
# Freeze phewas-server with PyInstaller into apps/desktop/src-tauri/sidecar/phewas-server/
# (one directory per build; the desktop shell bundles it as a resource).
#   scripts/build_sidecar.sh            build for the current machine/architecture
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/apps/desktop/src-tauri/sidecar"
WORK="$ROOT/.build/pyinstaller"
cd "$ROOT"

uv sync --locked --python 3.12 --group build
rm -rf "$WORK" "$OUT/phewas-server"
mkdir -p "$OUT" "$WORK"
uv run pyinstaller --noconfirm --clean --log-level WARN \
    --distpath "$OUT" --workpath "$WORK" \
    packages/phewas_server/pyinstaller/phewas-server.spec

# the built frontend ships inside the sidecar directory (served by the server itself)
if [ ! -f "$ROOT/apps/web/dist/index.html" ]; then
    echo "frontend not built; run: (cd apps/web && npm ci && npm run build)" >&2; exit 1
fi
cp -R "$ROOT/apps/web/dist" "$OUT/phewas-server/web"

exe="$OUT/phewas-server/phewas-server"; [ -f "$exe.exe" ] && exe="$exe.exe"
echo "sidecar: $exe ($(du -sh "$OUT/phewas-server" | cut -f1))"
# smoke: the frozen server must start and answer /api/health
PHEWAS_TOKEN=smoke PHEWAS_HOME="$WORK/home" "$exe" --port 8599 --no-open > "$WORK/smoke.log" 2>&1 &
pid=$!
ok=0
for _ in $(seq 1 40); do
    if curl -sf http://127.0.0.1:8599/api/health >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.5
done
if [ "$ok" != 1 ]; then kill "$pid" 2>/dev/null || true; echo "frozen server did not answer; log:"; cat "$WORK/smoke.log"; exit 1; fi
if ! curl -sf http://127.0.0.1:8599/ 2>/dev/null | grep -q "<title>PheWAS Browser"; then kill "$pid" 2>/dev/null || true; echo "frozen server does not serve the frontend"; exit 1; fi
kill "$pid" 2>/dev/null || true
echo "frozen server answers /api/health and serves the frontend"
