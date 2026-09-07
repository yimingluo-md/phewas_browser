#!/bin/bash
# Double-click to stop only the IEI PheWAS Browser process we started.
STATE_DIR="${IEI_PHEWAS_STATE_DIR:-$HOME/Library/Application Support/IEI PheWAS Browser}"
PID_FILE="$STATE_DIR/server.pid"

if [ -f "$PID_FILE" ]; then
    PID="$(/bin/cat "$PID_FILE")"
else
    PID=""
fi

case "$PID" in
    ''|*[!0-9]*) ;;
    *)
        if /bin/kill -0 "$PID" 2>/dev/null; then
            PROCESS_COMMAND="$(/bin/ps -ww -p "$PID" -o command= 2>/dev/null)"
            case "$PROCESS_COMMAND" in
                *"/macos/python-"*" -m uvicorn app:app "*) ;;
                *)
                    /bin/rm -f "$PID_FILE"
                    echo "IEI PheWAS Browser is not running."
                    /bin/sleep 1
                    exit 0
                    ;;
            esac
            /bin/kill "$PID" 2>/dev/null
            for _ in $(/usr/bin/seq 1 20); do
                /bin/kill -0 "$PID" 2>/dev/null || break
                /bin/sleep 0.1
            done
            echo "IEI PheWAS Browser stopped."
            /bin/rm -f "$PID_FILE"
            /bin/sleep 1
            exit 0
        fi
        ;;
esac

/bin/rm -f "$PID_FILE"
echo "IEI PheWAS Browser is not running."
/bin/sleep 1
