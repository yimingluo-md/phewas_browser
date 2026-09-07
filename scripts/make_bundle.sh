#!/bin/bash
# Create separate, self-contained Mac and Windows downloads for collaborators.
# Usage: ./scripts/make_bundle.sh [all|mac|windows] [output-directory]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
OUT_DIR="${2:-$HOME/Desktop}"
APP_NAME="IEI PheWAS Browser.app"
WORK="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/iei-phewas-bundle.XXXXXX")"
trap '/bin/rm -rf "$WORK"' EXIT

case "$MODE" in
    all|mac|windows) ;;
    *) echo "Usage: $0 [all|mac|windows] [output-directory]" >&2; exit 2 ;;
esac

copy_item() {
    local source="$1" destination="$2"
    # APFS clone copies make staging the 2.9 GB database nearly instantaneous.
    /bin/cp -cR "$source" "$destination" 2>/dev/null \
        || /usr/bin/ditto "$source" "$destination"
}

require_file() {
    [ -e "$ROOT/$1" ] || {
        echo "Required distribution file is missing: $1" >&2
        exit 1
    }
}

for required in app.py launch.sh static/index.html data/phewas.duckdb; do
    require_file "$required"
done
/bin/mkdir -p "$OUT_DIR"

build_mac() {
    require_file "macos/python-arm64/bin/python3"
    require_file "macos/python-x86_64/bin/python3"
    require_file "$APP_NAME/Contents/MacOS/launcher"

    local folder="$WORK/IEI PheWAS Browser (Mac)"
    local app="$folder/$APP_NAME"
    local payload="$app/Contents/Resources/browser"
    local output="$OUT_DIR/IEI_PheWAS_Browser_Mac.zip"
    /bin/mkdir -p "$folder"

    copy_item "$ROOT/$APP_NAME" "$app"
    /bin/mkdir -p "$payload"
    copy_item "$ROOT/app.py" "$payload/app.py"
    copy_item "$ROOT/launch.sh" "$payload/launch.sh"
    copy_item "$ROOT/requirements.txt" "$payload/requirements.txt"
    copy_item "$ROOT/requirements.lock.txt" "$payload/requirements.lock.txt"
    copy_item "$ROOT/static" "$payload/static"
    copy_item "$ROOT/data" "$payload/data"
    copy_item "$ROOT/macos" "$payload/macos"
    copy_item "$ROOT/Stop PheWAS Browser.command" "$folder/Stop IEI PheWAS Browser.command"
    copy_item "$ROOT/README-Mac.txt" "$folder/READ ME - Mac.txt"

    /usr/bin/xattr -cr "$app"
    /usr/bin/codesign --force --deep --sign - "$app"
    /usr/bin/codesign --verify --deep --strict "$app"
    /bin/rm -f "$output"
    (cd "$WORK" && /usr/bin/ditto -c -k --norsrc --keepParent "$(/usr/bin/basename "$folder")" "$output")
    echo "Mac download: $output ($(/usr/bin/du -h "$output" | /usr/bin/cut -f1))"
}

build_windows() {
    require_file "windows/python/python.exe"
    local folder="$WORK/IEI PheWAS Browser (Windows)"
    local output="$OUT_DIR/IEI_PheWAS_Browser_Windows.zip"
    /bin/mkdir -p "$folder"

    copy_item "$ROOT/app.py" "$folder/app.py"
    copy_item "$ROOT/static" "$folder/static"
    copy_item "$ROOT/data" "$folder/data"
    copy_item "$ROOT/windows" "$folder/windows"
    copy_item "$ROOT/Launch PheWAS Browser (Windows).bat" "$folder/Launch IEI PheWAS Browser.bat"
    copy_item "$ROOT/Stop PheWAS Browser (Windows).bat" "$folder/Stop IEI PheWAS Browser.bat"
    copy_item "$ROOT/README-Windows.txt" "$folder/READ ME - Windows.txt"

    /bin/rm -f "$output"
    (cd "$WORK" && /usr/bin/ditto -c -k --norsrc --keepParent "$(/usr/bin/basename "$folder")" "$output")
    echo "Windows download: $output ($(/usr/bin/du -h "$output" | /usr/bin/cut -f1))"
}

case "$MODE" in
    all) build_mac; build_windows ;;
    mac) build_mac ;;
    windows) build_windows ;;
esac

echo "Research Use Only — share through a secure institutional channel."
