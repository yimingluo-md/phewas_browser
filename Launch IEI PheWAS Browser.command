#!/bin/bash
# Reliable Finder launcher and fallback when Gatekeeper blocks the app bundle.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec /bin/bash "$DIR/launch.sh"
