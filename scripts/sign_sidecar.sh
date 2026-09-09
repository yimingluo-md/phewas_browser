#!/usr/bin/env bash
# Sign every Mach-O inside the frozen sidecar with a Developer ID, hardened runtime and the
# app's entitlements, so the notary service accepts the bundle that embeds it.
#
#   scripts/sign_sidecar.sh "Developer ID Application: Name (TEAMID)" [sidecar-dir]
#
# Tauri signs Contents/MacOS and Contents/Frameworks of the .app, but not resources; the
# PyInstaller directory (a bootloader executable, libpython, and hundreds of .so/.dylib
# extension modules) ships as a resource and must be signed beforehand, innermost first.
set -euo pipefail

IDENTITY="${1:?signing identity required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${2:-$ROOT/apps/desktop/src-tauri/sidecar/phewas-server}"
ENTITLEMENTS="$ROOT/apps/desktop/src-tauri/entitlements.plist"
[ -d "$DIR" ] || { echo "sidecar directory not found: $DIR" >&2; exit 1; }

sign() {
    codesign --force --options runtime --timestamp --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$1"
}

count=0
# libraries and extension modules first (nested code must be signed before the executable)
while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then
        sign "$f"
        count=$((count + 1))
    fi
done < <(find "$DIR/_internal" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0)

# the bootloader last
sign "$DIR/phewas-server"
count=$((count + 1))
echo "signed $count Mach-O files in $DIR"

codesign --verify --strict --verbose=1 "$DIR/phewas-server"
echo "sidecar signature verified"
