#!/bin/bash
# Start the self-contained IEI PheWAS Browser and open it in the default browser.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${IEI_PHEWAS_PORT:-8555}"
URL="http://127.0.0.1:${PORT}"
HEALTH_URL="$URL/api/health"
STATE_DIR="${IEI_PHEWAS_STATE_DIR:-$HOME/Library/Application Support/IEI PheWAS Browser}"
LOG_FILE="$STATE_DIR/server.log"
PID_FILE="$STATE_DIR/server.pid"

alert() {
    /usr/bin/osascript - "$1" <<'APPLESCRIPT' 2>/dev/null || true
on run argv
    display alert "IEI PheWAS Browser" message (item 1 of argv) as critical
end run
APPLESCRIPT
}

fail() {
    echo "ERROR: $1" >&2
    alert "$1"
    exit 1
}

is_our_server() {
    /usr/bin/curl --silent --fail --max-time 2 "$HEALTH_URL" 2>/dev/null \
        | /usr/bin/grep -q '"application":"IEI PheWAS Browser"'
}

case "$PORT" in
    ''|*[!0-9]*) fail "The configured network port is invalid." ;;
esac
[ "$PORT" -ge 1024 ] 2>/dev/null && [ "$PORT" -le 65535 ] 2>/dev/null \
    || fail "The configured network port must be between 1024 and 65535."

for required in app.py static/index.html data/phewas.duckdb packages/phewas_core/phewas_core/__init__.py; do
    [ -f "$DIR/$required" ] \
        || fail "A required browser file is missing: $required. Please re-extract the complete download and try again."
done

case "$(/usr/bin/uname -m)" in
    arm64)  PYTHON="$DIR/macos/python-arm64/bin/python3" ;;
    x86_64) PYTHON="$DIR/macos/python-x86_64/bin/python3" ;;
    *)      fail "This Mac processor is not supported. Supported processors: Apple Silicon and Intel." ;;
esac

[ -x "$PYTHON" ] \
    || fail "The bundled Mac runtime is missing. Please re-extract the complete download and try again."

if is_our_server; then
    if [ "${IEI_PHEWAS_NO_OPEN:-0}" != "1" ]; then /usr/bin/open "$URL"; fi
    exit 0
fi

# Do not open an unrelated application that happens to own our port.
if /usr/bin/curl --silent --output /dev/null --max-time 2 "$URL" 2>/dev/null; then
    fail "Another application is already using network port $PORT. Close that application, then try again."
fi

/bin/mkdir -p "$STATE_DIR" || fail "Could not create the browser's local settings folder."
: > "$LOG_FILE" || fail "Could not write the browser log: $LOG_FILE"

if ! PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -I -c \
    'import duckdb, fastapi, uvicorn' >> "$LOG_FILE" 2>&1; then
    fail "The bundled runtime is incomplete. Please re-extract the complete download and try again."
fi

cd "$DIR" || fail "Could not open the browser data folder."
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    /usr/bin/nohup "$PYTHON" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" \
    >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# The database can take a moment to open on slower or external disks.
for _ in $(/usr/bin/seq 1 180); do
    if is_our_server; then break; fi
    if ! /bin/kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
    /bin/sleep 0.5
done

if ! is_our_server; then
    /bin/rm -f "$PID_FILE"
    fail "The browser could not start. Diagnostic details were saved to: $LOG_FILE"
fi

if [ "${IEI_PHEWAS_NO_OPEN:-0}" != "1" ]; then /usr/bin/open "$URL"; fi
