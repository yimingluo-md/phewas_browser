#!/bin/bash
# Build offline Mac runtimes for both Apple Silicon and Intel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MACOS_DIR="$ROOT/macos"
LOCK_FILE="$ROOT/requirements.lock.txt"
RELEASE=20260807
PYTHON_VERSION=3.12.13
BASE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$RELEASE"
ARM_ARCHIVE="cpython-${PYTHON_VERSION}+${RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
INTEL_ARCHIVE="cpython-${PYTHON_VERSION}+${RELEASE}-x86_64-apple-darwin-install_only_stripped.tar.gz"
ARM_SHA256=25baa97c65b3f0aa90e21131b4f9e80aef8899e8144006db8a9d2c1ab9e807e3
INTEL_SHA256=127053f1736f721e391ddb46f07585d05756e15bb8d757d3bbc0519738998ba1
WORK="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/iei-phewas-runtime.XXXXXX")"
trap '/bin/rm -rf "$WORK"' EXIT

download_and_verify() {
    local archive="$1" expected="$2"
    /usr/bin/curl -L --fail --show-error --progress-bar "$BASE_URL/$archive" -o "$WORK/$archive"
    local actual
    actual="$(/usr/bin/shasum -a 256 "$WORK/$archive" | /usr/bin/awk '{print $1}')"
    [ "$actual" = "$expected" ] || {
        echo "Checksum failed for $archive" >&2
        exit 1
    }
}

download_and_verify "$ARM_ARCHIVE" "$ARM_SHA256"
download_and_verify "$INTEL_ARCHIVE" "$INTEL_SHA256"

/bin/mkdir -p "$WORK/python-arm64" "$WORK/python-x86_64"
/usr/bin/tar -xzf "$WORK/$ARM_ARCHIVE" --strip-components=1 -C "$WORK/python-arm64"
/usr/bin/tar -xzf "$WORK/$INTEL_ARCHIVE" --strip-components=1 -C "$WORK/python-x86_64"

case "$(/usr/bin/uname -m)" in
    arm64)  BUILD_PYTHON="$WORK/python-arm64/bin/python3" ;;
    x86_64) BUILD_PYTHON="$WORK/python-x86_64/bin/python3" ;;
    *) echo "This packaging script requires an Apple Silicon or Intel Mac." >&2; exit 1 ;;
esac

install_packages() {
    local target="$1" platform="$2"
    "$BUILD_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir \
        --only-binary=:all: --no-compile --requirement "$LOCK_FILE" \
        --implementation cp --python-version 3.12 --abi cp312 --platform "$platform" \
        --target "$target/lib/python3.12/site-packages"
}

install_packages "$WORK/python-arm64" macosx_11_0_arm64
install_packages "$WORK/python-x86_64" macosx_10_13_x86_64

/bin/mkdir -p "$MACOS_DIR"
/bin/rm -rf "$MACOS_DIR/python-arm64.new" "$MACOS_DIR/python-x86_64.new"
/bin/mv "$WORK/python-arm64" "$MACOS_DIR/python-arm64.new"
/bin/mv "$WORK/python-x86_64" "$MACOS_DIR/python-x86_64.new"
/bin/rm -rf "$MACOS_DIR/python-arm64" "$MACOS_DIR/python-x86_64"
/bin/mv "$MACOS_DIR/python-arm64.new" "$MACOS_DIR/python-arm64"
/bin/mv "$MACOS_DIR/python-x86_64.new" "$MACOS_DIR/python-x86_64"

echo "Mac runtimes are ready (Apple Silicon and Intel)."
